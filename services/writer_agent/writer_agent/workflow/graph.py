from __future__ import annotations

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from writer_agent.agents.writer import run_writer_pipeline


class WriterState(TypedDict, total=False):
    research: dict[str, Any]
    context: dict[str, Any]
    mode: Literal["full", "minimal_context"]
    draft: dict[str, Any]
    verifications: list[dict[str, Any]]
    errors: list[str]


def writer_node(state: WriterState) -> WriterState:
    if not state.get("research"):
        return {"errors": [*state.get("errors", []), "research is required"]}
    try:
        result = run_writer_pipeline(
            state["research"],
            state.get("context"),
            mode=state.get("mode", "full"),
        )
    except Exception as exc:
        return {"errors": [*state.get("errors", []), str(exc)]}
    return {
        "draft": result.draft.model_dump(mode="json"),
        "verifications": [item.model_dump(mode="json") for item in result.verifications],
    }


graph_builder = StateGraph(WriterState)
graph_builder.add_node("writer", writer_node)
graph_builder.add_edge(START, "writer")
graph_builder.add_edge("writer", END)

writer_graph = graph_builder.compile()
