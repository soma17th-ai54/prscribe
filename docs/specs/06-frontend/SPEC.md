# SPEC — Frontend (Streamlit Demo UI)

**담당:** 공통 (홍지호 보조 — 골든셋 결과 표시 섹션)
**디렉토리:** `06-frontend/`
**관련 기획서 섹션:** §3.1 (사용자 시나리오), §3.3 (사용자 워크플로우), §4.1.2 (Streamlit), §4.2 (UI 계층)

> **변경 이력 (v0.4):** 디렉토리 번호 `07` → `06`. Verification Layer 노드 폐기에 따라 진행 단계 표시는 **3 steps**(Researcher / Context / Writer). 각 단계 self-eval 카드는 그대로.
>
> **v0.3:** 별도 Evaluation 탭 폐기. 평가가 각 단계 self-eval로 분산되었으므로 UI도 **단계별 self-eval 카드 3개**를 노출. 최상단에는 Writer self-eval의 grade(A~F)를 헤더로 표시.

---

## 1. 목적

심사위원/사용자가 **PR URL 한 번 입력으로 전체 파이프라인을 시연**할 수 있는 데모 UI.
Streamlit으로 빠르게 만들고, 결과 Markdown / Agent Trace / 단계별 self-eval 점수를 한 화면에서 보여준다.

## 2. 화면 구성

```
┌───────────────────────────────────────────────────────────────┐
│ [Header] GitHub PR → 기술 블로그 초안 생성기                  │
│           ─ Final Grade: B (4.1/5.0) [from Writer.self_eval]  │
│ [Sidebar]                                                     │
│   - GitHub Token (optional, password type)                    │
│   - Solar API Key (env에서 읽기 옵션)                         │
│   - 모드: full / minimal_context                              │
│ [Main]                                                        │
│   1) PR URL 입력 + [생성] 버튼                                │
│   2) 진행 상황 (3 steps progress)                             │
│   3) 결과 탭                                                  │
│      ├─ 📝 초안 (rendered Markdown + 다운로드)               │
│      ├─ 🧭 Agent Trace (각 노드 펼쳐보기 + ReAct steps)        │
│      ├─ 🎯 Self-Eval (단계별 self_eval 카드 4개)              │
│      └─ 🐞 Errors (있을 때만)                                 │
└───────────────────────────────────────────────────────────────┘
```

## 3. 사용자 흐름

| Step | UI 행동 | 내부 동작 |
|------|---------|----------|
| 1 | UI 접속 | `streamlit run app.py` |
| 2 | PR URL 입력 → 생성 클릭 | form submit |
| 3 | 진행상황 3단계 (Researcher / Context (검증 포함) / Writer) | LangGraph `app.stream(stream_mode="updates")` |
| 4 | Researcher 결과 미리보기 + research.self_eval 카드 | trace 펼치기 |
| 5 | Context + Verification 결과 + context.self_eval 카드 | 통과/거부 reference 리스트 |
| 6 | Writer 초안 생성 | 자동으로 `초안` 탭 활성화 |
| 7 | reflection 자동 패치 표시 | "수정됨" 배지 |
| 8 | Writer self_eval grade 헤더 + 4축 점수 카드 | grade 색상 (A=초록, F=빨강) |
| 9 | 결과 확인 | 탭 전환 가능 |
| 10 | Markdown 다운로드 | `st.download_button` |

## 4. Trace 표시 규칙

각 노드 카드:
```
[Researcher (ReAct)] ✅ 4.2s   self_eval: 4★ (coverage 0.83)
  ├─ input: pr_identifier="owner/repo#142"
  ├─ ReAct steps: 5 (stopped_by=finish_tool)
  │   ├ #1 thought: "변경 파일 7개 확인" → list_pr_files
  │   ├ #2 thought: "user.py 핵심 함수 확인" → read_pr_file
  │   └ ... [펼쳐보기]
  ├─ output: facts=18, search_chunks=5
  └─ [JSON 펼치기]
```

`st.expander` + 내부 ReAct steps `st.expander` (중첩).

## 5. Self-Eval 탭 구성

```
🎯 Self-Evaluation Summary

[Writer]      Grade: B (4.1/5.0)    ← 가장 강조, 헤더에도 노출
  - accuracy:        4 ★★★★☆   "Solar API 인용은 정확하나, 결과 수치 출처가 모호"
  - readability:     5 ★★★★★
  - structure:       4 ★★★★☆
  - code_explanation: 4 ★★★★☆
  Checklist: 7/8 통과 (✗ has_outro_section)
  Reflection: 1회 자동 수정 (missing_fact 1건)

[Context]     Confidence: 4/5
  - coverage:  0.83 (5/6 청크에 유효 reference)
  - relevance: 4/5
  - diversity: 3/5
  rationale: "Context7 공식문서 + 1개 블로그로 다양성은 보통"

[Researcher]  Confidence: 4/5
  - coverage:     0.83 (변경 함수 5/6 매핑)
  - groundedness: 1.0  (모든 fact source 검증)
  - chunk_quality: 4/5
  rationale: "ORM 관련 키워드는 강한데, 'optimization' 같은 일반 단어 1개 포함"
```

> 한계 명시(footnote): "self-eval은 같은 모델 가족이 자기 출력을 평가하므로 **점수가 후할 수 있음**.
> 정확한 회귀 측정은 골든셋(사람 채점 5~10개) 비교 필요."

## 6. 컴포넌트 매핑

| UI 컴포넌트 | 데이터 소스 |
|-------------|------------|
| Markdown 렌더 | `DraftResult.full_markdown` |
| Trace | `GraphState.trace` + `GraphState.react_traces` |
| Writer self-eval 카드 (grade 헤더) | `DraftResult.self_eval` |
| Context self-eval 카드 | `ContextResult.self_eval` |
| Researcher self-eval 카드 | `ResearchResult.self_eval` |
| Reflection finding 리스트 | `verifications[-1].findings` |
| 에러 박스 | `state.errors` |
| 다운로드 | `DraftResult.full_markdown` → `*.md` |

## 7. 상태 관리 / 비동기

- `st.session_state["graph_state"]`: 마지막 실행 결과 (전체 GraphState)
- `st.session_state["streaming"]`: bool — 진행 중 여부
- 스트리밍: `for update in app.stream(...): update_progress(update)`
- 사용자가 새 PR 입력 시 session_state reset

## 8. 에러 / 빈 상태

| 상황 | UI |
|------|----|
| PR URL invalid | `st.error("올바른 GitHub PR URL을 입력하세요")` |
| GitHub 토큰 없음 + private | `st.warning("토큰이 필요합니다")` |
| 생성 실패 | 빨간 박스 + 재시도 버튼 |
| Writer self_eval grade ≤ D | 노란 박스 + suggestions 출력 + "사람 검토 필요" |
| `*.self_eval is None` (어느 단계든) | 회색 카드 + "평가 실패 — 초안은 정상 생성됨" |

## 9. 접근성 / UX

- 폰트: Pretendard / 시스템 한국어
- 코드블록: `st.code(language="python")`
- 색상은 grade에 의미 부여 (단, 흑백에서도 등급 텍스트 명시 — 색맹 대응)

## 10. 테스트 전략

- **수동 시나리오:** 5개 샘플 PR로 E2E
- **자동:** Streamlit `AppTest` 라이브러리로 위젯 입력→출력 확인 (선택)
- **시각 회귀:** 스크린샷 diff (선택)

## 11. 관측성

- 사용자 입력 PR URL, 시작/종료 시간 (개인정보 없음)
- 진행 단계별 latency
- 에러 발생률
- grade 분포 (시계열, 시연 후 운영 시 의미)

## 12. 시연 시나리오 (Day 7)

1. 발표자가 데모 UI 접속
2. 미리 준비한 샘플 PR (Django N+1 fix) URL 붙여넣기
3. 4단계 progress가 흘러가는 것을 보여줌
4. 초안 탭에서 4-Act Markdown 렌더링 확인 + 헤더에 **Grade B** 표시
5. Trace 탭에서 Researcher ReAct steps → Context references → Writer reflection 흐름 시연
6. Self-Eval 탭에서 단계별 점수 4개를 보여주고 "각 에이전트가 자기 출력을 채점한다" 강조
7. 한계 footnote("self-eval bias") 자체를 발표 슬라이드에 포함 → 정직성 어필

## 13. 레퍼런스

- [Streamlit Docs](https://docs.streamlit.io/)
- [LangGraph Streaming Docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [00-common/AGENTIC-EVALUATION.md §9~§10](../00-common/AGENTIC-EVALUATION.md)
- [03-context-agent SPEC](../03-context-agent/SPEC.md)
- [05-backend §10 골든셋](../05-backend/SPEC.md)
