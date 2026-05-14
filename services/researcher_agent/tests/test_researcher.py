from __future__ import annotations

import pytest

from researcher_agent.agents import researcher
from researcher_agent.github.client import RawPRBundle
from researcher_agent.schemas.research import (
    CommitInfo,
    ExtraContextPlan,
    FileChange,
    GitHubToolRequest,
    GitHubToolResult,
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


def test_collect_extra_context_emits_frontend_safe_trace(monkeypatch: pytest.MonkeyPatch) -> None:
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
        lambda bundle: ExtraContextPlan(requests=[]),
    )

    events = []
    results, notes = researcher.collect_extra_context(Bundle(), emit_trace=events.append)

    assert results == []
    assert notes == []
    assert [event["stage"] for event in events] == ["extra_context_router", "extra_context_router"]
    assert events[-1]["status"] == "completed"
    assert events[-1]["metadata"]["requested_tools"] == 0
    assert all("UPSTAGE_API_KEY" not in str(event) for event in events)
    assert all("SOLAR_API_KEY" not in str(event) for event in events)


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
    monkeypatch.setattr(
        researcher,
        "call_solar_for_self_eval",
        lambda raw, result, metrics: {
            "coverage": metrics["coverage"],
            "groundedness": metrics["groundedness"],
            "chunk_quality": 4,
            "confidence": 4,
            "rationale": "stubbed",
        },
    )

    result = researcher.extract_research_result(raw_pr())

    assert result.search_chunks
    assert "search_chunks" in result.notes[0]


def test_extract_research_result_emits_trace_without_changing_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_solar(*args, **kwargs):
        return researcher._fallback_result(raw_pr()).model_dump(mode="json")

    monkeypatch.setattr(researcher, "call_solar_for_research", fake_solar)
    monkeypatch.setattr(
        researcher,
        "call_solar_for_self_eval",
        lambda raw, result, metrics: {
            "coverage": metrics["coverage"],
            "groundedness": metrics["groundedness"],
            "chunk_quality": 4,
            "confidence": 4,
            "rationale": "stubbed",
        },
    )

    events = []
    result = researcher.extract_research_result(raw_pr(), emit_trace=events.append)

    assert isinstance(result, ResearchResult)
    assert result.pr_identifier == "acme/demo#7"
    assert "react_traces" not in result.model_dump(mode="json")
    assert any(event["stage"] == "self_eval" and event["status"] == "completed" for event in events)
    assert any(event["stage"] == "research_extraction" and event["status"] == "completed" for event in events)


def test_self_eval_uses_llm_scores_for_chunk_quality_and_confidence(monkeypatch: pytest.MonkeyPatch) -> None:
    base = researcher._fallback_result(raw_pr())
    monkeypatch.setattr(
        researcher,
        "call_solar_for_self_eval",
        lambda raw, result, metrics: {
            "coverage": 0.0,
            "groundedness": 0.0,
            "chunk_quality": 5,
            "confidence": 5,
            "rationale": "Identifier-level keywords present; facts grounded via source_locator.",
        },
    )

    eval_result = researcher._self_eval(raw_pr(), base)

    assert eval_result.chunk_quality == 5
    assert eval_result.confidence == 5
    assert eval_result.rationale.startswith("Identifier-level")
    deterministic = researcher._compute_deterministic_metrics(raw_pr(), base)
    assert eval_result.coverage == deterministic["coverage"]
    assert eval_result.groundedness == deterministic["groundedness"]


def test_self_eval_falls_back_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    base = researcher._fallback_result(raw_pr())

    def boom(*args, **kwargs):
        raise researcher.ResearcherError("solar down")

    monkeypatch.setattr(researcher, "call_solar_for_self_eval", boom)

    eval_result = researcher._self_eval(raw_pr(), base)

    assert "Deterministic" in eval_result.rationale
    assert eval_result.chunk_quality in (3, 4)


def test_self_eval_falls_back_on_invalid_llm_output(monkeypatch: pytest.MonkeyPatch) -> None:
    base = researcher._fallback_result(raw_pr())
    monkeypatch.setattr(
        researcher,
        "call_solar_for_self_eval",
        lambda raw, result, metrics: {"chunk_quality": 99, "confidence": 5, "rationale": "out of range"},
    )

    eval_result = researcher._self_eval(raw_pr(), base)

    assert "Deterministic" in eval_result.rationale


def test_researcher_graph_streams_react_trace_updates() -> None:
    from researcher_agent.workflow.graph import researcher_graph

    updates = list(researcher_graph.stream({}, stream_mode="updates"))

    assert updates
    first_update = updates[0]["collect_core_pr_data"]
    assert first_update["errors"] == ["pr_url or repo_url is required"]
    assert first_update["react_traces"][0]["node"] == "researcher"
    assert first_update["react_traces"][0]["stage"] == "core_pr_data"


def test_researcher_graph_skips_extra_context_when_router_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    from researcher_agent.workflow import graph as workflow_graph

    bundle = RawPRBundle("acme", "demo", 7, "base", "head", raw_pr())
    monkeypatch.setattr(workflow_graph, "fetch_raw_pr_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(
        workflow_graph,
        "plan_extra_context",
        lambda bundle, emit_trace=None: ([], ["router skipped extra context"]),
    )
    monkeypatch.setattr(
        workflow_graph,
        "extract_research_result",
        lambda raw, tool_results, notes, emit_trace=None: researcher._fallback_result(raw, notes),
    )

    updates = list(
        workflow_graph.researcher_graph.stream(
            {"pr_url": "https://github.com/acme/demo/pull/7"},
            stream_mode="updates",
        )
    )
    node_names = [next(iter(update)) for update in updates]
    final_state = {}
    for update in updates:
        final_state.update(next(iter(update.values())))

    assert node_names == [
        "collect_core_pr_data",
        "route_extra_context",
        "extract_research_result",
    ]
    assert final_state["research"]["notes"] == ["router skipped extra context"]
    assert final_state["needs_extra_context"] is False


def test_researcher_graph_executes_extra_context_when_router_selects_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from researcher_agent.workflow import graph as workflow_graph

    bundle = RawPRBundle("acme", "demo", 7, "base", "head", raw_pr())
    request = GitHubToolRequest(
        tool_name="fetch_readme",
        reason="Need project purpose.",
    )
    tool_result = GitHubToolResult(
        tool_name="fetch_readme",
        reason=request.reason,
        ok=True,
        output="# Demo",
    )
    seen = {"tool_result_count": 0}

    def fake_extract(raw, tool_results, notes, emit_trace=None):
        seen["tool_result_count"] = len(tool_results)
        return researcher._fallback_result(raw, notes)

    monkeypatch.setattr(workflow_graph, "fetch_raw_pr_bundle", lambda *args, **kwargs: bundle)
    monkeypatch.setattr(workflow_graph, "plan_extra_context", lambda bundle, emit_trace=None: ([request], []))
    monkeypatch.setattr(
        workflow_graph,
        "execute_planned_extra_context",
        lambda bundle, requests, emit_trace=None: [tool_result],
    )
    monkeypatch.setattr(workflow_graph, "extract_research_result", fake_extract)

    updates = list(
        workflow_graph.researcher_graph.stream(
            {"pr_url": "https://github.com/acme/demo/pull/7"},
            stream_mode="updates",
        )
    )
    node_names = [next(iter(update)) for update in updates]
    final_state = {}
    for update in updates:
        final_state.update(next(iter(update.values())))

    assert node_names == [
        "collect_core_pr_data",
        "route_extra_context",
        "collect_extra_context",
        "extract_research_result",
    ]
    assert final_state["needs_extra_context"] is True
    assert seen["tool_result_count"] == 1
