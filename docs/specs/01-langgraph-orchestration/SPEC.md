# SPEC — LangGraph Orchestration

**담당:** 조재영 (Context Agent도 동일 담당 — [03-context-agent](../03-context-agent/SPEC.md))
**디렉토리:** `01-langgraph-orchestration/`
**관련 기획서 섹션:** §2.2 (LangGraph Orchestrator), §3.4 (시스템 워크플로우), §4.2 (오케스트레이션 계층)

> **변경 이력 (v0.4):** Verification Layer 노드 폐기 → Context Agent 안으로 흡수.
> 본 그래프는 이제 **3-노드 골격**(Researcher → Context → Writer) + `fetch_github` 진입 노드.

> **v0.3:** 별도 `evaluation` 노드 폐기 (각 에이전트 self-eval 분산)
> **v0.2:** Researcher / Context / Verification(당시) / Self-verify 부분 ReAct화

---

## 1. 목적 (Goal)

Researcher / Context / Writer 세 단계를 **LangGraph StateGraph** 로 묶어
**순서·상태·실패·재시도·관측·체크포인트**를 일관되게 책임진다.
모든 Agent는 본 모듈을 통해서만 호출되며, **Agent 간 직접 호출은 금지**한다.
별도 Verification / Evaluation 노드는 **없다** — 검증은 Context Agent 내부, 평가는 각 에이전트 self-eval에서 이미 끝났다.

## 2. 조재영의 두 책임 (이 SPEC + 03-context-agent)

조재영은 **흐름 통제**와 **그 흐름 안에서 가장 복잡한 단일 노드**를 함께 맡는다.
이 둘은 자연스럽게 연결된다 — Orchestrator가 어떤 reducer / retry / streaming 을 쓰는지가
Context Agent의 ReAct 구현 방식을 결정하기 때문이다.

| 영역 | SPEC | 핵심 산출 |
|------|------|----------|
| 그래프 골격 / 상태 / 체크포인터 / retry / streaming | 본 SPEC (01) | `app = graph.compile(...)` |
| Context Agent 노드 내부 ReAct + 검증 흡수 + self-eval | [03-context-agent SPEC](../03-context-agent/SPEC.md) | `context_node(state) -> {"context": ContextResult}` |

## 3. 입력 / 출력 계약

### 입력
- `pr_identifier: str` (예: `"openai/whisper#142"` 또는 PR URL)
- 옵션: `config: GraphConfig` (체크포인터 종류, reflection 최대, retry 정책)

### 출력
- `GraphState` ([DATA-CONTRACTS §7](../00-common/DATA-CONTRACTS.md#7-orchestrator-state-langgraph-stategraph-전체-상태))
- 각 노드 산출물의 `self_eval` 필드 동봉 (Researcher / Context / Writer)
- 부산물: `trace: list[dict]`, `react_traces: list[ReActTrace]`

## 4. 핵심 책임

✅ **이 모듈이 하는 일**
- StateGraph 정의 및 컴파일
- 노드 등록 (각 Agent를 비-부수효과적 함수로 wrap)
- 조건부 엣지 (실패 / coverage 분기)
- Retry policy
- Checkpointer 연동 (MVP: `MemorySaver`)
- Trace/Observability 데이터 수집 + LangGraph stream API 노출
- E2E 타임아웃·취소 처리

❌ **명시적으로 하지 않는 일**
- Agent 내부 로직 (각 Agent SPEC가 책임)
- LLM 직접 호출 (Agent 안에서 처리)
- Self-evaluation (각 Agent 내부 책임)
- 사용자 인증·HTTP 라우팅 (05-backend)

## 5. 그래프 정의

### 5.1 노드 (총 4개: 결정적 1 + 에이전트 3)

| 노드명 | 함수 시그니처 | 패턴 | 비고 |
|--------|--------------|------|------|
| `fetch_github` | `(state) -> {"raw": RawPRData}` | 결정적 | 05-backend `github_client.fetch_pr` 래핑 |
| `researcher` | `(state) -> {"research": ResearchResult, "react_traces": [...]}` | **Tool-using ReAct + 내부 self-eval** | 02 SPEC |
| `context` | `(state) -> {"context": ContextResult, "react_traces": [...]}` | **풀 ReAct (per-chunk) + Verification 흡수 + self-eval** | 03 SPEC |
| `writer` | `(state) -> {"draft": DraftResult, "verifications": [...]}` | **Workflow + reflection + self-eval (grade A~F)** | 04 SPEC |

> 별도 `verification` 노드는 v0.4에서 사라졌다 — Context Agent의 ReAct 안에서 `compare_text_to_facts` tool 호출로 대체.

### 5.2 엣지

```
START
  └─► fetch_github
        ├─error─► END(error=GitHubFetchFailed)
        └─ok────► researcher
                    └─► context
                          ├─[coverage<0.2]─► writer  (mode=minimal_context)
                          └─[coverage≥0.2]─► writer  (mode=full)
                                                └─► END
```

### 5.3 의사코드

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import RetryPolicy

graph = StateGraph(GraphState)

graph.add_node("fetch_github", fetch_github_node)
graph.add_node("researcher",   researcher_node, retry=RetryPolicy(max_attempts=2))
graph.add_node("context",      context_node,    retry=RetryPolicy(max_attempts=3))
graph.add_node("writer",       writer_node,     retry=RetryPolicy(max_attempts=2))

graph.add_edge(START, "fetch_github")

def after_fetch(state):
    return END if state.errors else "researcher"

graph.add_conditional_edges("fetch_github", after_fetch,
                             {END: END, "researcher": "researcher"})
graph.add_edge("researcher", "context")

def writer_mode(state):
    cov = state.context.coverage if state.context else 0.0
    return "writer_minimal" if cov < 0.2 else "writer"

graph.add_conditional_edges("context", writer_mode,
                             {"writer_minimal": "writer", "writer": "writer"})

graph.add_edge("writer", END)

app = graph.compile(checkpointer=MemorySaver())
```

> `writer_minimal` 분기는 단일 `writer` 노드 안에서 `state.minimal_context_mode` 플래그로 구현.

## 6. State 관리

- 각 노드는 **부분 dict** 만 반환 (LangGraph reducer가 머지).
- `errors`, `trace`, `react_traces` 는 **append 전용 reducer**.
- `verifications` 는 reflection iteration별 누적 (Writer 노드 안).
- `pr_identifier` 는 불변.

## 7. Checkpointer

| 환경 | Saver | 비고 |
|------|-------|------|
| Local Dev / Demo | `MemorySaver` | 프로세스 종료 시 사라짐. MVP에 충분. |
| Production (참고) | `AsyncPostgresSaver` | 발표 자료에서 "교체 가능"만 언급. |

`thread_id` = `pr_identifier`.

## 8. Retry & Fallback 정책

| 노드 | 외부 retry | 내부 ReAct / reflection 한계 | 사유 |
|------|-----------|------------------------------|------|
| `fetch_github` | exponential backoff, 3회 | — | rate limit / transient |
| `researcher` | 2회 | `recursion_limit=8`, `max_tool_calls=6`, `timeout=20s` + self_eval 1회 | 탐색 폭주 방지 |
| `context` (per chunk) | 3회 | `recursion_limit=6`, `max_tool_calls=4`, `timeout=12s` + context self_eval 1회 | 외부 검색 불안정 |
| `writer` | 2회 | reflection ≤ 2회 + self_eval 1회 | LLM 빈출력 회피 |

> 청크별 Context ReAct는 `asyncio.gather(return_exceptions=True)` — 한 청크 실패가 다른 청크를 막지 않는다.
> Self-eval 실패는 외부 retry에 포함되지 않으며, 실패 시 `self_eval=None`.

## 9. 관측성

- 모든 노드는 시작/종료 시 `state.trace`에 append:
  ```json
  {
    "node": "context",
    "started_at": "...",
    "ended_at": "...",
    "duration_ms": 5421,
    "input_summary": "5 chunks",
    "output_summary": "verified=4 rejected=1 coverage=0.83",
    "self_eval_summary": "confidence=4, relevance=4, diversity=3",
    "error": null
  }
  ```
- ReAct 노드는 추가로 `state.react_traces`에 [`ReActTrace`](../00-common/DATA-CONTRACTS.md#8-react--tool-스키마-researcher--context--self-verify-공통) append.
- LangGraph stream API (`app.stream(..., stream_mode="updates")`) 로 UI 실시간 trace.
- 에러는 `state.errors`.

## 10. 실패 모드

| 상황 | 처리 |
|------|------|
| GitHub API 실패 | END + `errors=["GitHubFetchFailed: ..."]` |
| Researcher 빈 결과 | minimal `ResearchResult` (facts=[]) + `self_eval.confidence=1`, 진행하되 Writer는 추측 금지 모드 |
| Context coverage < 0.2 | Writer minimal 모드 |
| Context 5개 청크 모두 give_up | coverage=0 + Writer minimal 모드, UI에 경고 |
| Writer 출력 스키마 위반 | 1회 재시도 후 템플릿 fallback |
| Self-reflection 무한 루프 | iteration 2 도달 시 강제 종료, `needs_human_review=True` |
| Self-eval 실패 | `self_eval=None` 으로 진행, UI 배지 |
| 전체 타임아웃 (예: 90s) | `asyncio.timeout` 취소, 부분 상태 반환 |

## 11. 테스트 전략

- **단위:** 노드 함수마다 mock state/mock client로 입출력 형 검증.
- **그래프 통합:** 가짜 노드 4개로 그래프 컴파일 → END 도달.
- **회귀:** 샘플 PR 5개 → `app.invoke()` 결과 스냅샷 (`DraftResult.full_markdown` SHA + `draft.self_eval.overall_grade` + `context.coverage`).
- **실패 주입:** GitHub mock 4xx/5xx → END + error.
- **체크포인터:** 동일 `thread_id` 재실행 시 마지막 상태 복원.
- **분기 검증:** `coverage<0.2` 합성 → Writer가 `mode=minimal_context` 로 호출되는지.

## 12. Open Questions / TODO

- [ ] PR이 너무 큰 경우 (≥ 50 파일) Researcher만 chunk-streaming?
- [ ] (Post-MVP) Writer self-eval grade < D 시 Writer 재진입
- [ ] (Post-MVP) Context coverage < 0.3 시 Researcher에게 키워드 재생성 요청 — orchestrator-level evaluator-optimizer

## 13. 레퍼런스

- [LangGraph — Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph — Persistence & Checkpointer](https://github.com/langchain-ai/langgraph)
- [LangGraph — Error handling and retry policies](https://deepwiki.com/langchain-ai/langgraph/3.7-error-handling-and-retry-policies)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [Anthropic — Reflection / Evaluator-Optimizer](https://www.anthropic.com/research/building-effective-agents)
- [00-common/AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md)
- [03-context-agent/SPEC.md](../03-context-agent/SPEC.md)
