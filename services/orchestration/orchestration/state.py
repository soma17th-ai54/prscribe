from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    # ── 입력 ────────────────────────────────────────
    pr_url: str
    pr_number: int | None

    # ── 노드 출력 ────────────────────────────────────
    research: dict[str, Any]   # ResearchResult.model_dump()
    context: dict[str, Any]    # ContextResult.model_dump()
    draft: dict[str, Any]      # DraftResult.draft.model_dump()
    verifications: list[dict[str, Any]]

    # ── 공유 메타 ────────────────────────────────────
    react_traces: list[Any]
    errors: list[str]
