import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from context_agent.models import SearchChunk, FactBullet, ResearchResult


def make_research_result():
    return ResearchResult(
        pr_identifier="owner/repo#1",
        summary_one_line="Fix N+1 with select_related",
        changed_files=[],
        changed_functions=[],
        tech_stack_hints=[],
        facts=[
            FactBullet(
                statement="PR uses select_related() for N+1 fix",
                source="diff",
                source_locator="files[0].patch L10",
            )
        ],
        search_chunks=[
            SearchChunk(chunk_id="c1", keywords=["django", "select_related", "N+1"], intent="best_practice"),
            SearchChunk(chunk_id="c2", keywords=["django", "queryset", "performance"], intent="concept_lookup"),
        ],
    )


def test_context_solar_api_key_accepts_upstage_alias(monkeypatch):
    from context_agent.solar import solar_api_key

    monkeypatch.delenv("SOLAR_API_KEY", raising=False)
    monkeypatch.setenv("UPSTAGE_API_KEY", "upstage-test-key")

    assert solar_api_key() == "upstage-test-key"


@pytest.mark.asyncio
async def test_run_context_agent_returns_context_result():
    fake_finish_output = json.dumps([{
        "chunk_id": "c1",
        "title": "Django ORM docs",
        "url": "https://docs.djangoproject.com/orm",
        "source_kind": "official_docs",
        "excerpt": "select_related() reduces database queries.",
        "fetched_at": "2026-05-08T00:00:00+00:00",
    }])

    mock_agent_output = {
        "messages": [
            MagicMock(content=f"__FINISH__:{fake_finish_output}", name="finish")
        ]
    }

    with patch("context_agent.agent.create_react_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value=mock_agent_output)
        mock_create.return_value = mock_agent

        from context_agent.agent import run_context_agent
        result = await run_context_agent(make_research_result())

    assert result.pr_identifier == "owner/repo#1"
    assert 0.0 <= result.coverage <= 1.0
    for call in mock_agent.ainvoke.call_args_list:
        assert call.kwargs["config"]["recursion_limit"] == 10


@pytest.mark.asyncio
async def test_run_context_agent_emits_trace_events():
    fake_finish_output = json.dumps([{
        "chunk_id": "c1",
        "title": "Django ORM docs",
        "url": "https://docs.djangoproject.com/orm",
        "source_kind": "official_docs",
        "excerpt": "select_related() reduces database queries.",
        "fetched_at": "2026-05-08T00:00:00+00:00",
    }])
    events = []

    with patch("context_agent.agent.create_react_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(
            return_value={"messages": [MagicMock(content=f"__FINISH__:{fake_finish_output}")]}
        )
        mock_create.return_value = mock_agent

        from context_agent.agent import run_context_agent
        result = await run_context_agent(make_research_result(), emit_trace=events.append)

    assert result.verified_references
    assert any(event["node"] == "context" for event in events)
    assert any(event["stage"] == "context_agent" and event["status"] == "started" for event in events)
    assert any(event["stage"] == "context_chunk" and event["status"] == "running" for event in events)
    assert any(event["stage"] == "context_agent" and event["status"] == "completed" for event in events)


@pytest.mark.asyncio
async def test_coverage_zero_when_all_give_up():
    mock_agent_output = {
        "messages": [
            MagicMock(content="__GIVE_UP__:zero_hits_after_paraphrase", name="give_up")
        ]
    }

    with patch("context_agent.agent.create_react_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value=mock_agent_output)
        mock_create.return_value = mock_agent

        from context_agent.agent import run_context_agent
        result = await run_context_agent(make_research_result())

    assert result.coverage == 0.0
    assert result.verified_references == []


@pytest.mark.asyncio
async def test_parallel_chunks_use_semaphore():
    chunks = [
        SearchChunk(chunk_id=f"c{i}", keywords=[f"kw{i}"], intent="concept_lookup")
        for i in range(5)
    ]
    research = ResearchResult(
        pr_identifier="owner/repo#2",
        summary_one_line="test",
        changed_files=[],
        changed_functions=[],
        tech_stack_hints=[],
        facts=[],
        search_chunks=chunks,
    )

    mock_agent_output = {"messages": [MagicMock(content="__GIVE_UP__:no_results", name="give_up")]}

    with patch("context_agent.agent.create_react_agent") as mock_create:
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value=mock_agent_output)
        mock_create.return_value = mock_agent

        from context_agent.agent import run_context_agent
        result = await run_context_agent(research)

    assert result.coverage == 0.0
    assert mock_agent.ainvoke.call_count == 5
