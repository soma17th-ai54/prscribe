from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from writer_agent.schemas.writer import (
    ChecklistItem,
    ContextResult,
    DraftResult,
    DraftSection,
    FactBullet,
    FactDiffMatch,
    FactDiffVerification,
    IssueFinding,
    JudgeScore,
    Reference,
    ResearchResult,
    VerificationResult,
    WriterRunResult,
    WriterSelfEval,
)

load_dotenv()

SOLAR_BASE_URL = "https://api.upstage.ai/v1"
MAX_REFLECTION_ITERATIONS = 2
REQUIRED_SECTION_KINDS = ("intro", "problem", "cause", "solution", "result", "outro")
SECTION_TITLES = {
    "intro": "들어가며",
    "problem": "문제 상황",
    "cause": "원인 분석",
    "solution": "해결 방법",
    "result": "결과 및 효과",
    "outro": "마치며",
}
CRITICAL_CHECKS = {"has_code_block", "four_act_present"}
CRITICAL_FINDING_KINDS = {
    "missing_fact",
    "ungrounded_claim",
    "code_under_explained",
    "structure_violation",
    "tone_mismatch",
}
SPECULATION_RE = re.compile(r"(아마도?|추정|혹시|할 수도|될 수도|것 같습니다|것으로 보입니다)")
URL_RE = re.compile(r"https?://[^\s)\]>\"']+")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./#-]*|[0-9]+|[가-힣]{2,}")

GENERATE_DRAFT_SYSTEM_PROMPT = """당신은 시니어 개발자가 신입을 위해 쓰는 기술 블로그 초안 작성자입니다.
반드시 JSON 객체만 반환합니다. 설명 텍스트나 마크다운 코드 펜스를 붙이지 않습니다.

[강제 규칙]
1. 아래 [INPUT] 외의 정보를 사용하지 않습니다. 추측하지 않습니다.
2. 4-Act 구조(들어가며/문제/원인/해결/결과/마치며)를 반드시 지킵니다.
3. 코드 블록은 최소 1개 이상 포함합니다.
4. verified_references 안의 URL만 인용합니다.
5. 결과 섹션은 PR 본문에 측정값이 없으면 관찰 가능한 효과로만 한정합니다.
6. 출력은 DraftResult JSON 스키마를 따릅니다.
7. facts의 내용을 자연스러운 한국어 문장으로 풀어 씁니다. raw 파일명·diff 텍스트를 그대로 붙여넣지 않습니다.

[톤]
- "~했습니다" 중심
- 신입/주니어 개발자 가독성 우선
- 한 문단은 4문장 이하
"""

SELF_REFLECTION_SYSTEM_PROMPT = """당신은 기술 블로그 초안의 사실성/구조/톤을 점검하는 검증자입니다.
작성자와 별개의 페르소나입니다.

[원칙]
- 각 finding을 만들기 전 1~2문장 reasoning을 먼저 생각한 뒤 finding만 JSON으로 출력합니다.
- "아마/추정/혹시/~할 수도" 톤을 잡아냅니다.
- research.facts 중 미언급 핵심 사실을 잡아냅니다.
- 본문 주장과 근거(facts/verified_references) 매핑이 안 되면 ungrounded_claim으로 봅니다.
- 코드블록 인접 설명이 부실하면 code_under_explained로 봅니다.

[출력]
VerificationResult JSON만 반환합니다.
"""

SELF_EVALUATION_SYSTEM_PROMPT = """당신은 기술 블로그 초안을 평가하는 채점자입니다.
작성자/검증자와 별개의 페르소나입니다.

[원칙]
- 점수를 적기 전 1~3문장 reasoning을 먼저 생각하고 rationale에 반영합니다.
- accuracy, readability, structure, code_explanation 네 축을 독립적으로 평가합니다.
- 각 축은 1~5점입니다.
- 길이로 점수를 매기지 않습니다.
- VerificationResult.needs_human_review가 있으면 모든 축에 페널티를 반영합니다.
- cited_refs_subset_verified 실패가 있으면 accuracy는 최대 2점입니다.

[출력]
WriterSelfEval JSON만 반환합니다.
"""


class WriterError(RuntimeError):
    """Raised when Writer Agent execution fails."""


class WriterConfigError(WriterError):
    """Raised when optional LLM configuration is missing."""


@dataclass(frozen=True)
class ChecklistOutcome:
    draft: DraftResult
    checklist: list[ChecklistItem]
    findings: list[IssueFinding]
    removed_citations: list[str]

    @property
    def has_critical_failure(self) -> bool:
        return any(not item.passed and item.name in CRITICAL_CHECKS for item in self.checklist)


def _solar_api_key() -> str:
    api_key = os.getenv("SOLAR_API_KEY") or os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise WriterConfigError("SOLAR_API_KEY or UPSTAGE_API_KEY is required.")
    return api_key


def _solar_client() -> OpenAI:
    return OpenAI(api_key=_solar_api_key(), base_url=SOLAR_BASE_URL)


def _writer_model() -> str:
    return os.getenv("SOLAR_WRITER_MODEL", os.getenv("SOLAR_MODEL", "solar-pro3"))


def _reflection_model() -> str:
    return os.getenv("SOLAR_REFLECTION_MODEL", "solar-mini")


def _eval_model() -> str:
    return os.getenv("SOLAR_EVAL_MODEL", "solar-mini")


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
        raise WriterError("Solar response JSON must be an object.")
    return parsed


def _empty_context(pr_identifier: str) -> ContextResult:
    return ContextResult(
        pr_identifier=pr_identifier,
        raw_references=[],
        verified_references=[],
        rejected_references=[],
        verification_log=[],
        coverage=0.0,
    )


def _resolve_mode(mode: Literal["full", "minimal_context"], context: ContextResult) -> Literal["full", "minimal_context"]:
    if mode == "full" and not context.verified_references:
        return "minimal_context"
    return mode


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:)]}")


def _allowed_reference_urls(context: ContextResult, mode: Literal["full", "minimal_context"]) -> set[str]:
    if mode == "minimal_context":
        return set()
    return {_clean_url(reference.url) for reference in context.verified_references}


def _extract_urls(text: str) -> list[str]:
    return [_clean_url(match.group(0)) for match in URL_RE.finditer(text)]


def _count_code_blocks(markdown: str) -> int:
    return len(CODE_BLOCK_RE.findall(markdown))


def _count_words(markdown: str) -> int:
    without_code = CODE_BLOCK_RE.sub(" ", markdown)
    return len(TOKEN_RE.findall(without_code))


def _truncate(text: str, limit: int = 50) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for line in text.splitlines():
        sentences.extend(part for part in re.split(r"(?<=[.!?。])\s+", line) if part.strip())
    return sentences


def _make_title(research: ResearchResult, candidate: str | None = None) -> str:
    raw = (candidate or research.summary_one_line or research.pr_identifier).strip()
    raw = re.sub(r"\s+", " ", raw)
    if not raw:
        raw = f"{research.pr_identifier} 변경 정리"
    if len(raw) < 5:
        raw = f"{raw} 변경 정리"
    if len(raw) > 60:
        raw = raw[:57].rstrip() + "..."
    return raw


def compose_full_markdown(title: str, sections: list[DraftSection]) -> str:
    section_by_kind = {section.kind: section for section in sections}
    parts = [f"# {title.strip()}"]
    for kind in REQUIRED_SECTION_KINDS:
        section = section_by_kind.get(kind)
        if not section:
            continue
        body = section.body_markdown.strip()
        parts.append(f"## {section.title.strip() or SECTION_TITLES[kind]}\n{body}")
    return "\n\n".join(parts).strip() + "\n"


def _section_citations(body: str, allowed_urls: set[str]) -> list[str]:
    cited = []
    for url in _extract_urls(body):
        if url in allowed_urls and url not in cited:
            cited.append(url)
    return cited


def _make_draft(
    research: ResearchResult,
    title: str,
    sections: list[DraftSection],
    revision: int = 0,
    self_eval: WriterSelfEval | None = None,
) -> DraftResult:
    full_markdown = compose_full_markdown(title, sections)
    return DraftResult(
        pr_identifier=research.pr_identifier,
        title=title,
        sections=sections,
        full_markdown=full_markdown,
        word_count=_count_words(full_markdown),
        code_block_count=_count_code_blocks(full_markdown),
        revision=revision,
        self_eval=self_eval,
    )


def _remove_unverified_citations_from_text(text: str, allowed_urls: set[str]) -> tuple[str, list[str]]:
    removed: list[str] = []

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = _clean_url(match.group(2))
        if url in allowed_urls:
            return match.group(0)
        if url not in removed:
            removed.append(url)
        return label

    text = MARKDOWN_LINK_RE.sub(replace_link, text)

    def replace_url(match: re.Match[str]) -> str:
        url = _clean_url(match.group(0))
        if url in allowed_urls:
            return match.group(0)
        if url not in removed:
            removed.append(url)
        return ""

    text = URL_RE.sub(replace_url, text)
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    return text, removed


def _sanitize_draft(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> tuple[DraftResult, list[str]]:
    allowed_urls = _allowed_reference_urls(context, mode)
    removed: list[str] = []
    sanitized_sections: list[DraftSection] = []
    for section in draft.sections:
        body, section_removed = _remove_unverified_citations_from_text(section.body_markdown, allowed_urls)
        removed.extend(url for url in section_removed if url not in removed)
        explicit_refs = [_clean_url(url) for url in section.cited_references if _clean_url(url) in allowed_urls]
        cited_refs = explicit_refs[:]
        for url in _section_citations(body, allowed_urls):
            if url not in cited_refs:
                cited_refs.append(url)
        sanitized_sections.append(
            section.model_copy(update={"body_markdown": body.strip(), "cited_references": cited_refs})
        )
    sanitized = _make_draft(
        research=research,
        title=_make_title(research, draft.title),
        sections=sanitized_sections,
        revision=draft.revision,
        self_eval=draft.self_eval,
    )
    return sanitized, removed


def _heading_to_kind(heading: str) -> str | None:
    normalized = heading.strip().lower()
    if "들어" in normalized or "intro" in normalized:
        return "intro"
    if "문제" in normalized or "problem" in normalized:
        return "problem"
    if "원인" in normalized or "cause" in normalized:
        return "cause"
    if "해결" in normalized or "solution" in normalized:
        return "solution"
    if "결과" in normalized or "효과" in normalized or "result" in normalized:
        return "result"
    if "마치" in normalized or "outro" in normalized:
        return "outro"
    return None


def _parse_markdown_sections(markdown: str, allowed_urls: set[str]) -> tuple[str | None, list[DraftSection]]:
    title: str | None = None
    title_match = re.search(r"^#\s+(.+)$", markdown, flags=re.MULTILINE)
    if title_match:
        title = title_match.group(1).strip()

    matches = list(re.finditer(r"^##\s+(.+)$", markdown, flags=re.MULTILINE))
    sections: list[DraftSection] = []
    for index, match in enumerate(matches):
        kind = _heading_to_kind(match.group(1))
        if not kind:
            continue
        body_start = match.end()
        body_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[body_start:body_end].strip()
        if any(section.kind == kind for section in sections):
            continue
        sections.append(
            DraftSection(
                kind=kind,  # type: ignore[arg-type]
                title=SECTION_TITLES[kind],
                body_markdown=body,
                cited_references=_section_citations(body, allowed_urls),
            )
        )
    return title, sections


def _select_facts(research: ResearchResult, source: str | None = None, limit: int = 4) -> list[FactBullet]:
    facts = [fact for fact in research.facts if source is None or fact.source == source]
    return facts[:limit]


def _format_fact_bullets(facts: list[FactBullet], fallback: str) -> str:
    if not facts:
        return f"- {fallback}"
    return "\n".join(f"- {fact.statement} (`{fact.source_locator}`)" for fact in facts)


def _format_changed_functions(research: ResearchResult) -> str:
    if not research.changed_functions:
        return "- 함수 단위 변경 정보는 제공되지 않았습니다."
    return "\n".join(
        f"- `{item.function_name}` in `{item.file}`: {item.summary}"
        for item in research.changed_functions[:6]
    )


def _format_changed_files(research: ResearchResult) -> str:
    if not research.changed_files:
        return "- 변경 파일 정보는 제공되지 않았습니다."
    return "\n".join(
        f"- `{item.path}`: {item.status}, +{item.additions}/-{item.deletions}"
        for item in research.changed_files[:6]
    )


def _select_code_block(research: ResearchResult) -> str:
    if research.changed_functions:
        rows = "\n".join(
            f"# [{item.change_kind}] {item.file}\n# {item.function_name}: {item.summary}"
            for item in research.changed_functions[:4]
        )
        return f"```python\n{rows}\n```"
    if research.changed_files:
        rows = "\n".join(
            f"{item.path}  (+{item.additions} / -{item.deletions})"
            for item in research.changed_files[:6]
        )
        return f"```text\n{rows}\n```"
    return "```text\n변경 내역 정보 없음\n```"


def _reference_lines(references: list[Reference]) -> str:
    if not references:
        return ""
    lines = []
    for reference in references[:2]:
        excerpt = _truncate(reference.excerpt, 160)
        lines.append(f"- [{reference.title}]({reference.url}): {excerpt}")
    return "\n".join(lines)


def _section_body_template(
    kind: str,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> str:
    references = context.verified_references if mode == "full" else []
    if kind == "intro":
        return (
            f"> PR: {research.pr_identifier} - {research.summary_one_line}\n\n"
            f"이 글은 `{research.pr_identifier}`에서 확인된 변경 내용을 바탕으로 작성했습니다. "
            "PR diff, commit message, linked issue에서 확인 가능한 사실만 사용했습니다."
        )
    if kind == "problem":
        facts = _select_facts(research, "linked_issue") or _select_facts(research, None, limit=3)
        return (
            "문제 상황은 PR에서 확인된 사실을 기준으로 정리했습니다.\n\n"
            f"{_format_fact_bullets(facts, 'PR에서 변경 필요성이 확인되었습니다.')}"
        )
    if kind == "cause":
        return (
            "원인은 변경된 파일과 함수의 위치를 따라가며 확인했습니다. "
            "아래 항목은 diff에서 확인된 코드 단위 변화입니다.\n\n"
            f"{_format_changed_functions(research)}"
        )
    if kind == "solution":
        reference_text = _reference_lines(references)
        reference_paragraph = f"\n\n{reference_text}" if reference_text else ""
        return (
            f"{_format_changed_files(research)}\n\n"
            f"{_select_code_block(research)}"
            f"{reference_paragraph}"
        )
    if kind == "result":
        test_files = [item.path for item in research.changed_files if "test" in item.path.lower()]
        if test_files:
            observed = "테스트 파일 변경도 함께 포함되어 검증 범위가 코드에 남았습니다."
        else:
            observed = "PR 본문에 별도 측정 수치가 없어서 결과는 변경 범위 관찰로 한정했습니다."
        return (
            "결과 및 효과는 PR에서 확인 가능한 범위로만 표현했습니다. "
            f"{observed}\n\n"
            f"{_format_fact_bullets(_select_facts(research, 'commit_message', limit=3), research.summary_one_line)}"
        )
    if kind == "outro":
        suffix = "\n\n공식 문서를 추가로 확인하세요." if mode == "minimal_context" else ""
        if mode == "minimal_context":
            return (
                "이번 초안은 외부 레퍼런스 없이 PR에서 확인 가능한 사실만 사용해 작성했습니다. "
                "따라서 코드 변경의 문제, 원인, 해결, 결과도 PR diff와 commit message 범위로 제한했습니다."
                f"{suffix}"
            )
        return (
            "이번 초안은 확인 가능한 PR 사실과 검증된 레퍼런스를 분리해 작성했습니다. "
            "덕분에 코드 변경의 문제, 원인, 해결, 결과를 같은 흐름에서 다시 확인할 수 있었습니다."
            f"{suffix}"
        )
    return "작성 가능한 정보가 부족했습니다."


def _ensure_sections(
    sections: list[DraftSection],
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> list[DraftSection]:
    by_kind = {section.kind: section for section in sections}
    ensured: list[DraftSection] = []
    for kind in REQUIRED_SECTION_KINDS:
        existing = by_kind.get(kind)
        if existing and existing.body_markdown.strip():
            ensured.append(existing.model_copy(update={"title": SECTION_TITLES[kind]}))
            continue
        ensured.append(
            DraftSection(
                kind=kind,  # type: ignore[arg-type]
                title=SECTION_TITLES[kind],
                body_markdown=_section_body_template(kind, research, context, mode),
                cited_references=[],
            )
        )
    return ensured


def _fallback_draft(
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
    note: str | None = None,
) -> DraftResult:
    title = _make_title(research, f"{research.summary_one_line} 변경 과정 정리")
    sections = [
        DraftSection(
            kind=kind,  # type: ignore[arg-type]
            title=SECTION_TITLES[kind],
            body_markdown=_section_body_template(kind, research, context, mode),
            cited_references=[],
        )
        for kind in REQUIRED_SECTION_KINDS
    ]
    if note:
        sections[-1] = sections[-1].model_copy(
            update={"body_markdown": f"{sections[-1].body_markdown}\n\n> note: {note}"}
        )
    draft = _make_draft(research, title, sections)
    sanitized, _ = _sanitize_draft(draft, research, context, mode)
    return sanitized


def _slim_research(research: ResearchResult) -> dict[str, Any]:
    """patch 원문 제외 — 토큰 절약용."""
    d = research.model_dump(mode="json")
    for f in d.get("changed_files", []):
        f.pop("patch", None)
    d.pop("search_chunks", None)
    return d


def build_generate_draft_prompt(
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
    retry_instruction: str | None = None,
) -> str:
    references = context.verified_references if mode == "full" else []
    payload = {
        "mode": mode,
        "research": _slim_research(research),
        "verified_references": [reference.model_dump(mode="json") for reference in references],
        "section_titles": SECTION_TITLES,
        "output_schema": DraftResult.model_json_schema(),
    }
    retry_text = f"\nRetry instruction: {retry_instruction}\n" if retry_instruction else ""
    return f"""반드시 DraftResult JSON만 반환하세요. 설명 텍스트 없이 JSON 객체만 출력합니다.

규칙:
- research.pr_identifier를 그대로 사용합니다.
- verified_references의 URL만 cited_references와 마크다운 링크에 사용합니다.
- mode가 minimal_context이면 외부 URL을 인용하지 않습니다.
- full_markdown은 제목과 6개 섹션을 이어붙인 완성된 마크다운입니다.
- 각 섹션은 사실(facts)을 자연스러운 문장으로 풀어 씁니다. raw diff 텍스트를 그대로 복사하지 않습니다.
{retry_text}
[INPUT]
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_draft(
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
    retry_instruction: str | None = None,
) -> dict[str, Any]:
    completion = _solar_client().chat.completions.create(
        model=_writer_model(),
        messages=[
            {"role": "system", "content": GENERATE_DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": build_generate_draft_prompt(research, context, mode, retry_instruction)},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    content = completion.choices[0].message.content
    if not content:
        raise WriterError("Solar returned an empty DraftResult.")
    return _parse_json_object(content)


def _normalize_draft_candidate(
    candidate: dict[str, Any],
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> DraftResult:
    allowed_urls = _allowed_reference_urls(context, mode)
    title = _make_title(research, candidate.get("title") if isinstance(candidate.get("title"), str) else None)
    sections_payload = candidate.get("sections")
    sections: list[DraftSection] = []
    if isinstance(sections_payload, list):
        for item in sections_payload:
            try:
                section = DraftSection.model_validate(item)
            except ValidationError:
                continue
            if section.kind in REQUIRED_SECTION_KINDS:
                sections.append(section)
    if not sections and isinstance(candidate.get("full_markdown"), str):
        parsed_title, parsed_sections = _parse_markdown_sections(candidate["full_markdown"], allowed_urls)
        if parsed_title:
            title = _make_title(research, parsed_title)
        sections = parsed_sections
    if not sections:
        raise WriterError("DraftResult response did not contain parseable sections.")
    draft = _make_draft(
        research=research,
        title=title,
        sections=sections,
        revision=int(candidate.get("revision") or 0),
    )
    sanitized, _ = _sanitize_draft(draft, research, context, mode)
    return sanitized


def generate_draft(
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"] = "full",
) -> DraftResult:
    effective_mode = _resolve_mode(mode, context)
    if effective_mode == "minimal_context":
        return _fallback_draft(research, context, effective_mode)
    retry_instruction: str | None = None
    last_error: Exception | None = None
    for _ in range(2):
        try:
            candidate = call_solar_for_draft(research, context, effective_mode, retry_instruction)
            return _normalize_draft_candidate(candidate, research, context, effective_mode)
        except WriterConfigError as exc:
            return _fallback_draft(research, context, effective_mode, f"LLM configuration unavailable: {exc}")
        except (json.JSONDecodeError, ValidationError, WriterError, OpenAIError) as exc:
            last_error = exc
            retry_instruction = f"Previous output failed validation: {exc}. Return only valid DraftResult JSON."
    return _fallback_draft(
        research,
        context,
        effective_mode,
        f"draft generation failed after retry; deterministic fallback used: {last_error}",
    )


def _collect_cited_references(draft: DraftResult) -> list[str]:
    cited: list[str] = []
    for section in draft.sections:
        for url in section.cited_references:
            clean = _clean_url(url)
            if clean not in cited:
                cited.append(clean)
        for url in _extract_urls(section.body_markdown):
            if url not in cited:
                cited.append(url)
    for url in _extract_urls(draft.full_markdown):
        if url not in cited:
            cited.append(url)
    return cited


def deterministic_checklist(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"] = "full",
) -> ChecklistOutcome:
    effective_mode = _resolve_mode(mode, context)
    allowed_urls = _allowed_reference_urls(context, effective_mode)
    cited_before = _collect_cited_references(draft)
    sanitized, removed = _sanitize_draft(draft, research, context, effective_mode)
    section_kinds = {section.kind for section in sanitized.sections if section.body_markdown.strip()}
    title_len = len(sanitized.title)
    speculation_matches = [
        _truncate(sentence)
        for sentence in _split_sentences(sanitized.full_markdown)
        if SPECULATION_RE.search(sentence)
    ]
    cited_after = [url for url in cited_before if url not in removed]
    cited_subset_passed = all(url in allowed_urls for url in cited_after) and not removed
    pr_metadata_present = (
        research.pr_identifier in sanitized.full_markdown
        or research.summary_one_line in sanitized.full_markdown
    )
    word_count = _count_words(sanitized.full_markdown)
    checklist = [
        ChecklistItem(
            name="title_length",
            passed=5 <= title_len <= 60,
            detail=f"title length={title_len}",
        ),
        ChecklistItem(
            name="has_code_block",
            passed=sanitized.code_block_count >= 1,
            detail=f"code_block_count={sanitized.code_block_count}",
        ),
        ChecklistItem(
            name="four_act_present",
            passed=all(kind in section_kinds for kind in REQUIRED_SECTION_KINDS),
            detail="required sections: intro, problem, cause, solution, result, outro",
        ),
        ChecklistItem(
            name="pr_metadata_present",
            passed=True,
            detail=(
                "PR title or pr_identifier appears in markdown"
                if pr_metadata_present
                else "PR title or pr_identifier is missing; finding emitted"
            ),
        ),
        ChecklistItem(
            name="cited_refs_subset_verified",
            passed=cited_subset_passed,
            detail=(
                "all cited references are verified"
                if cited_subset_passed
                else f"removed unverified URLs: {', '.join(removed)}"
            ),
        ),
        ChecklistItem(
            name="no_speculation_words",
            passed=not speculation_matches,
            detail=(
                "no speculation words"
                if not speculation_matches
                else f"speculative sentences: {' | '.join(speculation_matches[:3])}"
            ),
        ),
        ChecklistItem(
            name="length_in_range",
            passed=600 <= word_count <= 3000,
            detail=f"word_count={word_count}; warning only",
        ),
    ]
    findings: list[IssueFinding] = []
    if sanitized.code_block_count < 1:
        findings.append(
            IssueFinding(
                kind="structure_violation",
                section_kind="solution",
                quote="코드 블록 없음",
                suggestion="해결 방법 섹션에 PR diff 또는 변경 함수 코드 블록을 추가하세요.",
            )
        )
    missing_sections = [kind for kind in REQUIRED_SECTION_KINDS if kind not in section_kinds]
    if missing_sections:
        findings.append(
            IssueFinding(
                kind="structure_violation",
                section_kind=None,
                quote=", ".join(missing_sections),
                suggestion="6개 필수 섹션을 모두 포함하세요.",
            )
        )
    if removed:
        findings.append(
            IssueFinding(
                kind="ungrounded_claim",
                section_kind=None,
                quote=", ".join(removed)[:50],
                suggestion="verified_references에 없는 URL 인용을 제거했습니다.",
            )
        )
    for sentence in speculation_matches[:3]:
        findings.append(
            IssueFinding(
                kind="tone_mismatch",
                section_kind=None,
                quote=sentence,
                suggestion="추측 표현을 제거하고 확인된 사실로만 문장을 다시 쓰세요.",
            )
        )
    if not pr_metadata_present:
        findings.append(
            IssueFinding(
                kind="other",
                section_kind="intro",
                quote="PR metadata missing",
                suggestion=f"`{research.pr_identifier}` 또는 PR 제목을 본문에 포함하세요.",
            )
        )
    return ChecklistOutcome(
        draft=sanitized,
        checklist=checklist,
        findings=_dedupe_findings(findings),
        removed_citations=removed,
    )


def _tokens(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "was",
        "were",
        "this",
        "that",
        "변경",
        "추가",
        "수정",
        "삭제",
        "확인",
        "했습니다",
    }
    result = set()
    for token in TOKEN_RE.findall(text.lower()):
        if len(token) < 2 and not token.isdigit():
            continue
        if token in stopwords:
            continue
        result.add(token)
    return result


def _overlap_score(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _fact_is_represented(fact: FactBullet, markdown: str) -> bool:
    statement = fact.statement.strip()
    if not statement:
        return True
    if statement.lower() in markdown.lower():
        return True
    fact_tokens = _tokens(statement)
    path_like_tokens = {token for token in fact_tokens if "/" in token or "." in token or "#" in token}
    if path_like_tokens and any(token in markdown.lower() for token in path_like_tokens):
        return True
    if len(fact_tokens) <= 2:
        return bool(fact_tokens & _tokens(markdown))
    return _overlap_score(statement, markdown) >= 0.4


def verify_fact_in_diff(statement: str, research: ResearchResult) -> FactDiffVerification:
    matches: list[FactDiffMatch] = []
    for fact in research.facts:
        score = _overlap_score(statement, fact.statement)
        if score >= 0.45:
            matches.append(
                FactDiffMatch(file=fact.source_locator, line_text=fact.statement, score=round(score, 2))
            )
    for file_change in research.changed_files:
        if not file_change.patch:
            continue
        for line in file_change.patch.splitlines():
            score = _overlap_score(statement, line)
            if score >= 0.45:
                matches.append(
                    FactDiffMatch(file=file_change.path, line_text=line[:240], score=round(score, 2))
                )
    matches = sorted(matches, key=lambda item: item.score, reverse=True)[:5]
    if matches:
        return FactDiffVerification(
            statement=statement,
            verdict="consistent",
            matches=matches,
            reasoning="The statement overlaps with PR facts or diff lines.",
        )
    return FactDiffVerification(
        statement=statement,
        verdict="needs_review",
        matches=[],
        reasoning="No strong overlap was found in PR facts or diff lines.",
    )


def _section_for_kind(draft: DraftResult, kind: str) -> DraftSection | None:
    return next((section for section in draft.sections if section.kind == kind), None)


def _section_with_code(draft: DraftResult) -> DraftSection | None:
    return next((section for section in draft.sections if CODE_BLOCK_RE.search(section.body_markdown)), None)


def _code_under_explained(section: DraftSection) -> bool:
    if not CODE_BLOCK_RE.search(section.body_markdown):
        return False
    prose = CODE_BLOCK_RE.sub(" ", section.body_markdown)
    return _count_words(prose) < 24


def _classify_findings(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> list[IssueFinding]:
    outcome = deterministic_checklist(draft, research, context, mode)
    findings = list(outcome.findings)
    section_kinds = {section.kind for section in outcome.draft.sections if section.body_markdown.strip()}
    for kind in REQUIRED_SECTION_KINDS:
        if kind not in section_kinds:
            findings.append(
                IssueFinding(
                    kind="structure_violation",
                    section_kind=None,
                    quote=kind,
                    suggestion=f"{SECTION_TITLES[kind]} 섹션을 추가하세요.",
                )
            )
    for fact in research.facts[:8]:
        if _fact_is_represented(fact, outcome.draft.full_markdown):
            continue
        verification = verify_fact_in_diff(fact.statement, research)
        if verification.verdict == "consistent":
            findings.append(
                IssueFinding(
                    kind="missing_fact",
                    section_kind="problem" if fact.source == "linked_issue" else "solution",
                    quote=_truncate(fact.statement),
                    suggestion=f"본문에 다음 확인 사실을 추가하세요: {fact.statement}",
                )
            )
    if outcome.draft.code_block_count < 1:
        findings.append(
            IssueFinding(
                kind="structure_violation",
                section_kind="solution",
                quote="코드 블록 없음",
                suggestion="해결 방법 섹션에 코드 블록을 추가하세요.",
            )
        )
    code_section = _section_with_code(outcome.draft)
    if code_section and _code_under_explained(code_section):
        findings.append(
            IssueFinding(
                kind="code_under_explained",
                section_kind=code_section.kind,
                quote=_truncate(code_section.body_markdown),
                suggestion="코드 블록 앞뒤에 변경 위치와 읽는 방법을 설명하세요.",
            )
        )
    return _dedupe_findings(findings)


def _finding_key(finding: IssueFinding) -> tuple[str, str, str]:
    return (finding.kind, finding.section_kind or "", finding.quote.lower())


def _dedupe_findings(findings: list[IssueFinding]) -> list[IssueFinding]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[IssueFinding] = []
    for finding in findings:
        key = _finding_key(finding)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _critical_findings(findings: list[IssueFinding]) -> list[IssueFinding]:
    return [finding for finding in findings if finding.kind in CRITICAL_FINDING_KINDS]


def build_reflection_prompt(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
    iteration: int,
) -> str:
    references = context.verified_references if mode == "full" else []
    payload = {
        "mode": mode,
        "iteration": iteration,
        "research_facts": [fact.model_dump(mode="json") for fact in research.facts],
        "verified_references": [reference.model_dump(mode="json") for reference in references],
        "draft": draft.model_dump(mode="json"),
        "available_tool": "verify_fact_in_diff(statement)",
        "output_schema": VerificationResult.model_json_schema(),
    }
    return f"""Return VerificationResult JSON for this draft.

Use pr_identifier exactly: {research.pr_identifier}
Use iteration exactly: {iteration}
Set auto_patched=false because patching is performed by the caller.

[INPUT]
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_reflection(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
    iteration: int,
) -> VerificationResult:
    completion = _solar_client().chat.completions.create(
        model=_reflection_model(),
        messages=[
            {"role": "system", "content": SELF_REFLECTION_SYSTEM_PROMPT},
            {"role": "user", "content": build_reflection_prompt(draft, research, context, mode, iteration)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content:
        raise WriterError("Solar returned an empty VerificationResult.")
    parsed = _parse_json_object(content)
    parsed["pr_identifier"] = research.pr_identifier
    parsed["iteration"] = iteration
    return VerificationResult.model_validate(parsed)


def _remove_speculative_lines(text: str) -> str:
    output: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            output.append(line)
            continue
        if not in_code and SPECULATION_RE.search(line):
            continue
        output.append(line)
    return "\n".join(output).strip()


def _append_once(body: str, addition: str) -> str:
    if addition.strip() in body:
        return body
    return f"{body.rstrip()}\n\n{addition.strip()}".strip()


def _patch_draft(
    draft: DraftResult,
    findings: list[IssueFinding],
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"],
) -> DraftResult:
    effective_mode = _resolve_mode(mode, context)
    section_map = {section.kind: section for section in _ensure_sections(draft.sections, research, context, effective_mode)}

    for kind, section in list(section_map.items()):
        cleaned = _remove_speculative_lines(section.body_markdown)
        section_map[kind] = section.model_copy(update={"body_markdown": cleaned})

    intro = section_map["intro"]
    if research.pr_identifier not in intro.body_markdown and research.summary_one_line not in intro.body_markdown:
        intro_body = f"> PR: {research.pr_identifier} - {research.summary_one_line}\n\n{intro.body_markdown}"
        section_map["intro"] = intro.model_copy(update={"body_markdown": intro_body.strip()})

    solution = section_map["solution"]
    if _count_code_blocks(solution.body_markdown) < 1 and draft.code_block_count < 1:
        section_map["solution"] = solution.model_copy(
            update={"body_markdown": _append_once(solution.body_markdown, _select_code_block(research))}
        )

    for finding in findings:
        if finding.kind == "missing_fact":
            statement = finding.suggestion.split(":", 1)[-1].strip() or finding.quote
            target_kind = finding.section_kind or "solution"
            target = section_map.get(target_kind, section_map["solution"])
            if not _fact_is_represented(
                FactBullet(statement=statement, source="diff", source_locator="reflection_patch"),
                target.body_markdown,
            ):
                section_map[target.kind] = target.model_copy(
                    update={"body_markdown": _append_once(target.body_markdown, f"- {statement}")}
                )

    if effective_mode == "minimal_context":
        outro = section_map["outro"]
        if "공식 문서를 추가로 확인하세요." not in outro.body_markdown:
            section_map["outro"] = outro.model_copy(
                update={"body_markdown": _append_once(outro.body_markdown, "공식 문서를 추가로 확인하세요.")}
            )

    ordered_sections = [section_map[kind] for kind in REQUIRED_SECTION_KINDS]
    patched = _make_draft(
        research=research,
        title=_make_title(research, draft.title),
        sections=ordered_sections,
        revision=min(draft.revision + 1, MAX_REFLECTION_ITERATIONS),
    )
    sanitized, _ = _sanitize_draft(patched, research, context, effective_mode)
    return sanitized


def self_reflect_and_patch(
    draft: DraftResult,
    research: ResearchResult,
    context: ContextResult,
    mode: Literal["full", "minimal_context"] = "full",
) -> tuple[DraftResult, list[VerificationResult]]:
    effective_mode = _resolve_mode(mode, context)
    current = draft
    verifications: list[VerificationResult] = []
    previous_critical_keys: set[tuple[str, str, str]] = set()

    for iteration in range(1, MAX_REFLECTION_ITERATIONS + 1):
        deterministic_findings = _classify_findings(current, research, context, effective_mode)
        llm_findings: list[IssueFinding] = []
        try:
            llm_result = call_solar_for_reflection(current, research, context, effective_mode, iteration)
            llm_findings = llm_result.findings
        except (WriterConfigError, json.JSONDecodeError, ValidationError, WriterError, OpenAIError):
            llm_findings = []

        findings = _dedupe_findings([*deterministic_findings, *llm_findings])
        critical = _critical_findings(findings)
        critical_keys = {_finding_key(finding) for finding in critical}

        if not critical:
            verifications.append(
                VerificationResult(
                    pr_identifier=research.pr_identifier,
                    iteration=iteration,
                    findings=findings,
                    auto_patched=False,
                    needs_human_review=False,
                )
            )
            break

        if iteration > 1 and critical_keys == previous_critical_keys:
            verifications.append(
                VerificationResult(
                    pr_identifier=research.pr_identifier,
                    iteration=iteration,
                    findings=findings,
                    auto_patched=False,
                    needs_human_review=True,
                )
            )
            break

        current = _patch_draft(current, findings, research, context, effective_mode)
        verifications.append(
            VerificationResult(
                pr_identifier=research.pr_identifier,
                iteration=iteration,
                findings=findings,
                auto_patched=True,
                needs_human_review=False,
            )
        )
        previous_critical_keys = critical_keys
    else:
        unresolved = _critical_findings(_classify_findings(current, research, context, effective_mode))
        if unresolved and verifications:
            verifications[-1] = verifications[-1].model_copy(update={"needs_human_review": True})

    if not verifications:
        verifications.append(
            VerificationResult(
                pr_identifier=research.pr_identifier,
                iteration=1,
                findings=[],
                auto_patched=False,
                needs_human_review=False,
            )
        )

    current = current.model_copy(update={"revision": sum(1 for item in verifications if item.auto_patched)})
    return current, verifications


def _grade_from_average(average: float) -> Literal["A", "B", "C", "D", "F"]:
    if average >= 4.5:
        return "A"
    if average >= 4.0:
        return "B"
    if average >= 3.0:
        return "C"
    if average >= 2.0:
        return "D"
    return "F"


def _int_score(value: float) -> int:
    return max(1, min(5, int(value + 0.5)))


def _check_pass(checklist: list[ChecklistItem], name: str) -> bool:
    item = next((entry for entry in checklist if entry.name == name), None)
    return bool(item and item.passed)


def _deterministic_self_eval(
    draft: DraftResult,
    checklist: list[ChecklistItem],
    verifications: list[VerificationResult],
    mode: Literal["full", "minimal_context"],
) -> WriterSelfEval:
    pass_count = sum(1 for item in checklist if item.passed)
    pass_rate = round(pass_count / len(checklist), 2) if checklist else 0.0
    findings = [finding for verification in verifications for finding in verification.findings]
    finding_kinds = {finding.kind for finding in findings}
    needs_human_review = any(verification.needs_human_review for verification in verifications)
    cited_failed = not _check_pass(checklist, "cited_refs_subset_verified")

    accuracy = 5.0
    if cited_failed:
        accuracy = 2.0
    elif "ungrounded_claim" in finding_kinds:
        accuracy = 3.0
    elif "missing_fact" in finding_kinds:
        accuracy = 4.0
    if mode == "minimal_context":
        accuracy = min(accuracy, 4.0)

    readability = 5.0 if _check_pass(checklist, "no_speculation_words") else 3.0
    if not _check_pass(checklist, "length_in_range"):
        readability = min(readability, 4.0)

    structure = 5.0
    if not _check_pass(checklist, "four_act_present"):
        structure = 2.0
    elif not _check_pass(checklist, "title_length"):
        structure = 4.0

    code_explanation = 5.0
    if not _check_pass(checklist, "has_code_block"):
        code_explanation = 1.0
    elif "code_under_explained" in finding_kinds:
        code_explanation = 3.0

    if needs_human_review:
        accuracy -= 0.5
        readability -= 0.5
        structure -= 0.5
        code_explanation -= 0.5

    float_scores = {
        "accuracy": max(1.0, accuracy),
        "readability": max(1.0, readability),
        "structure": max(1.0, structure),
        "code_explanation": max(1.0, code_explanation),
    }
    average = round(sum(float_scores.values()) / 4, 2)
    suggestions = []
    for item in checklist:
        if not item.passed and item.name != "length_in_range":
            suggestions.append(f"{item.name}: {item.detail or 'check failed'}")
    for finding in findings[:4]:
        suggestions.append(f"{finding.kind}: {finding.suggestion}")
    if mode == "minimal_context":
        suggestions.append("minimal_context 모드라 외부 검증 부재를 accuracy rationale에 반영했습니다.")
    if needs_human_review:
        suggestions.append("자동 reflection으로 해결되지 않은 critical finding이 있어 사람 검토가 필요합니다.")
    if not suggestions:
        suggestions.append("현재 초안은 결정적 체크리스트와 reflection 기준을 통과했습니다.")

    return WriterSelfEval(
        checklist=checklist,
        checklist_pass_rate=pass_rate,
        judge_scores=[
            JudgeScore(
                dimension="accuracy",
                score=_int_score(float_scores["accuracy"]),
                rationale=(
                    "verified_references 범위와 PR facts 근거를 기준으로 평가했습니다."
                    if mode == "full"
                    else "minimal_context 모드라 외부 검증이 없음을 반영했습니다."
                ),
            ),
            JudgeScore(
                dimension="readability",
                score=_int_score(float_scores["readability"]),
                rationale="추측 표현, 문단 길이, 신입 개발자 대상 설명 흐름을 기준으로 평가했습니다.",
            ),
            JudgeScore(
                dimension="structure",
                score=_int_score(float_scores["structure"]),
                rationale="필수 6개 섹션과 4-Act 흐름 유지 여부를 기준으로 평가했습니다.",
            ),
            JudgeScore(
                dimension="code_explanation",
                score=_int_score(float_scores["code_explanation"]),
                rationale="코드 블록 포함 여부와 주변 설명의 충분성을 기준으로 평가했습니다.",
            ),
        ],
        judge_average=average,
        overall_grade=_grade_from_average(average),
        suggestions=suggestions,
    )


def build_self_eval_prompt(
    draft: DraftResult,
    checklist: list[ChecklistItem],
    verifications: list[VerificationResult],
    mode: Literal["full", "minimal_context"],
) -> str:
    payload = {
        "mode": mode,
        "draft": draft.model_dump(mode="json"),
        "checklist": [item.model_dump(mode="json") for item in checklist],
        "verifications": [item.model_dump(mode="json") for item in verifications],
        "output_schema": WriterSelfEval.model_json_schema(),
    }
    return f"""Return WriterSelfEval JSON.

Use the supplied checklist as the checklist field.
Compute checklist_pass_rate from the supplied checklist.
Return exactly four judge_scores: accuracy, readability, structure, code_explanation.
Compute overall_grade from judge_average using: avg >= 4.5 A, >= 4.0 B, >= 3.0 C, >= 2.0 D, else F.

[INPUT]
{json.dumps(payload, ensure_ascii=False)}
"""


def call_solar_for_self_eval(
    draft: DraftResult,
    checklist: list[ChecklistItem],
    verifications: list[VerificationResult],
    mode: Literal["full", "minimal_context"],
) -> dict[str, Any]:
    completion = _solar_client().chat.completions.create(
        model=_eval_model(),
        messages=[
            {"role": "system", "content": SELF_EVALUATION_SYSTEM_PROMPT},
            {"role": "user", "content": build_self_eval_prompt(draft, checklist, verifications, mode)},
        ],
        temperature=0,
    )
    content = completion.choices[0].message.content
    if not content:
        raise WriterError("Solar returned an empty WriterSelfEval.")
    return _parse_json_object(content)


def _normalize_self_eval_candidate(
    candidate: dict[str, Any],
    draft: DraftResult,
    checklist: list[ChecklistItem],
    verifications: list[VerificationResult],
    mode: Literal["full", "minimal_context"],
) -> WriterSelfEval:
    fallback = _deterministic_self_eval(draft, checklist, verifications, mode)
    try:
        parsed = WriterSelfEval.model_validate(candidate)
    except ValidationError:
        return fallback
    scores = {score.dimension: score for score in parsed.judge_scores}
    if set(scores) != {"accuracy", "readability", "structure", "code_explanation"}:
        return fallback
    checklist_pass_rate = round(sum(1 for item in checklist if item.passed) / len(checklist), 2) if checklist else 0.0
    average = round(sum(score.score for score in scores.values()) / 4, 2)
    grade = _grade_from_average(average)
    if not _check_pass(checklist, "cited_refs_subset_verified"):
        scores["accuracy"] = scores["accuracy"].model_copy(
            update={
                "score": min(scores["accuracy"].score, 2),
                "rationale": f"{scores['accuracy'].rationale} cited_refs_subset_verified 실패를 반영했습니다.",
            }
        )
        average = round(sum(score.score for score in scores.values()) / 4, 2)
        grade = _grade_from_average(average)
    return parsed.model_copy(
        update={
            "checklist": checklist,
            "checklist_pass_rate": checklist_pass_rate,
            "judge_scores": [scores[dimension] for dimension in ("accuracy", "readability", "structure", "code_explanation")],
            "judge_average": average,
            "overall_grade": grade,
        }
    )


def self_evaluate(
    draft: DraftResult,
    checklist: list[ChecklistItem],
    verifications: list[VerificationResult],
    mode: Literal["full", "minimal_context"] = "full",
) -> WriterSelfEval:
    try:
        candidate = call_solar_for_self_eval(draft, checklist, verifications, mode)
        return _normalize_self_eval_candidate(candidate, draft, checklist, verifications, mode)
    except (WriterConfigError, json.JSONDecodeError, ValidationError, WriterError, OpenAIError):
        return _deterministic_self_eval(draft, checklist, verifications, mode)


def run_writer_pipeline(
    research_input: ResearchResult | dict[str, Any],
    context_input: ContextResult | dict[str, Any] | None = None,
    mode: Literal["full", "minimal_context"] = "full",
) -> WriterRunResult:
    research = (
        research_input
        if isinstance(research_input, ResearchResult)
        else ResearchResult.model_validate(research_input)
    )
    if context_input is None:
        context = _empty_context(research.pr_identifier)
    elif isinstance(context_input, ContextResult):
        context = context_input
    else:
        context = ContextResult.model_validate(context_input)
    effective_mode = _resolve_mode(mode, context)

    initial_draft = generate_draft(research, context, effective_mode)
    initial_check = deterministic_checklist(initial_draft, research, context, effective_mode)
    reflected_draft, verifications = self_reflect_and_patch(
        initial_check.draft,
        research,
        context,
        effective_mode,
    )
    final_check = deterministic_checklist(reflected_draft, research, context, effective_mode)
    final_draft = final_check.draft
    eval_result = self_evaluate(final_draft, final_check.checklist, verifications, effective_mode)
    final_draft = final_draft.model_copy(update={"self_eval": eval_result})
    return WriterRunResult(draft=final_draft, verifications=verifications)


def run_writer(
    research_input: ResearchResult | dict[str, Any],
    context_input: ContextResult | dict[str, Any] | None = None,
    mode: Literal["full", "minimal_context"] = "full",
) -> DraftResult:
    return run_writer_pipeline(research_input, context_input, mode).draft
