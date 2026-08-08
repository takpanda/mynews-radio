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
