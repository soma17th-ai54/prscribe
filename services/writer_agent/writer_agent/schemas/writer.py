from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str
    timestamp: str


class FileChange(BaseModel):
    path: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    patch: str | None = None


class ChangedFunction(BaseModel):
    file: str
    function_name: str
    change_kind: Literal["added", "modified", "removed", "renamed"]
    summary: str


class TechStackHint(BaseModel):
    name: str
    evidence: str


class FactBullet(BaseModel):
    statement: str
    source: Literal["diff", "commit_message", "linked_issue"]
    source_locator: str


class SearchChunk(BaseModel):
    chunk_id: str
    keywords: list[str]
    intent: Literal["concept_lookup", "api_usage", "best_practice", "error_or_pitfall"]
    related_files: list[str] = Field(default_factory=list)


class ResearcherSelfEval(BaseModel):
    coverage: float = Field(..., ge=0.0, le=1.0)
    groundedness: float = Field(..., ge=0.0, le=1.0)
    chunk_quality: int = Field(..., ge=1, le=5)
    confidence: int = Field(..., ge=1, le=5)
    rationale: str


class ResearchResult(BaseModel):
    pr_identifier: str
    summary_one_line: str
    changed_files: list[FileChange]
    changed_functions: list[ChangedFunction]
    tech_stack_hints: list[TechStackHint]
    facts: list[FactBullet]
    search_chunks: list[SearchChunk]
    notes: list[str] = Field(default_factory=list)
    self_eval: ResearcherSelfEval | None = None


class Reference(BaseModel):
    chunk_id: str
    title: str
    url: str
    source_kind: Literal["context7", "official_docs", "blog", "stackoverflow", "other"]
    excerpt: str
    fetched_at: str


class VerificationDecision(BaseModel):
    reference_url: str
    fact_id: str | None = None
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
    self_eval: ContextSelfEval | None = None


class DraftSection(BaseModel):
    kind: Literal["intro", "problem", "cause", "solution", "result", "outro"]
    title: str
    body_markdown: str
    cited_references: list[str] = Field(default_factory=list)


class ChecklistItem(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class JudgeScore(BaseModel):
    dimension: Literal["accuracy", "readability", "structure", "code_explanation"]
    score: int = Field(..., ge=1, le=5)
    rationale: str


class WriterSelfEval(BaseModel):
    checklist: list[ChecklistItem]
    checklist_pass_rate: float = Field(..., ge=0.0, le=1.0)
    judge_scores: list[JudgeScore]
    judge_average: float
    overall_grade: Literal["A", "B", "C", "D", "F"]
    suggestions: list[str] = Field(default_factory=list)


class DraftResult(BaseModel):
    pr_identifier: str
    title: str
    sections: list[DraftSection]
    full_markdown: str
    word_count: int
    code_block_count: int
    revision: int = 0
    self_eval: WriterSelfEval | None = None


class IssueFinding(BaseModel):
    kind: Literal[
        "missing_fact",
        "ungrounded_claim",
        "code_under_explained",
        "structure_violation",
        "tone_mismatch",
        "other",
    ]
    section_kind: Literal["intro", "problem", "cause", "solution", "result", "outro"] | None = None
    quote: str
    suggestion: str


class VerificationResult(BaseModel):
    pr_identifier: str
    iteration: int
    findings: list[IssueFinding]
    auto_patched: bool
    needs_human_review: bool


class FactDiffMatch(BaseModel):
    file: str
    line_text: str
    score: float = Field(..., ge=0.0, le=1.0)


class FactDiffVerification(BaseModel):
    statement: str
    verdict: Literal["consistent", "needs_review"]
    matches: list[FactDiffMatch] = Field(default_factory=list)
    reasoning: str


class WriterRunResult(BaseModel):
    draft: DraftResult
    verifications: list[VerificationResult] = Field(default_factory=list)


EvaluationResult = WriterSelfEval
