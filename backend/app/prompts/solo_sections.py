"""単一話者（solo）専用の指示区間を SOLO_ONLY マーカーで扱う。

区間は「開始」と「終了」のパターンで一意に特定する。マーカーの有無や順序に依存せず、
マーカーを外した本文から区間を特定し直すため、部分的・逆順・入れ子の版も同じ結果に正規化される。
区間を一意に特定できない本文は、dialogue 生成・レビューで使わないよう拒否する。
"""

from __future__ import annotations

import re

SOLO_OPEN = "<!-- SOLO_ONLY -->"
SOLO_CLOSE = "<!-- END_SOLO_ONLY -->"

# 旧版の行内マーカー（レビューの solo 行）。改名して SOLO_ONLY として扱う。
_LEGACY_INLINE_OPEN = "<!-- solo -->"
_LEGACY_INLINE_CLOSE = "<!-- END_SOLO -->"

# (モード, 開始パターン, 終了パターン)。"line" は行単位、"inline" は行内の断片。
# 終了パターンは開始位置より後で検索する。None は開始パターンと同じ範囲だけを区間にする。
_SOLO_BLOCKS = {
    "generate_commentary_script": (
        ("line", re.compile(r"## スタイル=solo（一人解説）の場合\n"),
         re.compile(r"各 news ラインには最低1件以上の具体的な事実・数字を含める\n")),
        ("line", re.compile(r"\*\*solo の場合（基本フォーマット）\*\*:\n"),
         re.compile(r"\}\}\n(?=\n<!-- DIALOGUE_ONLY -->)")),
        ("line", re.compile(r'- solo ?の場合: speaker は "[^"\n]*" のみ\n'), None),
    ),
    "review_synthesize": (
        ("line", re.compile(r"## solo モードのMCについて\n"),
         re.compile(r"元の台本に含まれる数値・金額・日時・固有名詞をぼかさず元の値をそのまま使う\n")),
        ("inline", re.compile(r"3\. 一人解説の語り口・トーン・スタイルを維持する"), None),
        ("line", re.compile(r"## 出力例（solo モード）\n"),
         re.compile(r"\}\}\n(?=\n## 共通条件)")),
        ("line", re.compile(r"## solo モードの条件\n"),
         re.compile(r"- section は intro/news/outro のいずれか\n?\Z")),
    ),
}


class SoloSectionsUnmarkedError(ValueError):
    """solo 専用の指示区間を特定できないプロンプトを dialogue で使おうとした場合のエラー。"""


def unwrap_solo_only_markers(text: str) -> str:
    """マーカーを外し、本文と改行を保つ。行単独のマーカーは行ごと除く。"""
    text = re.sub(r"(?m)^<!-- (?:END_)?SOLO_ONLY -->\n", "", text)
    return re.sub(r"<!-- (?:END_)?SOLO_ONLY -->", "", text)


def strip_solo_only_sections(text: str) -> str:
    """dialogue 用に solo 区間を除去する。行単独の区間は改行ごと、行内の区間は前後の行を残す。"""
    text = re.sub(r"(?s)(?m)^<!-- SOLO_ONLY -->\n.*?<!-- END_SOLO_ONLY -->\n", "", text)
    return re.sub(r"(?s)<!-- SOLO_ONLY -->.*?<!-- END_SOLO_ONLY -->", "", text)


def _mark_sections(text: str, key: str) -> str | None:
    """マーカーのない本文に区間を付ける。区間を一意に特定できなければ None。"""
    spans = []
    for mode, start_re, end_re in _SOLO_BLOCKS[key]:
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

    spans.sort()
    for (_, prev_end, _), (next_start, _, _) in zip(spans, spans[1:]):
        if next_start < prev_end:
            return None

    # 後ろの区間から挿入し、前の区間の位置を崩さない。
    for start, end, mode in reversed(spans):
        if mode == "line":
            text = text[:end] + SOLO_CLOSE + "\n" + text[end:]
            text = text[:start] + SOLO_OPEN + "\n" + text[start:]
        else:
            text = text[:end] + SOLO_CLOSE + text[end:]
            text = text[:start] + SOLO_OPEN + text[start:]
    return text


def canonical_solo_marking(text: str, key: str) -> str | None:
    """本文を、区間の正しいマーカー付けの正規形に変換する。区間を特定できなければ None。

    既に正しく付いた本文は変わらない（冪等）。部分的・逆順・入れ子の本文も、
    マーカーを外してから付け直すため正規形になる。区間の文言を編集した本文は None になる。
    """
    if _LEGACY_INLINE_OPEN in text or _LEGACY_INLINE_CLOSE in text:
        if text.count(_LEGACY_INLINE_OPEN) != 1 or text.count(_LEGACY_INLINE_CLOSE) != 1:
            return None
        text = text.replace(_LEGACY_INLINE_OPEN, SOLO_OPEN).replace(_LEGACY_INLINE_CLOSE, SOLO_CLOSE)
    return _mark_sections(unwrap_solo_only_markers(text), key)


def require_canonical_solo_marking(text: str, key: str) -> None:
    """dialogue で使うテンプレートの solo 区間が正しく区切られていることを要求する。"""
    if canonical_solo_marking(text, key) != text:
        raise SoloSectionsUnmarkedError(
            f"prompt template {key!r} has solo-only sections that cannot be identified; "
            "refusing to use it for dialogue. Restore the default template or re-mark the solo sections."
        )
