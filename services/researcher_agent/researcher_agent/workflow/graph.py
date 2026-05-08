from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from researcher_agent.agents.researcher import collect_extra_context, extract_research_result, run_researcher
from researcher_agent.github.client import fetch_raw_pr_bundle
from researcher_agent.schemas.research import GitHubToolResult, RawPRData


class ResearcherState(TypedDict, total=False):
    pr_url: str
    repo_url: str
    pr_number: int
    raw: dict[str, Any]
    bundle_meta: dict[str, Any]
    tool_results: list[dict[str, Any]]
    notes: list[str]
    research: dict[str, Any]
    errors: list[str]


def _source_url(state: ResearcherState) -> str | None:
    return state.get("pr_url") or state.get("repo_url")


def collect_core_pr_data_node(state: ResearcherState) -> ResearcherState:
    source_url = _source_url(state)
    if not source_url:
        return {"errors": [*state.get("errors", []), "pr_url or repo_url is required"]}
    try:
        bundle = fetch_raw_pr_bundle(source_url, pull_number=state.get("pr_number"))
    except Exception as exc:
        return {"errors": [*state.get("errors", []), str(exc)]}
    return {
        "raw": bundle.raw.model_dump(mode="json"),
        "bundle_meta": {
            "owner": bundle.owner,
            "repo": bundle.repo,
            "pull_number": bundle.pull_number,
            "base_sha": bundle.base_sha,
            "head_sha": bundle.head_sha,
        },
    }


def collect_extra_context_node(state: ResearcherState) -> ResearcherState:
    source_url = _source_url(state)
    if not source_url:
        return {"errors": [*state.get("errors", []), "pr_url or repo_url is required"]}
    try:
        bundle = fetch_raw_pr_bundle(source_url, pull_number=state.get("pr_number"))
        results, notes = collect_extra_context(bundle)
    except Exception as exc:
        return {"errors": [*state.get("errors", []), str(exc)]}
    return {
        "tool_results": [result.model_dump(mode="json") for result in results],
        "notes": notes,
    }


def extract_research_result_node(state: ResearcherState) -> ResearcherState:
    if not state.get("raw"):
        return {"errors": [*state.get("errors", []), "raw is required"]}
    try:
        raw = RawPRData.model_validate(state["raw"])
        tool_results = [
            GitHubToolResult.model_validate(result)
            for result in state.get("tool_results", [])
        ]
        result = extract_research_result(raw, tool_results, state.get("notes", []))
    except Exception as exc:
        return {"errors": [*state.get("errors", []), str(exc)]}
    return {"research": result.model_dump(mode="json")}


def researcher_node(state: ResearcherState) -> ResearcherState:
    source_url = _source_url(state)
    if not source_url:
        return {"errors": [*state.get("errors", []), "pr_url or repo_url is required"]}
    try:
        result = run_researcher(source_url, pull_number=state.get("pr_number"))
    except Exception as exc:
        return {"errors": [*state.get("errors", []), str(exc)]}
    return {"research": result.model_dump(mode="json")}


graph_builder = StateGraph(ResearcherState)
graph_builder.add_node("collect_core_pr_data", collect_core_pr_data_node)
graph_builder.add_node("collect_extra_context", collect_extra_context_node)
graph_builder.add_node("extract_research_result", extract_research_result_node)
graph_builder.add_edge(START, "collect_core_pr_data")
graph_builder.add_edge("collect_core_pr_data", "collect_extra_context")
graph_builder.add_edge("collect_extra_context", "extract_research_result")
graph_builder.add_edge("extract_research_result", END)

researcher_graph = graph_builder.compile()
