from __future__ import annotations

import asyncio

from langgraph.graph import END, START, StateGraph

from researcher_agent.agents.researcher import run_researcher
from researcher_agent.schemas.research import ResearchResult
from context_agent.node import context_node as _context_node
from context_agent.models import ContextResult
from writer_agent.agents.writer import run_writer_pipeline

from orchestration.state import GraphState


async def researcher_node(state: GraphState) -> dict:
    pr_url = state.get("pr_url", "")
    pr_number = state.get("pr_number")
    try:
        result: ResearchResult = await asyncio.to_thread(
            run_researcher, pr_url, pr_number
        )
        return {"research": result.model_dump(mode="json")}
    except Exception as e:
        return {"errors": state.get("errors", []) + [str(e)]}


async def context_node(state: GraphState) -> dict:
    research_dict = state.get("research")
    if not research_dict:
        return {"errors": state.get("errors", []) + ["research is missing"]}

    research = ResearchResult.model_validate(research_dict)

    class _Adapter:
        pass

    adapter = _Adapter()
    adapter.research = research
    adapter.errors = state.get("errors", [])
    adapter.react_traces = state.get("react_traces", [])

    result = await _context_node(adapter)

    if "context" in result:
        ctx: ContextResult = result["context"]
        return {
            "context": ctx.model_dump(mode="json"),
            "react_traces": result.get("react_traces", []),
        }
    return result


async def writer_node(state: GraphState) -> dict:
    research_dict = state.get("research")
    if not research_dict:
        return {"errors": state.get("errors", []) + ["research is missing"]}

    context_dict = state.get("context")
    override = state.get("mode_override")
    if override in ("full", "minimal_context"):
        mode = override
    else:
        coverage = (context_dict or {}).get("coverage", 0.0)
        mode = "minimal_context" if coverage < 0.2 else "full"

    try:
        result = await asyncio.to_thread(
            run_writer_pipeline, research_dict, context_dict, mode
        )
        return {
            "draft": result.draft.model_dump(mode="json"),
            "verifications": [v.model_dump(mode="json") for v in result.verifications],
        }
    except Exception as e:
        return {"errors": state.get("errors", []) + [str(e)]}


def _route_after_researcher(state: GraphState) -> str:
    if state.get("errors"):
        return END
    return "context"


graph_builder = StateGraph(GraphState)
graph_builder.add_node("researcher", researcher_node)
graph_builder.add_node("context", context_node)
graph_builder.add_node("writer", writer_node)
graph_builder.add_edge(START, "researcher")
graph_builder.add_conditional_edges("researcher", _route_after_researcher)
graph_builder.add_edge("context", "writer")
graph_builder.add_edge("writer", END)

prscribe_graph = graph_builder.compile()
