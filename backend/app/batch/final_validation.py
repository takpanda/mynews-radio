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
import unicodedata
from itertools import combinations
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
from app.batch.script_structure import check_discussion_layout, normalize_discussion_layout
from app.batch.script_contracts import COMMENTARY_IGNORED_LINT_CODES, FAREWELL_RE
from app.services.article_service import titles_are_similar

logger = logging.getLogger(__name__)

FINAL_VALIDATION_PHASE = "final_validation"
HUMAN_REVIEW_PHASE = "human_review"

_MINOR_LINT_CODES = {
    "TRANS_VARIATION",
    "INTRO_LINEUP",
    "TRUNCATED_TRANS",
}


def _issue(
    code: str,
    message: str,
    *,
    line_indices: list[int] | None = None,
    **details: Any,
) -> dict[str, Any]:
    result = {
        "code": code,
        "message": message,
        "line_indices": line_indices or [],
    }
    result.update(details)
    return result


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


_TITLE_ANCHOR_RE = re.compile(r"[一-龥々ー]{2,}|[A-Za-z][A-Za-z0-9_-]{3,}")
_GENERIC_TITLE_ANCHORS = {
    "ニュース", "発表", "公開", "対応", "問題", "影響", "最新", "情報", "動き",
    "news", "update", "updates", "announcement", "announces", "announced",
}


def _article_id_value(item: dict[str, Any]) -> Any:
    value = item.get("article_id")
    return item.get("id") if value is None else value


def _article_id_key(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, set, tuple)):
        return None
    return str(value)


def _news_article_blocks(lines: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """台本上の連続するnews行を記事ブロックとして集計する。"""
    blocks: dict[str, list[dict[str, Any]]] = {}
    current_key: str | None = None
    current_article_id: Any = None
    current_indices: list[int] = []

    def flush() -> None:
        nonlocal current_key, current_article_id, current_indices
        if current_key is not None and current_indices:
            blocks.setdefault(current_key, []).append(
                {
                    "article_id": current_article_id,
                    "line_indices": list(current_indices),
                }
            )
        current_key = None
        current_article_id = None
        current_indices = []

    for index, line in enumerate(lines):
        if line.get("section") != "news":
            flush()
            continue
        key = _article_id_key(line.get("article_id"))
        if key is None:
            flush()
            continue
        if current_key != key:
            flush()
            current_key = key
            current_article_id = line.get("article_id")
        current_indices.append(index)
    flush()
    return blocks


def _title_anchors(title: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", title or "").casefold()
    return {
        anchor
        for anchor in _TITLE_ANCHOR_RE.findall(normalized)
        if anchor not in _GENERIC_TITLE_ANCHORS
    }


def article_recurrence_issues(
    lines: list[dict[str, Any]], summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """記事の再登場を検出し、削除せずレビュー用の根拠として返す。

    This is a public module contract because the review phase uses the same
    detector for its diagnostic snapshot. ``final_validation.json`` remains
    the canonical result for the post-repair, synthesis-bound script.
    """
    blocks_by_key = _news_article_blocks(lines)
    if not blocks_by_key:
        return []

    article_values: dict[str, Any] = {
        key: blocks[0].get("article_id")
        for key, blocks in blocks_by_key.items()
        if blocks and blocks[0].get("article_id") is not None
    }
    evidence_by_key: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        article_id = _article_id_value(summary)
        key = _article_id_key(article_id)
        if key is None:
            continue
        article_values.setdefault(key, article_id)
        title = str(summary.get("title") or "").strip()
        if title:
            evidence_by_key[key] = {
                "article_id": article_id,
                "title": title,
                "category": summary.get("category"),
            }

    findings: list[dict[str, Any]] = []
    for key, blocks in blocks_by_key.items():
        if len(blocks) < 2:
            continue
        article_id = article_values.get(key, key)
        line_indices = [index for block in blocks for index in block["line_indices"]]
        findings.append(
            _issue(
                "ARTICLE_REUSED_IN_NEWS_BLOCKS",
                f"同一 article_id={article_id} が複数のnewsブロックで使われています。人間確認が必要です",
                line_indices=line_indices,
                article_ids=[article_id],
                evidence={
                    "block_count": len(blocks),
                    "blocks": blocks,
                    "title": evidence_by_key.get(key, {}).get("title", ""),
                },
                review_status="pending_human_review",
                auto_action="none",
            )
        )

    comparable = [
        (key, article_values.get(key, key), evidence_by_key[key])
        for key in blocks_by_key
        if key in evidence_by_key and evidence_by_key[key].get("title")
    ]
    for (left_key, left_id, left), (right_key, right_id, right) in combinations(comparable, 2):
        left_title = left["title"]
        right_title = right["title"]
        shared_anchors = sorted(_title_anchors(left_title) & _title_anchors(right_title))
        if titles_are_similar(left_title, right_title):
            detection_method = "title_similarity"
        elif shared_anchors:
            detection_method = "shared_title_anchor"
        else:
            continue
        line_indices = [
            index
            for key in (left_key, right_key)
            for block in blocks_by_key[key]
            for index in block["line_indices"]
        ]
        findings.append(
            _issue(
                "RELATED_TOPIC_REAPPEARANCE",
                f"異なるarticle_id={left_id},{right_id} に同一主体・近接主題の可能性があります。自動削除せず人間確認してください",
                line_indices=line_indices,
                article_ids=[left_id, right_id],
                evidence={
                    "detection_method": detection_method,
                    "shared_title_anchors": shared_anchors,
                    "titles": {str(left_id): left_title, str(right_id): right_title},
                    "review_reason": "同一主体・近接主題・矛盾の可能性をタイトル根拠で検出",
                },
                review_status="pending_human_review",
                auto_action="none",
            )
        )
    return findings


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
        if FAREWELL_RE.search(text):
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


def _outro_issues(
    lines: list[dict[str, Any]], *, commentary: bool = False,
) -> list[dict[str, Any]]:
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
    if commentary:
        # URL解説のoutroは「まとめ」1〜2行で、ラジオ本編の
        # 「振り返り・問い→別れの挨拶」契約とは異なる。
        return issues

    question_positions = [
        index for index, text in enumerate(texts) if text and _generate_is_question(text)
    ]
    if not question_positions:
        issues.append(_issue("OUTRO_QUESTION_MISSING", "outroに振り返り・問いがありません"))

    farewell_positions = [
        index for index, text in enumerate(texts) if text and FAREWELL_RE.search(text)
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
        if not FAREWELL_RE.search(texts[-1]):
            issues.append(
                _issue(
                    "OUTRO_NOT_TERMINATED",
                    "outroの最終行が別れの挨拶で終わっていません",
                    line_indices=[outro_indices[-1]],
                )
            )
        for index in range(first_farewell + 1, len(texts)):
            if not FAREWELL_RE.search(texts[index]):
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


def _lint_errors(
    lines: list[dict[str, Any]], *, program_name: str, commentary: bool,
    expected_discussion_article_id: Any = None,
) -> list[str]:
    errors = lint_script(
        lines,
        program_name=program_name,
        expected_discussion_article_id=expected_discussion_article_id,
    )
    if not commentary:
        return errors

    filtered: list[str] = []
    for error in errors:
        warn_match = re.search(r"\[WARN\]\[([^]]+)\]", error)
        code_match = re.search(r"\[([^]]+)\]", error)
        code = warn_match.group(1) if warn_match else (code_match.group(1) if code_match else "LINT")
        if code not in COMMENTARY_IGNORED_LINT_CODES:
            filtered.append(error)
    return filtered


def validate_final_script(
    lines: list[dict[str, Any]],
    *,
    summaries: list[dict[str, Any]] | None = None,
    program_name: str = "ニュースのとなり",
    style: str = "dialogue",
    expected_discussion_article_id: Any = None,
    prior_review_result: dict[str, Any] | None = None,
    commentary: bool = False,
) -> dict[str, Any]:
    """Validate the post-review script and return a synthesis decision.

    ``human_review`` is returned only when a critical issue remains after the
    deterministic, block-local repairs.  Warnings never block synthesis.
    """
    source_lines = [line for line in lines if isinstance(line, dict)]
    repaired_lines, repairs = _repair_outro_questions(source_lines)
    critical: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = list(repairs)

    repaired_lines, layout_repairs, layout_repair_issues = normalize_discussion_layout(
        repaired_lines,
        expected_discussion_article_id=expected_discussion_article_id,
    )
    repairs.extend(layout_repairs)
    warnings.extend(layout_repairs)
    critical.extend(layout_repair_issues)

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
        _lint_errors(
            repaired_lines,
            program_name=program_name,
            commentary=commentary,
            expected_discussion_article_id=expected_discussion_article_id,
        )
    )
    critical.extend(lint_critical)
    warnings.extend(lint_warnings)

    transition_issues = check_transition_integrity(repaired_lines)
    critical.extend(_issue("TRANSITION_INTEGRITY", message) for message in transition_issues)
    critical.extend(
        check_discussion_layout(
            repaired_lines,
            expected_discussion_article_id=expected_discussion_article_id,
        )
    )
    critical.extend(_outro_issues(repaired_lines, commentary=commentary))
    critical.extend(_transition_reaction_issues(repaired_lines, summaries or []))
    recurrence_issues = article_recurrence_issues(repaired_lines, summaries or [])
    # 再登場は根拠不足のまま記事を削除・書き換えしてはならないため、
    # synthesisを止めないレビュー警告として記録する。
    warnings.extend(recurrence_issues)

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
    # post_review_lint_issues は review.json で correction 直後の診断を保持し、
    # この関数では同じ台本へ再実行した lint の結果だけを判定に使う。
    # ここで再加算すると repair 前後の行番号差で重複した human_review 理由になる。

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
        "article_recurrence": {
            "status": "review_required" if recurrence_issues else "clear",
            "findings": recurrence_issues,
            "auto_action": "none",
        },
    }


def validate_final_script_file(
    script_path: str,
    *,
    summaries_path: str | None = None,
    output_dir: str | None = None,
    program_name: str = "ニュースのとなり",
    article: dict[str, Any] | None = None,
    commentary: bool = False,
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
    if not summaries and isinstance(article, dict):
        summaries = [dict(article)]

    result = validate_final_script(
        script.get("lines", []) if isinstance(script, dict) else [],
        summaries=summaries,
        program_name=program_name,
        style=str(script.get("style", "solo" if commentary else "dialogue")) if isinstance(script, dict) else ("solo" if commentary else "dialogue"),
        expected_discussion_article_id=(
            script.get("discussion_article_id")
            if isinstance(script, dict)
            else None
        ),
        commentary=commentary,
        prior_review_result=prior_review_result,
    )
    if isinstance(script, dict):
        for recorded_issue in script.get("discussion_layout_issues", []) or []:
            if not isinstance(recorded_issue, dict):
                continue
            result["critical_issues"].append(
                _issue(
                    str(recorded_issue.get("code", "DISCUSSION_LAYOUT")),
                    str(recorded_issue.get("message", "discussionの構造を保証できません")),
                )
            )
            result["can_synthesize"] = False
        if not result["can_synthesize"]:
            result["status"] = HUMAN_REVIEW_PHASE
    if result["repairs"]:
        repaired_script = dict(script)
        repaired_script["lines"] = result["lines"]
        path.write_text(json.dumps(repaired_script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_report(result, output_dir or str(path.parent))
    return result


def script_file_has_discussion_layout_issues(script_path: str) -> bool:
    """Return whether generation recorded an unrepairable discussion layout."""
    try:
        script = json.loads(Path(script_path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return False
    return isinstance(script, dict) and bool(script.get("discussion_layout_issues"))


def should_run_final_validation(script_path: str, review_result: dict[str, Any]) -> bool:
    """Return whether the final quality gate is needed for this script."""
    if script_file_has_discussion_layout_issues(script_path):
        return True
    if not isinstance(review_result, dict):
        return False
    if review_result.get("post_review_lint_issues"):
        return True
    if review_result.get("revised") and any(
        key in review_result
        for key in (
            "transition_integrity_issues",
            "question_response_issues",
            "dialogue_balance_issues",
        )
    ):
        return True
    return any(
        review_result.get(key)
        for key in (
            "transition_integrity_issues",
            "question_response_issues",
            "dialogue_balance_issues",
        )
    )


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
