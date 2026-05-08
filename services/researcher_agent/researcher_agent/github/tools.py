from __future__ import annotations

import fnmatch
from typing import Any

from researcher_agent.github.client import GitHubClientError, RawPRBundle, fetch_file_content
from researcher_agent.schemas.research import GitHubToolRequest, GitHubToolResult

MAX_TOOL_CONTENT_CHARS = 12_000
DEPENDENCY_MANIFEST_CANDIDATES = [
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
]
README_CANDIDATES = ["README.md", "readme.md", "README.rst", "README.txt"]


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_CONTENT_CHARS:
        return text
    return f"{text[:MAX_TOOL_CONTENT_CHARS]}\n...[truncated {len(text) - MAX_TOOL_CONTENT_CHARS} chars]"


def _line_window(text: str, start_line: int | None, end_line: int | None) -> str:
    if start_line is None and end_line is None:
        return text
    lines = text.splitlines()
    start = max((start_line or 1) - 1, 0)
    end = min(end_line or len(lines), len(lines))
    return "\n".join(lines[start:end])


def _first_existing_file(bundle: RawPRBundle, candidates: list[str], ref: str) -> tuple[str, str]:
    errors: list[str] = []
    sha = bundle.head_sha if ref == "head" else bundle.base_sha
    for path in candidates:
        try:
            return path, fetch_file_content(bundle.owner, bundle.repo, path, sha)
        except GitHubClientError as exc:
            errors.append(f"{path}: {exc}")
    raise GitHubClientError("; ".join(errors))


def execute_github_tool_request(bundle: RawPRBundle, request: GitHubToolRequest) -> GitHubToolResult:
    try:
        selected_path = request.path
        if request.tool_name == "read_pr_file":
            if not request.path:
                raise GitHubClientError("path is required for read_pr_file.")
            sha = bundle.head_sha if request.ref == "head" else bundle.base_sha
            content = fetch_file_content(bundle.owner, bundle.repo, request.path, sha)
            output: Any = _line_window(content, request.start_line, request.end_line)
        elif request.tool_name == "fetch_dependency_manifest":
            selected_path, output = _first_existing_file(
                bundle,
                DEPENDENCY_MANIFEST_CANDIDATES,
                request.ref,
            )
        elif request.tool_name == "fetch_readme":
            selected_path, output = _first_existing_file(bundle, README_CANDIDATES, request.ref)
        else:
            raise GitHubClientError(f"Unsupported GitHub tool: {request.tool_name}")

        if isinstance(output, str):
            output = _truncate(output)
        return GitHubToolResult(
            tool_name=request.tool_name,
            reason=request.reason,
            path=selected_path,
            ok=True,
            output=output,
        )
    except Exception as exc:
        return GitHubToolResult(
            tool_name=request.tool_name,
            reason=request.reason,
            path=request.path,
            ok=False,
            error=str(exc),
        )


def execute_github_tool_requests(
    bundle: RawPRBundle,
    requests: list[GitHubToolRequest],
) -> list[GitHubToolResult]:
    return [execute_github_tool_request(bundle, request) for request in requests]


def grep_changed_patches(bundle: RawPRBundle, pattern: str, glob: str = "*") -> list[dict[str, str]]:
    """Cheap deterministic grep over collected patches, useful for future ReAct tools."""
    import re

    regex = re.compile(pattern)
    matches = []
    for file_change in bundle.raw.files:
        if not fnmatch.fnmatch(file_change.path, glob) or not file_change.patch:
            continue
        for line_number, line in enumerate(file_change.patch.splitlines(), start=1):
            if regex.search(line):
                matches.append({"path": file_change.path, "line": str(line_number), "text": line})
    return matches
