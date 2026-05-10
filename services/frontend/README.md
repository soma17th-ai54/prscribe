# prscribe-frontend

Streamlit 데모 UI. PR URL 한 번 입력으로 Researcher → Context → Writer 파이프라인을 시연한다.

## 실행

```bash
# repo root에서 의존성 동기화 (최초 1회)
uv sync

# UI 실행
cd services/frontend
uv run streamlit run frontend/app.py
```

기본 주소: http://localhost:8501

## 환경변수

`.env` (repo root)에서 자동 로드. 사이드바에서도 입력 가능.

| 키 | 필수 | 설명 |
|---|---|---|
| `UPSTAGE_API_KEY` | ✓ | Solar API 키 (Writer / Researcher / Context 모두 사용) |
| `GITHUB_TOKEN` | optional | private repo 또는 rate limit 회피 용 |

## Writer 모드

사이드바 셀렉터:

- `auto` (기본) — Context coverage `< 0.2` 이면 `minimal_context`, 아니면 `full`
- `full` — verified references 인용 활성
- `minimal_context` — PR diff/commit/issue만 사용
