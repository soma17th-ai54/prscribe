# PRScribe Researcher Agent

Researcher Agent는 GitHub PR에서 확인 가능한 사실만 추출해 공통 계약의 `ResearchResult` JSON으로 반환합니다.

## 위치와 책임

이 서비스는 다른 팀 Agent와 충돌하지 않도록 `services/researcher_agent/`에 독립 패키지로 둡니다.

처리 흐름:

```txt
GitHub PR/repo URL
-> deterministic core collector
-> Solar extra-context router
-> GitHub tool executor (router가 필요하다고 판단한 경우만)
-> Solar ResearchResult extraction
-> Pydantic validation + deterministic fallback
```

공통 계약은 `docs/specs/00-common/DATA-CONTRACTS.md`의 `RawPRData`와 `ResearchResult`를 따릅니다.

## 실행 준비

```bash
cd services/researcher_agent
uv sync
cp .env.example .env
```

필수:

```env
SOLAR_API_KEY=up_xxx
```

선택:

```env
GITHUB_TOKEN=ghp_xxx
SOLAR_MODEL=solar-pro3
```

`GITHUB_TOKEN`은 private repo 또는 GitHub rate limit 회피가 필요할 때 사용합니다.

## CLI 실행

repo URL만 넘기면 최신 open PR을 분석합니다.

```bash
uv run python -m researcher_agent.cli https://github.com/soma17th-ai54/demo_app
```

특정 PR 번호를 지정할 수도 있습니다.

```bash
uv run python -m researcher_agent.cli https://github.com/soma17th-ai54/demo_app --pr-number 1
```

직접 PR URL을 넘겨도 됩니다.

```bash
uv run python -m researcher_agent.cli https://github.com/OWNER/REPO/pull/1
```

Researcher 내부 LangGraph 진행 로그를 로컬에서 확인하려면 `--stream`을 붙입니다.
로그는 stderr에 JSON Lines로 출력되고, 최종 `ResearchResult`는 stdout에 출력됩니다.

```bash
uv run python -m researcher_agent.cli https://github.com/OWNER/REPO/pull/1 --stream
```

## Python / LangGraph 사용

```python
from researcher_agent import run_researcher

result = run_researcher(
    "https://github.com/soma17th-ai54/demo_app",
    pull_number=1,
)
print(result.model_dump(mode="json"))
```

LangGraph 노드는 `researcher_agent.workflow.graph`에 있습니다.

```python
from researcher_agent.workflow.graph import researcher_graph

state = {
    "repo_url": "https://github.com/soma17th-ai54/demo_app",
    "pr_number": 1,
}
result = researcher_graph.invoke(state)
print(result["research"])
```

Streamlit이나 다른 프론트엔드는 `researcher_graph.stream(..., stream_mode="updates")`에서
각 partial state의 `react_traces`를 읽어 진행 로그로 표시할 수 있습니다.

## Optional GitHub Tools

Core PR data는 항상 코드가 먼저 수집합니다. Solar는 부족한 맥락이 있을 때만 아래 tool을 선택합니다.

| tool | 설명 |
| --- | --- |
| `read_pr_file` | PR head/base 기준으로 파일 일부 또는 전체를 읽습니다. |
| `fetch_dependency_manifest` | `pyproject.toml`, `requirements.txt`, `package.json` 등을 찾습니다. |
| `fetch_readme` | repo README를 읽어 프로젝트 목적을 보강합니다. |

완전한 patch가 이미 있는 changed file은 다시 fetch하지 않도록 sanitization합니다.

## 테스트

```bash
uv run pytest
```

단위 테스트는 GitHub/Solar 호출을 mock 처리합니다.

## 출력

성공 시 `ResearchResult` JSON을 출력합니다.

핵심 필드:

- `pr_identifier`
- `summary_one_line`
- `changed_files`
- `changed_functions`
- `tech_stack_hints`
- `facts`
- `search_chunks`
- `notes`
- `self_eval`
