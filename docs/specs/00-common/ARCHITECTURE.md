# SYSTEM ARCHITECTURE

> 기획서 §3.4(시스템 워크플로우) + §4.2(시스템 아키텍처)의 SDD 정렬판.
>
> **변경 이력 (v0.4):** Verification Layer 노드 폐기 → Context Agent 안으로 흡수 (`compare_text_to_facts` tool).
> 03-context-agent 디렉토리 신설(조재영). 디렉토리 번호 재매핑.
>
> **v0.3:** 별도 Evaluation Layer 폐기, 평가 책임을 각 에이전트 self-evaluation으로 분산.

## 1. 컴포넌트 다이어그램 (텍스트, v0.4)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          [User Interface Layer]                          │
│   Streamlit Demo UI (06-frontend)                                        │
│     · PR URL 입력 폼 / Webhook 시뮬레이터                                │
│     · 초안(Markdown) 렌더 / Agent Trace / 단계별 self-eval 카드          │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │ HTTP (FastAPI 옵션) or in-process
┌────────────────────────────────────▼─────────────────────────────────────┐
│             [Backend / Integration — 05-backend]                         │
│   github_client / solar_client / context_search (tool 핸들러)            │
│   tools/{pr_tools, verify_tools, search_tools, termination}              │
│   webhook_listener (옵션) / api.py (옵션) / goldenset/                   │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │ Python in-process
┌────────────────────────────────────▼─────────────────────────────────────┐
│             [Orchestration Layer — 01-langgraph]                         │
│             (조재영)                                                     │
│                                                                          │
│   START                                                                  │
│     │                                                                    │
│     ▼                                                                    │
│   ┌──────────────────────────┐                                          │
│   │ fetch_github (결정적)    │                                          │
│   └──────────────┬───────────┘                                          │
│                  ▼                                                       │
│   ┌──────────────────────────┐                                          │
│   │ Researcher (ReAct)       │   ★ 우재민                              │
│   │   ├─ extract             │                                          │
│   │   └─ self_eval ★         │  → ResearchResult (+self_eval)           │
│   └──────────────┬───────────┘                                          │
│                  ▼                                                       │
│   ┌─────────────────────────────────────┐                                │
│   │ Context Agent (per-chunk ReAct)     │   ★ 조재영                   │
│   │   ├─ search per chunk                │                               │
│   │   ├─ compare_text_to_facts           │  ← Verification 흡수         │
│   │   └─ self_eval ★                     │  → ContextResult (+self_eval)│
│   └──────────────┬───────────────────────┘                               │
│                  ▼                                                       │
│   ┌──────────────────────────────────────────┐                           │
│   │ Writer (Workflow + reflection + eval)     │  ★ 정민기 + 김영표      │
│   │   ├─ generate_draft       (정민기)        │                          │
│   │   ├─ deterministic_checklist (정민기)     │                          │
│   │   ├─ self_reflection (김영표) ◄──┐       │                          │
│   │   └─ self_evaluation (정민기)    │       │  → DraftResult (+self_eval│
│   └──────────────┬─────────────────────┘       │     incl. grade A~F)    │
│                  ▼                                                       │
│                 END                                                      │
│                                                                          │
│   ★ = 다른 system prompt + 다른 페르소나로 호출되는 self-evaluation     │
└──────────────────────────────────────────────────────────────────────────┘
```

> 별도 `Verification` / `Evaluation` 노드는 **없다**. 검증은 Context 안, 평가는 단계마다 분산.

## 2. 책임 분담 (Responsibility Matrix, v0.4)

| 책임 | Researcher (02) | Context (03) | Writer (04) | Backend (05) | Orchestrator (01) |
|------|:--------------:|:------------:|:-----------:|:------------:|:-----------------:|
| 담당자 | 우재민 | **조재영** | 정민기 + 김영표 | 홍지호 | **조재영** |
| PR diff/commit/issue 파싱 | ✅ | | | | |
| 사실 정보 구조화(JSON) | ✅ | | | | |
| **추출 품질 자기 평가** | ✅ self_eval | | | | |
| 검색용 청킹·키워드 | ✅ | | | | |
| MCP/문서 검색 | | ✅ | | tool 핸들러 | |
| **문서 ↔ PR 일치 검증** | | ✅ (compare_text_to_facts) | | tool 핸들러 | |
| **검색 결과 품질 자기 평가** | | ✅ self_eval | | | |
| Markdown 초안 작성 | | | ✅ (정민기) | | |
| 결정적 체크리스트 게이트 | | | ✅ (정민기) | | |
| Reflection (수정 finding) | | | ✅ (김영표) | | |
| **글 품질 자기 평가 + grade(A~F)** | | | ✅ (정민기) self_eval | | |
| 골든셋 사람 채점 / 동의율 | | | | ✅ (홍지호) | |
| 인프라 (GitHub / Solar / Context7) | | | | ✅ (홍지호) | |
| 노드 실행 순서 / Retry / Fallback | | | | | ✅ (조재영) |
| 상태 영속화(체크포인터) | | | | | ✅ (조재영) |
| Streaming / Trace 노출 | | | | | ✅ (조재영) |

## 3. 단계별 IO 계약 (요약)

| 단계 | 입력 | 처리 | 출력 |
|------|------|------|------|
| Demo UI (06) | URL or PR Webhook | 입력 수집 | `pr_identifier` |
| GitHub API (05) | `pr_identifier` | diff/commit/issue 수집 | `RawPRData` |
| Researcher (02) | `RawPRData` | 사실 추출 + 청킹 + 키워드 + **self_eval** | `ResearchResult` |
| Context (03) | `ResearchResult.search_chunks` + `facts` | 검색 + **검증** + **self_eval** (한 노드) | `ContextResult` |
| Writer (04) | `ResearchResult` + `ContextResult` | generate → checklist → reflection → **self_eval** | `DraftResult` (markdown + grade) |
| Result UI (06) | `DraftResult` + Trace + 각 단계 self_eval | 렌더링 | 사용자에게 노출 |

자세한 스키마는 [DATA-CONTRACTS.md](./DATA-CONTRACTS.md).

## 4. 동기/비동기 & 동시성 결정

- **MVP**: LangGraph 순차 실행 (3 노드).
- **Context Agent 내부**: 청크별 `asyncio.gather(return_exceptions=True)` 병렬 (concurrency ≤ 5).
- **Writer reflection**: 같은 노드 안에서 ≤ 2회.
- **Self-evaluation** (각 노드): 1회 호출, 결과 저장, 시스템 행동에 피드백 안 됨 (보고용).
- **체크포인터**: MVP `MemorySaver`. Production `AsyncPostgresSaver`.

## 5. 실패 모드별 라우팅

| 실패 | 라우팅 | 사용자 가시화 |
|------|-------|--------------|
| GitHub API 4xx/5xx | 즉시 `END(error_state)` | UI 에러 + 재시도 버튼 |
| `linked_issue` 없음 | Researcher 가 `linked_issue=[]` 진행 | Trace에 "이슈 없음" |
| Context 검색 0건 (청크 1개) | 해당 청크 give_up, 다른 청크 영향 없음 | Trace에 "청크 N 0건" |
| Context coverage < 0.2 | Writer minimal 모드 | Trace에 "외부 컨텍스트 부족" |
| Writer 빈 출력 / 스키마 위반 | 1회 retry 후 템플릿 fallback | UI에 "초안 일부 생성 실패" |
| Reflection 2회 모두 수정 권고 | 마지막 출력 채택 + grade 페널티 | self_eval rationale 명시 |
| Self-eval 실패 (어느 단계든) | `self_eval=None`, 노드 출력은 정상 반환 | UI 배지 "평가 실패" |

## 6. 보안/프라이버시 (MVP 수준)

- GitHub PAT은 환경변수(`GITHUB_TOKEN`)만.
- Private repo는 토큰 권한 부족 시 종료.
- LLM 프롬프트에 토큰 미포함 — Researcher 출력만 전달.

## 7. v0.4에서 의도적으로 받아들인 한계

| 한계 | 완화책 |
|------|--------|
| **Self-eval bias** | 다른 system prompt + 다른 페르소나 + 더 작은 모델(`solar-mini` for eval) |
| **객관 회귀 지표 부재** | 골든셋(사람 채점 5~10개, 홍지호) 동의율 ≥ 0.8 추적 |
| **단일 grade의 시계열 비교 불안정** | 차원별 점수(4 dim) + 결정적 체크리스트 통과율 + coverage 등 다축 보고 |
| **Verification 흡수에 따른 결과 추적성** | `verification_log` 는 ContextResult 안에 그대로 유지 — 어떤 reference가 왜 reject 됐는지 보존 |

## 8. 레퍼런스

- [LangGraph — workflows-agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph — Persistence & Checkpointer](https://github.com/langchain-ai/langgraph)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [Anthropic — Reflection / Evaluator-Optimizer / Autonomous Agent](https://www.anthropic.com/research/building-effective-agents)
- [Confident AI — LLM-as-Judge](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method)
- [00-common/AGENTIC-EVALUATION.md](./AGENTIC-EVALUATION.md)
- [00-common/AGENT-PATTERNS.md](./AGENT-PATTERNS.md)
