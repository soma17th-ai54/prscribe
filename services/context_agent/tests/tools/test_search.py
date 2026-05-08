import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_web_search_returns_references():
    mock_results = [
        {"title": "Django ORM", "href": "https://docs.djangoproject.com", "body": "QuerySet docs"},
        {"title": "N+1 issue", "href": "https://example.com/n1", "body": "Use select_related"},
    ]
    with patch("context_agent.tools.search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.__enter__.return_value.text.return_value = mock_results
        from context_agent.tools.search import _web_search_impl
        refs = await _web_search_impl("Django N+1 problem", k=2)
    assert len(refs) == 2
    assert refs[0]["url"] == "https://docs.djangoproject.com"


@pytest.mark.asyncio
async def test_fetch_url_returns_excerpt_under_500_chars():
    html = "<html><body><p>" + "A" * 1000 + "</p></body></html>"
    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
        from context_agent.tools.search import _fetch_url_impl
        result = await _fetch_url_impl("https://docs.djangoproject.com")
    assert len(result) <= 500


@pytest.mark.asyncio
async def test_context7_search_falls_back_when_no_key(monkeypatch):
    monkeypatch.delenv("CONTEXT7_API_KEY", raising=False)
    mock_results = [
        {"title": "Django", "href": "https://docs.djangoproject.com", "body": "docs"}
    ]
    with patch("context_agent.tools.search.DDGS") as mock_ddgs:
        mock_ddgs.return_value.__enter__.return_value.text.return_value = mock_results
        from context_agent.tools.search import _context7_search_impl
        refs = await _context7_search_impl("django", "ORM", k=1)
    assert isinstance(refs, list)
