"""Final script validation before audio synthesis.

The generation linter is intentionally allowed to keep the best effort output
after its retry limit.  This module is the last quality gate after review: it
classifies remaining findings, applies only deterministic block-local repairs,
and reports whether synthesis may start.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.batch.generate_script import (
    _SENSITIVE_INAPPROPRIATE_TRANSITION_MARKERS,
    _SENSITIVE_NEWS_KEYWORDS,
    lint_script,
)
from app.batch.review_script import (
    _is_question as _generate_is_question,
    check_question_response_contract,
    check_transition_integrity,
)

logger = logging.getLogger(__name__)

FINAL_VALIDATION_PHASE = "final_validation"
HUMAN_REVIEW_PHASE = "human_review"

_FAREWELL_RE = re.compile(
    r"(?:また(?:明日|次回|来週)|それではまた|お会いしましょう|"
    r"さようなら|お元気で|お届けしました|お聴きいただき|"
    r"お聞きいただき|番組を終わります|締めくくり)",
)
_MINOR_LINT_CODES = {
    "TRANS_VARIATION",
    "INTRO_LINEUP",
    "TRUNCATED_TRANS",
}


def _issue(code: str, message: str, *, line_indices: list[int] | None = None) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "line_indices": line_indices or [],
    }


def _is_sensitive_article(article: dict[str, Any]) -> bool:
    text = " ".join(str(article.get(key, "") or "") for key in ("category", "title", "summary"))
    return any(keyword in text for keyword in _SENSITIVE_NEWS_KEYWORDS)


def _sensitive_article_ids(summaries: list[dict[str, Any]]) -> set[Any]:
    return {
        article.get("id", article.get("article_id"))
        for article in summaries
        if isinstance(article, dict) and _is_sensitive_article(article)
    }


def _transition_reaction_issues(
    lines: list[dict[str, Any]], summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect celebratory reactions immediately before sensitive news."""
    sensitive_ids = _sensitive_article_ids(summaries)
    if not sensitive_ids:
        return []

    issues: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if line.get("section") != "transition":
            continue
        article_id = line.get("article_id")
        if article_id not in sensitive_ids:
            continue
        text = str(line.get("text", "") or "")
        if any(marker in text for marker in _SENSITIVE_INAPPROPRIATE_TRANSITION_MARKERS):
            issues.append(
                _issue(
                    "INAPPROPRIATE_REACTION",
                    f"transition行 {index} に重大事故・災害の直前として不適切な反応があります",
                    line_indices=[index],
                )
            )
    return issues


def _repair_outro_questions(lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Remove only reinserted questions that occur after the farewell begins.

    The outro contract is summary/question followed by farewell lines.  A
    question after a farewell is unambiguously misplaced and can be removed
    without rewriting factual content.  Missing summary/question/farewell
    content remains a human-review finding.
    """
    repaired = [dict(line) for line in lines]
    outro_indices = [i for i, line in enumerate(repaired) if line.get("section") == "outro"]
    if not outro_indices:
        return repaired, []

    farewell_started = False
    remove_indices: set[int] = set()
    repairs: list[dict[str, Any]] = []
    for index in outro_indices:
        text = str(repaired[index].get("text", "") or "").strip()
        if _FAREWELL_RE.search(text):
            farewell_started = True
            continue
        if farewell_started and _generate_is_question(text):
            remove_indices.add(index)
            repairs.append(
                _issue(
                    "OUTRO_QUESTION_REINSERTED",
                    f"outro行 {index} の問いを別れの挨拶の後から削除しました",
                    line_indices=[index],
                )
            )

    if remove_indices:
        repaired = [line for index, line in enumerate(repaired) if index not in remove_indices]
    return repaired, repairs


def _outro_issues(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    outro_indices = [i for i, line in enumerate(lines) if line.get("section") == "outro"]
    if not outro_indices:
        return [_issue("OUTRO_STRUCTURE", "outroセクションがありません")]

    if outro_indices[-1] != len(lines) - 1:
        issues = [
            _issue(
                "OUTRO_POSITION",
                "outroの後に別セクションの行があります",
                line_indices=[outro_indices[-1]],
            )
        ]
    else:
        issues = []

    outro = [lines[i] for i in outro_indices]
    texts = [str(line.get("text", "") or "").strip() for line in outro]
    question_positions = [
        index for index, text in enumerate(texts) if text and _generate_is_question(text)
    ]
    if not question_positions:
        issues.append(_issue("OUTRO_QUESTION_MISSING", "outroに振り返り・問いがありません"))

    farewell_positions = [
        index for index, text in enumerate(texts) if text and _FAREWELL_RE.search(text)
    ]
    if not farewell_positions:
        issues.append(_issue("OUTRO_FAREWELL_MISSING", "outroに別れの挨拶がありません"))
    else:
        first_farewell = farewell_positions[0]
        if question_positions and max(question_positions) >= first_farewell:
            issues.append(
                _issue(
                    "OUTRO_QUESTION_ORDER",
                    "outroの問いは別れの挨拶より前に置く必要があります",
                )
            )
        if not _FAREWELL_RE.search(texts[-1]):
            issues.append(
                _issue(
                    "OUTRO_NOT_TERMINATED",
                    "outroの最終行が別れの挨拶で終わっていません",
                    line_indices=[outro_indices[-1]],
                )
            )
        for index in range(first_farewell + 1, len(texts)):
            if not _FAREWELL_RE.search(texts[index]):
                issues.append(
                    _issue(
                        "OUTRO_AFTER_FAREWELL",
                        f"outro行 {outro_indices[index]} に別れの挨拶後の本文があります",
                        line_indices=[outro_indices[index]],
                    )
                )
    return issues


def _classify_lint_errors(errors: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    critical: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for error in errors:
        match = re.search(r"\[WARN\]\[([^]]+)\]", error)
        if match:
            code = match.group(1)
        else:
            code_match = re.search(r"\[([^]]+)\]", error)
            code = code_match.group(1) if code_match else "LINT"
        item = _issue(code, error)
        if code in _MINOR_LINT_CODES or error.startswith("[WARN]"):
            warnings.append(item)
        else:
            critical.append(item)
    return critical, warnings


def validate_final_script(
    lines: list[dict[str, Any]],
    *,
    summaries: list[dict[str, Any]] | None = None,
    program_name: str = "ニュースのとなり",
    style: str = "dialogue",
    prior_review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the post-review script and return a synthesis decision.

    ``human_review`` is returned only when a critical issue remains after the
    deterministic, block-local repairs.  Warnings never block synthesis.
    """
    source_lines = [line for line in lines if isinstance(line, dict)]
    repaired_lines, repairs = _repair_outro_questions(source_lines)
    critical: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(repairs)

    malformed_indices = [index for index, line in enumerate(lines) if not isinstance(line, dict)]
    if malformed_indices:
        critical.append(
            _issue(
                "GRAMMAR_BREAKDOWN",
                f"台本の行構造が不正です（行 {malformed_indices}）",
                line_indices=malformed_indices,
            )
        )
    invalid_line_indices = [
        index
        for index, line in enumerate(repaired_lines)
        if line.get("speaker") not in {"male", "female"}
        or line.get("section") not in {"intro", "news", "transition", "discussion", "outro"}
        or not str(line.get("text", "") or "").strip()
    ]
    if invalid_line_indices:
        critical.append(
            _issue(
                "GRAMMAR_BREAKDOWN",
                f"台本に話者・セクション・本文が不正な行があります（行 {invalid_line_indices}）",
                line_indices=invalid_line_indices,
            )
        )

    if style != "solo":
        critical.extend(
            _issue("DIRECT_ANSWER_MISSING", message)
            for message in check_question_response_contract(repaired_lines)
            if "DIRECT_ANSWER_MISSING" in message
        )

    lint_critical, lint_warnings = _classify_lint_errors(
        lint_script(repaired_lines, program_name=program_name)
    )
    critical.extend(lint_critical)
    warnings.extend(lint_warnings)

    transition_issues = check_transition_integrity(repaired_lines)
    critical.extend(_issue("TRANSITION_INTEGRITY", message) for message in transition_issues)
    critical.extend(_outro_issues(repaired_lines))
    critical.extend(_transition_reaction_issues(repaired_lines, summaries or []))

    review_result = prior_review_result or {}
    critical.extend(
        _issue("DIRECT_ANSWER_MISSING", message)
        for message in review_result.get("question_response_issues", [])
        if "DIRECT_ANSWER_MISSING" in str(message)
    )
    critical.extend(
        _issue("TRANSITION_INTEGRITY", message)
        for message in review_result.get("transition_integrity_issues", [])
    )
    warnings.extend(
        _issue("DIALOGUE_BALANCE", message)
        for message in review_result.get("dialogue_balance_issues", [])
    )

    # De-duplicate repeated findings from review and deterministic checks while
    # preserving the first occurrence and its line references.
    def unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[str, str]] = set()
        result: list[dict[str, Any]] = []
        for item in items:
            key = (str(item.get("code")), str(item.get("message")))
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result

    critical = unique(critical)
    warnings = unique(warnings)
    status = "human_review" if critical else ("warning" if warnings else "passed")
    return {
        "status": status,
        "can_synthesize": not critical,
        "critical_issues": critical,
        "warnings": warnings,
        "repairs": repairs,
        "lines": repaired_lines,
    }


def validate_final_script_file(
    script_path: str,
    *,
    summaries_path: str | None = None,
    output_dir: str | None = None,
    program_name: str = "ニュースのとなり",
    prior_review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read, validate, and persist the final-validation report."""
    path = Path(script_path)
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        result = {
            "status": "human_review",
            "can_synthesize": False,
            "critical_issues": [_issue("SCRIPT_READ", f"台本を読み込めません: {exc}")],
            "warnings": [],
            "repairs": [],
            "lines": [],
        }
        _write_report(result, output_dir or str(path.parent))
        return result

    summaries: list[dict[str, Any]] = []
    if summaries_path:
        try:
            payload = json.loads(Path(summaries_path).read_text(encoding="utf-8"))
            if isinstance(payload, list):
                summaries = [item for item in payload if isinstance(item, dict)]
        except (OSError, TypeError, ValueError):
            logger.warning("final validation: summaries could not be loaded: %s", summaries_path)

    result = validate_final_script(
        script.get("lines", []) if isinstance(script, dict) else [],
        summaries=summaries,
        program_name=program_name,
        style=str(script.get("style", "dialogue")) if isinstance(script, dict) else "dialogue",
        prior_review_result=prior_review_result,
    )
    if result["repairs"]:
        repaired_script = dict(script)
        repaired_script["lines"] = result["lines"]
        path.write_text(json.dumps(repaired_script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(result, output_dir or str(path.parent))
    return result


def _write_report(result: dict[str, Any], output_dir: str) -> None:
    try:
        report_path = Path(output_dir) / "final_validation.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({k: v for k, v in result.items() if k != "lines"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("final validation report could not be written", exc_info=True)


def human_review_message(result: dict[str, Any]) -> str:
    """Build a concise, inspectable reason for the existing episode field."""
    issues = result.get("critical_issues", [])
    details = " / ".join(str(item.get("message", "")) for item in issues[:5])
    suffix = "（詳細は final_validation.json を確認してください）"
    return f"最終検証で重大な品質問題が残ったため人間確認待ちです: {details} {suffix}".strip()
