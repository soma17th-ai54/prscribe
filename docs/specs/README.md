# 54조 — GitHub PR 기반 기술블로그 생성 에이전트 SPEC

본 디렉토리는 [54조 프로젝트 기획서](../[54조]프로젝트%20기획서%20양식_54조_GitHub%20PR%20기반%20기술블로그%20생성%20에이전트.docx.pdf)를
**Spec-Driven Development(SDD)** 관점에서 구현 가능한 단위로 분해한 명세 모음입니다.

> 모든 문서는 "기획서 → SPEC → 코드"의 단방향 의존성을 가지며,
> SPEC을 변경할 때는 반드시 [00-common/CHANGELOG.md](./00-common/CHANGELOG.md)에 사유를 남깁니다.

> **현재 버전: v0.4** (2026-05-06).
> 변경 사유 / v0.1~v0.4 매핑 / 결정 근거는 [00-common/CHANGELOG.md](./00-common/CHANGELOG.md) 와
> [00-common/AGENTIC-EVALUATION.md](./00-common/AGENTIC-EVALUATION.md) 참조.

---

## 1. 디렉토리 맵 (v0.4)

| 번호 | 디렉토리 | 담당자 | 핵심 산출물 | 패턴 | 입력 → 출력 |
|----|----------|--------|------------|------|-------------|
| 00 | `00-common/` | 공통(전원) | 프로젝트 개요 / 아키텍처 / 데이터 계약 / Agentic 평가 / Agent-Patterns / CHANGELOG | — | — |
| 01 | `01-langgraph-orchestration/` | **조재영** | StateGraph 정의 (3-노드 골격), 체크포인터, retry, streaming | 결정적 그래프 | `pr_identifier` → `GraphState` |
| 02 | `02-researcher-agent/` | **우재민** | PR 사실 추출 + 청킹 + 키워드 + **내부 self-eval** | Tool-using ReAct | `RawPRData` → `ResearchResult` |
| 03 | `03-context-agent/` | **조재영** | 외부 검색 + **검증 흡수** + **self-eval** (한 노드) | 풀 ReAct (per-chunk) | `ResearchResult.search_chunks` → `ContextResult` |
| 04 | `04-writer-agent/` | **정민기** + **김영표** | 4-Act Markdown + 결정적 checklist + **reflection ≤2회** + **self-eval (grade A~F)** | Workflow + 내부 reflection 루프 | `ResearchResult` + `ContextResult` → `DraftResult` |
| 05 | `05-backend/` | **홍지호** | GitHub / Solar / Context7 인프라 + 공통 tool 핸들러 + **골든셋 채점 / 동의율 분석** | 인프라 (얇은 어댑터) | HTTP / in-process |
| 06 | `06-frontend/` | 공통 (홍지호 보조) | Streamlit Demo UI (PR 입력 / 초안 / Trace / **단계별 self-eval 카드**) | UI | 사용자 입력 → 시각화 |

### 1.1 역할 재배정 (v0.4)

| 멤버 | 책임 | 디렉토리 |
|------|------|---------|
| **조재영** | LangGraph 흐름 통제 + Context Agent ReAct 노드 (검증 흡수 포함) | 01 + 03 |
| 우재민 | Researcher ReAct + 청킹 정책 + Researcher self-eval | 02 |
| 정민기 | Writer 본체 (generate / checklist / self_evaluation) | 04 (정민기 섹션) |
| 김영표 | Writer self_reflection (시스템 프롬프트 / 5종 finding 분류기 / `verify_fact_in_diff` 정책) | 04 (김영표 섹션) |
| 홍지호 | 05-backend 인프라 + Solar 모델 라우팅 + **골든셋 5~10개 채점 / 동의율 분석** | 05 |

> v0.4 변경: Context Agent를 own SPEC으로 끌어올리고 Verification Layer를 그 안으로 흡수.
> v0.3: 04-writer-self-verification 와 05-evaluation-layer 디렉토리 폐기 (Writer 내부 reflection + 분산 self-eval로).
> 사유 / 한계는 [00-common/AGENTIC-EVALUATION.md §9~§10](./00-common/AGENTIC-EVALUATION.md), [CHANGELOG.md](./00-common/CHANGELOG.md) 참조.

---

## 2. 읽는 순서

처음 합류한 팀원은 다음 순서를 권장합니다.

1. [00-common/PROJECT-OVERVIEW.md](./00-common/PROJECT-OVERVIEW.md) — 무엇을, 왜 만드는가
2. [00-common/ARCHITECTURE.md](./00-common/ARCHITECTURE.md) — 시스템 전체 그림 (3-노드 골격)
3. [00-common/DATA-CONTRACTS.md](./00-common/DATA-CONTRACTS.md) — Pydantic 스키마 (모든 hand-off)
4. [00-common/AGENTIC-EVALUATION.md](./00-common/AGENTIC-EVALUATION.md) — 본 시스템이 진짜 "에이전틱"인지 + 한계 명시
5. [00-common/AGENT-PATTERNS.md](./00-common/AGENT-PATTERNS.md) — Workflow vs ReAct 결정 매트릭스 / Tool 카탈로그 / 종료조건
6. [00-common/CHANGELOG.md](./00-common/CHANGELOG.md) — v0.1 → v0.4 변천사
7. 본인 담당 디렉토리의 `SPEC.md`

---

## 3. SPEC 문서 작성 규칙

각 SPEC은 다음 8개 섹션을 반드시 포함합니다.

1. **목적(Goal)** — 한 문단으로 표현되는 모듈의 존재 이유
2. **입력/출력 계약** — Pydantic 모델 명, 필수/선택 필드, 예시 JSON
3. **핵심 책임** — 이 모듈만 책임지는 일 + **명시적으로 하지 않는 일**
4. **알고리즘/프롬프트 전략** — 의사코드 또는 프롬프트 템플릿
5. **실패 모드 & 폴백** — PR이 비정상이거나 LLM이 실패할 때 동작
6. **테스트 전략** — 단위/통합/회귀 테스트 케이스
7. **관측성** — 로깅, Trace, 메트릭
8. **레퍼런스** — 공식 문서·논문 링크

> 다중 담당자 SPEC은 §0 또는 §책임 분담 테이블에 **Subsection Ownership** 명시 (04 SPEC 참고).

---

## 4. Definition of Done (전체 시스템)

MVP 완료 기준은 [00-common/PROJECT-OVERVIEW.md](./00-common/PROJECT-OVERVIEW.md#definition-of-done)에서 정의합니다.
요약:

- [ ] 데모 UI에서 PR URL을 입력 → Markdown 초안이 30초 이내 생성
- [ ] 3단계(Researcher → Context → Writer) Trace + ReAct steps가 UI에 노출
- [ ] Writer self-eval 평균 ≥ 4.0/5.0 (grade ≥ B), 결정적 체크리스트 통과율 ≥ 90%
- [ ] 단계별 self-eval(Researcher / Context / Writer) 모두 UI에 카드로 표시 + bias 한계 footnote 명시
- [ ] PR diff 누락·linked issue 없음·GitHub API 실패 등 3가지 fallback 시나리오 통과
- [ ] (홍지호) 골든셋 5~10개 사람-LLM 동의율 ≥ 0.8
