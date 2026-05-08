from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ── Researcher Agent 스키마 stub ──────────────────────────────────────────────
# PR #2 (feat/researcher-agent) merge 후 아래 import로 교체:
#   from researcher_agent.schemas.research import (
#       FactBullet, SearchChunk, ResearchResult
#   )


class FactBullet(BaseModel):
    statement: str
    source: Literal["diff", "commit_message", "linked_issue"]
    source_locator: str


class SearchChunk(BaseModel):
    chunk_id: str
    keywords: list[str]
    intent: Literal["concept_lookup", "api_usage", "best_practice", "error_or_pitfall"]
    related_files: list[str] = Field(default_factory=list)

    @field_validator("keywords")
    @classmethod
    def keywords_should_be_useful(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("search chunk keywords must not be empty")
        return value[:7]


class ResearchResult(BaseModel):
    """PR #2 merge 후 researcher_agent.schemas.research.ResearchResult로 교체."""
    pr_identifier: str
    summary_one_line: str = ""
    facts: list[FactBullet] = Field(default_factory=list)
    search_chunks: list[SearchChunk] = Field(default_factory=list)


# ── Context Agent 전용 스키마 ────────────────────────────────────────────────


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
