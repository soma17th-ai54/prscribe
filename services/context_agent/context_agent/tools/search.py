import json
import os
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from langchain_core.tools import tool


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _web_search_impl(query: str, k: int = 5) -> list[dict]:
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=k))
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "excerpt": r.get("body", "")[:500],
            "source_kind": "blog",
            "fetched_at": _now_iso(),
        }
        for r in results
    ]


async def _fetch_url_impl(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text[:500]


async def _context7_search_impl(library: str, topic: str, k: int = 3) -> list[dict]:
    api_key = os.environ.get("CONTEXT7_API_KEY", "")
    if not api_key:
        query = f"{library} {topic} official documentation"
        return await _web_search_impl(query, k=k)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://context7.com/api/v1/libraries/search",
                params={"query": library},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                raise ValueError(f"context7 search failed: {resp.status_code}")
            libraries = resp.json().get("results", [])
            if not libraries:
                raise ValueError("library not found in context7")

            lib_id = libraries[0]["id"]
            resp = await client.get(
                f"https://context7.com/api/v1/libraries/{lib_id}/docs",
                params={"topic": topic, "tokens": k * 300},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                raise ValueError(f"context7 docs failed: {resp.status_code}")

            sections = resp.json().get("sections", [])[:k]
            return [
                {
                    "title": s.get("title", library),
                    "url": s.get("url", f"https://context7.com/{lib_id}"),
                    "excerpt": s.get("content", "")[:500],
                    "source_kind": "context7",
                    "fetched_at": _now_iso(),
                }
                for s in sections
            ]
    except Exception:
        query = f"{library} {topic} official documentation"
        return await _web_search_impl(query, k=k)


@tool
async def context7_search(library: str, topic: str, k: int = 3) -> str:
    """Context7 MCP에서 라이브러리 공식 문서를 검색한다. 실패 시 web_search로 자동 폴백.
    library: 라이브러리 이름 (예: django, spring-boot, react)
    topic: 검색 주제 (예: ORM N+1, caching, authentication)
    k: 반환할 결과 수 (기본 3)"""
    results = await _context7_search_impl(library, topic, k)
    return json.dumps(results, ensure_ascii=False)


@tool
async def web_search(query: str, k: int = 5) -> str:
    """DuckDuckGo로 웹 검색. context7_search 폴백 또는 일반 보조 검색.
    query: 검색어
    k: 반환할 결과 수 (기본 5)"""
    results = await _web_search_impl(query, k)
    return json.dumps(results, ensure_ascii=False)


@tool
async def fetch_url(url: str) -> str:
    """URL에서 페이지 본문을 가져온다 (최대 500자 excerpt).
    url: 가져올 페이지 URL"""
    try:
        return await _fetch_url_impl(url)
    except Exception as e:
        return f"fetch_url 실패: {e}"
