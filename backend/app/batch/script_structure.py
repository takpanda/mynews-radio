"""Deterministic structural checks and repairs for generated scripts."""

from __future__ import annotations

from typing import Any

from app.programs.profiles import ProgramProfile

_CONTENT_SECTIONS = {"news", "discussion"}


def _issue(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "line_indices": []}


def _uses_legacy_layout(profile: ProgramProfile | None) -> bool:
    if profile is None:
        return True
    from app.programs.prompt_builder import PromptBuilder

    return PromptBuilder(profile).uses_legacy_prompt


def check_profile_structure(
    lines: list[dict[str, Any]], profile: ProgramProfile,
) -> list[dict[str, Any]]:
    """Expose profile-specific structural checks alongside layout checks."""
    from app.batch.script_validator import ScriptValidator

    return ScriptValidator(profile).validate_structure(lines)


def _content_segments(lines: list[dict[str, Any]], start: int, end: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the body into transition-prefixed news/discussion segments.

    A transition belongs to the content block immediately following it. This
    makes moving an article preserve its existing handoff text and speakers.
    """
    segments: list[dict[str, Any]] = []
    structural_issues: list[dict[str, Any]] = []
    pending_transitions: list[dict[str, Any]] = []
    current_section: str | None = None
    current_lines: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current_section, current_lines, pending_transitions
        if current_section is not None:
            segments.append({
                "section": current_section,
                "prefix": pending_transitions,
                "content": current_lines,
                "lines": pending_transitions + current_lines,
            })
            pending_transitions = []
            current_section = None
            current_lines = []

    for index in range(start, end):
        line = lines[index]
        section = line.get("section")
        if section == "transition":
            flush()
            pending_transitions.append(line)
            continue
        if section in _CONTENT_SECTIONS:
            if current_section != section:
                flush()
                current_section = section
            current_lines.append(line)
            continue

        flush()
        structural_issues.append(
            _issue(
                "DISCUSSION_LAYOUT",
                f"ニュース・討論部に移動できないセクションがあります（行 {index}）",
            )
        )

    flush()
    if pending_transitions:
        structural_issues.append(
            _issue("DISCUSSION_LAYOUT", "コンテンツに紐付かないtransitionがあります")
        )
    return segments, structural_issues


def check_discussion_layout(
    lines: list[dict[str, Any]],
    *,
    expected_discussion_article_id: Any = None,
    program_profile: ProgramProfile | None = None,
) -> list[dict[str, Any]]:
    """Check legacy placement rules or custom-profile article identity."""
    if not _uses_legacy_layout(program_profile):
        discussion_indices = [i for i, line in enumerate(lines) if line.get("section") == "discussion"]
        if not discussion_indices:
            return []
        discussion_ids = {lines[i].get("article_id") for i in discussion_indices}
        issues: list[dict[str, Any]] = []
        if len(discussion_ids) != 1:
            issues.append(
                _issue(
                    "DISCUSSION_ARTICLE_DRIFT",
                    f"discussion内でarticle_idが複数、または未指定です: {sorted(str(value) for value in discussion_ids)}",
                )
            )
        elif expected_discussion_article_id is not None and next(iter(discussion_ids)) != expected_discussion_article_id:
            discussion_id = next(iter(discussion_ids))
            issues.append(
                _issue(
                    "DISCUSSION_ARTICLE_DRIFT",
                    f"discussionのarticle_id={discussion_id}が選定記事(article_id={expected_discussion_article_id})と一致しません",
                )
            )
        return issues

    news_indices = [i for i, line in enumerate(lines) if line.get("section") == "news"]
    discussion_indices = [i for i, line in enumerate(lines) if line.get("section") == "discussion"]
    if not discussion_indices:
        return []

    issues: list[dict[str, Any]] = []
    if not news_indices:
        return [_issue("DISCUSSION_LAYOUT", "discussionがあるのにnewsセクションがありません")]

    if discussion_indices != list(range(discussion_indices[0], discussion_indices[-1] + 1)):
        issues.append(_issue("DISCUSSION_LAYOUT", "discussionが連続した1ブロックになっていません"))

    first_outro = next(
        (i for i, line in enumerate(lines) if line.get("section") == "outro"),
        len(lines),
    )
    if discussion_indices[0] <= max(news_indices) or discussion_indices[-1] >= first_outro:
        issues.append(_issue("DISCUSSION_POSITION", "discussionは全newsの後、outroの前に配置する必要があります"))

    discussion_ids = {lines[i].get("article_id") for i in discussion_indices}
    if len(discussion_ids) != 1:
        issues.append(
            _issue(
                "DISCUSSION_ARTICLE_DRIFT",
                f"discussion内でarticle_idが複数、または未指定です: {sorted(str(value) for value in discussion_ids)}",
            )
        )
        return issues

    discussion_id = next(iter(discussion_ids))
    if expected_discussion_article_id is not None and discussion_id != expected_discussion_article_id:
        issues.append(
            _issue(
                "DISCUSSION_ARTICLE_DRIFT",
                f"discussionのarticle_id={discussion_id}が選定記事(article_id={expected_discussion_article_id})と一致しません",
            )
        )
    last_news_id = lines[max(news_indices)].get("article_id")
    if discussion_id != last_news_id:
        issues.append(
            _issue(
                "DISCUSSION_ARTICLE_POSITION",
                f"ニュース部の最終記事(article_id={last_news_id})とdiscussion対象(article_id={discussion_id})が一致しません",
            )
        )
    return issues


def normalize_discussion_layout(
    lines: list[dict[str, Any]],
    *,
    expected_discussion_article_id: Any = None,
    program_profile: ProgramProfile | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Move the selected article and discussion to their canonical positions.

    Only existing, transition-prefixed blocks are moved. If the selected
    article cannot be moved without losing a boundary transition, the caller
    receives a critical finding and must not synthesize the script.

    Custom profiles own their section order. The legacy article-block repair
    only understands the built-in radio layout, so custom profiles are returned
    unchanged and checked against their declared segment order instead.
    """
    repaired = [dict(line) for line in lines]
    if program_profile is not None:
        from app.programs.prompt_builder import PromptBuilder

        if not PromptBuilder(program_profile).uses_legacy_prompt:
            return repaired, [], []

    discussion_indices = [i for i, line in enumerate(repaired) if line.get("section") == "discussion"]
    if not discussion_indices:
        return repaired, [], []

    news_indices = [i for i, line in enumerate(repaired) if line.get("section") == "news"]
    if not news_indices:
        return repaired, [], [_issue("DISCUSSION_LAYOUT", "discussionがあるのにnewsセクションがありません")]

    first_body = min(
        i for i, line in enumerate(repaired)
        if line.get("section") in {"news", "discussion", "transition"}
    )
    first_outro = next(
        (i for i, line in enumerate(repaired[first_body:], first_body) if line.get("section") == "outro"),
        len(repaired),
    )
    segments, issues = _content_segments(repaired, first_body, first_outro)
    if issues:
        return repaired, [], issues

    discussion_segments = [segment for segment in segments if segment["section"] == "discussion"]
    news_segments = [segment for segment in segments if segment["section"] == "news"]
    if len(discussion_segments) != 1:
        return repaired, [], [
            _issue("DISCUSSION_LAYOUT", "discussionが1つの連続ブロックとして構成されていません")
        ]

    discussion_segment = discussion_segments[0]
    discussion_ids = {line.get("article_id") for line in discussion_segment["content"]}
    if len(discussion_ids) != 1 or None in discussion_ids:
        return repaired, [], [
            _issue(
                "DISCUSSION_ARTICLE_DRIFT",
                f"discussion内でarticle_idを一意に決定できません: {sorted(str(value) for value in discussion_ids)}",
            )
        ]
    discussion_id = next(iter(discussion_ids))
    if expected_discussion_article_id is not None and discussion_id != expected_discussion_article_id:
        return repaired, [], [
            _issue(
                "DISCUSSION_ARTICLE_DRIFT",
                f"discussionのarticle_id={discussion_id}が選定記事(article_id={expected_discussion_article_id})と一致しません",
            )
        ]

    invalid_news = []
    for segment in news_segments:
        article_ids = {line.get("article_id") for line in segment["content"]}
        if len(article_ids) != 1 or None in article_ids:
            invalid_news.append(segment)
    if invalid_news:
        return repaired, [], [
            _issue("DISCUSSION_LAYOUT", "newsブロック内のarticle_idが一意でないため安全に並べ替えできません")
        ]

    target_segments = [
        segment for segment in news_segments
        if {line.get("article_id") for line in segment["content"]} == {discussion_id}
    ]
    if len(target_segments) != 1:
        return repaired, [], [
            _issue(
                "DISCUSSION_ARTICLE_POSITION",
                f"discussion対象(article_id={discussion_id})のnewsブロックを一意に特定できません",
            )
        ]
    target_segment = target_segments[0]
    desired_segments = [segment for segment in news_segments if segment is not target_segment]
    desired_segments.append(target_segment)
    desired_segments.append(discussion_segment)

    if [id(segment) for segment in segments] == [id(segment) for segment in desired_segments]:
        return repaired, [], []

    # A first article has no incoming transition to carry with it. Moving it
    # would require inventing a sentence, so leave the script for a human.
    if target_segment is not news_segments[-1] and not target_segment["prefix"]:
        return repaired, [], [
            _issue(
                "DISCUSSION_LAYOUT",
                f"discussion対象(article_id={discussion_id})を移動するためのtransitionがありません",
            )
        ]

    reordered_body = [
        line
        for segment in desired_segments
        for line in segment["lines"]
    ]
    repaired = repaired[:first_body] + reordered_body + repaired[first_outro:]
    repairs = [
        _issue(
            "DISCUSSION_REORDERED",
            f"discussion対象(article_id={discussion_id})をニュース部の最終記事へ移動し、discussionをoutro直前へ配置しました",
        )
    ]
    return repaired, repairs, check_discussion_layout(
        repaired,
        expected_discussion_article_id=expected_discussion_article_id,
        program_profile=program_profile,
    )
