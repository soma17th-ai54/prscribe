# SPEC — Backend / Integration Layer

**담당:** 홍지호 (인프라 + 골든셋 채점/동의율 분석 + Solar 모델 라우팅)
**디렉토리:** `05-backend/`
**관련 기획서 섹션:** §3.4 (시스템 워크플로우), §4.1.2 (Backend & Integration), §4.5 (제약/예외)

> **변경 이력 (v0.4):**
> - 디렉토리 번호 `06` → `05`.
> - `verification.py` 제거 — 검증 로직은 [03-context-agent](../03-context-agent/SPEC.md) 안에서 `compare_text_to_facts` tool 호출로 자연스럽게 수행. **본 모듈은 tool 핸들러만 제공**, 검증 정책은 03이 책임.
> - 본 모듈은 **얇은 인프라**(GitHub / Solar / Context7) + **공통 tool 핸들러** + **골든셋 채점 인프라**. 비즈니스 로직 없음.
> - 홍지호의 새 책임: (a) 인프라 신뢰성, (b) 골든셋 5~10개 사람 채점 → Writer self-eval과 동의율 분석, (c) Solar 모델 라우팅 정책 관리.

---

## 1. 목적

LLM·외부 API·MCP를 안전하게 호출하는 **얇은 인프라 계층**.
LangGraph 노드들은 본 모듈의 클라이언트 객체만 사용하고, **HTTP 디테일을 알지 않는다.**

## 2. 구성

```
backend/
├── github_client.py       # PR diff/commit/issue 가져오기
├── solar_client.py        # Solar API LLM 호출 + 모델 라우팅
├── context_search.py      # Context Agent 의 ReAct tool 핸들러 (Context7 / Web / fetch)
├── tools/
│   ├── pr_tools.py        # read_pr_file / grep_pr / list_pr_files / get_commit_message / get_linked_issue
│   ├── verify_tools.py    # verify_fact_in_diff (Writer self_reflection 용, 김영표 정책 / 홍지호 핸들러)
│   ├── search_tools.py    # context7_search / web_search / fetch_url / compare_text_to_facts
│   └── termination.py     # finish / give_up
├── webhook_listener.py    # (선택) GitHub webhook 수신
├── goldenset/             # 골든셋 5~10개 채점 자료 + 동의율 분석 스크립트
└── api.py                 # FastAPI (선택, Streamlit이 in-process 호출 시 불필요)
```

## 3. 모듈별 책임

### 3.1 `github_client.py`
- 입력: PR URL 또는 `owner/repo#N`
- 인증: env `GITHUB_TOKEN` (없으면 public repo만 — rate limit 60/h)
- 호출:
  - `GET /repos/{owner}/{repo}/pulls/{n}` (PR meta)
  - `GET /repos/{owner}/{repo}/pulls/{n}/files` (page 100)
  - `GET /repos/{owner}/{repo}/issues/{linked}` (linked issue)
  - PR body / commit message에서 `closes #N` regex로 linked issue 추출
- 출력: `RawPRData`
- 실패: 4xx → 사용자 메시지("권한 부족 또는 PR 없음"). 5xx → 3회 재시도 후 raise.

### 3.2 `solar_client.py`
- env: `SOLAR_API_KEY`
- 공통 함수
  - `chat_json(model, system, user, schema: BaseModel) -> BaseModel`
    - `response_format={"type":"json_schema", ...}` 또는 후처리 파싱 + 1회 재시도
  - `chat_text(...)` (필요 시)
- 모델 라우팅:
  - 무거운 작업(Researcher 추출, Writer 생성): `solar-pro` (가정)
  - 가벼운 작업(verification, **모든 self-evaluation**): `solar-mini` (가정) — 비용 절감 + 자체 평가용 분리
- **Self-evaluation 호출 분리:** 각 노드의 self-eval은 별도 system prompt + 별도 `chat_json` 호출.
  같은 모델 가족이지만 페르소나/프롬프트 분리로 self-eval bias를 부분 완화한다.
- timeout: 30s, retry 2회 (jitter)

### 3.3 `context_search.py` (Context Agent ReAct **tool 핸들러** 제공)

> 본 모듈은 [03-context-agent](../03-context-agent/SPEC.md) 가 사용하는 tool 핸들러를 제공하는 **얇은 인프라**.
> ReAct 정책 / 시스템 프롬프트 / 종료조건은 03 책임. 본 모듈은 호출되는 함수만 책임.

제공하는 핸들러:
- `context7_search(library, topic, k=3)` — Context7 MCP 우선 사용
- `web_search(query, k=5)` — DDG/일반 폴백
- `fetch_url(url)` — 페이지 본문 (≤500자 excerpt)
- `compare_text_to_facts(excerpt, facts)` — LLM-driven 검증 (1~3문장 reasoning + verdict)
- `finish(output_json)` / `give_up(reason)` — 공통 종료 도구

**캐시:** `(query, top_k)` 30분 in-memory + 결과 timestamp 기록 (재실행 결정성).
**병렬:** 03이 청크별로 `asyncio.gather` 호출 시 concurrency ≤ 5 강제.

### 3.4 `tools/verify_tools.py` (Writer self_reflection 용)

- `verify_fact_in_diff(statement: str)` — 의심 문장이 PR diff/commit/issue 안에 substring 또는 paraphrase 형태로 있는지 매칭
- 정책 / finding 분류기 / 시스템 프롬프트는 [04-writer-agent §7.2 (김영표)](../04-writer-agent/SPEC.md). 본 모듈은 핸들러만.

### 3.5 `webhook_listener.py` (선택)
- POST `/webhook/github` (`X-Hub-Signature-256` 검증)
- `pull_request.merged == true` 만 처리
- payload에서 PR URL 추출 → 그래프 invoke (백그라운드 큐 가능)
- MVP에서는 데모 시연 시 "PR URL 입력"으로 대체 가능 — webhook은 옵션.

### 3.6 `api.py` (FastAPI, 선택)
- `POST /generate` body: `{"pr_url": "..."}` → SSE 또는 JSON `{draft, evaluation, trace}`
- Streamlit이 in-process로 LangGraph를 직접 부르면 FastAPI 불필요.
- 시연 시 발표 화면이 분리되어야 한다면 FastAPI 사용.

## 4. 환경 변수 / 설정

| Key | 필수 | 설명 |
|-----|------|------|
| `GITHUB_TOKEN` | (Public repo만이면 선택) | repo:read |
| `SOLAR_API_KEY` | ✅ | LLM |
| `CONTEXT7_API_KEY` | (가능하면) | MCP |
| `WEBHOOK_SECRET` | webhook 사용 시 | HMAC 검증 |
| `LOG_LEVEL` | optional | DEBUG/INFO/... |

## 5. 보안

- 로그·trace에 토큰/키 절대 출력 금지 (마스킹 데코레이터)
- LLM 입력에 토큰 포함 금지
- PR이 private이면 사용자가 토큰 권한을 명시적으로 입력했을 때만 진행

## 6. 실패 모드

| 상황 | 처리 |
|------|------|
| GitHub rate limit | `Retry-After` 존중, 사용자에게 안내 |
| Solar API 5xx | 2회 재시도 후 호출자에게 raise |
| Context7 다운 | 자동으로 web search 폴백 |
| 모든 검색 실패 | `coverage=0` 으로 진행, Writer는 minimal 모드 |

## 7. 테스트 전략

- **WireMock-style fakes:** `responses` 라이브러리로 GitHub/Solar/Context7 fixture
- **계약 테스트:** 각 클라이언트의 출력이 DATA-CONTRACTS와 일치
- **부하/타임아웃:** 30초 budget 안에 LLM·검색 모두 마감

## 8. 관측성

- 호출별 latency 히스토그램
- 4xx/5xx 카운트
- 캐시 hit율
- 토큰 사용량 (Solar)

## 9. 레퍼런스

- [GitHub REST API — Pulls](https://docs.github.com/en/rest/pulls/pulls)
- [Context7 MCP](https://github.com/upstash/context7)
- [LangGraph + MCP Multi-agent guide](https://techbytes.app/posts/langgraph-mcp-multi-agent-workflow-guide-2026/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [03-context-agent SPEC](../03-context-agent/SPEC.md)
- [04-writer-agent §7.2 self_reflection](../04-writer-agent/SPEC.md)

---

## 10. 골든셋 (홍지호 책임)

> v0.4: Evaluation Layer 폐기 후, "self-eval이 사람과 얼마나 일치하는지" 가 유일한 객관 지표.
> 이를 측정·관리하는 책임은 본 모듈로 이동.

**구성:**
- `goldenset/samples/` — 사람이 채점한 PR 5~10개 (각 PR에 대해 4-dim 인간 점수 + grade)
- `goldenset/score.py` — Writer self-eval 결과 vs 인간 점수 비교
- `goldenset/report.md` — 동의율(≥0.8 목표), 차원별 |LLM-human| 분포

**동의 정의:** 차원별 `|LLM_score - human_score| ≤ 1` → "동의".
**임계:** 동의율 ≥ 0.8 — 미달 시 self-eval 시스템 프롬프트(04 §7.3) 검토 필요.

**Day 5 일정:**
1. 팀이 직접 5~10개 PR을 4-dim으로 채점 (1.5h)
2. `score.py` 실행 → `report.md` 생성 (0.5h)
3. 미달 차원 발견 시 04 §7.3 프롬프트 패치 (1h)
