import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.graph import context_node, researcher_node
from orchestration.state import GraphState


def _make_research_dict():
    return {
        "pr_identifier": "owner/repo#1",
        "summary_one_line": "Fix N+1 with select_related",
        "changed_files": [],
        "changed_functions": [],
        "tech_stack_hints": [],
        "facts": [
            {"statement": "Uses select_related", "source": "diff", "source_locator": "L1"}
        ],
        "search_chunks": [
            {"chunk_id": "c1", "keywords": ["django", "orm"], "intent": "concept_lookup", "related_files": []}
        ],
        "notes": [],
        "self_eval": None,
    }


@pytest.mark.asyncio
async def test_researcher_node_success():
    mock_result = MagicMock()
    mock_result.model_dump.return_value = _make_research_dict()

    with patch("orchestration.graph.run_researcher", return_value=mock_result):
        state: GraphState = {"pr_url": "https://github.com/owner/repo/pull/1"}
        result = await researcher_node(state)

    assert "research" in result
    assert result["research"]["pr_identifier"] == "owner/repo#1"


@pytest.mark.asyncio
async def test_researcher_node_error():
    with patch("orchestration.graph.run_researcher", side_effect=RuntimeError("API fail")):
        state: GraphState = {"pr_url": "https://github.com/owner/repo/pull/1", "errors": []}
        result = await researcher_node(state)

    assert "errors" in result
    assert any("API fail" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_context_node_success():
    from context_agent.models import ContextResult

    mock_ctx = ContextResult(
        pr_identifier="owner/repo#1",
        raw_references=[],
        verified_references=[],
        verification_log=[],
        coverage=0.5,
    )

    with patch("orchestration.graph._context_node", AsyncMock(return_value={"context": mock_ctx, "react_traces": []})):
        state: GraphState = {"research": _make_research_dict(), "errors": [], "react_traces": []}
        result = await context_node(state)

    assert "context" in result
    assert result["context"]["coverage"] == 0.5


@pytest.mark.asyncio
async def test_context_node_missing_research():
    state: GraphState = {"errors": []}
    result = await context_node(state)

    assert "errors" in result
    assert any("research" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_graph_compiles():
    from orchestration.graph import prscribe_graph
    assert prscribe_graph is not None
