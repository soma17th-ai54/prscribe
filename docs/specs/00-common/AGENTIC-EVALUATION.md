# AGENTIC-EVALUATION — 본 시스템은 진짜 "에이전틱"한가?

> 기획서가 스스로를 *LangGraph 기반 Agentic Workflow* 라고 부르고 있는 만큼,
> 외부 레퍼런스 기준으로 그 주장을 검증하고 개선 방향을 제시합니다.
>
> **Update (v0.2):** 초안 분석 결과 시스템이 거의 전부 *Prompt Chaining + Evaluator-Optimizer* 였다.
> 이를 보완하기 위해 [AGENT-PATTERNS.md](./AGENT-PATTERNS.md)를 추가하고
> Researcher / Context / Verification / Self-verify 4개 노드를 **부분 ReAct화** 했다.
>
> **Update (v0.3):** v0.2의 약점이었던 "Evaluation 점수가 시스템 행동에 피드백되지 않음" 을
> 정면 수용 — 별도 Evaluation 노드를 **폐기**하고 평가를 **각 에이전트 내부 self-evaluation** 으로 분산했다.
> 자세한 사유 / 한계 / 분산 매핑은 §9 참조.
>
> **Update (v0.4):** Verification Layer 노드도 폐기 — Context Agent의 ReAct 안 `compare_text_to_facts` tool로 흡수.
> Context Agent 가 own SPEC(03) 으로 격상되었고, 조재영이 Orchestration(01)과 함께 담당. §10 참조.

## 1. 평가에 쓴 외부 정의

| 출처 | 핵심 정의 |
|------|----------|
| Anthropic — *Building Effective Agents* | **Workflow** = LLM·툴이 **사전 정의된 코드 경로**로 오케스트레이션됨. **Agent** = LLM이 **자기 프로세스와 툴 사용을 동적으로 결정**하며 루프 안에서 환경 피드백을 본다. |
| LangChain Docs — *Workflows and agents* | Workflow는 예측 가능성·일관성, Agent는 유연성·모델 주도 의사결정. 실제 시스템은 둘을 **합성** 한다. |
| IBM — *What are Agentic Workflows?* | Agentic의 핵심은 (1) 의사결정 권한, (2) 적응성, (3) 거버넌스 가능성. |
| ScienceDirect — *AI Agents vs Agentic AI* | 단일 LLM 호출이 아니라 다단계·도구 사용·자기 점검·외부 환경 상호작용이 있어야 "Agentic"으로 분류. |

본 시스템은 위 기준을 **부분적으로** 만족하는 **하이브리드(Workflow + 부분 Agent)** 입니다.
이는 결함이 아니라 MVP에 적절한 선택이지만, **솔직하게 표현**해야 학회·발표 자리에서 과장 비판을 피할 수 있습니다.

## 2. 차원별 평가

| 차원 | 본 시스템 | 평가 | 근거 |
|------|-----------|------|------|
| 도구 사용을 LLM이 **동적으로** 결정 | ❌ (사전 정의된 그래프) | Workflow 성격 | Researcher → Context → Writer 순서 고정 |
| 환경 피드백 루프 | △ (Self-verification 1개 루프) | 부분 Agent | Anthropic의 *evaluator-optimizer* 패턴에 해당 |
| 자기 비판 / 반성 | ✅ (Writer self-verification) | Agent | reflection 패턴 채택 |
| 인간 개입(HITL) | △ (UI에서 사람이 최종 발행) | 거버넌스 OK | 자동 발행 제외는 의도적 선택 |
| 외부 지식 검색 적응 | ✅ (Context7 MCP, 청크별 검색) | Agent | 청크당 검색 키워드를 LLM이 생성 |
| 다중 시도 / 재계획 | △ (self-verification ≤ 2회) | 약한 Agent | 더 강화 가능 |
| 안전한 행위 한계 | ✅ (코드 수정·자동 발행 제외) | 거버넌스 우수 | §2.4 자율성 범위 명확 |

요약: **"Prompt Chaining 골격 + Evaluator-Optimizer 반복(Writer 내부) + 부분 ReAct 노드 3개(Researcher / Context / Verification) + 1-step ReAct(Self-verify)"** 의
**합성 패턴**. 이는 Anthropic이 권장하는 *"패턴을 합성하라 — 필요한 곳에만 Agent를 도입하라"* 와 정확히 일치합니다.

> **정정:** 초안 SPEC v0.1에서는 Researcher/Context/Verification 도 Workflow였습니다(=Prompt Chaining만).
> 사용자 피드백을 반영해 v0.2에서 ReAct화했습니다.
> 이로써 본 시스템은 **Anthropic 5 Workflow 패턴 + Autonomous Agent(부분)** 의 합성으로 격상되었습니다.

## 3. 진단: 무엇이 충분히 Agentic하고, 무엇이 아닌가

### ✅ 잘 한 점
1. **단일 거대 프롬프트 회피**: §2.2에서 "하나의 프롬프트에 모든 작업을 맡기는 방식이 아니라" 라고 명시 → Anthropic이 강조하는 **단일 책임 에이전트**.
2. **Reflection 내장**: Writer self-verification은 *Reflection / Evaluator-Optimizer* 의 정식 적용.
3. **거버넌스 명확**: 자동 발행·코드 수정 금지가 §2.4에 분명히 적혀 있음 → 학회 측에서 가장 좋아하는 부분.
4. **사실/추측 분리**: Researcher가 "사실만", Writer가 "서사", Self-verify가 "검증" — 책임 분담이 깨끗함.
5. **구조화 출력**: Pydantic + JSON Schema 강제 → hand-off 안정성 확보.

### ⚠️ 약한 곳 / 개선 권장

| 약점 | 개선 방향 (난이도) |
|------|-------------------|
| Context Agent가 검색 **키워드는 동적으로 만들지만 검색 횟수/깊이는 고정** | "결과 부족 시 키워드 재생성" 작은 루프 추가 (난이도 中) |
| Verification Layer가 LLM 한 번 호출로 끝남 | 모순 발견 시 Researcher에게 "원본 다시 보기" 요청 가능하게 (난이도 中, MVP 후순위) |
| Self-verification 종료 조건이 불명확하면 **무한 루프 위험** | 최대 2회·동일 finding 반복 시 즉시 종료 명시 (본 SPEC에 이미 반영) |
| Evaluation 점수가 시스템 행동에 **피드백되지 않음** (단순 보고용) | "judge_average < 3.5면 Writer에 다시 보내기" 옵션 (난이도 中, MVP 후순위) |
| LangGraph 채택했지만 그래프의 **분기 조건이 정적** | 실패 시 다른 노드로 재라우팅 (예: Context 실패 시 minimal-context Writer) — `add_conditional_edges` 활용 |
| **Trace의 사람-가독성** 부족 위험 | Trace JSON 외에 "이번 단계에서 뭘 했는가" 한 문단 요약을 각 노드가 추가 |

### 🔁 발표·문서에서 표현 권장 (정직성)

- ❌ "완전 자율 Agentic 시스템"
- ✅ "**Anthropic Orchestrator-Workers 워크플로우** + **Evaluator-Optimizer 반복(Writer 내부)** + **동적 외부 지식 검색(Context Agent)** 으로 합성된 **에이전틱 워크플로우**"

이렇게 표현하면 (a) 정확하고 (b) 학술/실무 양쪽에서 지적받지 않습니다.

## 4. 합성 패턴 매핑 (Anthropic 5 Workflow + Agent 패턴)

| Anthropic 패턴 | 본 시스템 매핑 |
|---------------|---------------|
| Prompt chaining | Researcher → Writer 의 정보 흐름 |
| Routing | (없음, 추후 PR 종류별 — 성능/기능/리팩터/문서 — 분기 시 도입 가능) |
| Parallelization | Context Agent가 청크별 검색을 병렬화 가능 |
| Orchestrator-Workers | LangGraph orchestrator + Researcher/Context/Writer/Evaluation workers |
| Evaluator-Optimizer | Writer ↔ Self-verification 의 reflection 루프 |
| Autonomous agent | Context Agent의 검색이 약한 형태로 해당 (키워드 결정·툴 사용) |

## 5. MVP 이후 진짜 Agent로 진화시키는 단계 제안

| 단계 | 변화 |
|------|------|
| Step 1 (Day 5 보너스) | Context Agent가 "결과 0건"이면 키워드를 재생성해 1회 더 검색 |
| Step 2 (Post-MVP) | Evaluation 점수가 임계값 미만이면 Writer에 재진입 (orchestrator-level evaluator-optimizer) |
| Step 3 | PR 종류 라우팅: 성능 PR ↔ 기능 PR ↔ 버그 PR 별 다른 Writer 프롬프트 |
| Step 4 | 사용자가 "이 부분 다시 써줘" 하면 부분 재작성 (HITL middleware) |
| Step 5 | 멀티 PR(릴리즈 노트) — 여러 PR을 supervisor agent가 묶어 1편으로 작성 |

## 7. v0.1 약점 → v0.2 해결 매핑

| v0.1 지적된 약점 | v0.2에서 어떻게 해결했는가 | 근거 SPEC |
|------------------|------------------------|----------|
| Context Agent가 검색 횟수/깊이 고정 | **풀 ReAct화** — 결과 부족 시 키워드 재생성 후 재검색 (recursion_limit=6, max_tool_calls=4) | [03-context-agent](../03-context-agent/SPEC.md), [AGENT-PATTERNS §3.2](./AGENT-PATTERNS.md) |
| Verification Layer가 LLM 1회로 끝 | **1-step ReAct** (v0.2~v0.3) → v0.4에서 Context Agent ReAct 안으로 흡수 | [03-context-agent §4](../03-context-agent/SPEC.md) |
| Self-verification 종료 조건 모호 | **5종 termination 모두 명시** (iteration / explicit / no-tool / loop / confidence) | [AGENT-PATTERNS §2.2](./AGENT-PATTERNS.md) |
| Researcher가 사전 정의된 파이프라인 | **Tool-using ReAct** — `read_pr_file`/`grep_pr` 등으로 코드 동적 탐색 | [02-researcher-agent §4](../02-researcher-agent/SPEC.md) |
| Self-verify가 본문 이외 정보를 못 봄 | **`verify_fact_in_diff` tool 1개** 추가 — 의심 문장의 PR diff 매칭 | [03-writer-agent §reflection](../03-writer-agent/SPEC.md) (v0.3에서 04 → 03 흡수) |
| Trace의 사람-가독성 | `ReActTrace.steps` 에 thought 요약 누적 → UI 펼침 카드 | [DATA-CONTRACTS §8](./DATA-CONTRACTS.md) |
| 무한 루프 / 비용 폭주 위험 | step budget + loop detection + 명시적 finish/give_up | [AGENT-PATTERNS §2](./AGENT-PATTERNS.md) |

> 의도적으로 **유지한** Workflow 부분: Writer / Evaluation.
> Anthropic 권고 — *"글 생성·평가는 일관성이 중요하므로 워크플로우가 안전하다"*.

---

## 9. v0.3 — Evaluation Layer 폐기와 self-eval 분산 (Distributed Self-Evaluation)

### 9.1 사유

v0.2에서 **별도 Evaluation 노드**의 가장 큰 약점은:
> "점수가 시스템 행동에 피드백되지 않음 — 단순 보고용"

즉, 평가가 끝났을 때 글을 다시 쓰지 않으면 **그 평가는 회고에 불과**합니다.
사용자 피드백: "각 에이전트 안에서 self-reflection 하는 게 더 효과적이다.
어차피 마지막에 남는 건 글이고, 별도 평가 노드는 데모 점수카드 외 가치가 낮다."

이는 Anthropic의 **Reflection 패턴**과 일치합니다 — 평가는 *현장에서 즉시 교정*할 수 있을 때 의미가 있습니다.

### 9.2 분산 매핑

| 책임 | v0.2 위치 | v0.3 위치 |
|------|----------|----------|
| 사실 추출 품질 | (없음) | **Researcher.self_eval** (coverage, groundedness, chunk_quality, confidence) |
| 검색 품질 / 다양성 | (없음) | **Context.self_eval** (coverage, relevance, diversity, confidence) |
| Reference ↔ PR 일치 | Verification Layer | Verification Layer (유지) — 결과를 Context.self_eval에 반영 |
| 글 사실성/구조/추측 점검 | 04 self-verification | **Writer.self_reflection** (≤2회, finding-driven) |
| 글 자동 체크리스트 (결정적) | Evaluation Layer | **Writer.deterministic_checklist** (LLM 호출 전 게이트) |
| 글 4-dim 점수 + grade(A~F) | Evaluation Layer | **Writer.self_evaluation** (1회 호출, 다른 system prompt) |
| 글 회귀 측정 (시계열) | Evaluation Layer | Writer.self_eval 시계열 + 골든셋 동의율 |

> 04-writer-self-verification 디렉토리는 v0.3에서 03-writer-agent로 흡수되었습니다.
> 05-evaluation-layer 디렉토리는 폐기되었습니다.

### 9.3 한계 (정직하게)

| 한계 | 설명 | 완화책 |
|------|------|--------|
| **Self-eval bias** | 같은 모델 가족이 자기 출력을 평가 → 점수가 후할 수 있음 | 다른 system prompt + 별도 페르소나 + 더 작은 모델(`solar-mini`)로 self-eval 분리. 완전 분리는 post-MVP에서 다른 vendor로 |
| **객관 회귀 지표 부재** | "이번 주 평균이 지난주보다 정말 나아졌나?" 단정 어려움 | 골든셋(사람 채점 5~10개) 동의율 ≥ 0.8 추적 |
| **단일 grade의 신뢰도** | 1회 호출이라 분산 큼 | 4 dimension 분리 + 결정적 체크리스트 통과율을 함께 보고 |
| **self-eval LLM 실패 시** | grade 부재 | `self_eval=None` 으로 진행, UI에 "평가 실패" 배지. 초안 자체는 정상 반환 |

### 9.4 발표/문서 권장 표현 (정확성 우선)

- ❌ "객관적 평가 시스템을 갖춘 자율 에이전트"
- ✅ "**각 에이전트가 자기 출력을 자체 채점하는 분산 self-evaluation 패턴**.
   Writer는 결정적 체크리스트 + reflection + 4-dim self-eval(grade A~F)을 한 노드에서 수행한다.
   완전한 객관성을 위해서는 골든셋 비교 또는 다른 vendor judge가 필요하며, 이는 post-MVP의 과제다."

### 9.5 합성 패턴 재분류 (v0.3)

| Anthropic 패턴 | 본 시스템 매핑 (v0.3) |
|---------------|---------------------|
| Prompt chaining | Researcher → Context → Verification → Writer 의 정보 흐름 |
| Routing | (없음, post-MVP에서 PR 종류별 분기 가능) |
| Parallelization | Context Agent의 청크별 검색 |
| Orchestrator-Workers | LangGraph orchestrator + 4 workers |
| **Evaluator-Optimizer** | **각 에이전트 내부에서 self-eval / self-reflection** (분산) |
| Autonomous agent | Researcher (Tool-using ReAct), Context (풀 ReAct), Verification (1-step ReAct) |

---

## 10. v0.4 — Context Agent 승격 + Verification 흡수

### 10.1 사유

v0.3까지 Verification Layer는 `06-backend/SPEC.md` 안의 한 섹션이었고, LangGraph 그래프에서는 별도 노드였다.
하지만 실제로 Verification이 하는 일은 *"검색 결과의 verdict 판정"* 한 가지뿐이고, 이는 Context Agent의 ReAct 안에서
`compare_text_to_facts` tool 한 번이면 끝나는 일이다.

별도 노드로 두는 것은:
- 그래프 복잡도를 늘리고
- IO 계약 / Pydantic 모델을 한 단계 더 나누고
- "검색 후 검증" 의 자연스러운 흐름을 인위적으로 끊는다.

따라서 v0.4에서 Verification 노드를 폐기하고 Context Agent ReAct 안으로 흡수했다.

### 10.2 변경 매핑

| 책임 | v0.3 위치 | v0.4 위치 |
|------|----------|----------|
| 외부 검색 (Context7 / web) | 06-backend `context_search.py` (정책 + 핸들러 함께) | **03-context-agent** (정책) + **05-backend `context_search.py`** (핸들러) |
| 검증 (verdict per reference) | 06-backend `verification.py` + 별도 LangGraph 노드 | **03-context-agent ReAct 안 `compare_text_to_facts` tool 호출** |
| ContextSelfEval 산출 | 06-backend `verification.py` | **03-context-agent §4.5** |
| GraphState | `verification` 노드 산출물 별도 | Context 한 노드의 `ContextResult` 단일 |
| 디렉토리 번호 | 03-writer / 06-backend / 07-frontend | **04-writer / 05-backend / 06-frontend** + 신규 **03-context-agent** |

### 10.3 한계 (정직성)

| 한계 | 설명 | 완화책 |
|------|------|--------|
| ReAct가 검증을 까먹을 수 있음 | LLM이 `compare_text_to_facts` 호출을 빠뜨리고 `finish` 직행할 가능성 | 시스템 프롬프트에 강제 + 후처리 검증 (verdict이 비어있는 reference는 자동 reject) |
| 청크별 ReAct 비용 | 청크 5개면 5번의 ReAct 인스턴스 | `solar-mini` 사용 + 캐시 + 청크 한도 (Researcher 가 너무 많이 만들지 않도록) |
| Verification 정책의 단일 모델 의존 | `compare_text_to_facts` 내부 LLM 한 번 | post-MVP: ensemble 또는 다른 vendor verdict |

### 10.4 합성 패턴 재분류 (v0.4)

| Anthropic 패턴 | 본 시스템 매핑 (v0.4) |
|---------------|---------------------|
| Prompt chaining | Researcher → Context → Writer 의 3-노드 흐름 |
| Routing | `coverage<0.2` 분기 (Writer minimal mode) — 정적 |
| **Parallelization** | Context Agent의 청크별 ReAct 병렬 (`asyncio.gather`) |
| Orchestrator-Workers | LangGraph orchestrator(01) + 3 agent workers(02/03/04) |
| **Evaluator-Optimizer** | **각 에이전트 내부 self-eval / self-reflection** (분산) |
| **Autonomous agent** | Researcher (Tool ReAct) + Context (per-chunk 풀 ReAct, **검증 흡수**) |

## 11. 레퍼런스

- [Anthropic — Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)
- [LangChain Docs — Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [IBM — What are Agentic Workflows?](https://www.ibm.com/think/topics/agentic-workflows)
- [IBM — What is a ReAct Agent?](https://www.ibm.com/think/topics/react-agent)
- [ScienceDirect — AI Agents vs. Agentic AI: A Conceptual taxonomy](https://www.sciencedirect.com/science/article/pii/S1566253525006712)
- [HuggingFace Blog — Reflection in AI Agents](https://huggingface.co/blog/Kseniase/reflection)
- [HuggingFace — Thought-Action-Observation Cycle](https://huggingface.co/learn/agents-course/en/unit1/agent-steps-and-structure)
- [Phil Schmid — Zero to One: Learning Agentic Patterns](https://www.philschmid.de/agentic-pattern)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [Prompting Guide — ReAct](https://www.promptingguide.ai/techniques/react)
- [Confident AI — LLM-as-a-Judge Guide](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method)
- [Adnan Masood — Rubric-Based Evals & LLM-as-a-Judge](https://medium.com/@adnanmasood/rubric-based-evals-llm-as-a-judge-methodologies-and-empirical-validation-in-domain-context-71936b989e80)
