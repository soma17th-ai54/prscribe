from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


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


class LinkedIssue(BaseModel):
    number: int
    title: str
    body: str | None = None
    labels: list[str] = Field(default_factory=list)


class RawPRData(BaseModel):
    pr_identifier: str
    title: str
    body: str | None = None
    author: str
    base_branch: str
    head_branch: str
    state: Literal["open", "closed", "merged"]
    commits: list[CommitInfo]
    files: list[FileChange]
    linked_issues: list[LinkedIssue] = Field(default_factory=list)
    fetched_at: str


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

    @field_validator("keywords")
    @classmethod
    def keywords_should_be_useful(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("search chunk keywords must not be empty")
        return value[:7]


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


class GitHubToolRequest(BaseModel):
    tool_name: Literal[
        "read_pr_file",
        "fetch_dependency_manifest",
        "fetch_readme",
    ]
    reason: str
    path: str | None = None
    ref: Literal["head", "base"] = "head"
    start_line: int | None = None
    end_line: int | None = None


class ExtraContextPlan(BaseModel):
    requests: list[GitHubToolRequest] = Field(default_factory=list)


class GitHubToolResult(BaseModel):
    tool_name: str
    reason: str
    path: str | None = None
    ok: bool
    output: Any = None
    error: str | None = None
