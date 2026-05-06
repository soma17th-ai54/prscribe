# Researcher Agent Implementation Notes

## 배치

Researcher Agent 구현은 `services/researcher_agent/`에 독립 Python package로 배치한다.

이 위치를 선택한 이유:

- `01-langgraph-orchestration`, `03-context-agent`, `04-writer-agent`가 각자 코드 패키지를 추가해도 root-level `app/`, `agents/`, `schemas/` 이름 충돌이 없다.
- 공통 문서의 `RawPRData` / `ResearchResult` 계약을 서비스 내부 Pydantic schema로 구현하되, 다른 Agent는 JSON contract만 바라보면 된다.
- `uv`로 독립 실행과 테스트가 가능하다.

## 인터페이스

CLI:

```bash
cd services/researcher_agent
uv run python -m researcher_agent.cli https://github.com/OWNER/REPO --pr-number 1
```

Python:

```python
from researcher_agent import run_researcher

research = run_researcher("https://github.com/OWNER/REPO", pull_number=1)
```

LangGraph:

```python
from researcher_agent.workflow.graph import researcher_graph

state = {"repo_url": "https://github.com/OWNER/REPO", "pr_number": 1}
state = researcher_graph.invoke(state)
research = state["research"]
```

## 구현 구조

```txt
services/researcher_agent/
  researcher_agent/
    agents/researcher.py
    github/client.py
    github/tools.py
    schemas/research.py
    workflow/graph.py
```

## 공통 계약 정렬

`schemas/research.py`는 `docs/specs/00-common/DATA-CONTRACTS.md`의 다음 모델을 코드화한다.

- `RawPRData`
- `FileChange`
- `CommitInfo`
- `LinkedIssue`
- `ResearchResult`
- `ChangedFunction`
- `TechStackHint`
- `FactBullet`
- `SearchChunk`
- `ResearcherSelfEval`

## 다른 Agent와의 연결

Context Agent는 `ResearchResult.search_chunks`, `ResearchResult.facts`, `ResearchResult.pr_identifier`만 의존하면 된다.

Writer Agent는 `ResearchResult` 전체와 Context Agent가 만든 `ContextResult.verified_references`를 함께 사용한다.

Orchestrator는 `state["research"]`에 `ResearchResult.model_dump(mode="json")`를 저장한다.
