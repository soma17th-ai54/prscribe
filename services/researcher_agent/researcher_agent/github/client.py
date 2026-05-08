from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import requests
from dotenv import load_dotenv

from researcher_agent.schemas.research import CommitInfo, FileChange, LinkedIssue, RawPRData

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
MAX_PAGES = 10
PER_PAGE = 100


class GitHubClientError(RuntimeError):
    """Raised when GitHub data cannot be fetched or parsed."""


@dataclass(frozen=True)
class PRRef:
    owner: str
    repo: str
    pull_number: int


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str


@dataclass(frozen=True)
class RawPRBundle:
    owner: str
    repo: str
    pull_number: int
    base_sha: str
    head_sha: str
    raw: RawPRData


ISSUE_KEYWORD_RE = re.compile(
    r"(?i)\b(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)"
    r"\s+(?:(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+))?#(?P<number>\d+)"
)


def parse_pr_url(pr_url: str) -> PRRef:
    parsed = urlparse(pr_url.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() != "github.com":
        raise GitHubClientError("PR URL must use github.com.")
    if len(parts) < 4 or parts[2] != "pull":
        raise GitHubClientError("PR URL must look like https://github.com/{owner}/{repo}/pull/{number}.")
    try:
        pull_number = int(parts[3])
    except ValueError as exc:
        raise GitHubClientError("Pull request number must be an integer.") from exc
    return PRRef(owner=parts[0], repo=parts[1], pull_number=pull_number)


def parse_repo_url(repo_url: str) -> RepoRef:
    parsed = urlparse(repo_url.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() != "github.com":
        raise GitHubClientError("Repo URL must use github.com.")
    if len(parts) < 2:
        raise GitHubClientError("Repo URL must look like https://github.com/{owner}/{repo}.")
    repo = parts[1][:-4] if parts[1].endswith(".git") else parts[1]
    return RepoRef(owner=parts[0], repo=repo)


def github_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    if not path.startswith("/"):
        path = f"/{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "prscribe-researcher-agent",
    }
    if token := os.getenv("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        f"{GITHUB_API_BASE}{path}",
        headers=headers,
        params=params or {},
        timeout=30,
    )
    if response.status_code == 401:
        raise GitHubClientError("GitHub authentication failed. Check GITHUB_TOKEN.")
    if response.status_code == 403:
        raise GitHubClientError("GitHub request was forbidden or rate-limited. Set a valid GITHUB_TOKEN.")
    if response.status_code == 404:
        raise GitHubClientError("GitHub resource was not found. Check repo, PR number, or token permissions.")
    if not response.ok:
        raise GitHubClientError(f"GitHub API error {response.status_code}: {response.text[:500]}")
    return response.json()


def _github_get_paginated(path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        data = github_get(path, {**(params or {}), "per_page": PER_PAGE, "page": page})
        if not isinstance(data, list):
            raise GitHubClientError(f"Expected list response from {path}.")
        items.extend(data)
        if len(data) < PER_PAGE:
            break
    return items


def resolve_pr_ref(source_url: str, pull_number: int | None = None) -> PRRef:
    parsed = urlparse(source_url.strip())
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 4 and parts[2] == "pull":
        pr_ref = parse_pr_url(source_url)
        if pull_number is not None and pull_number != pr_ref.pull_number:
            raise GitHubClientError("Do not pass --pr-number when source URL already contains a PR number.")
        return pr_ref

    repo_ref = parse_repo_url(source_url)
    if pull_number is not None:
        return PRRef(repo_ref.owner, repo_ref.repo, pull_number)

    pulls = _github_get_paginated(
        f"/repos/{repo_ref.owner}/{repo_ref.repo}/pulls",
        {"state": "open", "sort": "updated", "direction": "desc"},
    )
    if not pulls:
        raise GitHubClientError(
            f"No open pull requests found in {repo_ref.owner}/{repo_ref.repo}. "
            "Pass a full PR URL or use --pr-number."
        )
    return PRRef(repo_ref.owner, repo_ref.repo, int(pulls[0]["number"]))


def extract_linked_issue_numbers(
    texts: Iterable[str | None],
    owner: str | None = None,
    repo: str | None = None,
) -> list[int]:
    numbers: set[int] = set()
    owner_norm = owner.lower() if owner else None
    repo_norm = repo.lower() if repo else None
    for text in texts:
        if not text:
            continue
        for match in ISSUE_KEYWORD_RE.finditer(text):
            match_owner = match.group("owner")
            match_repo = match.group("repo")
            if match_owner and match_repo and owner_norm and repo_norm:
                if match_owner.lower() != owner_norm or match_repo.lower() != repo_norm:
                    continue
            numbers.add(int(match.group("number")))
    return sorted(numbers)


def _map_file_status(status: str) -> str:
    if status in {"added", "removed", "renamed"}:
        return status
    return "modified"


def fetch_file_content(owner: str, repo: str, path: str, ref: str) -> str:
    encoded_path = quote(path, safe="/")
    data = github_get(f"/repos/{owner}/{repo}/contents/{encoded_path}", {"ref": ref})
    if not isinstance(data, dict) or data.get("type") != "file":
        raise GitHubClientError("GitHub contents response is not a file.")
    import base64

    content = data.get("content") or ""
    return base64.b64decode(content).decode("utf-8", errors="replace")


def fetch_raw_pr_bundle(source_url: str, pull_number: int | None = None) -> RawPRBundle:
    pr_ref = resolve_pr_ref(source_url, pull_number=pull_number)
    pr = github_get(f"/repos/{pr_ref.owner}/{pr_ref.repo}/pulls/{pr_ref.pull_number}")
    files = _github_get_paginated(f"/repos/{pr_ref.owner}/{pr_ref.repo}/pulls/{pr_ref.pull_number}/files")
    commits = _github_get_paginated(f"/repos/{pr_ref.owner}/{pr_ref.repo}/pulls/{pr_ref.pull_number}/commits")
    if not isinstance(pr, dict):
        raise GitHubClientError("Pull request response was not an object.")

    issue_texts = [pr.get("body")]
    issue_texts.extend(commit.get("commit", {}).get("message") for commit in commits)
    issue_numbers = extract_linked_issue_numbers(issue_texts, pr_ref.owner, pr_ref.repo)
    linked_issues: list[LinkedIssue] = []
    for number in issue_numbers:
        issue = github_get(f"/repos/{pr_ref.owner}/{pr_ref.repo}/issues/{number}")
        if isinstance(issue, dict):
            linked_issues.append(
                LinkedIssue(
                    number=number,
                    title=issue.get("title") or "",
                    body=issue.get("body"),
                    labels=[
                        label.get("name", "")
                        for label in issue.get("labels", [])
                        if isinstance(label, dict)
                    ],
                )
            )

    raw = RawPRData(
        pr_identifier=f"{pr_ref.owner}/{pr_ref.repo}#{pr_ref.pull_number}",
        title=pr.get("title") or "",
        body=pr.get("body"),
        author=(pr.get("user") or {}).get("login") or "",
        base_branch=(pr.get("base") or {}).get("ref") or "",
        head_branch=(pr.get("head") or {}).get("ref") or "",
        state="merged" if pr.get("merged") else pr.get("state", "open"),
        commits=[
            CommitInfo(
                sha=commit.get("sha") or "",
                message=commit.get("commit", {}).get("message") or "",
                author=commit.get("commit", {}).get("author", {}).get("name") or "",
                timestamp=commit.get("commit", {}).get("author", {}).get("date") or "",
            )
            for commit in commits
        ],
        files=[
            FileChange(
                path=file_data.get("filename") or "",
                status=_map_file_status(file_data.get("status") or "modified"),
                additions=file_data.get("additions") or 0,
                deletions=file_data.get("deletions") or 0,
                patch=file_data.get("patch"),
            )
            for file_data in files
        ],
        linked_issues=linked_issues,
        fetched_at=datetime.now(UTC).isoformat(),
    )
    return RawPRBundle(
        owner=pr_ref.owner,
        repo=pr_ref.repo,
        pull_number=pr_ref.pull_number,
        base_sha=(pr.get("base") or {}).get("sha") or "",
        head_sha=(pr.get("head") or {}).get("sha") or "",
        raw=raw,
    )


def fetch_raw_pr_data(source_url: str, pull_number: int | None = None) -> RawPRData:
    return fetch_raw_pr_bundle(source_url, pull_number=pull_number).raw
