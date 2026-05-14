import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from context_agent.models import (
    ContextResult, ContextSelfEval, FactBullet,
    ResearchResult, SearchChunk,
)


def _make_research():
    return ResearchResult(
        pr_identifier="owner/repo#42",
        summary_one_line="Fix N+1",
        changed_files=[],
        changed_functions=[],
        tech_stack_hints=[],
        facts=[FactBullet(statement="uses select_related", source="diff", source_locator="L1")],
        search_chunks=[SearchChunk(chunk_id="c1", keywords=["django"], intent="best_practice")],
    )


def _make_state(research):
    state = MagicMock()
    state.research = research
    state.errors = []
    state.react_traces = []
    return state


def _make_context_result():
    return ContextResult(
        pr_identifier="owner/repo#42",
        raw_references=[],
        verified_references=[],
        verification_log=[],
        coverage=0.5,
    )


@pytest.mark.asyncio
async def test_context_node_returns_context_result():
    mock_ctx = _make_context_result()
    mock_eval = ContextSelfEval(coverage=0.5, relevance=4, diversity=3, confidence=4, rationale="ok")

    with patch("context_agent.node.run_context_agent", AsyncMock(return_value=mock_ctx)), \
         patch("context_agent.node.run_self_eval", AsyncMock(return_value=mock_eval)):
        from context_agent.node import context_node
        result = await context_node(_make_state(_make_research()))

    assert "context" in result
    assert result["context"].coverage == 0.5
    assert result["context"].self_eval.confidence == 4
    assert any(event["stage"] == "context_self_eval" for event in result["react_traces"])


@pytest.mark.asyncio
async def test_context_node_handles_error_gracefully():
    with patch("context_agent.node.run_context_agent", AsyncMock(side_effect=RuntimeError("LLM error"))):
        from context_agent.node import context_node
        result = await context_node(_make_state(_make_research()))

    assert "errors" in result
    assert any("LLM error" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_context_node_self_eval_failure_does_not_crash():
    mock_ctx = _make_context_result()

    with patch("context_agent.node.run_context_agent", AsyncMock(return_value=mock_ctx)), \
         patch("context_agent.node.run_self_eval", AsyncMock(return_value=None)):
        from context_agent.node import context_node
        result = await context_node(_make_state(_make_research()))

    assert "context" in result
    assert result["context"].self_eval is None


@pytest.mark.asyncio
async def test_context_self_eval_failure_emits_reason():
    events = []

    with patch("context_agent.self_eval.get_solar_mini", side_effect=RuntimeError("solar schema error")):
        from context_agent.self_eval import run_self_eval
        result = await run_self_eval(
            _make_context_result(),
            _make_research(),
            emit_trace=events.append,
        )

    assert result is None
    assert events
    assert events[-1]["stage"] == "context_self_eval"
    assert events[-1]["status"] == "warning"
    assert events[-1]["metadata"]["exception_type"] == "RuntimeError"
    assert "solar schema error" in events[-1]["metadata"]["error"]
