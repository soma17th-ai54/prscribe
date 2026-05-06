# SPEC CHANGELOG

본 파일은 SPEC 변경 이력을 기록합니다. 코드 변경보다 **항상 먼저** 기록합니다.

## [0.4.0] — Day 0 (Context Agent 승격 + Verification 흡수, 2026-05-06)

### Added
- **`03-context-agent/SPEC.md` 신규.** Context Agent를 own SPEC으로 끌어올림. 조재영이 LangGraph Orchestration(01)과 함께 담당.
  - 풀 ReAct (per-chunk, `asyncio.gather` 병렬, concurrency ≤ 5)
  - **Verification Layer 흡수** — `compare_text_to_facts` tool 호출로 검증이 자연스럽게 ReAct 안에서 수행
  - 청크 0건 시 키워드 paraphrase 후 1회 재검색 (Anthropic 권고)
  - Self-Eval (coverage / relevance / diversity / confidence) 내장
- `05-backend/SPEC.md §10` "골든셋" 신설 — 홍지호 책임. 사람-LLM 동의율 ≥ 0.8 추적.
- `04-writer-agent/SPEC.md §0` "Subsection Ownership" 표 — 정민기 / 김영표 / 홍지호 책임 명시.

### Removed
- **별도 Verification Layer LangGraph 노드 폐기.** v0.3까지 `06-backend/verification.py` + 그래프의 별도 노드였음. v0.4에서 Context Agent ReAct 내부 tool 호출로 흡수.
- `GraphState` 의 별도 verification 단계 산출물 (이미 v0.3에서 ContextResult로 통합되어 있던 것을 SPEC 문서에서도 깨끗하게 정리).
- `ReActTrace.node` Literal 에서 `"verification"` / `"self_verification"` 제거 — 새 노드명은 `"researcher"`, `"context"`, `"self_reflection"`.

### Changed (디렉토리 번호 재매핑)
| v0.3 | v0.4 | 사유 |
|------|------|------|
| (없음) | `03-context-agent/` | 신규 — Context Agent own SPEC |
| `03-writer-agent/` | `04-writer-agent/` | 번호 한 칸 밀림 |
| `06-backend/` | `05-backend/` | 빈 04, 05 자리 채우기 |
| `07-frontend/` | `06-frontend/` | 번호 정렬 |

### Changed (내용)
- `00-common/ARCHITECTURE.md`: 컴포넌트 다이어그램 갱신 (3-노드 골격: Researcher → Context → Writer + 진입 `fetch_github`)
- `00-common/DATA-CONTRACTS.md §3`: ContextResult 머리말에 "Context Agent + Self-Eval" 명시 (Verification Layer 명칭 제거).
  `ReActTrace.node` Literal / `ToolSpec.available_to` Literal 갱신.
- `00-common/AGENT-PATTERNS.md`: 결정 매트릭스에서 Verification Layer 행 폐기, Context Agent 행에 "검증 흡수" 명시. Step Budget 표에서 Verification / Self-verification 항목 삭제, Writer self_reflection 추가.
- `00-common/AGENTIC-EVALUATION.md §10` "Context Agent 승격 + Verification 흡수" 신설 — 사유 / 매핑 / 한계 / 합성 패턴 재분류.
- `00-common/PROJECT-OVERVIEW.md`: §3.2 핵심 가치 표 / §4.1 MVP / §5 7-Day 일정 갱신 (Context Agent + 골든셋 명시).
- `01-langgraph-orchestration/SPEC.md`: **재작성** — 노드 4개(fetch_github 결정적 + 3 agent ReAct/Workflow), conditional edges는 `coverage<0.2` 하나만, Verification 행 제거. §2 "조재영의 두 책임" 섹션 신설.
- `02-researcher-agent/SPEC.md`: cross-link 번호 갱신 (`03-context-agent` 인용 추가).
- `04-writer-agent/SPEC.md`: 헤더 / 디렉토리 번호 갱신, §0 Subsection Ownership 추가.
- `05-backend/SPEC.md`: **재구조화** — `verification.py` 제거, `tools/{pr_tools, verify_tools, search_tools, termination}` 구조 명시. §10 "골든셋" 신설. 홍지호 책임 재정의.
- `06-frontend/SPEC.md`: 진행 단계 4 → **3 steps**, self-eval 카드 4 → **3개**.
- `README.md`: 디렉토리 맵 / 역할 재배정 / 읽는 순서 / DoD 모두 v0.4로 갱신.

### Rationale
- 사용자 피드백: "조재영이가 LangGraph Orchestration + Context Agent까지 짜기로 했다. 폴더별 구조까지 재정립."
- 동의 근거 (ultrathink):
  1. Context Agent는 시스템에서 **가장 복잡한 단일 노드** (per-chunk ReAct + 검증 + self-eval). own SPEC을 가질 가치가 충분.
  2. Verification Layer를 별도 노드로 두는 건 v0.2의 잔재. 실제 행위는 `compare_text_to_facts` tool 한 번이고, 이는 Context ReAct 안에서 자연스럽게 흐름.
  3. 조재영이 Orchestration + Context를 모두 담당하면, 그래프 reducer / streaming / retry 정책과 Context ReAct 구현이 같은 사람의 책임이라 자연스럽게 정합성 확보.
  4. 디렉토리 번호 재매핑은 SDD 원칙 (디렉토리 번호 = 데이터 흐름 순서) 강화.

### 호환성
- v0.3 코드가 `verification` 노드를 임포트하면 deprecation warning 후 에러. (한 사이클 = Day 5까지 alias 유지 권장)
- `06-backend.context_search` → `05-backend.context_search` 경로 변경 — import 경로 갱신 필요.

## [0.3.0] — Day 0 (Distributed Self-Evaluation, 2026-05-05)

### Removed
- **`05-evaluation-layer/` 디렉토리 폐기.** 별도 Evaluation 노드 제거.
- **`04-writer-self-verification/` 디렉토리 폐기.** Writer 내부 reflection으로 흡수.
- `EvaluationResult` Pydantic 모델 deprecation (alias로 한 사이클 유지 후 제거).
- `GraphState.evaluation` 필드 제거.

### Added
- **각 에이전트 self-evaluation:**
  - `ResearcherSelfEval` (coverage / groundedness / chunk_quality / confidence)
  - `ContextSelfEval` (coverage / relevance / diversity / confidence)
  - `WriterSelfEval` (4-dim judge_scores: accuracy/readability/structure/code_explanation + checklist + grade A~F)
- 각 산출물에 `self_eval` 필드 추가 (`ResearchResult` / `ContextResult` / `DraftResult`)
- Writer 노드 내부 3단계 파이프라인:
  1. `deterministic_checklist` (LLM 호출 전 결정적 게이트)
  2. `self_reflection` (≤2회, 다른 system prompt — 수정용)
  3. `self_evaluation` (1회, 또 다른 system prompt — 등급용)
- `AGENTIC-EVALUATION.md §9` "Distributed Self-Evaluation" 신설 — 사유 / 한계 / 분산 매핑 / 합성 패턴 재분류
- `ARCHITECTURE.md` 컴포넌트 다이어그램 갱신 (4-노드 골격 + 단계별 ★ self_eval 마커)

### Changed
- `01-langgraph-orchestration/SPEC.md`: 노드 5개 → **4개**(`fetch_github` 제외 시 4개) — `evaluation` 노드 제거
- `02-researcher-agent/SPEC.md`: 파이프라인 끝에 self-eval 단계 추가 + §4.5 신설
- `03-writer-agent/SPEC.md`: **전면 재작성** — generate + 결정적 checklist + reflection + self-eval 3단계 + 한계 명시
- `06-backend/SPEC.md`: solar_client 모델 라우팅에 self-eval 분리 명시 / verification.py가 `ContextSelfEval` 산출
- `07-frontend/SPEC.md`: Evaluation 탭 → **Self-Eval 탭** (단계별 카드 4개) + 헤더에 grade(A~F) 노출 + bias footnote
- `00-common/PROJECT-OVERVIEW.md`: 핵심가치/MVP/일정/DoD 갱신
- `00-common/DATA-CONTRACTS.md`: `EvaluationResult` deprecated, `*SelfEval` 모델 신설
- `00-common/AGENT-PATTERNS.md`: 결정 매트릭스 갱신, 안티패턴 2개 추가 (self-eval과 self-reflection 분리)
- Day 5 일정: "별도 Evaluation Layer" → **"각 에이전트 self-eval + 골든셋"**

### Rationale
- 사용자 피드백: "Evaluation Layer가 마지막에 필요할까? 각각 에이전트 안에서 self-reflection 하는 게 낫다.
  자동 워크플로우니까 마지막 출력은 글일 뿐. 그 글이 잘 쓰였는지만 판단하면 된다."
- 동의 근거: v0.2 AGENTIC-EVALUATION이 이미 지적했던 "Evaluation 점수가 시스템 행동에 피드백되지 않음" 약점을 정면 수용.
  Anthropic Reflection 패턴은 *현장 즉시 교정*이 핵심.
- 정직성: self-eval은 같은 모델 가족이 자기 출력을 평가하므로 bias가 있음을 SPEC과 UI에 명시.
  완전 분리는 post-MVP에서 다른 vendor judge로.

## [0.2.0] — Day 0 (ReAct/Tool 보강, 2026-05-05)

### Added
- `00-common/AGENT-PATTERNS.md` — Workflow vs ReAct 결정 매트릭스, Tool 카탈로그, 종료조건 5종, step budget 표준
- `DATA-CONTRACTS §8` — `ToolCall`, `Observation`, `ReActStep`, `ReActTrace`, `ToolSpec`(ToolRegistry) 추가
- `GraphState.react_traces: list[ReActTrace]` 필드

### Changed
- **Researcher** (02): Prompt Chain → **Tool-using ReAct**. 도구: `read_pr_file`, `grep_pr`, `list_pr_files`, `get_commit_message`, `get_linked_issue`, `finish`, `give_up`. `recursion_limit=8`, `max_tool_calls=6`, `timeout=20s`.
- **Context Agent** (06-backend §3.3): Workflow → **풀 ReAct (per chunk)**. 도구: `context7_search`, `web_search`, `fetch_url`, `compare_text_to_facts`, `finish`, `give_up`. `recursion_limit=6`.
- **Verification Layer** (06-backend §3.4): 단순 LLM 호출 → **1-step ReAct**. 도구: `fetch_url`, `compare_text_to_facts`. `recursion_limit=3`.
- **Self-verification** (04): 결정적 + LLM 검사 → 같은 + **`verify_fact_in_diff` 도구 1개** 추가 (1-step ReAct).
- **Orchestrator** (01): 노드 표에 패턴 컬럼 추가, retry/timeout 표에 ReAct 내부 한계 컬럼 추가.
- **AGENTIC-EVALUATION**: §7 "v0.1 약점 → v0.2 해결 매핑" 신설.

### Rationale
- 사용자 피드백: 초안 시스템이 사실상 *Prompt Chaining + Evaluator-Optimizer* 였음.
  Anthropic *Building Effective AI Agents* 의 "필요한 곳에만 Agent" 권고에 맞춰 부분 ReAct화.
- Writer/Evaluation은 의도적으로 Workflow 유지 (일관성·결정성 우선).

## [0.1.0] — Day 0 (Initial Draft, 2026-05-05)

### Added
- 전체 SPEC 디렉토리 구조 (`00-common`, `01-langgraph-orchestration`, `02-researcher-agent`, `03-writer-agent`, `04-writer-self-verification`, `05-evaluation-layer`, `06-backend`, `07-frontend`)
- 공통 문서: `PROJECT-OVERVIEW`, `ARCHITECTURE`, `DATA-CONTRACTS`, `AGENTIC-EVALUATION`
- 5개 역할별 SPEC 초안

### Decisions
- Editor Agent를 별도 노드로 두지 않고 **Writer 내부 self-verification 루프**로 통합 (기획서 §2.2 반영)
- Verification Layer는 **Context Agent 결과 검증** 전용으로 한정 (Writer 자체 검증은 §04에서 담당)
- MVP 체크포인터는 `MemorySaver`. 발표 시 Production은 `PostgresSaver` 권장 언급만.
