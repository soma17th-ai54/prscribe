from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from researcher_agent.schemas.research import (  # noqa: F401 — re-exported for internal use
    FactBullet,
    ResearchResult,
    SearchChunk,
)


class Reference(BaseModel):
    chunk_id: str
    title: str
    url: str
    source_kind: Literal["context7", "official_docs", "blog", "stackoverflow", "other"]
    excerpt: str
    fetched_at: str


class VerificationDecision(BaseModel):
    reference_url: str
    fact_id: Optional[str] = None
    verdict: Literal["consistent", "contradicts", "unrelated", "needs_review"]
    reasoning: str


class ContextSelfEval(BaseModel):
    coverage: float = Field(..., ge=0.0, le=1.0)
    relevance: int = Field(..., ge=1, le=5)
    diversity: int = Field(..., ge=1, le=5)
    confidence: int = Field(..., ge=1, le=5)
    rationale: str


class ContextResult(BaseModel):
    pr_identifier: str
    raw_references: list[Reference]
    verified_references: list[Reference]
    rejected_references: list[Reference] = Field(default_factory=list)
    verification_log: list[VerificationDecision]
    coverage: float = Field(..., ge=0.0, le=1.0)
    self_eval: Optional[ContextSelfEval] = None
