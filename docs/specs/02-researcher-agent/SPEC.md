# SPEC — Researcher Agent

**담당:** 우재민
**디렉토리:** `02-researcher-agent/`
**관련 기획서 섹션:** §2.2 (사실 수집), §4.3 (프롬프트 설계 — Researcher), §4.4 (Chunking)

---

## 1. 목적

PR diff·commit message·linked issue에서 **확인 가능한 사실만**을 추출해
구조화된 JSON(`ResearchResult`)으로 변환하고,
이후 Context Agent가 외부 문서를 검색할 수 있도록
**전략적 청킹(Chunking)** 과 **검색 키워드 변환** 을 수행한다.

> 추측 금지 (Anthropic의 *grounded extraction* 원칙).

## 2. 입력 / 출력

- 입력: [`RawPRData`](../00-common/DATA-CONTRACTS.md#1-raw-pr-data-github-api--researcher-입력)
- 출력: [`ResearchResult`](../00-common/DATA-CONTRACTS.md#2-researchresult-researcher-agent-출력)

## 3. 핵심 책임

✅ 이 Agent가 하는 일
- diff에서 변경 파일·함수·클래스 목록 추출
- commit message에서 작업 의도 단서 추출 (단, 의도를 새로 만들지 않음)
- linked issue에서 문제 진술 추출
- import / 파일 확장자 / 디렉토리명에서 tech stack hint 식별
- diff hunk를 **의미 단위 청크** 로 분할
- 각 청크 → 외부 검색용 **키워드 3~7개** + intent 라벨

❌ 하지 않는 일
- "왜 그렇게 고쳤을까?" 추측
- "이 코드는 더 빠를 것이다" 같은 평가성 발언
- 외부 문서 검색 (Context Agent 책임)
- Markdown 글 작성 (Writer 책임)

## 4. 알고리즘 / 프롬프트

> 본 SPEC은 **Tool-using ReAct 노드 + 내부 Self-Evaluation** 으로 구현됩니다.
> 공통 골격·Tool 카탈로그·종료조건은 [AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md) 참조.
>
> **변경 이력 (v0.3):** 별도 Evaluation Layer 폐기에 따라 본 노드도 자체 self-evaluation
> (사실 추출 충실성·청크 품질) 단계를 추가한다. 같은 노드 내부, 다른 시스템 프롬프트.

### 4.1 파이프라인 (전처리 → ReAct → 후처리 → Self-Eval)

```
RawPRData
   │
   ├─[전처리, 결정적]─▶ extract_changed_files()
   │                  extract_changed_functions()  (AST or regex)
   │                  extract_tech_stack_hints()
   │                  pre_chunk_diff()             (token-aware)
   │
   ├─[ReAct 루프, 최대 8 step]
   │   tools: read_pr_file, grep_pr, list_pr_files,
   │          get_commit_message, get_linked_issue,
   │          finish, give_up
   │   목표: facts[], search_chunks[], notes[] 채우기
   │
   ├─[후처리, 결정적]─▶ Pydantic 검증 / 추측 단어 검출 / source_locator 검증
   │
   └─[Self-Evaluation, LLM 1회, 다른 시스템 프롬프트]
        │ 출력 자체를 채점:
        │   coverage     — 변경 파일/함수 중 facts에 매핑된 비율 (결정적 + LLM)
        │   groundedness — 모든 fact가 source_locator로 PR 안에 있는가 (결정적)
        │   chunk_quality — search_chunks의 키워드가 검색 가능한 식별력을 가지는가 (LLM, 1~5)
        │   confidence   — 종합 (1~5)
        │ 결과는 ResearchResult.self_eval 에 저장.
```

### 4.1.1 ReAct 도구 사용 시나리오 (예시)

| 의도 | 호출 |
|------|------|
| "이 함수 변경의 호출자가 어디?" | `grep_pr(pattern=r"\\bfoo\\(", glob="*.py")` |
| "이 함수의 시그니처 확인" | `read_pr_file("services/user.py", (40, 80))` |
| "linked issue 본문 다시 보기" | `get_linked_issue(142)` |
| "확신 없는 사실 — 패스" | (finish의 `notes`에 "확인 필요" 추가) |
| 종료 | `finish(output_json=ResearchResult.model_dump())` |

### 4.2 청킹 정책 (기획서 §4.4 충실 구현)

- **Chunk unit**: 한 파일의 한 hunk + 주변 ±5라인 컨텍스트.
- **Token budget per chunk**: ≤ 1,200 input tokens (Solar context window 보호).
- **Overlap**: 인접 hunk 사이 2라인 overlap → 의미 단절 방지.
- **분할 우선순위**:
  1. 파일 단위 우선
  2. 파일 ≥ 1,200 토큰이면 함수 경계로 재분할 (AST 또는 정규식)
  3. 함수 ≥ 1,200 토큰이면 라인 윈도우로 재분할
- **메타데이터**: 각 chunk에 `file`, `function`, `lang`, `loc_range` 유지.

### 4.3 ReAct 시스템 프롬프트 (요약)

```
[SYSTEM]
당신은 코드 변경의 "사실"만 추출하는 분석가입니다.

[원칙]
- 추측 금지. 코드/메시지/이슈에 적힌 표현 또는 직접적 paraphrase 만 사용.
- 모르면 "확인 필요"로 표시 (notes에 기록).
- 더 이상 새 사실이 안 나오면 즉시 finish.
- 같은 도구를 같은 인자로 두 번 호출하지 말 것 (loop_detected).

[도구]
- read_pr_file, grep_pr, list_pr_files, get_commit_message, get_linked_issue
- finish(output_json=ResearchResult), give_up(reason)

[종료]
1) 모든 변경 파일·함수가 facts에 매핑되었거나
2) recursion_limit=8 도달 또는
3) 동일 호출 반복 감지

[출력]
finish 시 output_json은 ResearchResult Pydantic 스키마.
```

`max_tool_calls=6`, `temperature=0`, `recursion_limit=8`, `timeout=20s` (AGENT-PATTERNS §2.1).

#### Search keyword 변환 (전용 LLM 호출 1회 — 결정적, ReAct 외부)
```
[SYSTEM]
다음 코드 변경 청크를 외부 문서 검색용 키워드로 변환합니다.
- 영어/한국어 혼합 허용. 일반 단어보다 식별력 있는 용어 우선.
- intent 중 하나로 분류: concept_lookup / api_usage / best_practice / error_or_pitfall
- 출력은 SearchChunk[] JSON.
```

### 4.4 출력 검증

- Pydantic으로 강제 (실패 시 1회 재요청).
- `facts[*].source_locator` 가 실제 파일/라인 범위 안인지 후처리 검사.
- 빈 `facts`는 허용하되 `notes` 에 사유 기록.

### 4.5 Self-Evaluation 시스템 프롬프트 (요약)

```
[SYSTEM]
당신은 사실 추출기의 출력을 채점하는 검증자입니다.
(추출자와 별개의 페르소나입니다.)

[원칙]
- 점수 전 1~2문장 reasoning을 먼저 적습니다 (G-Eval).
- 4 dimension 독립 평가:
  1) coverage:     변경 파일/함수 중 facts에 등장한 비율 (이미 결정적으로 산출된 값을 검토)
  2) groundedness: 모든 fact가 source_locator로 검증 가능한가 (결정적 + 의심 시 LLM)
  3) chunk_quality: search_chunks 키워드가 일반 단어가 아닌 식별력 있는 용어인가
  4) confidence:   종합 (1~5)

[출력]
ResearcherSelfEval Pydantic 스키마 (DATA-CONTRACTS §2.1).

[유의]
- 점수 산출용. 자신의 추출 결과를 다시 만들지 마세요.
- 임계 미만이라도 시스템 행동 변화 없음 — 보고만 합니다.
```
`temperature=0`. 단일 호출.

## 5. 실패 모드 / Fallback

| 상황 | 동작 |
|------|------|
| diff가 5,000줄 초과 | 상위 변경 빈도 파일·함수 30개로 절단 + `notes`에 명시 |
| linked issue 없음 | `linked_issues=[]`, fact 추출은 commit/diff만으로 진행 |
| 코드가 비-주요 언어 (Brainfuck 등) | tech_stack_hints에 `unknown` 추가, AST 시도 실패 시 라인 단위 청킹으로 폴백 |
| LLM 빈 출력 | 1회 재시도, 재시도도 실패면 빈 `ResearchResult` + 1줄 summary |
| 바이너리/이미지 변경 | `path`만 기록, body 추출 생략 |
| ReAct가 `recursion_limit` 도달 | 마지막 step에서 `finish` 강제 — 부분 결과 + `notes`에 "탐색 한도 도달" |
| Loop detected | 즉시 종료 + `notes`에 검출된 호출 패턴 기록 |
| 동일 tool 연속 4회 실패 | `give_up` 강제 → 최소 ResearchResult |

## 6. 테스트 전략

- **단위:**
  - 파일 1개·함수 1개 PR → `changed_functions` 정확히 1개
  - 파일 50개 PR → 청크 수가 token budget 안에 들어옴
  - "TODO: ..." 같은 commit msg → fact가 추측이 아니라 인용 형태로 들어감
- **속성 기반 (property-based):**
  - 모든 `FactBullet.statement` 가 PR 본문/diff/issue 안의 substring 또는 paraphrase 화이트리스트 안에 있음
- **회귀:** Day 1 샘플 PR 5개 — `ResearchResult` 스냅샷 SHA 비교
- **실패 주입:** Solar API 5xx → fallback 동작 확인

## 7. 관측성

- 청크별 토큰 수, LLM 호출 시간 → trace
- `facts` 개수가 0개로 떨어지면 warning 로그
- "추측 가능성 단어"(예: "아마도", "추정") 후처리 검출 시 reject
- `ReActTrace.steps`를 압축 형태로 GraphState에 기록 (UI에서 펼쳐볼 수 있도록)
- `stopped_by` 분포 — `finish_tool`이 90% 이상이어야 정상
- `self_eval.confidence` 분포 시계열 (시간이 지나며 추출 품질 변화 감시)
- `self_eval.coverage` < 0.6 비율 (낮으면 청크 정책/AST 보강 검토)

## 8. Open Questions

- [ ] Tree-sitter를 도입해 AST 기반 함수 추출을 얼마나 풍부하게? MVP는 Python/JS만 지원, 그 외는 정규식.
- [ ] `search_chunks.keywords` 의 개수 (3~7) 상한을 정량화할지

## 9. 레퍼런스

- [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [GitHub — flows-network/github-pr-summary (chunking 사례)](https://github.com/flows-network/github-pr-summary)
- [Pydantic v2 — Structured outputs](https://docs.pydantic.dev/latest/)
- [LangGraph — `create_react_agent`](https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent)
- [IBM — What is a ReAct Agent?](https://www.ibm.com/think/topics/react-agent)
- [00-common/AGENT-PATTERNS.md](../00-common/AGENT-PATTERNS.md)
