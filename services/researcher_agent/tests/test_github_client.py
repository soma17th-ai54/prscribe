from __future__ import annotations

import pytest

from researcher_agent.github import client
from researcher_agent.github.client import GitHubClientError, PRRef, RepoRef


def test_parse_pr_url() -> None:
    assert client.parse_pr_url("https://github.com/acme/demo/pull/42") == PRRef("acme", "demo", 42)


def test_parse_repo_url() -> None:
    assert client.parse_repo_url("https://github.com/acme/demo.git") == RepoRef("acme", "demo")


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/acme/demo/pull/1",
        "https://github.com/acme/demo/issues/1",
        "https://github.com/acme/demo/pull/nope",
    ],
)
def test_parse_pr_url_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(GitHubClientError):
        client.parse_pr_url(url)


def test_extract_linked_issue_numbers_filters_cross_repo_refs() -> None:
    texts = ["Fixes #1", "Closes acme/demo#2", "Resolves other/repo#3", "mentions #4"]
    assert client.extract_linked_issue_numbers(texts, "acme", "demo") == [1, 2]
