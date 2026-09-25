"""Profile-aware script checks shared by generation, review and final validation."""

from __future__ import annotations

import re
from typing import Any

from app.programs.profiles import ProgramProfile, validate_program_profile


class ScriptValidator:
    """Run profile-specific checks while retaining legacy checker adapters."""

    def __init__(self, profile: ProgramProfile):
        validate_program_profile(profile)
        self.profile = profile

    def validate_structure(self, lines: list[Any]) -> list[dict[str, Any]]:
        """Check allowed speakers, segment order and configured line bounds."""
        issues: list[dict[str, Any]] = []
        allowed = self.profile.speaker_keys
        section_to_segment = {segment.kind: segment for segment in self.profile.segments}
        segment_by_id = {segment.id: segment for segment in self.profile.segments}
        has_profile_segments = all(
            not isinstance(line, dict) or "segment" in line for line in lines
        )
        blocks: list[tuple[str, list[int]]] = []
        current_kind: str | None = None
        current_indices: list[int] = []
        primary_orders: list[int] = []

        for index, line in enumerate(lines):
            if not isinstance(line, dict):
                continue
            speaker = line.get("speaker")
            if speaker not in allowed:
                issues.append(self._issue(
                    "UNKNOWN_SPEAKER",
                    f"話者 {speaker!r} は番組「{self.profile.name}」に登録されていません",
                    [index],
                ))

            section = line.get("section")
            segment = (
                segment_by_id.get(line.get("segment"))
                if has_profile_segments
                else section_to_segment.get(section)
            )
            if has_profile_segments and segment is None:
                issues.append(self._issue(
                    "UNKNOWN_SEGMENT",
                    f"セグメント {line.get('segment')!r} は番組「{self.profile.name}」に定義されていません",
                    [index],
                ))
                continue
            if segment is not None and segment.kind != section:
                issues.append(self._issue(
                    "SEGMENT_SECTION_MISMATCH",
                    f"セグメント {segment.id!r} の種別は {segment.kind!r} ですが section は {section!r} です",
                    [index],
                ))
            if segment is None:
                continue
            if segment.speaker_keys and speaker not in segment.speaker_keys and speaker in allowed:
                issues.append(self._issue(
                    "SEGMENT_SPEAKER",
                    f"{segment.kind}セグメントに話者 {speaker!r} は指定されていません",
                    [index],
                ))
            if current_kind != segment.kind:
                if current_kind is not None:
                    blocks.append((current_kind, current_indices))
                current_kind, current_indices = segment.kind, []
            current_indices.append(index)
            if segment.kind != "transition":
                primary_orders.append(segment.order)

        if current_kind is not None:
            blocks.append((current_kind, current_indices))

        if has_profile_segments and primary_orders != sorted(primary_orders):
            indexes = [index for _, block_indices in blocks for index in block_indices]
            issues.append(self._issue(
                "SEGMENT_ORDER",
                f"番組「{self.profile.name}」のセグメント順序が定義と一致しません",
                indexes,
            ))

        if has_profile_segments and "transition" in section_to_segment:
            intro_indices = [
                i for i, line in enumerate(lines)
                if isinstance(line, dict) and line.get("section") == "intro"
            ]
            outro_indices = [
                i for i, line in enumerate(lines)
                if isinstance(line, dict) and line.get("section") == "outro"
            ]
            for kind, indexes in blocks:
                if kind != "transition":
                    continue
                if (
                    (intro_indices and indexes[0] < intro_indices[0])
                    or (outro_indices and indexes[-1] > outro_indices[0])
                ):
                    issues.append(self._issue(
                        "SEGMENT_ORDER",
                        f"番組「{self.profile.name}」のtransitionはintro後、outro前に配置してください",
                        indexes,
                    ))

        for segment in self.profile.segments if has_profile_segments else ():
            matching_blocks = [indices for kind, indices in blocks if kind == segment.kind]
            for indices in matching_blocks or [[]]:
                count = len(indices)
                if segment.min_lines <= count <= segment.max_lines:
                    continue
                issues.append(self._issue(
                    "SEGMENT_LINE_COUNT",
                    f"{segment.kind}セグメントが{count}行です（{segment.min_lines}〜{segment.max_lines}行である必要があります）",
                    indices,
                ))

        if len(self.profile.cast) == 1:
            issues.extend(self._solo_style_issues(lines))
        return issues

    def legacy_lint_issues(
        self, lines: list[Any], **legacy_options: Any,
    ) -> list[dict[str, Any]]:
        """Adapt the established string linter output to the structured issue shape."""
        from app.batch.generate_script import _lint_script_legacy

        legacy = _lint_script_legacy(
            lines,
            program_name=self.profile.name,
            **legacy_options,
        )
        issues = [self.from_legacy_message(message) for message in legacy]
        issues.extend(self.validate_structure(lines))
        return self._dedupe(issues)

    def validate(self, lines: list[Any], **legacy_options: Any) -> list[dict[str, Any]]:
        """Return machine-readable issues suitable for API and persisted reports."""
        return self.legacy_lint_issues(lines, **legacy_options)

    def lint_messages(self, lines: list[Any], **legacy_options: Any) -> list[str]:
        """Return the historic linter messages for generation retry prompts."""
        return [issue["message"] for issue in self.validate(lines, **legacy_options)]

    @staticmethod
    def from_legacy_message(message: str) -> dict[str, Any]:
        warn = re.search(r"\[WARN\]\[([^]]+)\]", message)
        code_match = re.search(r"\[([^]]+)\]", message)
        code = warn.group(1) if warn else (code_match.group(1) if code_match else "LINT")
        line_match = re.search(r"(?:行|行インデックス=)\s*(\d+)", message)
        return {
            "code": code,
            "message": message,
            "line_indices": [int(line_match.group(1))] if line_match else [],
            "severity": "warning" if warn or message.startswith("[WARN]") else "error",
        }

    def dialogue_issues(self, lines: list[dict[str, Any]]) -> list[str]:
        """Check question-heavy news blocks for profiles with multiple speakers."""
        if len(self.profile.cast) < 2:
            return []
        if self.profile.id == "radio_news_neighbor":
            from app.batch.review_script import check_dialogue_balance

            return check_dialogue_balance(lines)
        asker, responder = self.profile.cast[1], self.profile.cast[0]
        issues: list[str] = []
        blocks: list[list[tuple[int, dict[str, Any]]]] = []
        current: list[tuple[int, dict[str, Any]]] = []
        for index, line in enumerate(lines):
            if line.get("section") == "news":
                current.append((index, line))
            elif current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)

        from app.batch.review_script import _is_question

        for block in blocks:
            entries = [(index, line) for index, line in block if line.get("speaker") == asker.key]
            if entries and all(_is_question(str(line.get("text", ""))) for _, line in entries):
                indices = [index for index, _ in entries]
                issues.append(
                    f"[{asker.key.upper()}_QUESTION_ONLY] news行 {indices} の"
                    f"{asker.name or asker.role}発言が全て疑問文です。"
                    "感想・分析・別角度の提起など疑問文以外の発言を1行以上含めてください"
                )
            if len(block) >= 2 and len(entries) == 1:
                (question_index, question), (answer_index, answer) = block[-2:]
                if (
                    question.get("speaker") == asker.key
                    and _is_question(str(question.get("text", "")))
                    and answer.get("speaker") == responder.key
                ):
                    issues.append(
                        f"[QA_RELAY] news行 {question_index}〜{answer_index} が"
                        f"{asker.name or asker.role}の質問→{responder.name or responder.role}の回答"
                        "の1往復だけで終わっています。掛け合いを続けてください"
                    )
        return issues

    def _solo_style_issues(self, lines: list[Any]) -> list[dict[str, Any]]:
        conversational = re.compile(r"(?:でしょうか(?:ね)?|ですか[？?]?$|ですね[。！!]?$|ますね[。！!]?$)")
        issues = []
        for index, line in enumerate(lines):
            if not isinstance(line, dict):
                continue
            text = str(line.get("text", "") or "").strip()
            if text.endswith(("?", "？")) or conversational.search(text):
                issues.append(self._issue(
                    "SOLO_DIALOGUE_STYLE",
                    f"一人語りの行 {index} に自問や対話相手への相槌があります",
                    [index],
                ))
        return issues

    @staticmethod
    def _issue(code: str, message: str, line_indices: list[int]) -> dict[str, Any]:
        return {
            "code": code,
            "message": message,
            "line_indices": line_indices,
            "severity": "error",
        }

    @staticmethod
    def _dedupe(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        found: set[tuple[str, str, tuple[int, ...]]] = set()
        result = []
        for issue in issues:
            key = (issue["code"], issue["message"], tuple(issue["line_indices"]))
            if key not in found:
                found.add(key)
                result.append(issue)
        return result
