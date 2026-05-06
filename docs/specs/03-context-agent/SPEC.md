# SPEC — Context Agent (with absorbed Verification + Self-Evaluation)

**담당:** 조재영 (LangGraph Orchestration과 함께)
**디렉토리:** `03-context-agent/`
**관련 기획서 섹션:** §2.2 (배경 보강 / 배경 검증), §3.4 (시스템 워크플로우 — Context Agent + Verification Layer), §4.5 (Context 레퍼런스 검증 실패)

> **변경 이력 (v0.4):**
> - **신규 디렉토리.** v0.3까지 `06-backend/SPEC.md §3.3~3.4` 안에 묻혀 있던 Context Agent와 Verification Layer를 끌어올려 own SPEC을 부여했다.
> - **Verification Layer 흡수.** v0.3까지 별도 노드였던 Verification은 본 노드의 ReAct 루프 안에서 `compare_text_to_facts` tool 호출로 자연스럽게 수행된다. 별도 LangGraph 노드는 폐기.
> - **Self-evaluation 내장.** Context 결과 품질(coverage / relevance / diversity / confidence)을 본 노드가 자체 채점한다.

---

## 1. 목적 (Goal)

Researcher가 추출한 `SearchChunk[]` 의 각 청크에 대해
**(a) 외부 지식을 검색** → **(b) 검색 결과가 PR 사실과 일치하는지 검증** → **(c) 결과 품질을 자체 채점** 하여
`ContextResult` 한 개를 반환한다.

> 한 노드 안에서 *검색·검증·평가* 가 모두 끝난다.
> Writer는 이 결과의 `verified_references` 만 인용 가능하므로 본 노드가 **할루시네이션 1차 방어선** 이다.

## 2. 입력 / 출력

### 입력
- `ResearchResult` (전체) — 단, 본 노드가 직접 사용하는 부분은:
  - `search_chunks: list[SearchChunk]` — 청크별 키워드 + intent
  - `facts: list[FactBullet]` — 검증의 ground truth
  - `pr_identifier`

### 출력
- [`ContextResult`](../00-common/DATA-CONTRACTS.md#3-contextresult-context-agent--verification-layer-출력) — `verified_references` + `rejected_references` + `verification_log` + `coverage` + `self_eval`

## 3. 핵심 책임

✅ **이 Agent가 하는 일**
- 청크별 외부 검색 (Context7 MCP 우선, 폴백 web search)
- 검색 결과의 PR 사실 일치도 검증 (verdict 4종)
- `verified_references` 만 Writer에게 노출 (인용 게이트)
- coverage 계산 (= unique chunk_id with consistent ref / total chunks)
- 본 노드의 결과 품질을 자체 채점 (`ContextSelfEval`)
- 청크별 ReAct 인스턴스를 `asyncio.gather` 로 병렬 실행 (concurrency ≤ 5)
- 캐시: `(query, top_k)` 30분 in-memory + 결과 timestamp 기록 (재실행 결정성)

❌ **하지 않는 일**
- PR 사실 추가 추출 (Researcher 책임)
- Markdown 글 생성 (Writer 책임)
- 코드 수정 / 자동 발행
- LLM 직접 호출 — `solar_client.py` 인터페이스 사용 (06-... → **05-backend**)
- 노드 실행 순서 / retry / 체크포인터 — Orchestrator(01) 책임

## 4. 알고리즘

> 본 SPEC은 **풀 ReAct (per chunk) + Verification 흡수 + Self-Eval** 노드입니다.
> 공통 골격·Tool 카탈로그·종료조건은 [AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md).

### 4.1 노드 내부 파이프라인

```
ResearchResult
   │
   ├─[per-chunk 병렬 ReAct, asyncio.gather, concurrency≤5]
   │   ├─ chunk #1 ─► ReAct ─► Reference[] (consistent only)
   │   ├─ chunk #2 ─► ReAct ─► Reference[] (consistent only)
   │   └─ ...
   │
   ├─[병합 + 결정적 처리]─▶ raw_references / verified_references / rejected_references
   │                       coverage = consistent chunks / total chunks
   │                       verification_log 누적
   │
   └─[Self-Evaluation, LLM 1회, 다른 system prompt]
        │ relevance (1~5) / diversity (1~5) / confidence (1~5)
        │ rationale + suggestions
        ▼
      ContextResult
```

### 4.2 청크별 ReAct 루프 (단일 청크)

```
loop (recursion_limit=6, max_tool_calls=4, timeout=12s):
  Thought  → "이 청크 키워드(intent=...) 에 가장 정확한 공식 문서는?"
  Action   → context7_search(library, topic, k=3)            # 1순위
             | web_search(query, k=5)                         # 폴백
             | fetch_url(url)                                 # 본문 확보
             | compare_text_to_facts(excerpt, facts)          # ★ 검증 (verification 흡수)
             | finish(output_json=Reference[])  | give_up(reason)
  Observe  → tool 결과를 messages에 append
  종료조건 검사 (AGENT-PATTERNS §2.2: 5종)
```

**핵심**: `compare_text_to_facts` 가 verdict (`consistent` / `contradicts` / `unrelated` / `needs_review`) 을 직접 반환하므로, ReAct 모델은 검증 결과까지 본 뒤 `finish` 를 호출한다. 즉 **검색과 검증이 같은 ReAct 안에서 한 번에 끝난다.**

`finish` 시 LLM은 **`consistent` 판정을 받은 reference 만** `Reference[]` 에 담아 반환해야 한다 (시스템 프롬프트로 강제).

### 4.3 0건 fallback (Anthropic 권고: "결과 부족 시 키워드 paraphrase")

청크별 ReAct가 0건으로 종료될 가능성이 있다. 이때:

1. 마지막 step에서 LLM이 키워드를 paraphrase 한 후 `web_search` 1회 더 시도 (시스템 프롬프트로 권장)
2. 그래도 0건이면 `give_up(reason="zero_hits_after_paraphrase")` 호출
3. 해당 청크는 `coverage` 계산에서 제외되지 않는다 (분모에 포함, 분자에 제외)

### 4.4 ReAct 시스템 프롬프트 (요약)

```
[SYSTEM]
당신은 코드 변경의 외부 컨텍스트를 검색·검증하는 분석가입니다.
한 청크씩 처리합니다.

[원칙]
- Context7 MCP를 web search보다 우선 사용합니다.
- 모든 reference는 finish 호출 전 compare_text_to_facts 로 verdict를 받아야 합니다.
- consistent verdict 만 finish의 output_json에 포함합니다.
- 0건이면 키워드를 paraphrase 후 1회 더 web_search 한 뒤 give_up.
- 같은 도구를 같은 인자로 두 번 호출하지 말 것 (loop_detected).

[도구]
- context7_search(library, topic, k=3)
- web_search(query, k=5)
- fetch_url(url)
- compare_text_to_facts(excerpt, facts)  ← 검증 핵심
- finish(output_json=Reference[]), give_up(reason)

[종료]
1) consistent reference ≥ 1개 확보 → finish
2) recursion_limit=6 / max_tool_calls=4 / timeout=12s 도달
3) 동일 호출 반복 (loop_detected)
4) 0건 + paraphrase 1회 후도 0건 → give_up

[출력]
finish 시 output_json 은 Reference[] (DATA-CONTRACTS §3).
verdict 결과는 별도로 verification_log 에 누적되도록 호출자가 처리한다.
```

`temperature=0`, 모델 라우팅은 비용 절감을 위해 `solar-mini` (05-backend §3.2 참조).

### 4.5 Self-Evaluation 시스템 프롬프트 (요약)

```
[SYSTEM]
당신은 외부 컨텍스트 검색 결과를 채점하는 검증자입니다.
(검색자와 별개의 페르소나입니다.)

[원칙]
- 점수 전 1~2문장 reasoning을 먼저 적습니다 (G-Eval).
- 4 dimension 독립 평가:
  1) coverage:   = unique(chunk_id with consistent ref) / total chunks  (결정적, 검토만)
  2) relevance:  references가 PR 사실에 얼마나 직접 관련 있는가 (1~5)
  3) diversity:  출처(domain) 다양성 — 같은 사이트만 나오면 점수 낮음 (1~5)
  4) confidence: 종합 (1~5)

[페널티]
- coverage < 0.3 → confidence ≤ 2
- 모든 reference가 동일 domain → diversity = 1

[출력]
ContextSelfEval Pydantic 스키마 (DATA-CONTRACTS §3).

[유의]
- 평가만 합니다. 자신의 검색을 다시 만들지 마세요.
- 점수가 낮아도 시스템 행동 변화 없음 — 보고 + 시계열 모니터링 용도.
```

`temperature=0`. 단일 호출.

## 5. Tool 책임 분담 (구현 위치)

본 노드의 ReAct 인스턴스는 LangGraph 의 `create_react_agent` 로 구성하지만,
**tool 핸들러 자체는 `05-backend/context_search.py` 에 구현**되어 있다.
즉:
- **본 SPEC**: ReAct 정책 / 시스템 프롬프트 / 종료조건 / self-eval 책임
- **05-backend SPEC**: HTTP 호출 / Context7 MCP 어댑터 / 캐시 / 폴백 라우팅

이 분리는 *"오케스트레이션은 03, 인프라는 05"* 원칙을 따른다.

## 6. 종료 조건 (AGENT-PATTERNS §2.2 정렬)

| 종류 | 트리거 |
|------|-------|
| Iteration limit | `recursion_limit=6` 도달 |
| Explicit finish | LLM이 `finish(output_json=Reference[])` 호출 |
| Loop detected | 동일 (tool, args_hash) 연속 2회 |
| No tool call | LLM이 도구 없이 텍스트만 반환 |
| Confidence gate | (선택) confidence ≥ 0.85 self-report + finish |

청크 하나가 timeout(12s) 도달 시 해당 청크는 `give_up` 처리되고 다른 청크는 영향받지 않음.

## 7. 실패 모드 / Fallback

| 상황 | 동작 |
|------|------|
| Context7 MCP 다운 | 자동 web_search 폴백 (05-backend가 처리) |
| 모든 검색 실패 (청크 단위) | 해당 청크는 0건, coverage 분모에 포함 / 분자에 제외 |
| `compare_text_to_facts` 가 모두 `contradicts` | rejected에 누적, verified_references=[] |
| 청크 5개 모두 give_up | `coverage=0`, Writer는 자동으로 minimal-context 모드 (Orchestrator §writer_mode) |
| Self-eval LLM 실패 | `self_eval=None`, ContextResult 자체는 정상 반환 |
| 청크 1개 timeout | 해당 청크만 fail, 나머지는 정상 (`asyncio.gather(return_exceptions=True)` 사용) |
| Loop detected | 즉시 종료, 마지막까지 누적된 consistent ref 만 finish |

## 8. 테스트 전략

- **단위:**
  - 청크 1개 + 가짜 검색 결과 → 정확히 1개 ReAct 인스턴스 실행
  - `compare_text_to_facts` mock 으로 verdict 분기 모두 커버
- **속성 기반:**
  - 모든 `verified_references` 는 verdict=`consistent` 인 reference 의 부분집합
  - `rejected_references ∪ verified_references = raw_references`
- **회귀:** 샘플 PR 5개 — `ContextResult` 스냅샷 (verified URL 정렬 SHA + coverage)
- **부하:** 청크 10개 동시 실행 시 wall-clock < 청크 1개 시간의 2배 (병렬성 검증)
- **실패 주입:** Context7 mock 다운 → web_search 폴백 활성화 확인
- **Self-eval 안정성:** 동일 입력에 대해 confidence 분산 ≤ 0.5 (3회 호출)
- **Loop detection:** 같은 tool/args 강제 반복 → 즉시 종료

## 9. 관측성

- 청크별 `ReActTrace.steps` 압축본을 `state.react_traces` 에 append
- `stopped_by` 분포: `finish_tool` 80%+ / `give_up_tool` ≤ 20% 가 정상
- `coverage` 시계열 (낮으면 Researcher의 키워드 품질 검토)
- `self_eval.confidence` / `relevance` / `diversity` 분포
- 캐시 hit율 (Backend가 측정, 본 노드가 trace에 인용)
- per-chunk wall-clock 히스토그램

## 10. UI 표현 (06-frontend §5와 정렬)

```
[Context Agent (per-chunk ReAct)] ✅ 5.4s   self_eval: 4★
  ├─ chunks: 5/5 (coverage 0.83)
  ├─ verified: 4 / rejected: 1 / total raw: 7
  ├─ self_eval:
  │   relevance: 4 / diversity: 3 / confidence: 4
  │   "Context7 공식문서 + 1개 블로그로 다양성은 보통"
  └─ ReAct steps per chunk [펼치기]
```

## 11. Open Questions / TODO

- [ ] Post-MVP: `coverage < 0.3` 시 자동으로 Researcher에게 "키워드 더 만들어줘" 재요청 (orchestrator-level evaluator-optimizer)
- [ ] Context7 외에도 GitHub Code Search / docs.langchain.com 어댑터 추가
- [ ] 청크간 **상관관계** 활용 — 한 청크에서 찾은 reference가 다른 청크에도 유효한 경우 재사용

## 12. Why MCP + Web Search instead of pre-indexed RAG (rationale)

> 이 섹션은 *"왜 vector DB로 RAG 안 만들고 MCP/웹검색을 쓰나?"* 라는 (당연한) 질문에
> 답을 박아두기 위한 결정 기록입니다. 미래에 같은 질문이 나올 때 본 섹션을 인용하세요.

### 12.1 결론

> **MVP는 Context7 MCP + Web Search 로 가고, 자주 hit하는 결과를 캐시하는 RAG fast-path는 post-MVP에 단계적으로 도입한다.**
> RAG가 나쁘다는 게 아니라 **7-day MVP 시간 안에 끝낼 수 없다**는 게 핵심.

### 12.2 작업량 비교 (시간 단위 정직 추정)

#### Path A — Vector DB + RAG (학생 안)

| # | 작업 | 시간 | 누구 일이 막히나 |
|---|------|------|------------------|
| 1 | 어떤 라이브러리/문서를 인덱싱할지 결정 | 0.5d | 팀 회의 필요 |
| 2 | 문서 수집 (크롤러 또는 다운로드) | 0.5~1d | 라이브러리당 별도 처리 |
| 3 | 청킹 정책 설계 (헤딩 / sliding / semantic) | 0.5d | Researcher의 청킹과 일관성 → 우재민 작업 충돌 |
| 4 | 임베딩 모델 선택 (한국어/영문/코드 혼합) | 0.5d | 모델 비교 실험 필요 |
| 5 | Vector DB 셋업 (Chroma/FAISS/Qdrant) + 인덱스 빌드 | 0.5d | 데모 PC 환경 의존 |
| 6 | Retrieval 품질 평가 골든셋 (recall@k 측정) | 1d | **이걸 빼면 발표에서 첫 질문에 무너짐** |
| 7 | API 인터페이스 + Context Agent 통합 | 0.5d | 정상 경로 |
| 8 | 인덱스에 없는 라이브러리 fallback | 0.5d | **결국 웹검색을 또 만들어야 함** |
| | **합계** | **~4~5일** | 우재민·홍지호 작업 일부 막힘 |

#### Path B — MCP + Web Search API (우리 안)

| # | 작업 | 시간 |
|---|------|------|
| 1 | Context7 MCP 어댑터 (`pip install` + API key + `resolve-library-id`/`query-docs`) | 2~3h |
| 2 | Web Search API 폴백 (DDG 무료 API or `requests` + BeautifulSoup) | 2~3h |
| 3 | `fetch_url` 핸들러 (페이지 본문 ≤500자 excerpt) | 1h |
| 4 | `compare_text_to_facts` (LLM 호출 1번) | 2h |
| 5 | Context Agent ReAct 통합 (`create_react_agent`) | 3h |
| 6 | 캐시 (in-memory dict, 30분 TTL) | 1h |
| | **합계** | **~1.5일 (Day 2 통째)** |

> 일정 매칭: 본 SPEC 의 **Day 2** 슬롯(Context Agent + tool 핸들러)에 정확히 들어맞는 분량.
> Path A는 Day 2 하루로는 절대 끝나지 않음.

### 12.3 시간이 절약되는 진짜 이유 3가지

#### 1) 품질 평가 책임의 외주화
RAG의 본질적 책임은 *"내가 인덱싱한 결과가 실제로 필요한 답을 가져오는가?"* 를 증명하는 것.
이 증명에 필요한 것:
- 골든셋 (PR ↔ 정답 문서) 30~50개 사람이 만들기
- recall@1 / recall@5 / MRR 측정 스크립트
- 청킹 정책 변경 시 재측정

= **최소 1일짜리 작업**. 그리고 7일 일정에 이 슬롯이 없음.

반면 MCP는 **Context7가 자기 인덱스 품질을 책임지는 외부 서비스**.
우리 책임은 *호출이 잘 되는가* 까지로 끝남 → 단순 통합 테스트.

#### 2) 인덱스라는 운영 부담의 제거
Vector DB 인덱스는 *살아있는 데이터*:
- Django 5.2 → 5.3 나오면 인덱스 갱신
- 새 라이브러리 PR 들어오면 인덱스에 없음 → 사용자 경험 깨짐
- 임베딩 모델 바꾸면 전체 재인덱싱

발표 후 *"이 시스템 어떻게 운영하나요?"* 질문에 답하려면 이 운영 비용까지 설명해야 함.
MCP는 이 부담을 외주화 — Context7가 자기 인덱스를 갱신하고, 우리는 호출만.

#### 3) Fallback이 어차피 필요 — RAG 가도 웹검색은 만들어야 함
Path A의 가장 미묘한 함정:

```
PR 입력 → 인덱스에 라이브러리 있음?
  Yes → RAG top-k
  No  → ???   ← 이걸 비워둘 수 없음
```

`???` 는 결국 **웹검색**으로 채워야 함 (아무것도 안 보여줄 수는 없으니).
→ **Path A는 "Path B에 RAG를 추가한 것"** 이지, "Path B를 RAG로 대체"가 아님.
→ 작업이 줄어드는 게 아니라 **추가**.

### 12.4 구현 난이도 비교

| 영역 | RAG | MCP+Web |
|------|-----|---------|
| 외부 의존성 셋업 | Vector DB 서버 / 임베딩 모델 / 디스크 | `pip install context7` + API key |
| 정확성 검증 책임 | 우리 (recall 평가) | Context7 (외부) |
| 라이브러리 커버리지 결정 | 우리가 사전 선정 | 무관 — Context7가 알아서 |
| 새 라이브러리 추가 비용 | 재인덱싱 | 0 (아무 라이브러리든 즉시) |
| 데이터 신선도 책임 | 우리 (인덱스 갱신) | Context7 (자동) |
| Agentic 정합성 | 정적 top-k = Workflow | 동적 도구 호출 = ReAct (본 시스템 패턴과 정합) |

### 12.5 학생 안을 단계적으로 흡수하는 로드맵

> 학생의 RAG 안은 **부정되는 게 아니라 후순위로 살아있다.**
> 본 SPEC §11 Open Questions 와 정렬.

| 단계 | 변화 | 학생 안의 자리 |
|------|------|---------------|
| MVP (Day 2) | Context7 + Web만 (본 SPEC 그대로) | — |
| Post-MVP Step 1 | (lib, topic) 캐시 hit 카운트 측정 | 측정 인프라 |
| Post-MVP Step 2 | hit ≥ N회인 쿼리는 **자동으로 vector DB에 인덱싱** | RAG fast-path 도입 자리 |
| Post-MVP Step 3 | Layer 1(RAG) → Layer 2(Context7) → Layer 3(Web) **layered retrieval** 완성 | 학생 안이 시스템의 1순위 계층이 됨 |

### 12.6 발표/심사 자리에서의 표현

- ❌ "우리는 vector DB가 별로여서 안 썼다"
- ✅ "우리는 *layered retrieval* 의 점진 도입 전략을 채택했다.
   MVP는 외부 서비스(Context7) + 웹검색으로 빠르게 동작 확보, 사용 패턴이 누적되면 자주 hit하는 쿼리를 RAG로 fast-path 캐시한다.
   이는 *premature optimization 회피* 와 *7-day 일정 안 동작 보장* 두 제약을 동시에 만족시키는 결정이다."

## 13. 레퍼런스

- [Anthropic — Building Effective AI Agents (Autonomous Agent / Tool Use)](https://www.anthropic.com/research/building-effective-agents)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [LangGraph + MCP Multi-agent guide](https://techbytes.app/posts/langgraph-mcp-multi-agent-workflow-guide-2026/)
- [Context7 MCP](https://github.com/upstash/context7)
- [HuggingFace — Thought-Action-Observation Cycle](https://huggingface.co/learn/agents-course/en/unit1/agent-steps-and-structure)
- [00-common/AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md)
- [00-common/AGENTIC-EVALUATION.md §9 (분산 self-evaluation)](../00-common/AGENTIC-EVALUATION.md)
