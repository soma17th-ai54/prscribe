from __future__ import annotations

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from researcher_agent.github.client import RawPRBundle, fetch_raw_pr_bundle
from researcher_agent.github.tools import execute_github_tool_requests
from researcher_agent.schemas.research import (
    ChangedFunction,
    ExtraContextPlan,
    FactBullet,
    FileChange,
    GitHubToolRequest,
    GitHubToolResult,
    RawPRData,
    ResearchResult,
    ResearcherSelfEval,
    SearchChunk,
    TechStackHint,
)

load_dotenv()

PATCH_CHAR_LIMIT = 8_000
MAX_EXTRA_TOOL_REQUESTS = 4
SOLAR_BASE_URL = "https://api.upstage.ai/v1"

EXTRA_CONTEXT_SYSTEM_PROMPT = """You are the tool-planning step of the PRScribe Researcher Agent.

Core PR metadata, file patches, commits, and linked issues are already available.
Request optional GitHub tools only when they materially reduce ambiguity.
Return valid JSON only, matching ExtraContextPlan.
"""

RESEARCH_SYSTEM_PROMPT = """You are the PRScribe Researcher Agent.

Extract only facts directly supported by PR diff, commit messages, linked issues, and successful tool observations.
Do not infer motivation, performance, business impact, or implementation details that are not visible.
Use unified diff semantics: lines starting with + are added and lines starting with - are removed.
Return valid JSON only, matching ResearchResult.
"""

SELF_EVAL_SYSTEM_PROMPT = """You are the verifier persona for the PRScribe Researcher Agent (a separate persona from the extractor).

Score the extractor's ResearchResult on four independent dimensions, G-Eval style:
- Write a 1-2 sentence rationale FIRST, then derive the scores.
- coverage (0.0-1.0): fraction of changed files/functions that appear in facts. A deterministic value is supplied; review and adjust only if you see clear evidence it is wrong.
- groundedness (0.0-1.0): every fact must be traceable via source_locator. A deterministic value is supplied; lower it only if statements look speculative or unsupported.
- chunk_quality (1-5): are search_chunks.keywords identifiable, distinctive terms (good) or generic words like "fix", "update", "code" (bad)?
- confidence (1-5): overall trust in the extraction.

Return valid JSON only, matching ResearcherSelfEval. Do not regenerate the extraction itself.
"""


class ResearcherError(RuntimeError):
    """Raised when Researcher Agent execution fails."""


class ResearcherConfigError(ResearcherError):
    """Raised when required configuration is missing."""


def _solar_api_key() -> str:
    api_key = os.getenv("SOLAR_API_KEY") or os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise ResearcherConfigError("SOLAR_API_KEY or UPSTAGE_API_KEY is required.")
    return api_key


def _solar_client() -> OpenAI:
    return OpenAI(api_key=_solar_api_key(), base_url=SOLAR_BASE_URL)


def _solar_model() -> str:
    return os.getenv("SOLAR_MODEL", "solar-pro3")


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        if start == -1:
            raise
        parsed, _ = json.JSONDecoder().raw_decode(stripped[start:])
    if not isinstance(parsed, dict):
        raise ResearcherError("Solar response JSON must be an object.")
    return parsed


def _truncate_patch(path: str, patch: str | None) -> tuple[str | None, str | None]:
    if patch is None or len(patch) <= PATCH_CHAR_LIMIT:
        return patch, None
    remaining = len(patch) - PATCH_CHAR_LIMIT
    return f"{patch[:PATCH_CHAR_LIMIT]}\n...[truncated {remaining} chars]", f"diff truncated for {path}"


def _safe_raw(raw: RawPRData) -> tuple[dict[str, Any], list[str]]:
    notes = []
    files = []
    for file_change in raw.files:
        patch, note = _truncate_patch(file_change.path, file_change.patch)
        if note:
            notes.append(note)
        files.append(file_change.model_copy(update={"patch": patch}).model_dump(mode="json"))
    payload = raw.model_dump(mode="json")
    payload["files"] = files
    return payload, notes


def build_extra_context_prompt(bundle: RawPRBundle) -> str:
    raw_payload, notes = _safe_raw(bundle.raw)
    payload = {
        "raw_pr_data": raw_payload,
        "notes": notes,
        "available_tools": [
            {
                "tool_name": "read_pr_file",
                "description": "Read a file at PR head/base. Use only for non-truncated context or imported symbol definitions.",
                "requires_path": True,
            },
            {
                "tool_name": "fetch_dependency_manifest",
                "description": "Fetch pyproject.toml, requirements.txt, package.json, or equivalent.",
                "requires_path": False,
            },
            {
                "tool_name": "fetch_readme",
                "description": "Fetch repository README when project purpose is needed for search chunks.",
                "requires_path": False,
            },
        ],
        "output_schema": ExtraContextPlan.model_json_schema(),
    }
    return f"""Return ExtraContextPlan JSON.

Use at most {MAX_EXTRA_TOOL_REQUESTS} tool requests.
Prefer an empty request list if RawPRData is enough.
Do not re-fetch a changed file when its patch is already complete.

Input:
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_extra_context(bundle: RawPRBundle) -> ExtraContextPlan:
    completion = _solar_client().chat.completions.create(
        model=_solar_model(),
        messages=[
            {"role": "system", "content": EXTRA_CONTEXT_SYSTEM_PROMPT},
            {"role": "user", "content": build_extra_context_prompt(bundle)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ResearcherError("Solar returned an empty extra-context plan.")
    plan = ExtraContextPlan.model_validate(_parse_json_object(content))
    plan.requests = plan.requests[:MAX_EXTRA_TOOL_REQUESTS]
    return plan


def _patch_is_complete(bundle: RawPRBundle, path: str) -> bool:
    for file_change in bundle.raw.files:
        if file_change.path == path:
            return bool(file_change.patch) and len(file_change.patch) <= PATCH_CHAR_LIMIT
    return False


def collect_extra_context(bundle: RawPRBundle) -> tuple[list[GitHubToolResult], list[str]]:
    try:
        plan = call_solar_for_extra_context(bundle)
    except ResearcherConfigError:
        raise
    except (json.JSONDecodeError, ValidationError, ResearcherError, OpenAIError) as exc:
        return [], [f"extra context planning failed: {exc}"]

    requests: list[GitHubToolRequest] = []
    notes: list[str] = []
    for request in plan.requests:
        if request.tool_name == "read_pr_file" and request.path and _patch_is_complete(bundle, request.path):
            notes.append(f"extra context request skipped; patch already complete: {request.path}")
            continue
        requests.append(request)
    if not requests:
        return [], notes
    return execute_github_tool_requests(bundle, requests), notes


def _function_kind(status: str) -> str:
    if status == "added":
        return "added"
    if status == "removed":
        return "removed"
    if status == "renamed":
        return "renamed"
    return "modified"


def extract_changed_functions(raw: RawPRData) -> list[ChangedFunction]:
    results: list[ChangedFunction] = []
    seen: set[tuple[str, str]] = set()
    hunk_name_re = re.compile(r"@@.*@@\s*(?:def|class|function|const|let|var)?\s*([A-Za-z_][\w]*)?")
    added_fn_re = re.compile(r"^\+\s*(?:async\s+def|def|class|function)\s+([A-Za-z_][\w]*)")
    for file_change in raw.files:
        if not file_change.patch:
            continue
        current_name: str | None = None
        for line in file_change.patch.splitlines():
            if line.startswith("@@"):
                match = hunk_name_re.search(line)
                current_name = match.group(1) if match and match.group(1) else None
                if current_name and (file_change.path, current_name) not in seen:
                    seen.add((file_change.path, current_name))
                    results.append(
                        ChangedFunction(
                            file=file_change.path,
                            function_name=current_name,
                            change_kind=_function_kind(file_change.status),
                            summary=f"{current_name} changed in {file_change.path}.",
                        )
                    )
            match = added_fn_re.search(line)
            if match and (file_change.path, match.group(1)) not in seen:
                seen.add((file_change.path, match.group(1)))
                results.append(
                    ChangedFunction(
                        file=file_change.path,
                        function_name=match.group(1),
                        change_kind="added",
                        summary=f"{match.group(1)} added in {file_change.path}.",
                    )
                )
        if not current_name and not any(item.file == file_change.path for item in results):
            results.append(
                ChangedFunction(
                    file=file_change.path,
                    function_name="<module>",
                    change_kind=_function_kind(file_change.status),
                    summary=f"Module-level change in {file_change.path}.",
                )
            )
    return results


def extract_tech_stack_hints(raw: RawPRData) -> list[TechStackHint]:
    hints: dict[str, str] = {}
    for file_change in raw.files:
        path = file_change.path
        if path.endswith(".py"):
            hints.setdefault("Python", f"file:{path}")
        if "test" in path.lower():
            hints.setdefault("unittest", f"file:{path}")
        if path.endswith((".ts", ".tsx")):
            hints.setdefault("TypeScript", f"file:{path}")
        if path.endswith((".js", ".jsx")):
            hints.setdefault("JavaScript", f"file:{path}")
        if path.endswith((".json", ".jsonl")):
            hints.setdefault("JSON", f"file:{path}")
        patch = file_change.patch or ""
        if "from pydantic" in patch or "import pydantic" in patch:
            hints.setdefault("Pydantic", f"file:{path}")
        if "pytest" in patch:
            hints.setdefault("pytest", f"file:{path}")
    return [TechStackHint(name=name, evidence=evidence) for name, evidence in sorted(hints.items())]


def _fallback_facts(raw: RawPRData) -> list[FactBullet]:
    facts: list[FactBullet] = []
    for index, file_change in enumerate(raw.files):
        facts.append(
            FactBullet(
                statement=(
                    f"{file_change.path} was {file_change.status} with "
                    f"{file_change.additions} additions and {file_change.deletions} deletions."
                ),
                source="diff",
                source_locator=f"files[{index}].patch",
            )
        )
    for commit in raw.commits[:3]:
        if commit.message:
            facts.append(
                FactBullet(
                    statement=commit.message.splitlines()[0],
                    source="commit_message",
                    source_locator=f"commit:{commit.sha}",
                )
            )
    for issue in raw.linked_issues:
        facts.append(
            FactBullet(
                statement=issue.title,
                source="linked_issue",
                source_locator=f"issue:#{issue.number}",
            )
        )
    return facts


def _fallback_chunks(raw: RawPRData) -> list[SearchChunk]:
    chunks = []
    for index, file_change in enumerate(raw.files, start=1):
        keywords = [
            raw.title,
            file_change.path,
            file_change.status,
        ]
        if file_change.path.endswith(".py"):
            keywords.append("Python")
        if "test" in file_change.path.lower():
            keywords.append("unit test")
        chunks.append(
            SearchChunk(
                chunk_id=f"chunk_{index}",
                keywords=keywords[:7],
                intent="api_usage" if "api" in file_change.path.lower() else "concept_lookup",
                related_files=[file_change.path],
            )
        )
    return chunks


def _compute_deterministic_metrics(raw: RawPRData, result: ResearchResult) -> dict[str, float]:
    file_paths = {file.path for file in raw.files}
    fact_files = {
        file.path
        for file in raw.files
        if any(file.path in fact.source_locator or file.path in fact.statement for fact in result.facts)
    }
    coverage = len(fact_files) / len(file_paths) if file_paths else 1.0
    grounded = sum(1 for fact in result.facts if fact.source_locator) / len(result.facts) if result.facts else 0.0
    return {"coverage": round(coverage, 2), "groundedness": round(grounded, 2)}


def _deterministic_self_eval(raw: RawPRData, result: ResearchResult) -> ResearcherSelfEval:
    metrics = _compute_deterministic_metrics(raw, result)
    chunk_quality = 4 if result.search_chunks and all(len(chunk.keywords) >= 3 for chunk in result.search_chunks) else 3
    confidence = 4 if metrics["coverage"] >= 0.8 and metrics["groundedness"] >= 0.8 else 3
    return ResearcherSelfEval(
        coverage=metrics["coverage"],
        groundedness=metrics["groundedness"],
        chunk_quality=chunk_quality,
        confidence=confidence,
        rationale="Deterministic self-evaluation based on changed-file coverage, source locators, and keyword count.",
    )


def build_self_eval_prompt(raw: RawPRData, result: ResearchResult, metrics: dict[str, float]) -> str:
    payload = {
        "deterministic_metrics": metrics,
        "changed_files": [file.path for file in raw.files],
        "changed_functions": [item.model_dump(mode="json") for item in result.changed_functions],
        "facts": [item.model_dump(mode="json") for item in result.facts],
        "search_chunks": [item.model_dump(mode="json") for item in result.search_chunks],
        "notes": result.notes,
        "output_schema": ResearcherSelfEval.model_json_schema(),
    }
    return f"""Score this ResearchResult and return ResearcherSelfEval JSON.

Begin the rationale with a 1-2 sentence reasoning, then assign scores consistent with that reasoning.
Treat deterministic_metrics.coverage and deterministic_metrics.groundedness as ground truth unless you can cite specific contradicting evidence.
Judge chunk_quality strictly: generic words like "fix", "update", "code", or the PR title alone are weak; identifier-level or domain terms are strong.

Input:
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_self_eval(raw: RawPRData, result: ResearchResult, metrics: dict[str, float]) -> dict[str, Any]:
    completion = _solar_client().chat.completions.create(
        model=_solar_model(),
        messages=[
            {"role": "system", "content": SELF_EVAL_SYSTEM_PROMPT},
            {"role": "user", "content": build_self_eval_prompt(raw, result, metrics)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ResearcherError("Solar returned an empty ResearcherSelfEval.")
    return _parse_json_object(content)


def _self_eval(raw: RawPRData, result: ResearchResult) -> ResearcherSelfEval:
    metrics = _compute_deterministic_metrics(raw, result)
    try:
        candidate = call_solar_for_self_eval(raw, result, metrics)
    except ResearcherConfigError:
        raise
    except (json.JSONDecodeError, ValidationError, ResearcherError, OpenAIError):
        return _deterministic_self_eval(raw, result)

    try:
        llm_eval = ResearcherSelfEval.model_validate(candidate)
    except ValidationError:
        return _deterministic_self_eval(raw, result)

    return llm_eval.model_copy(
        update={
            "coverage": metrics["coverage"],
            "groundedness": metrics["groundedness"],
        }
    )


def _fallback_result(raw: RawPRData, notes: list[str] | None = None) -> ResearchResult:
    result = ResearchResult(
        pr_identifier=raw.pr_identifier,
        summary_one_line=raw.title,
        changed_files=raw.files,
        changed_functions=extract_changed_functions(raw),
        tech_stack_hints=extract_tech_stack_hints(raw),
        facts=_fallback_facts(raw),
        search_chunks=_fallback_chunks(raw),
        notes=notes or [],
    )
    result.self_eval = _deterministic_self_eval(raw, result)
    return result


def build_research_prompt(
    raw: RawPRData,
    tool_results: list[GitHubToolResult] | None = None,
    retry_instruction: str | None = None,
) -> str:
    raw_payload, notes = _safe_raw(raw)
    payload = {
        "raw_pr_data": raw_payload,
        "deterministic_changed_functions": [
            item.model_dump(mode="json") for item in extract_changed_functions(raw)
        ],
        "deterministic_tech_stack_hints": [
            item.model_dump(mode="json") for item in extract_tech_stack_hints(raw)
        ],
        "tool_observations": [
            result.model_dump(mode="json") for result in (tool_results or []) if result.ok
        ],
        "notes_to_include": notes,
        "output_schema": ResearchResult.model_json_schema(),
    }
    retry_text = f"\nRetry instruction: {retry_instruction}\n" if retry_instruction else ""
    return f"""Return ResearchResult JSON.

Use raw_pr_data.pr_identifier exactly.
Use raw_pr_data.files exactly as changed_files.
Use deterministic_changed_functions unless you can make them more precise from the patch.
Use deterministic_tech_stack_hints unless the PR gives stronger evidence.
Every fact must have source and source_locator.
search_chunks must be non-empty when changed_files is non-empty.
Do not invent facts not grounded in raw_pr_data or tool_observations.
Include self_eval using the ResearcherSelfEval schema.
{retry_text}
Input:
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_research(
    raw: RawPRData,
    tool_results: list[GitHubToolResult] | None = None,
    retry_instruction: str | None = None,
) -> dict[str, Any]:
    completion = _solar_client().chat.completions.create(
        model=_solar_model(),
        messages=[
            {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
            {"role": "user", "content": build_research_prompt(raw, tool_results, retry_instruction)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content:
        raise ResearcherError("Solar returned an empty ResearchResult.")
    return _parse_json_object(content)


def _normalize_result(candidate: dict[str, Any], raw: RawPRData, notes: list[str]) -> dict[str, Any]:
    normalized = dict(candidate)
    missing_sections = [
        key
        for key in ("facts", "search_chunks", "changed_functions", "tech_stack_hints")
        if key not in candidate or not candidate.get(key)
    ]
    normalized["pr_identifier"] = raw.pr_identifier
    normalized["changed_files"] = [file.model_dump(mode="json") for file in raw.files]
    normalized.setdefault("summary_one_line", raw.title)
    if not normalized.get("changed_functions"):
        normalized["changed_functions"] = [item.model_dump(mode="json") for item in extract_changed_functions(raw)]
    if not normalized.get("tech_stack_hints"):
        normalized["tech_stack_hints"] = [item.model_dump(mode="json") for item in extract_tech_stack_hints(raw)]
    if not normalized.get("facts"):
        normalized["facts"] = [item.model_dump(mode="json") for item in _fallback_facts(raw)]
    if not normalized.get("search_chunks"):
        normalized["search_chunks"] = [item.model_dump(mode="json") for item in _fallback_chunks(raw)]
    merged_notes = list(normalized.get("notes") or [])
    if missing_sections:
        merged_notes.append(
            "Solar response omitted sections filled deterministically: "
            + ", ".join(missing_sections)
        )
    for note in notes:
        if note not in merged_notes:
            merged_notes.append(note)
    normalized["notes"] = merged_notes
    return normalized


def extract_research_result(
    raw: RawPRData,
    tool_results: list[GitHubToolResult] | None = None,
    notes: list[str] | None = None,
) -> ResearchResult:
    notes = notes or []
    retry_instruction: str | None = None
    last_error: Exception | None = None
    for _ in range(2):
        try:
            candidate = call_solar_for_research(raw, tool_results, retry_instruction)
            result = ResearchResult.model_validate(_normalize_result(candidate, raw, notes))
            result.self_eval = _self_eval(raw, result)
            return result
        except ResearcherConfigError:
            raise
        except (json.JSONDecodeError, ValidationError, ResearcherError, OpenAIError) as exc:
            last_error = exc
            retry_instruction = f"Previous output failed validation: {exc}. Return only valid ResearchResult JSON."

    return _fallback_result(
        raw,
        [*notes, f"Solar extraction failed after retry; deterministic fallback used: {last_error}"],
    )


def run_researcher(source_url: str, pull_number: int | None = None) -> ResearchResult:
    bundle = fetch_raw_pr_bundle(source_url, pull_number=pull_number)
    tool_results, notes = collect_extra_context(bundle)
    return extract_research_result(bundle.raw, tool_results, notes)
