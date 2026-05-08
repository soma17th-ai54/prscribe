# PRScribe Writer Agent

Writer Agent는 `ResearchResult`와 `ContextResult.verified_references`만 사용해 기술 블로그 초안을 생성합니다.

## 위치와 책임

이 서비스는 `services/writer_agent/`에 독립 패키지로 둡니다.

처리 흐름:

```txt
ResearchResult + ContextResult
-> Solar draft generation or deterministic fallback
-> deterministic checklist
-> self-reflection and automatic patch, max 2 revisions
-> self-evaluation grade A-F
-> DraftResult + VerificationResult[]
```

공통 계약은 `docs/specs/00-common/DATA-CONTRACTS.md`의 `ResearchResult`, `ContextResult`, `DraftResult`, `VerificationResult`를 따릅니다.

## 실행 준비

```bash
cd services/writer_agent
uv sync
cp .env.example .env
```

필수 LLM 실행 값:

```env
SOLAR_API_KEY=up_xxx
```

`SOLAR_API_KEY`가 없으면 로컬 테스트와 계약 검증을 위해 결정적 fallback 초안을 생성합니다.

## CLI 실행

```bash
uv run python -m writer_agent.cli ./research.json --context-json ./context.json
```

Context 결과가 없으면 `minimal_context`로 동작합니다.

```bash
uv run python -m writer_agent.cli ./research.json --mode minimal_context
```

## Python / LangGraph 사용

```python
from writer_agent import run_writer_pipeline

result = run_writer_pipeline(research_json, context_json)
print(result.draft.full_markdown)
print(result.verifications)
```

LangGraph 노드는 `writer_agent.workflow.graph`에 있습니다.

```python
from writer_agent.workflow.graph import writer_graph

state = {
    "research": research_json,
    "context": context_json,
    "mode": "full",
}
result = writer_graph.invoke(state)
print(result["draft"])
```

## 테스트

```bash
uv run pytest
```

테스트는 Solar 호출을 사용하지 않고 결정적 fallback과 monkeypatch로 동작합니다.
