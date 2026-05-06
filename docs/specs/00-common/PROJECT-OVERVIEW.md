# PROJECT OVERVIEW — GitHub PR 기반 기술블로그 생성 에이전트

> 본 문서는 기획서 §1, §3, §5를 SDD 관점에서 재정리한 것입니다.

## 1. 한 줄 정의

> "개발자가 PR을 머지하거나 PR URL을 입력하면, 시스템이 변경사항을 분석해
> **문제-원인-해결-결과 구조의 기술블로그 초안(Markdown)** 을 자동 생성하는
> **LangGraph 기반 Agentic Workflow**."

## 2. 풀고자 하는 문제

| 문제 | 현재 상태 | 본 시스템의 개입 |
|------|-----------|-----------------|
| 기술 블로그 작성 부담 | PR을 머지한 뒤에도 별도로 글의 구조와 문장을 다시 짜야 함 | PR diff/commit/issue로부터 초안을 자동 생성 |
| 코드 변경의 맥락 정리 어려움 | diff만으로는 "왜·어떻게·결과"를 한눈에 보기 어려움 | Researcher가 사실 추출, Writer가 서사 구조화 |
| 글 구조화 어려움 | 단순 코드 설명에 그치기 쉬움 | 문제-원인-해결-결과 4-Act 구조 강제 |
| 품질 평가의 주관성 | 사람마다 평가 기준이 다름 | 자동 체크리스트 + LLM-as-judge 루브릭 |

## 3. 페르소나 & 핵심 가치

### 3.1 페르소나
- **김개발 (백엔드, 20후~30초)**: N+1, API 성능 등 기술적 성과를 빠르게 글로 만들고 싶음
- **이주니어 (학생/신입)**: 자기 PR을 포트폴리오용 글로 자연스럽게 정리하고 싶음
- **개발팀**: PR 기반 의사결정을 사내 지식 자산으로 누적하고 싶음

### 3.2 핵심 가치 (기획서 §1.6, v0.4 정렬)
| 가치 | 어떤 SPEC에서 보장되나 |
|------|----------------------|
| 자동화 | [05-backend SPEC](../05-backend/SPEC.md) |
| 사실 기반 | [02-researcher-agent SPEC](../02-researcher-agent/SPEC.md) + Researcher self_eval |
| 맥락 보강 | [03-context-agent SPEC](../03-context-agent/SPEC.md) + Context self_eval |
| 신뢰도 확보 | [03-context-agent §검증 흡수](../03-context-agent/SPEC.md) + [04-writer-agent §reflection](../04-writer-agent/SPEC.md) |
| 구조화 | [04-writer-agent SPEC](../04-writer-agent/SPEC.md) |
| 가독성 | [04-writer-agent §톤앤매너](../04-writer-agent/SPEC.md) + reflection |
| 품질 검증 | [04-writer-agent §self-evaluation (grade A~F)](../04-writer-agent/SPEC.md) + [05-backend §골든셋](../05-backend/SPEC.md) — v0.3에서 별도 노드 폐기, 각 에이전트 self-eval + 골든셋 동의율로 분산 |

## 4. MVP 범위

### 4.1 반드시 구현 (v0.4)
- GitHub PR 파싱 (diff / commit / linked issue)
- Researcher Agent (사실 추출 + 청킹 + 키워드 + **self-eval**)
- Context Agent (외부 검색 + **검증 흡수** + **self-eval**, per-chunk ReAct)
- Writer Agent (한 노드 안의: 결정적 체크리스트 → reflection ≤2회 → **self-eval grade A~F**)
- LangGraph Orchestrator (`Researcher → Context → Writer`) — 3-노드 골격 + `fetch_github` 진입
- Solar API LLM 연동 (모델 라우팅: 추출/생성=pro, 검증/평가=mini)
- Streamlit 데모 UI (단계별 self-eval 카드)
- 골든셋 5~10개 채점 / 동의율 분석 (홍지호)

### 4.2 MVP 제외
- 블로그 자동 발행 (Velog/Tistory/Notion 직접 포스팅)
- 코드 자동 수정/커밋
- 팀 단위 권한 관리
- 대규모 코드베이스 인덱싱

## 5. 7일 일정 (기획서 §5.3 정렬, v0.4 반영)

| Day | 산출물 | 관련 SPEC |
|-----|--------|----------|
| 1 | GitHub Data Parsing + Researcher Agent baseline (extract만) | 02, 05 |
| 2 | **Context Agent ReAct (검증 흡수 포함)** + tool 핸들러 (search/verify) | 03, 05 |
| 3 | Writer Agent (generate + 결정적 체크리스트 + reflection) | 04 |
| 4 | LangGraph Orchestration (3-노드 연결, Trace, conditional edges) | 01 |
| 5 | **각 에이전트 self-eval 추가** (Researcher / Context / Writer 4-dim+grade) + 골든셋 5~10개 채점 (홍지호) | 02, 03, 04, 05 |
| 6 | Demo UI + E2E 테스트 + fallback 보강 | 06, 05 |
| 7 | 발표 자료 + 시연 시나리오 | — |

> 별도 Evaluation Layer / Verification Layer 노드 작업이 사라졌으므로 Day 2는 Context 풀 ReAct에, Day 5는 self-eval + 골든셋에 집중.

## 6. Definition of Done

MVP는 다음을 모두 만족해야 "완료"라 부릅니다.

| 항목 | 측정 방식 |
|------|----------|
| PR URL 입력 → 초안 생성 | Streamlit 데모에서 샘플 PR URL 5개 모두 정상 출력 |
| 응답 시간 | E2E p50 ≤ 30s, p95 ≤ 60s (Solar API 응답 시간 제외하지 않은 wall-clock) |
| Agent Trace 가시성 | UI에서 3개 노드(Researcher / Context / Writer) 의 입력/출력 JSON + ReAct steps 모두 펼쳐볼 수 있음 |
| Writer self-eval 점수 | 정확성/가독성/구조/코드설명 4개 축 평균 ≥ 4.0 / 5.0 (grade ≥ B) |
| 결정적 체크리스트 통과율 | 검증 항목(제목 길이, 결론 섹션, 코드블록 ≥ 1, PR 정보, 추측단어 부재 등) ≥ 90% |
| 단계별 self-eval 노출 | UI에서 Researcher / Context / Writer 의 self_eval 카드 모두 표시 |
| Fallback 시나리오 | (a) linked issue 없음 (b) GitHub API 실패 (c) Context 검증 실패 — 3개 모두 graceful degradation |
| Self-reflection 작동 | Writer가 자신의 초안에서 추측 문장을 ≥ 1개 식별·수정하는 케이스가 샘플의 30% 이상에서 관찰됨 |
| 골든셋 동의율 (선택) | 사람 채점 5~10개 vs Writer self-eval 차원별 |차이| ≤ 1, 동의율 ≥ 0.8 |

## 7. 주요 의존성 외부 시스템

| 외부 시스템 | 용도 | 실패 시 동작 |
|------------|------|-------------|
| GitHub REST API | PR diff/commit/issue 조회 | 사용자에게 토큰/URL 안내, 분석 중단 |
| Context7 MCP (혹은 일반 웹 검색) | 공식 문서 레퍼런스 보강 | "레퍼런스 없음"으로 표시, Writer 추측 금지 모드로 전환 |
| Solar API | LLM 호출 (생성/판정) | 재시도 3회 후 partial result 반환 |

## 8. 비목표 (Non-Goals)

- 블로그 발행 자동화 (사람이 검토 후 직접 복사·발행)
- PR 코드 자동 수정
- 한 PR 안에서 5,000줄 초과 diff의 완벽한 처리 (chunking 후 핵심만 다룸)
- 한국어 외 다국어 출력 (MVP는 한국어 단일)

## 9. 레퍼런스

- [Anthropic — Building Effective AI Agents](https://www.anthropic.com/research/building-effective-agents)
- [LangChain Docs — Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
