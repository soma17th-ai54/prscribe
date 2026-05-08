from __future__ import annotations

import pytest

from researcher_agent.agents import researcher
from researcher_agent.schemas.research import (
    CommitInfo,
    ExtraContextPlan,
    FileChange,
    GitHubToolRequest,
    RawPRData,
    ResearchResult,
)


def raw_pr() -> RawPRData:
    return RawPRData(
        pr_identifier="acme/demo#7",
        title="Validate resource filters before matching",
        body="Fixes #3",
        author="dev",
        base_branch="main",
        head_branch="feature/filter-validation",
        state="open",
        commits=[
            CommitInfo(
                sha="abc123",
                message="Validate resource filters before matching",
                author="dev",
                timestamp="2026-05-05T00:00:00Z",
            )
        ],
        files=[
            FileChange(
                path="demo_app/service.py",
                status="modified",
                additions=14,
                deletions=3,
                patch=(
                    "@@ -32,6 +32,7 @@ def list_resources(self, filters):\n"
                    "+        validate_filters(filters)\n"
                    "@@ -100,0 +110,8 @@\n"
                    "+def validate_filters(filters):\n"
                    "+    pass\n"
                ),
            ),
            FileChange(
                path="tests/test_service.py",
                status="modified",
                additions=10,
                deletions=0,
                patch="+def test_invalid_filter_values_raise_validation_error(self):\n+    pass\n",
            ),
        ],
        linked_issues=[],
        fetched_at="2026-05-05T00:00:00+00:00",
    )


def test_extract_changed_functions_from_patch() -> None:
    functions = researcher.extract_changed_functions(raw_pr())
    names = {(item.file, item.function_name, item.change_kind) for item in functions}

    assert ("demo_app/service.py", "list_resources", "modified") in names
    assert ("demo_app/service.py", "validate_filters", "added") in names
    assert ("tests/test_service.py", "test_invalid_filter_values_raise_validation_error", "added") in names


def test_fallback_result_matches_data_contract() -> None:
    result = researcher._fallback_result(raw_pr())

    assert isinstance(result, ResearchResult)
    assert result.pr_identifier == "acme/demo#7"
    assert result.changed_files[0].path == "demo_app/service.py"
    assert result.facts
    assert result.search_chunks
    assert result.self_eval is not None


def test_collect_extra_context_skips_complete_changed_file(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bundle:
        owner = "acme"
        repo = "demo"
        pull_number = 7
        base_sha = "base"
        head_sha = "head"
        raw = raw_pr()

    monkeypatch.setattr(
        researcher,
        "call_solar_for_extra_context",
        lambda bundle: ExtraContextPlan(
            requests=[
                GitHubToolRequest(
                    tool_name="read_pr_file",
                    reason="Need full changed file.",
                    path="demo_app/service.py",
                )
            ]
        ),
    )
    monkeypatch.setattr(
        researcher,
        "execute_github_tool_requests",
        lambda bundle, requests: pytest.fail("tool execution should be skipped"),
    )

    results, notes = researcher.collect_extra_context(Bundle())

    assert results == []
    assert "patch already complete" in notes[0]


def test_extract_research_result_falls_back_when_solar_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(researcher, "call_solar_for_research", lambda *args, **kwargs: {"bad": "shape"})

    result = researcher.extract_research_result(raw_pr())

    assert result.facts
    assert result.search_chunks
    assert result.notes


def test_extract_research_result_fills_empty_search_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_solar(*args, **kwargs):
        fallback = researcher._fallback_result(raw_pr()).model_dump(mode="json")
        fallback["search_chunks"] = []
        return fallback

    monkeypatch.setattr(researcher, "call_solar_for_research", fake_solar)

    result = researcher.extract_research_result(raw_pr())

    assert result.search_chunks
    assert "search_chunks" in result.notes[0]
