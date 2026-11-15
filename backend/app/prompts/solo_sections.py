"""単一話者（solo）専用の指示を SOLO_ONLY マーカーで区切る。

区切りの正は管理者が付けたマーカーである。既存のマーカーは削除・付け替えせず、
dialogue に使う前に次の2点を確認する。

- マーカーの対応が正しい（開始・終了が交互に並び、入れ子や逆順がない）
- マーカーの外の行に、solo 専用と分かる指示が残っていない

旧版（マーカーなし）には、既定の区間の位置を文言で特定して、不足分だけマーカーを挿入する。
特定できない場合は版を変更せず、dialogue では停止して、マーカーで囲むよう案内する。
"""

from __future__ import annotations

import re

SOLO_OPEN = "<!-- SOLO_ONLY -->"
SOLO_CLOSE = "<!-- END_SOLO_ONLY -->"
_MARKER_RE = re.compile(r"<!-- (?:END_)?SOLO_ONLY -->")

# 旧版の行内マーカー（レビューの solo 行）。SOLO_ONLY と同じ意味として改名して扱う。
_LEGACY_INLINE_OPEN = "<!-- solo -->"
_LEGACY_INLINE_CLOSE = "<!-- END_SOLO -->"

# 旧版の既定の区間。(モード, 開始パターン, 終了パターン)。
# "line" は行単位、"inline" は行内の断片。終了は開始より後で検索する。None は開始と同じ範囲。
_DEFAULT_BLOCKS = {
    "generate_commentary_script": (
        ("line", re.compile(r"## スタイル=solo（一人解説）の場合\n"),
         re.compile(r"各 news ラインには最低1件以上の具体的な事実・数字を含める\n")),
        ("line", re.compile(r"\*\*solo の場合（基本フォーマット）\*\*:\n"),
         re.compile(r"\}\}\n(?=(?:<!-- END_SOLO_ONLY -->\n)?\n<!-- DIALOGUE_ONLY -->)")),
        ("line", re.compile(r'- solo ?の場合: speaker は "\{mc_gender\}" のみ\n'), None),
    ),
    "review_synthesize": (
        ("line", re.compile(r"## solo モードのMCについて\n"),
         re.compile(r"元の台本に含まれる数値・金額・日時・固有名詞をぼかさず元の値をそのまま使う\n")),
        ("inline", re.compile(r"3\. 一人解説の語り口・トーン・スタイルを維持する"), None),
        ("line", re.compile(r"## 出力例（solo モード）\n"),
         re.compile(r"\}\}\n(?=(?:<!-- END_SOLO_ONLY -->\n)?\n## 共通条件)")),
        ("line", re.compile(r"## solo モードの条件\n"),
         re.compile(r"- section は intro/news/outro のいずれか\n?(?=(?:<!-- END_SOLO_ONLY -->\n)?\Z)")),
    ),
}

# マーカーの外に残っていると dialogue に混入する、solo 専用と分かる表現。
_SOLO_SIGNATURES = {
    "generate_commentary_script": ("1名のみ", "一人語り", "スタイル=solo", "solo の場合", "soloの場合", '"{mc_gender}"'),
    "review_synthesize": ('"{mc_gender}"', "1名（{mc_gender}）", "一人解説の語り口", "solo モード"),
}


class SoloSectionsUnmarkedError(ValueError):
    """solo 専用の指示が区切られていないテンプレートを dialogue で使おうとした場合のエラー。"""


def unwrap_solo_only_markers(text: str) -> str:
    """マーカーを外し、本文と改行を保つ。行単独のマーカーは行ごと除く。"""
    text = re.sub(r"(?m)^<!-- (?:END_)?SOLO_ONLY -->\n", "", text)
    return _MARKER_RE.sub("", text)


def strip_solo_only_sections(text: str) -> str:
    """dialogue 用に solo 区間を除去する。事前に require_dialogue_safe で対応を確認すること。"""
    text = re.sub(r"(?s)(?m)^<!-- SOLO_ONLY -->\n.*?<!-- END_SOLO_ONLY -->\n", "", text)
    return re.sub(r"(?s)<!-- SOLO_ONLY -->.*?<!-- END_SOLO_ONLY -->", "", text)


def _marker_pairs(text: str) -> list[tuple[int, int]] | None:
    """マーカーの対応を (開始位置, 終了位置) の一覧で返す。交互に並ばない場合は None。"""
    pairs = []
    open_at = None
    for match in _MARKER_RE.finditer(text):
        if match.group(0) == SOLO_OPEN:
            if open_at is not None:
                return None
            open_at = match.start()
        else:
            if open_at is None:
                return None
            pairs.append((open_at, match.end()))
            open_at = None
    return None if open_at is not None else pairs


def _default_spans(text: str, key: str) -> list[tuple[int, int, str]] | None:
    """既定の区間を文言で特定する。どれか一つでも一意に特定できなければ None。"""
    spans = []
    for mode, start_re, end_re in _DEFAULT_BLOCKS[key]:
        found = list(start_re.finditer(text))
        if len(found) != 1:
            return None
        start = found[0].start()
        if end_re is None:
            end = found[0].end()
        else:
            end_match = end_re.search(text, found[0].end())
            if end_match is None:
                return None
            end = end_match.end()
        spans.append((start, end, mode))
    return sorted(spans)


def _covered_by(span: tuple[int, int, str], pairs: list[tuple[int, int]]) -> bool | None:
    """区間がマーカーの組に完全に含まれれば True、どの組とも重ならなければ False、中途半端なら None。"""
    start, end, _ = span
    for open_at, close_at in pairs:
        if open_at <= start and end <= close_at:
            return True
    for open_at, close_at in pairs:
        if start < close_at and open_at < end:
            return None
    return False


def migrate_legacy_solo_markers(text: str, key: str) -> str | None:
    """旧版に既定の区間のマーカーを挿入する。既存マーカーは変更しない。

    既に全区間が囲まれていれば同じ文字列を返す。区間を特定できない、またはマーカーの対応が
    不正な場合は None を返し、版は変更しない。
    """
    if _LEGACY_INLINE_OPEN in text or _LEGACY_INLINE_CLOSE in text:
        if text.count(_LEGACY_INLINE_OPEN) != 1 or text.count(_LEGACY_INLINE_CLOSE) != 1:
            return None
        text = text.replace(_LEGACY_INLINE_OPEN, SOLO_OPEN).replace(_LEGACY_INLINE_CLOSE, SOLO_CLOSE)

    pairs = _marker_pairs(text)
    spans = _default_spans(text, key)
    if pairs is None or spans is None:
        return None

    missing = []
    for span in spans:
        covered = _covered_by(span, pairs)
        if covered is None:
            return None
        if not covered:
            missing.append(span)
    if not missing:
        return text

    # 元の文字列の位置で挿入位置を決め、挿入後に同じ区間が囲まれていることを確認する。
    insertions = []
    for start, end, mode in missing:
        if mode == "line":
            insertions.append((start, SOLO_OPEN + "\n"))
            insertions.append((end, SOLO_CLOSE + "\n"))
        else:
            insertions.append((start, SOLO_OPEN))
            insertions.append((end, SOLO_CLOSE))
    result = []
    cursor = 0
    for position, marker in sorted(insertions, key=lambda item: item[0]):
        result.append(text[cursor:position])
        result.append(marker)
        cursor = position
    result.append(text[cursor:])
    new_text = "".join(result)

    if unwrap_solo_only_markers(new_text) != unwrap_solo_only_markers(text):
        return None
    new_pairs = _marker_pairs(new_text)
    if new_pairs is None:
        return None
    for start, end, _ in spans:
        shifted = (
            start + sum(len(marker) for position, marker in insertions if position <= start),
            end + sum(len(marker) for position, marker in insertions if position < end),
            "",
        )
        if _covered_by(shifted, new_pairs) is not True:
            return None
    return new_text


def require_dialogue_safe(text: str, key: str) -> None:
    """dialogue で使うテンプレートに、区切られていない solo 専用の指示がないことを確認する。

    判定は文字単位。solo 専用の表現の全体がいずれかのマーカー組の内側に収まらなければ、
    同じ行にマーカーがあっても外側とみなす。
    """
    pairs = _marker_pairs(text)
    if pairs is None:
        raise SoloSectionsUnmarkedError(
            f"prompt template {key!r}: SOLO_ONLY markers are unbalanced (nested, reversed, or unclosed). "
            "Fix the markers so each solo section is opened once and closed once, then retry."
        )

    leaked_lines = {}
    for signature in _SOLO_SIGNATURES[key]:
        for match in re.finditer(re.escape(signature), text):
            inside = any(open_at <= match.start() and match.end() <= close_at for open_at, close_at in pairs)
            if not inside:
                line_no = text.count("\n", 0, match.start()) + 1
                leaked_lines[line_no] = text.splitlines()[line_no - 1].strip()
    if leaked_lines:
        listing = "\n".join(f"  行 {line_no}: {line}" for line_no, line in sorted(leaked_lines.items()))
        raise SoloSectionsUnmarkedError(
            f"prompt template {key!r}: solo-only instructions are not fully enclosed by markers, "
            "so dialogue would receive them. Wrap each solo section (including its output example) "
            "with <!-- SOLO_ONLY --> and <!-- END_SOLO_ONLY --> on lines of their own, "
            "then retry. Lines found:\n" + listing
        )
