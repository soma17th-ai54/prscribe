# DATA CONTRACTS — Pydantic Schemas (Source of Truth)

> 본 문서는 모든 Agent 간 hand-off 의 **단일 진실 원천**입니다.
> 코드를 변경하기 전에 본 문서를 먼저 갱신하고 PR을 올립니다.

## 0. 표기 규약

- 모든 필드명은 `snake_case`
- 시간은 UTC ISO-8601 (`datetime.isoformat()`)
- ID는 가능한 한 GitHub의 자연 ID(`repo/owner#PR`)를 그대로 사용
- 선택 필드는 `Optional[T] = None`, **빈 리스트는 의미 있는 fallback**(불확실 시 `None` 대신 `[]`)

---

## 1. Raw PR Data (GitHub API → Researcher 입력)

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

class CommitInfo(BaseModel):
    sha: str
    message: str
    author: str
    timestamp: str  # ISO-8601

class FileChange(BaseModel):
    path: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int
    patch: Optional[str] = None  # diff hunk; 너무 길면 None 후 chunked_patch 별도 보관

class LinkedIssue(BaseModel):
    number: int
    title: str
    body: Optional[str] = None
    labels: list[str] = []

class RawPRData(BaseModel):
    pr_identifier: str               # "owner/repo#142"
    title: str
    body: Optional[str] = None
    author: str
    base_branch: str
    head_branch: str
    state: Literal["open", "closed", "merged"]
    commits: list[CommitInfo]
    files: list[FileChange]
    linked_issues: list[LinkedIssue] = []
    fetched_at: str
```

---

## 2. ResearchResult (Researcher Agent 출력)

> 책임: PR에서 **확인 가능한 사실**만 추출. 추측 금지.

```python
class ChangedFunction(BaseModel):
    file: str
    function_name: str
    change_kind: Literal["added", "modified", "removed", "renamed"]
    summary: str  # 한 문장, "코드의 사실"만

class TechStackHint(BaseModel):
    name: str
    evidence: str  # 어느 파일/import에서 발견했는지

class FactBullet(BaseModel):
    """PR diff·commit·issue에서 직접 검증 가능한 사실 한 줄."""
    statement: str
    source: Literal["diff", "commit_message", "linked_issue"]
    source_locator: str  # "files[3].patch L12-L20" 또는 "commit:abcd1234"

class SearchChunk(BaseModel):
    """Context Agent가 외부 문서 검색에 사용할 키워드 묶음."""
    chunk_id: str
    keywords: list[str]            # 3~7개
    intent: Literal[
        "concept_lookup",          # 개념/용어
        "api_usage",               # 함수/메서드 사용법
        "best_practice",           # 권장 패턴
        "error_or_pitfall",        # 에러/주의사항
    ]
    related_files: list[str] = []

class ResearcherSelfEval(BaseModel):
    """Researcher 노드의 자기 채점 (별도 system prompt)."""
    coverage: float = Field(..., ge=0.0, le=1.0)        # changed (파일/함수) 중 facts에 매핑된 비율
    groundedness: float = Field(..., ge=0.0, le=1.0)    # facts 중 source_locator 검증 통과 비율
    chunk_quality: int = Field(..., ge=1, le=5)         # search_chunks 식별력 1~5
    confidence: int = Field(..., ge=1, le=5)            # 종합 1~5
    rationale: str                                       # G-Eval reasoning

class ResearchResult(BaseModel):
    pr_identifier: str
    summary_one_line: str
    changed_files: list[FileChange]
    changed_functions: list[ChangedFunction]
    tech_stack_hints: list[TechStackHint]
    facts: list[FactBullet]
    search_chunks: list[SearchChunk]
    notes: list[str] = []                       # 사람이 읽을 메모(선택)
    self_eval: Optional[ResearcherSelfEval] = None
```

> ⚠️ v0.3에서 `self_eval` 필드 추가. 별도 Evaluation Layer 폐기에 따라 각 에이전트가 자기 평가를 가진다.

---

## 3. ContextResult (Context Agent + Self-Eval 출력)

> v0.4 변경: 별도 Verification Layer 폐기 — Context Agent 의 ReAct 안에서 `compare_text_to_facts` tool 호출로 검증이 수행된다.
> 따라서 본 모델은 **Context Agent 한 노드** 의 단일 산출물이다.

```python
class Reference(BaseModel):
    chunk_id: str                  # 어느 SearchChunk에 답이 되는지
    title: str
    url: str
    source_kind: Literal["context7", "official_docs", "blog", "stackoverflow", "other"]
    excerpt: str                   # 100~500자
    fetched_at: str

class VerificationDecision(BaseModel):
    reference_url: str
    fact_id: Optional[str] = None  # 어떤 FactBullet과 비교했는지(있으면)
    verdict: Literal["consistent", "contradicts", "unrelated", "needs_review"]
    reasoning: str                 # 1~3문장

class ContextSelfEval(BaseModel):
    """Context Agent의 자기 채점."""
    coverage: float = Field(..., ge=0.0, le=1.0)        # = ContextResult.coverage 와 동일하나 이쪽이 SoT
    relevance: int = Field(..., ge=1, le=5)             # references가 PR 사실에 얼마나 관련있는지
    diversity: int = Field(..., ge=1, le=5)             # 출처(domain) 다양성
    confidence: int = Field(..., ge=1, le=5)            # 종합
    rationale: str

class ContextResult(BaseModel):
    pr_identifier: str
    raw_references: list[Reference]
    verified_references: list[Reference]      # verdict == "consistent" 만
    rejected_references: list[Reference] = [] # contradicts/unrelated
    verification_log: list[VerificationDecision]
    coverage: float = Field(..., ge=0.0, le=1.0)  # search_chunks 중 유효 reference가 붙은 비율
    self_eval: Optional[ContextSelfEval] = None
```

> ⚠️ v0.3에서 `self_eval` 필드 추가.

---

## 4. DraftResult (Writer Agent 최종 산출)

```python
class DraftSection(BaseModel):
    kind: Literal["intro", "problem", "cause", "solution", "result", "outro"]
    title: str
    body_markdown: str
    cited_references: list[str] = []  # Reference.url

class ChecklistItem(BaseModel):
    name: str
    passed: bool
    detail: Optional[str] = None

class JudgeScore(BaseModel):
    """Writer self-evaluation 결과 (단일 차원)."""
    dimension: Literal["accuracy", "readability", "structure", "code_explanation"]
    score: int = Field(..., ge=1, le=5)
    rationale: str             # G-Eval 스타일

class WriterSelfEval(BaseModel):
    """Writer 노드의 자기 채점. 별도 system prompt + 다른 페르소나."""
    checklist: list[ChecklistItem]
    checklist_pass_rate: float = Field(..., ge=0.0, le=1.0)
    judge_scores: list[JudgeScore]
    judge_average: float
    overall_grade: Literal["A", "B", "C", "D", "F"]
    suggestions: list[str] = []

class DraftResult(BaseModel):
    pr_identifier: str
    title: str                    # 블로그 제목
    sections: list[DraftSection]
    full_markdown: str            # 합쳐진 최종 본문
    word_count: int
    code_block_count: int
    revision: int = 0             # self-reflection으로 몇 번 수정됐는지
    self_eval: Optional[WriterSelfEval] = None
```

> ⚠️ v0.3에서 `self_eval` 필드 추가. 기존 EvaluationResult 가 본 모델로 이전·축소됨.

---

## 5. VerificationResult (Writer Self-Reflection 출력)

```python
class IssueFinding(BaseModel):
    kind: Literal[
        "missing_fact",        # PR에 있는 중요한 사실이 본문에 없음
        "ungrounded_claim",    # 본문에 있는 주장이 PR 또는 verified_reference에 근거 없음
        "code_under_explained",
        "structure_violation", # 4-Act 구조 위반
        "tone_mismatch",
        "other",
    ]
    section_kind: Optional[Literal["intro","problem","cause","solution","result","outro"]] = None
    quote: str                 # 문제가 된 본문 인용(50자 이내)
    suggestion: str            # 수정 제안

class VerificationResult(BaseModel):
    pr_identifier: str
    iteration: int             # 1, 2 (최대 2회)
    findings: list[IssueFinding]
    auto_patched: bool         # Writer가 같은 노드 안에서 자동 수정했는지
    needs_human_review: bool   # 자동 수정 불가 → 평가 페널티에만 반영
```

---

## 6. ~~EvaluationResult~~ (DEPRECATED — v0.3에서 폐기)

> v0.2까지 별도 노드의 결과 모델이었음.
> v0.3에서 평가가 각 에이전트의 self-eval로 분산되며 다음과 같이 이전됨:
> - 자동 체크리스트 / 4-dim judge / grade → [`WriterSelfEval`](#4-draftresult-writer-agent-최종-산출) (DraftResult.self_eval)
> - 사실 추출 품질 → [`ResearcherSelfEval`](#2-researchresult-researcher-agent-출력) (ResearchResult.self_eval)
> - 검색 결과 품질 → [`ContextSelfEval`](#3-contextresult-context-agent--verification-layer-출력) (ContextResult.self_eval)
>
> 호환성: 기존 코드가 `EvaluationResult` 를 import하면 deprecation warning 후
> `WriterSelfEval` 로 alias한다 (한 사이클 = Day 5까지).

---

## 7. Orchestrator State (LangGraph StateGraph 전체 상태)

```python
class GraphState(BaseModel):
    pr_identifier: str
    raw: Optional[RawPRData] = None
    research: Optional[ResearchResult] = None      # research.self_eval 포함
    context: Optional[ContextResult] = None        # context.self_eval 포함
    draft: Optional[DraftResult] = None            # draft.self_eval 포함 (= grade 노출용)
    verifications: list[VerificationResult] = []   # reflection iteration 누적
    errors: list[str] = []
    trace: list[dict] = []     # 노드명/입력요약/출력요약/wall-clock
    react_traces: list["ReActTrace"] = []   # ReAct 노드별 step-by-step 기록
```

> v0.3: `evaluation` 필드 제거. self-eval 결과는 각 단계 산출물 안에 포함된다.

---

## 8. ReAct / Tool 스키마 (Researcher / Context / Verification / Self-verify 공통)

> [AGENT-PATTERNS.md](./AGENT-PATTERNS.md)에서 정의한 Tool들의 hand-off 데이터 구조.

```python
from typing import Any

class ToolCall(BaseModel):
    """LLM이 발화한 1개 tool 호출."""
    name: str                           # 예: "grep_pr"
    args: dict[str, Any]                # Pydantic 입력 스키마와 호환
    args_hash: str                      # sha1(json.dumps(args, sort_keys=True))
    issued_at: str

class Observation(BaseModel):
    """Tool 실행 결과."""
    ok: bool
    output: Any                          # tool별 정의된 출력
    error: Optional[str] = None
    duration_ms: int

class ReActStep(BaseModel):
    """루프 1회분."""
    i: int                               # 1-based step index
    thought: str                         # LLM의 자연어 추론 (≤ 800자)
    action: Optional[ToolCall] = None    # final-answer 만 한 step이면 None
    observation: Optional[Observation] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class ReActTrace(BaseModel):
    """한 ReAct 노드의 전체 실행 기록."""
    node: Literal["researcher", "context", "self_reflection"]   # v0.4: verification 노드 폐기, self_verification → self_reflection 으로 통일
    pr_identifier: str
    steps: list[ReActStep]
    stopped_by: Literal[
        "finish_tool", "give_up_tool", "no_tool_call",
        "iteration_limit", "loop_detected", "timeout", "error",
    ]
    final_output: Optional[dict] = None  # finish() 의 output_json
    tokens_input: int = 0
    tokens_output: int = 0
    wall_clock_ms: int = 0
```

### 8.1 ToolRegistry (코드 차원)

```python
class ToolSpec(BaseModel):
    name: str
    input_model: type[BaseModel]         # Pydantic
    handler: Any                         # callable
    description: str                     # LLM에게 노출되는 docstring
    side_effect: Literal["none", "external_io", "write"] = "none"
    cost_hint: Literal["cheap", "medium", "expensive"] = "cheap"
    available_to: list[Literal[
        "researcher", "context", "self_reflection"   # v0.4: verification 폐기 / self_verification → self_reflection
    ]]
```

`available_to` 화이트리스트로 **Writer/Evaluation에 누출되지 않음**을 보장한다.

---

## 9. 호환성 정책

- **하위호환**: 새 필드는 기본값을 제공해야 한다.
- **삭제**: 한 사이클(=한 Day) deprecation warning을 남기고 제거한다.
- **JSON Schema 출력**: `python -m specs.tools.export_schema` 로 `specs/00-common/schemas/*.json` 자동 생성. (Day 4까지 구현)

## 10. 레퍼런스

- [Pydantic v2 — Models](https://docs.pydantic.dev/latest/concepts/models/)
- [LangGraph — State](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
