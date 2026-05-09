import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_compare_returns_consistent():
    mock_output = MagicMock()
    mock_output.verdict = "consistent"
    mock_output.reasoning = "The excerpt confirms the PR fact."

    with patch("context_agent.tools.verify.get_solar_mini") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        mock_factory.return_value.with_structured_output.return_value = mock_llm

        from context_agent.tools.verify import _compare_impl
        result = await _compare_impl(
            excerpt="select_related() reduces N+1 queries by SQL JOIN.",
            facts=["PR uses select_related() to fix N+1 problem"],
        )
    assert result.verdict == "consistent"


@pytest.mark.asyncio
async def test_compare_returns_contradicts():
    mock_output = MagicMock()
    mock_output.verdict = "contradicts"
    mock_output.reasoning = "Excerpt says opposite."

    with patch("context_agent.tools.verify.get_solar_mini") as mock_factory:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_output)
        mock_factory.return_value.with_structured_output.return_value = mock_llm

        from context_agent.tools.verify import _compare_impl
        result = await _compare_impl(
            excerpt="prefetch_related is always slower than select_related.",
            facts=["PR uses prefetch_related for ManyToMany optimization"],
        )
    assert result.verdict == "contradicts"
