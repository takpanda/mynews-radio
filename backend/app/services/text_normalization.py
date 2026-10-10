"""AIVIS Engineへの送信表記・辞書同期の比較キーで共通利用する正規化処理。"""

import re
import unicodedata

# 数字の3桁区切りとして成立するカンマ（例: "1,000" "12,345,678"）だけにマッチする。
# 前後どちらかが数字でない区切り（"A,B" "1,23" 先頭/末尾のカンマ等）にはマッチしない。
_THOUSANDS_GROUP_PATTERN = re.compile(r"(?<!\d)\d{1,3}(?:,\d{3})+(?!\d)")


def normalize_dictionary_surface(surface: str) -> str:
    """辞書表記をNFKCで正規化し、3桁区切りとして成立するカンマだけを除去する。

    DBの保存値そのものは変更せず、AIVIS Engineへの送信表記と辞書同期時の
    比較キーの算出でのみ使用する。
    """
    normalized = unicodedata.normalize("NFKC", surface)
    return _THOUSANDS_GROUP_PATTERN.sub(lambda match: match.group(0).replace(",", ""), normalized)


def has_unsupported_comma(normalized_surface: str) -> bool:
    """正規化後もカンマが残っている場合、AIVIS Engineは登録を拒否する。"""
    return "," in normalized_surface


def normalize_text_with_span_map(text: str) -> tuple[str, list[tuple[int, int]]]:
    """辞書照合用に、正規化後の各文字が元テキストのどの範囲由来かを保持しながら正規化する。

    normalize_dictionary_surface と同じ規則（NFKC → 3桁区切りカンマ除去）を文章全体へ適用する。
    戻り値の spans[i] は、正規化後文字列の i 文字目が元テキストの text[start:end] に
    対応することを表す。正規化で除去されたカンマは、直前の数字の範囲に吸収される。
    """
    nfkc_chars: list[str] = []
    nfkc_spans: list[tuple[int, int]] = []
    for i, ch in enumerate(text):
        for out_ch in unicodedata.normalize("NFKC", ch):
            nfkc_chars.append(out_ch)
            nfkc_spans.append((i, i + 1))
    nfkc_text = "".join(nfkc_chars)

    removed_comma_positions = {
        j
        for match in _THOUSANDS_GROUP_PATTERN.finditer(nfkc_text)
        for j in range(match.start(), match.end())
        if nfkc_text[j] == ","
    }

    normalized_chars: list[str] = []
    normalized_spans: list[tuple[int, int]] = []
    for j, ch in enumerate(nfkc_text):
        if j in removed_comma_positions:
            continue
        normalized_chars.append(ch)
        normalized_spans.append(nfkc_spans[j])

    return "".join(normalized_chars), normalized_spans
