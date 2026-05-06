# SPEC — Writer Agent (with internal Self-Reflection & Self-Evaluation)

**담당:** 정민기 (본체) + **김영표** (self_reflection 시스템 프롬프트 / finding 분류기 / `verify_fact_in_diff` tool)
**디렉토리:** `04-writer-agent/`
**관련 기획서 섹션:** §2.2 (초안 생성 + 자체 검토), §2.3 (성격 및 톤앤매너), §3.1 (사용자 시나리오), §4.3 (프롬프트 설계 — Writer)

> **변경 이력 (v0.4):** 디렉토리 번호 `03` → `04`. v0.3 결정(self-eval 분산)은 그대로.
> Verification Layer 폐기와 함께 본 노드 입력에서 `ContextResult` 의 의미가 강해짐 (이미 검증 끝난 reference만 들어옴).
>
> **v0.3:** 별도 `05-evaluation-layer` 노드 폐기, 평가 책임 분산. Writer가 가장 무거운 self-eval(grade A~F).

## 0. Subsection Ownership (v0.4 명시)

| 섹션 / 산출물 | 담당 |
|---------------|------|
| §5 generate_draft 시스템 프롬프트 | 정민기 |
| §6 deterministic_checklist 결정적 함수 | 정민기 |
| §7.2 self_reflection 시스템 프롬프트 + 종료조건 | **김영표** |
| §7.2의 5개 finding 분류기 (regex/LLM 검출 로직) | **김영표** |
| `verify_fact_in_diff` tool 핸들러 (코드 위치는 05-backend) | **김영표** |
| §7.3 self_evaluation 시스템 프롬프트 + 루브릭 | 정민기 |
| §12 골든셋 채점 / 동의율 분석 | **홍지호** ([05-backend SPEC §10](../05-backend/SPEC.md) 골든셋 섹션과 정렬) |

---

## 1. 목적

`ResearchResult`(사실)와 `ContextResult.verified_references`(검증된 외부 컨텍스트)만을 사용해,
**문제-원인-해결-결과** 4-Act 구조의 **Markdown 기술 블로그 초안** 을 생성한다.
같은 노드 안에서 (a) **결정적 체크리스트 게이트** → (b) **self-reflection (수정용)** → (c) **self-evaluation (등급용)** 을 수행해
사용자에게 노출 가능한 grade(A~F)와 함께 최종 `DraftResult` 를 반환한다.

## 2. 입력 / 출력

- 입력
  - [`ResearchResult`](../00-common/DATA-CONTRACTS.md#2-researchresult-researcher-agent-출력)
  - [`ContextResult`](../00-common/DATA-CONTRACTS.md#3-contextresult-context-agent--verification-layer-출력)
  - 옵션: `mode: "full" | "minimal_context"` (Orchestrator가 coverage에 따라 설정)
- 출력
  - [`DraftResult`](../00-common/DATA-CONTRACTS.md#4-draftresult-writer-agent-최종-산출) — `self_eval` 필드 포함
  - 보조: `VerificationResult[]` (reflection iteration 누적)

## 3. 핵심 책임

✅
- 4-Act 구조 강제 (intro / problem / cause / solution / result / outro)
- Markdown 출력 (헤딩, 코드 블록, 인용, 리스트)
- 신입~주니어 개발자가 이해할 수 있는 톤 유지
- 인용 가능한 외부 레퍼런스만 본문에 인용 (`verified_references` 외 사용 금지)
- **결정적 체크리스트 게이트** 통과 — 형식 위반은 LLM 호출 전에 잡는다
- **Self-reflection** (≤2회) — 사실성/구조/추측 점검 + 자동 패치
- **Self-evaluation** (1회) — 4축 점수 + grade(A~F), 사용자 노출용

❌
- 외부 검색 (Context Agent 책임)
- 사실 추출/추가 (Researcher 책임)
- 블로그 자동 발행
- self-eval 점수가 임계 미만이라고 자기 자신을 다시 호출하는 루프 (MVP에서는 grade는 보고용 — 시스템 행동에 피드백되지 않는다)

## 4. 출력 형식 (4-Act + Outro)

```markdown
# {title}

## 들어가며
- PR/이슈 한 줄 요약 (1~2문단)

## 문제 상황
- 어떤 문제가 있었는가? (issue/commit/diff 근거)

## 원인 분석
- 코드 차원에서 왜 발생했나? (changed_functions / facts 인용)

## 해결 방법
- 무엇을 바꿨는가? (필수 코드블록 ≥ 1)
- 왜 그렇게 바꿨는가? (verified_references 인용 가능)

## 결과 및 효과
- 측정·관찰 가능한 결과 (PR 본문에 있을 때만)

## 마치며
- 회고 1문단 (추측 금지)
```

### 4.1 톤앤매너 (기획서 §2.3)
- 문장 종결: `~했습니다` 중심.
- 청자: 신입/주니어 개발자.
- 어려운 개념은 1문장 풀어쓰기 후 사용.
- 1인칭 "저는" 사용 가능, 단정적 일반화 금지.
- 한 문단 ≤ 4문장.

### 4.2 인용 규칙
- 외부 사실: `verified_references` 의 URL을 [텍스트](URL) 형태로.
- PR 사실: 본문 인용으로 표시 (`> linked issue: ...`).
- 인용처가 없는 주장은 작성 금지.

## 5. 노드 내부 파이프라인

```
generate_draft (LLM, temperature=0.3)
       │
       ▼
deterministic_checklist  ← 결정적 게이트 (regex/구조)
       │  실패 시 (critical만): 1회 patch 트리거
       ▼
self_reflection  (LLM, ≤ 2회, finding-driven)
       │  iteration 1 → critical finding 있으면 patch → iteration 2
       │  종료 조건: AGENT-PATTERNS §2.2 (5종)
       ▼
self_evaluation  (LLM, 1회, 다른 시스템 프롬프트)
       │  4 dimension 점수 + rationale + grade(A~F) + suggestions
       ▼
DraftResult.final  (revision ≤ 2, self_eval 포함)
```

세 단계 모두 **같은 노드 안**에서 수행된다 (LangGraph 외부 노드 추가 없음).
self-reflection과 self-evaluation은 **분명히 다른 책임**이며 **다른 시스템 프롬프트**를 사용한다 (§7 참조).

## 6. 결정적 체크리스트 (LLM 호출 전 게이트)

LLM 호출 비용을 줄이고, 형식 사고를 일찍 잡는다.

| 항목 | 통과 조건 | 실패 시 동작 |
|------|----------|-------------|
| `title_length` | 5 ≤ len(title) ≤ 60 | reflection 1회 강제 |
| `has_code_block` | 본문에 ` ``` ` 코드블록 ≥ 1 | reflection 1회 강제 (critical) |
| `four_act_present` | problem/cause/solution/result 4개 섹션 모두 존재 | reflection 1회 강제 (critical) |
| `pr_metadata_present` | PR title 또는 pr_identifier 가 본문에 등장 | finding 만들고 통과 |
| `cited_refs_subset_verified` | `cited_references` ⊆ `verified_references.url` | 위반 URL 자동 제거 + finding |
| `no_speculation_words` | 본문에 "아마\|추정\|혹시\|~할 수도" 부재 | 위반 문장 표시 + finding |
| `length_in_range` | 600 ≤ word_count ≤ 3,000 | warning만, 차단 안 함 |

체크리스트는 결정적 함수 (LLM 미사용). [DATA-CONTRACTS §4.1](../00-common/DATA-CONTRACTS.md) `ChecklistItem` 스키마.

## 7. 프롬프트 전략 (3개의 분리된 시스템 프롬프트)

> 셋은 **다른 모델 인스턴스 또는 다른 시스템 프롬프트**로 호출되어야 한다 — self-eval bias 부분 완화.
> Writer 자체는 `solar-pro`, reflection/eval 은 `solar-mini` 권장 (비용 절감 + 경량 분리).

### 7.1 generate_draft 시스템 프롬프트 (요약)
```
당신은 시니어 개발자가 신입을 위해 쓰는 기술 블로그 초안 작성자입니다.

[강제 규칙]
1. 아래 [INPUT] 외의 정보를 사용하지 않습니다 — 추측 금지.
2. 4-Act 구조(들어가며/문제/원인/해결/결과/마치며)를 반드시 지킵니다.
3. 코드 블록은 최소 1개 이상 포함합니다.
4. verified_references 안의 URL만 인용합니다.
5. 결과 섹션은 PR 본문에 측정값이 없으면 "관찰된 효과" 정도로만 한정합니다.
6. 출력은 DraftResult JSON 스키마를 따릅니다.

[톤]
- "~했습니다" 중심 / 신입 개발자 가독성 우선 / 한 문단 4문장 이하
```
`temperature=0.3`.

### 7.2 self_reflection 시스템 프롬프트 (요약)
```
당신은 기술 블로그 초안의 사실성/구조/톤을 점검하는 검증자입니다.
(작성자와 별개의 페르소나입니다.)

[원칙]
- 각 finding을 만들기 전 1~2문장 reasoning을 먼저 적습니다 (G-Eval 스타일).
- "아마/추정/혹시/~할 수도" 톤을 잡아냅니다.
- research.facts 중 미언급 핵심 사실을 잡아냅니다.
- 본문 주장 → 근거(facts/verified_references) 매핑이 안 되면 ungrounded_claim.
- 코드블록 인접 ±1 문단의 설명이 부실하면 code_under_explained.

[도구]
- verify_fact_in_diff(statement)  ← 의심 시 PR diff 매칭

[출력]
VerificationResult Pydantic 스키마.

[종료]
critical finding이 0개면 즉시 종료. 동일 finding 반복 감지 시 종료.
```
`temperature=0`. `recursion_limit=3`, `max_tool_calls=2`.

### 7.3 self_evaluation 시스템 프롬프트 (요약)
```
당신은 기술 블로그 초안을 평가하는 채점자입니다.
(작성자/검증자와 별개의 페르소나입니다.)

[원칙]
- 점수를 적기 전 1~3문장 reasoning을 먼저 적습니다 (G-Eval).
- 4축은 독립적으로 평가합니다 (analytic rubric):
    accuracy, readability, structure, code_explanation
- 각 축 1~5점 + rationale.
- 길이로 점수를 매기지 마세요 (length bias 방지).

[루브릭 anchor]
5 = 모든 주장이 근거에 부합 / 신입도 이해 / 흠 없음
4 = 한두 곳 사소한 누락 / 전체 흐름은 정확
3 = 사실은 대체로 맞으나 한 항목에서 추측 또는 모호
2 = 핵심 주장 1개 이상이 근거 부족
1 = 사실관계 오류가 핵심에서 발견

[페널티]
- VerificationResult.needs_human_review == True → 모든 축 -0.5
- cited_refs_subset_verified 실패 → accuracy ≤ 2

[출력]
SelfEvaluationResult Pydantic 스키마 + grade.
grade: avg ≥ 4.5 → A, ≥ 4.0 → B, ≥ 3.0 → C, ≥ 2.0 → D, else F.
```
`temperature=0`. **단일 호출** (재시도 없음).

## 8. Mode별 차이

| Mode | 설명 |
|------|------|
| `full` | verified_references 사용 가능 |
| `minimal_context` | 외부 인용 금지, PR 정보만으로 작성. "공식 문서를 추가로 확인하세요" 한 문장만 outro에 허용. self-eval은 동일하게 수행하되 accuracy 차원에서 "외부 검증 부재"를 rationale에 명시 |

## 9. 종료 조건 (3단계 합산)

| 단계 | 종료 조건 |
|------|----------|
| deterministic_checklist | 모든 critical 항목 통과 |
| self_reflection | critical finding 0 / iteration 2 도달 / 동일 finding 반복 / no-tool answer |
| self_evaluation | 1회 호출 후 단일 SelfEvaluationResult 반환 |

자세한 종료 조건 5종은 [AGENT-PATTERNS §2.2](../00-common/AGENT-PATTERNS.md).

## 10. 실패 모드 / Fallback

| 상황 | 동작 |
|------|------|
| LLM 빈 출력 (generate) | 1회 재시도; 그래도 빈 출력이면 4-Act 빈 템플릿 + outro에 "초안 생성 실패" |
| 코드 블록 0개 | deterministic checklist가 critical → reflection 1회 강제 |
| `mode=minimal_context`인데 외부 URL 인용 시도 | 후처리에서 URL 제거 + finding 기록 |
| 본문이 5,000자 초과 | 섹션 단위로 압축 재작성 |
| `verified_references` 0건 | 자동으로 `mode=minimal_context` 적용 |
| reflection 무한 루프 | iteration 2 도달 시 강제 종료, `needs_human_review=True` |
| self-eval LLM 실패 | grade=`?`, score=null, suggestions=["평가 실패 — 사람 검토 필요"], 초안은 그대로 반환 |

## 11. 테스트 전략

- **스키마:** Pydantic 검증 통과 (Draft + self_eval)
- **체크리스트 단위:** 각 결정적 항목 합성 입력으로 통과/실패 검증
- **추측 단어 검출:** "아마도", "추정" 출현 시 후처리에서 제거 또는 finding
- **인용 검증:** `cited_references` ⊆ `verified_references` 자동 검사
- **회귀:** 샘플 PR 5개 markdown SHA + grade 추적
- **Self-eval 안정성:** 동일 입력에 대해 score 분산 ≤ 0.5 (3회 호출 평균, temperature=0)
- **편향 검사 (length bias):** 같은 본문을 단순히 늘리기만 했을 때 readability 점수가 올라가지 않아야 함
- **A/B:** `full` vs `minimal_context` 동일 PR의 grade 차이가 일정 폭 안

## 12. 골든셋 (선택, Day 5~6)

- 사람이 채점한 샘플 5~10개 (팀이 직접 점수)
- 차원별 |LLM_score - human_score| ≤ 1 → "동의"
- 목표: 동의율 ≥ 0.8

## 13. 관측성

- 토큰 수 (input/output), LLM 호출 시간 — 3개 단계 각각
- 섹션별 글자 수 분포
- 코드블록 개수
- self-reflection 반복 횟수, 자동 패치 적용 여부
- 결정적 체크리스트 항목별 통과율
- self-eval 점수 분포 / grade 분포 (시계열)
- length-vs-readability 산점도 (편향 모니터링)

## 14. 사용자 노출 형식 (UI)

```
# Generated Draft
[Markdown 렌더링]

# Self-Evaluation: B (4.1 / 5.0)
- accuracy:         4 ★★★★☆   "Solar API 인용은 정확하나, 결과 수치 출처가 모호"
- readability:      5 ★★★★★
- structure:        4 ★★★★☆
- code_explanation: 4 ★★★★☆

# Checklist: 7/8 통과
✗ has_outro_section

# Reflection: 1회 자동 수정됨 (missing_fact 1건 패치)
```

## 15. 한계 (정직성)

- **Self-eval bias**: 같은 모델 가족이 자기 출력을 평가하므로 점수가 후할 수 있다. 다른 시스템 프롬프트로만 부분 완화.
- **시계열 회귀 측정의 약점**: 외부 객관 지표가 없어 "이번 주가 지난주보다 정말 나아졌는지" 단정하기 어렵다 — 골든셋 동의율로 보완.
- 완전한 분리는 post-MVP에서 다른 vendor/모델로 self-evaluation을 옮기면 해소.

## 16. 레퍼런스

- [Anthropic — Building Effective AI Agents (Evaluator-Optimizer)](https://www.anthropic.com/research/building-effective-agents)
- [HuggingFace Blog — Reflection in AI Agents](https://huggingface.co/blog/Kseniase/reflection)
- [Confident AI — LLM-as-a-Judge Guide](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method)
- [Adnan Masood — Rubric-Based Evals & LLM-as-a-Judge](https://medium.com/@adnanmasood/rubric-based-evals-llm-as-a-judge-methodologies-and-empirical-validation-in-domain-context-71936b989e80)
- [arXiv 2509.05741 — Multi-Stage Self-Verification](https://arxiv.org/html/2509.05741v1)
- [LangChain Docs — Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [00-common/AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md)
- [00-common/AGENTIC-EVALUATION.md §9](../00-common/AGENTIC-EVALUATION.md)
