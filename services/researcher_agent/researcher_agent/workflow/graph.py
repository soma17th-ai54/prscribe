from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from researcher_agent.agents.researcher import (
    _trace_event,
    execute_planned_extra_context,
    extract_research_result,
    plan_extra_context,
    run_researcher,
)
from researcher_agent.github.client import RawPRBundle, fetch_raw_pr_bundle
from researcher_agent.schemas.research import GitHubToolRequest, GitHubToolResult, RawPRData


class ResearcherState(TypedDict, total=False):
    pr_url: str
    repo_url: str
    pr_number: int
    raw: dict[str, Any]
    bundle_meta: dict[str, Any]
    needs_extra_context: bool
    extra_context_requests: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    notes: list[str]
    research: dict[str, Any]
    react_traces: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[str], operator.add]


def _source_url(state: ResearcherState) -> str | None:
    return state.get("pr_url") or state.get("repo_url")


def _error_update(stage: str, message: str) -> ResearcherState:
    return {
        "errors": [message],
        "react_traces": [
            _trace_event(
                stage,
                "error",
                message,
            )
        ],
    }


def _bundle_from_state(state: ResearcherState) -> RawPRBundle:
    raw = RawPRData.model_validate(state["raw"])
    meta = state.get("bundle_meta") or {}
    return RawPRBundle(
        owner=str(meta["owner"]),
        repo=str(meta["repo"]),
        pull_number=int(meta["pull_number"]),
        base_sha=str(meta["base_sha"]),
        head_sha=str(meta["head_sha"]),
        raw=raw,
    )


def _route_after_core(state: ResearcherState) -> str:
    if state.get("errors"):
        return END
    return "route_extra_context"


def _route_after_extra_context_router(state: ResearcherState) -> str:
    if state.get("errors"):
        return END
    if state.get("needs_extra_context"):
        return "collect_extra_context"
    return "extract_research_result"


def collect_core_pr_data_node(state: ResearcherState) -> ResearcherState:
    source_url = _source_url(state)
    if not source_url:
        return _error_update("core_pr_data", "pr_url or repo_url is required")
    events: list[dict[str, Any]] = [
        _trace_event(
            "core_pr_data",
            "started",
            "Fetching core PR metadata, commits, files, and linked issues.",
            pull_number=state.get("pr_number"),
        )
    ]
    try:
        bundle = fetch_raw_pr_bundle(source_url, pull_number=state.get("pr_number"))
    except Exception as exc:
        events.append(_trace_event("core_pr_data", "error", str(exc)))
        return {"errors": [str(exc)], "react_traces": events}
    events.append(
        _trace_event(
            "core_pr_data",
            "completed",
            "Core PR data fetched.",
            pr_identifier=bundle.raw.pr_identifier,
            owner=bundle.owner,
            repo=bundle.repo,
            pull_number=bundle.pull_number,
            changed_files=len(bundle.raw.files),
            commits=len(bundle.raw.commits),
            linked_issues=len(bundle.raw.linked_issues),
        )
    )
    return {
        "raw": bundle.raw.model_dump(mode="json"),
        "bundle_meta": {
            "owner": bundle.owner,
            "repo": bundle.repo,
            "pull_number": bundle.pull_number,
            "base_sha": bundle.base_sha,
            "head_sha": bundle.head_sha,
        },
        "react_traces": events,
    }


def route_extra_context_node(state: ResearcherState) -> ResearcherState:
    if not state.get("raw"):
        return _error_update("extra_context_router", "raw is required")
    events: list[dict[str, Any]] = []
    try:
        bundle = _bundle_from_state(state)
        requests, notes = plan_extra_context(bundle, emit_trace=events.append)
    except Exception as exc:
        events.append(_trace_event("extra_context_router", "error", str(exc)))
        return {"errors": [str(exc)], "react_traces": events}
    return {
        "needs_extra_context": bool(requests),
        "extra_context_requests": [request.model_dump(mode="json") for request in requests],
        "notes": notes,
        "react_traces": events,
    }


def collect_extra_context_node(state: ResearcherState) -> ResearcherState:
    if not state.get("raw"):
        return _error_update("extra_context", "raw is required")
    events: list[dict[str, Any]] = []
    try:
        bundle = _bundle_from_state(state)
        requests = [
            GitHubToolRequest.model_validate(request)
            for request in state.get("extra_context_requests", [])
        ]
        results = execute_planned_extra_context(bundle, requests, emit_trace=events.append)
    except Exception as exc:
        events.append(_trace_event("extra_context", "error", str(exc)))
        return {"errors": [str(exc)], "react_traces": events}
    return {
        "tool_results": [result.model_dump(mode="json") for result in results],
        "react_traces": events,
    }


def extract_research_result_node(state: ResearcherState) -> ResearcherState:
    if not state.get("raw"):
        return _error_update("research_extraction", "raw is required")
    events: list[dict[str, Any]] = []
    try:
        raw = RawPRData.model_validate(state["raw"])
        tool_results = [
            GitHubToolResult.model_validate(result)
            for result in state.get("tool_results", [])
        ]
        result = extract_research_result(
            raw,
            tool_results,
            state.get("notes", []),
            emit_trace=events.append,
        )
    except Exception as exc:
        events.append(_trace_event("research_extraction", "error", str(exc)))
        return {"errors": [str(exc)], "react_traces": events}
    return {"research": result.model_dump(mode="json"), "react_traces": events}


def researcher_node(state: ResearcherState) -> ResearcherState:
    source_url = _source_url(state)
    if not source_url:
        return _error_update("researcher", "pr_url or repo_url is required")
    events: list[dict[str, Any]] = []
    try:
        result = run_researcher(
            source_url,
            pull_number=state.get("pr_number"),
            emit_trace=events.append,
        )
    except Exception as exc:
        events.append(_trace_event("researcher", "error", str(exc)))
        return {"errors": [str(exc)], "react_traces": events}
    return {"research": result.model_dump(mode="json"), "react_traces": events}


graph_builder = StateGraph(ResearcherState)
graph_builder.add_node("collect_core_pr_data", collect_core_pr_data_node)
graph_builder.add_node("route_extra_context", route_extra_context_node)
graph_builder.add_node("collect_extra_context", collect_extra_context_node)
graph_builder.add_node("extract_research_result", extract_research_result_node)
graph_builder.add_edge(START, "collect_core_pr_data")
graph_builder.add_conditional_edges("collect_core_pr_data", _route_after_core)
graph_builder.add_conditional_edges("route_extra_context", _route_after_extra_context_router)
graph_builder.add_edge("collect_extra_context", "extract_research_result")
graph_builder.add_edge("extract_research_result", END)

researcher_graph = graph_builder.compile()
