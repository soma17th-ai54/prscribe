# AGENT-PATTERNS — Workflow vs ReAct, Tool Inventory, 루프 통제

> 본 문서는 [AGENTIC-EVALUATION.md](./AGENTIC-EVALUATION.md)의 **개선 권고를 실제 SPEC에 반영**하기 위한
> 공통 가이드입니다. 각 Agent SPEC은 본 문서를 인용하며, 본 문서 변경은 [CHANGELOG.md](./CHANGELOG.md)에 기록합니다.

---

## 1. 패턴 결정 매트릭스

기획서 초기 설계는 거의 전부 **Prompt Chaining + Evaluator-Optimizer**(=Workflow)였습니다.
이를 Anthropic의 *Building Effective AI Agents* 권고에 맞춰 **부분 ReAct화** 합니다.
"전부 Agent"가 아니라 **필요한 곳만 Agent**가 되는 것이 핵심입니다.

| Agent | 결정 | 근거 |
|-------|------|------|
| **Researcher** (02) | **Tool-using ReAct + 내부 self-eval** | 코드 탐색은 본질적으로 동적. 출력 품질은 자체 채점 |
| **Context Agent** (03) | **풀 ReAct (per-chunk) + 검증 흡수 + 내부 self-eval** | 검색→검증→재검색이 한 ReAct에서 자연스럽게 흐름. `compare_text_to_facts` tool로 검증 |
| **Writer** (04) | **Workflow + reflection ≤2회 + self-eval (grade A~F)** | 글 생성은 일관성 우선. Reflection은 수정용, self-eval은 등급용 (분리) |
| ~~Verification Layer (별도 노드)~~ | **v0.4에서 Context Agent로 흡수** | 별도 노드 가치보다 자연스러운 흐름이 우선 |
| ~~Self-verification (별도 디렉토리)~~ | **v0.3에서 Writer 내부 reflection으로 흡수** | 같은 노드 안 reflection으로 통합 |
| ~~Evaluation Layer~~ | **v0.3에서 폐기 — 각 에이전트 self-eval로 분산** | "평가가 행동에 피드백되지 않으면 회고일 뿐" |

> 결론: 본 시스템의 정확한 분류는
> **"Prompt Chaining 골격 + Evaluator-Optimizer 루프(Writer 내부) + 부분 ReAct 노드 3개(Researcher/Context/Verification)"**
> = **Anthropic 5 Workflow 패턴 + Autonomous Agent 부분 도입의 합성** 입니다.

---

## 2. ReAct 루프 표준 정의

본 프로젝트의 ReAct 노드는 **모두 동일한 골격**을 따릅니다.

```
loop:
  Thought  → LLM이 다음 행동을 자연어로 추론
  Action   → tool_call 1개 (또는 final_answer)
  Observe  → tool 결과를 messages에 ToolMessage로 추가
  종료조건 검사
```

LangGraph 구현은 [`langgraph.prebuilt.create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)를 1순위로 사용하고,
세밀 제어가 필요하면 `StateGraph` 직접 작성으로 폴백합니다.

### 2.1 Step Budget (필수, v0.4)

| Agent | `recursion_limit` | `max_tool_calls` | timeout |
|-------|------------------:|-----------------:|--------:|
| Researcher (02) | 8 | 6 | 20s |
| Context Agent (03, per chunk) | 6 | 4 | 12s |
| Writer self_reflection (04) | 3 | 2 | 8s |

> v0.4 변경: 별도 Verification 노드 폐기에 따라 그 항목이 사라짐. Context Agent의 step budget이 verdict 호출까지 모두 책임지도록 `max_tool_calls=4` 유지 (search 1~2 + compare 1 + finish 1).

> Anthropic/IBM의 권고: 단일 사용자 요청이 3~7 reasoning-action 사이클을 일으킨다 — 본 값은 그 범위에 정렬.

### 2.2 종료 조건 (Termination Criteria, 5종 모두 적용)

1. **Iteration Limit**: 위 표의 `recursion_limit` 도달 → 즉시 종료
2. **Explicit Finish Tool**: 모델이 `finish(reason, output)` 도구를 호출 → 정상 종료
3. **No Tool Call**: LLM이 도구 없이 final answer 텍스트만 반환 → 정상 종료
4. **Loop Detection**: 동일 (tool_name, args_hash) 가 **연속 2회** 또는 누적 3회 호출되면 즉시 종료 + 페널티 finding
5. **Confidence Gate**: 모델이 `confidence ≥ 0.85` 라고 자체 보고하고 `final_answer` 호출 시 종료

> Loop Detection은 본 프로젝트의 **자체 보강** — Anthropic은 이를 "trajectory dedup"이라 부르고,
> 무한 루프 방지에 가장 비용이 적은 방법입니다.

### 2.3 Scratchpad (정상 동작 추적)

각 ReAct 노드는 다음을 누적합니다 (DATA-CONTRACTS §8 참조).

```python
scratchpad: list[ReActStep] = [
  ReActStep(thought="...", action=ToolCall(name="grep", args={...}), observation="...", confidence=0.7),
  ...
]
```

종료 시 LangGraph state의 `trace`에 압축본(처음 200자/스텝)이 들어갑니다.

---

## 3. Tool Catalog (단일 진실원천)

모든 Tool은 **Pydantic input schema** + **단일 책임** + **결정성 우선**으로 구현됩니다.
Tool 이름은 `snake_case`, 부수효과(쓰기) 가지면 `_write` 접미사.

### 3.1 PR / Codebase Tools (Researcher / Self-verification)

| 이름 | 입력 | 출력 | 부수효과 | 비고 |
|------|------|------|----------|------|
| `read_pr_file(path: str, range: tuple[int,int] \| None)` | path, line range | 텍스트 | 없음 | RawPRData에 캐시된 파일만 |
| `grep_pr(pattern: str, glob: str = "*")` | regex, 파일 글롭 | match[]: file/line/text | 없음 | 모든 ReAct에 노출 |
| `list_pr_files()` | — | FileChange[] | 없음 | RawPRData 사본 |
| `get_commit_message(sha: str)` | sha | str | 없음 | |
| `get_linked_issue(number: int)` | number | LinkedIssue | 없음 | 없으면 `None` |
| `verify_fact_in_diff(statement: str)` | 문장 | match[] + verdict | 없음 | self-verify 전용 |

### 3.2 External Knowledge Tools (Context Agent / Verification)

| 이름 | 입력 | 출력 | 비고 |
|------|------|------|------|
| `context7_search(library: str, topic: str, k: int = 3)` | 라이브러리/주제 | Reference[] | Context7 MCP 우선 |
| `web_search(query: str, k: int = 5)` | 쿼리 | Reference[] | DDG/일반 검색 폴백 |
| `fetch_url(url: str)` | url | excerpt(≤500자) | 페이지 본문 |
| `compare_text_to_facts(excerpt: str, facts: list[str])` | excerpt + facts | verdict + reasoning | LLM-driven |

### 3.3 Termination Tools (모든 ReAct 공통)

| 이름 | 입력 | 의미 |
|------|------|------|
| `finish(reason: str, output_json: dict)` | 종료 사유 + 최종 출력 | 정상 종료 (선호) |
| `give_up(reason: str)` | 사유 | 비정상 종료 (페널티) |

`finish`/`give_up` 호출 시 LLM은 **이외의 텍스트 출력 금지** (LangGraph가 그대로 반환).

### 3.4 금지 / 미부여 Tool

| 시도 | 거부 이유 |
|------|----------|
| 파일 쓰기, git commit, GitHub write API | 자율성 범위 밖 (기획서 §2.4) |
| 임의 셸 명령(`bash`) | 보안 |
| Writer 본체 / 모든 self-eval에 검색 도구 | 책임 분리 — 그 시점에 사실은 이미 fixed |
| self-eval에 patch/rewrite 도구 | self-eval은 채점만. 수정은 self-reflection 단계의 책임 |

---

## 4. Pydantic 입력 스키마 표기 규약

```python
from pydantic import BaseModel, Field

class GrepPRInput(BaseModel):
    pattern: str = Field(..., description="Python regex. 5~120자")
    glob: str = Field("*", description="파일 글롭. 예: '*.py'")
```

- 모든 Tool 입력은 BaseModel 하위.
- LLM에 노출되는 docstring(`description`)이 **스펙의 일부**다 → 변경 시 CHANGELOG 기록.

---

## 5. ReAct 노드의 LangGraph 통합

### 5.1 Prebuilt 사용 (선호)

```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import StructuredTool

researcher_react = create_react_agent(
    model=solar_pro_chat_model,
    tools=[read_pr_file_tool, grep_pr_tool, list_pr_files_tool, finish_tool, give_up_tool],
    state_modifier=RESEARCHER_SYSTEM_PROMPT,    # 시스템 프롬프트
)

def researcher_node(state: GraphState) -> dict:
    out = researcher_react.invoke(
        {"messages": [HumanMessage(initial_prompt(state.raw))]},
        config={"recursion_limit": 8, "configurable": {"thread_id": state.pr_identifier}},
    )
    research_result = parse_finish_output(out)   # finish() 출력 → ResearchResult
    return {"research": research_result, "trace": [react_summary(out)]}
```

### 5.2 직접 StateGraph (fallback, 세밀 제어)

`recursion_limit`/`max_tool_calls`/`loop_detection` 을 자체 구현하고 싶을 때.
표준 골격은 [Phil Schmid — Agentic Patterns](https://www.philschmid.de/agentic-pattern) 참고.

---

## 6. 비결정성 통제 (Anthropic 권고)

| 위험 | 대응 |
|------|------|
| 같은 입력에 다른 결과 | LLM `temperature=0` (Researcher/Verification/Self-verify), Writer만 0.3 |
| Tool 비결정성 | `web_search` 결과는 timestamp+seed 캐시(15분) — 재실행 시 동일 |
| Token 폭주 | 각 ReAct에 `total_input_tokens` 회계, 한도 초과 시 `give_up` 강제 |
| Cost 폭주 | 모델 라우팅 — 가벼운 step은 `solar-mini`, 종합 판단만 `solar-pro` |

---

## 7. Trace / 관측성 요구

ReAct 노드는 다음을 반드시 trace에 남깁니다.

```json
{
  "node": "researcher",
  "react_steps": [
    {"i": 1, "thought_summary": "...", "tool": "grep_pr", "args_summary": "...", "obs_chars": 412},
    {"i": 2, "thought_summary": "...", "tool": "read_pr_file", "args_summary": "...", "obs_chars": 88},
    {"i": 3, "thought_summary": "...", "tool": "finish",   "args_summary": "...", "obs_chars": 0}
  ],
  "stopped_by": "finish_tool",
  "tokens": {"input": 4120, "output": 580},
  "wall_clock_ms": 8421
}
```

UI(06-frontend)는 이 trace를 펼침 카드로 표시합니다.

---

## 8. 안티패턴 (하지 말 것)

- ❌ **모든 Agent를 ReAct로 만들기** — Writer를 ReAct로 만들면 글이 들쭉날쭉해진다 (Anthropic 권고 위반).
- ❌ **Tool 이름·시그니처를 LLM에게만 알리고 SPEC 미반영** — drift의 원인.
- ❌ **`recursion_limit=∞`** — 비용 폭주.
- ❌ **finish 없이 자연어로 종료** 만 허용 — 출력 파싱 비결정성.
- ❌ **검색 도구를 Writer/모든 self-eval에 노출** — 책임 분리 위반.
- ❌ **self-eval과 self-reflection을 한 프롬프트에 합치기** — 채점과 수정은 다른 페르소나여야 함 (v0.3 핵심 결정).
- ❌ **self-eval을 Writer 본체와 같은 system prompt로 호출** — bias 공유 심해짐.

---

## 9. 점진 도입 일정 (7-Day MVP 안에서, v0.4)

| Day | 추가/변경 |
|-----|----------|
| Day 1 | Tool 인터페이스 정의(05-backend `tools/`), `read_pr_file`/`grep_pr`/`list_pr_files`/`finish`/`give_up` 구현 |
| Day 2 | **Context Agent 풀 ReAct (조재영)** — `context7_search`/`web_search`/`fetch_url`/`compare_text_to_facts` 노출. 검증이 흡수된 단일 노드 |
| Day 3 | Researcher 를 prompt-chain → Tool-using ReAct로 마이그레이션 (우재민). Writer 본체 + reflection + `verify_fact_in_diff` (정민기 + 김영표) |
| Day 4 | LangGraph Orchestration (조재영) — 3-노드 골격 + conditional edges + checkpointer + streaming |
| Day 5 | **각 에이전트 self-eval 추가** (Researcher / Context / Writer 4-dim+grade) + 골든셋 5~10개 채점 (홍지호) |
| Day 6 | Trace UI에 ReAct step + 단계별 self-eval 카드 추가 (06-frontend) |
| Day 7 | 발표: **"분산 self-evaluation + Workflow 골격 + 부분 ReAct + Verification 흡수"** 합성 강조 |

---

## 10. 레퍼런스

- [Anthropic — Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [LangGraph DeepWiki — ReAct Agent](https://deepwiki.com/langchain-ai/langgraph/8.1-react-agent-(create_react_agent))
- [IBM — What is a ReAct Agent?](https://www.ibm.com/think/topics/react-agent)
- [HuggingFace — Thought-Action-Observation Cycle](https://huggingface.co/learn/agents-course/en/unit1/agent-steps-and-structure)
- [Phil Schmid — Zero to One: Learning Agentic Patterns](https://www.philschmid.de/agentic-pattern)
- [Prompting Guide — ReAct](https://www.promptingguide.ai/techniques/react)
- [LangGraph Tutorial: Build a Working ReAct Agent (v1.0 API)](https://dev.to/agentsindex/langgraph-tutorial-build-a-working-react-agent-with-the-v10-api-3bc1)
