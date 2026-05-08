from __future__ import annotations

from researcher_agent.github import tools
from researcher_agent.github.client import RawPRBundle
from researcher_agent.schemas.research import GitHubToolRequest
from tests.test_researcher import raw_pr


def test_read_pr_file_uses_head_sha(monkeypatch) -> None:
    calls = []

    def fake_fetch(owner: str, repo: str, path: str, ref: str) -> str:
        calls.append((owner, repo, path, ref))
        return "line1\nline2\nline3"

    monkeypatch.setattr(tools, "fetch_file_content", fake_fetch)
    bundle = RawPRBundle("acme", "demo", 7, "base-sha", "head-sha", raw_pr())
    result = tools.execute_github_tool_request(
        bundle,
        GitHubToolRequest(
            tool_name="read_pr_file",
            reason="Need context.",
            path="demo_app/service.py",
            start_line=2,
            end_line=3,
        ),
    )

    assert result.ok is True
    assert result.output == "line2\nline3"
    assert calls == [("acme", "demo", "demo_app/service.py", "head-sha")]
