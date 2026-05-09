import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestration.graph import context_node, researcher_node, writer_node
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
async def test_writer_node_full_mode():
    mock_draft = MagicMock()
    mock_draft.model_dump.return_value = {"title": "Test Post", "full_markdown": "# Hello"}
    mock_result = MagicMock()
    mock_result.draft = mock_draft
    mock_result.verifications = []

    with patch("orchestration.graph.run_writer_pipeline", return_value=mock_result):
        state: GraphState = {
            "research": _make_research_dict(),
            "context": {"coverage": 0.8},
            "errors": [],
        }
        result = await writer_node(state)

    assert "draft" in result
    assert result["draft"]["title"] == "Test Post"
    assert result.get("verifications") == []


@pytest.mark.asyncio
async def test_writer_node_minimal_mode():
    mock_draft = MagicMock()
    mock_draft.model_dump.return_value = {"title": "Minimal", "full_markdown": "# Minimal"}
    mock_result = MagicMock()
    mock_result.draft = mock_draft
    mock_result.verifications = []

    with patch("orchestration.graph.run_writer_pipeline", return_value=mock_result) as mock_fn:
        state: GraphState = {
            "research": _make_research_dict(),
            "context": {"coverage": 0.1},
            "errors": [],
        }
        await writer_node(state)

    _, kwargs = mock_fn.call_args
    assert kwargs.get("mode") == "minimal_context" or mock_fn.call_args[0][2] == "minimal_context"


@pytest.mark.asyncio
async def test_writer_node_missing_research():
    state: GraphState = {"errors": []}
    result = await writer_node(state)
    assert "errors" in result
    assert any("research" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_graph_compiles():
    from orchestration.graph import prscribe_graph
    assert prscribe_graph is not None
