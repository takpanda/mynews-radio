"""辞書表記の正規化（NFKC + 3桁区切りカンマ除去）のテスト。"""

import pytest

from app.services.text_normalization import (
    has_unsupported_comma,
    normalize_dictionary_surface,
    normalize_text_with_span_map,
)


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("1,000万人", "1000万人"),
        ("１，０００万人", "1000万人"),
        ("1000万人", "1000万人"),
        ("１０００万人", "1000万人"),
        ("12,345,678円", "12345678円"),
        ("1,000と2,000", "1000と2000"),
    ],
)
def test_normalize_removes_thousands_separator_comma(surface, expected):
    assert normalize_dictionary_surface(surface) == expected


@pytest.mark.parametrize(
    "surface",
    [
        "A,B",
        "1,23",
        ",1000万人",
        "1000万人,",
    ],
)
def test_normalize_keeps_unsupported_comma(surface):
    normalized = normalize_dictionary_surface(surface)
    assert "," in normalized
    assert has_unsupported_comma(normalized)


def test_normalize_without_comma_has_no_unsupported_comma():
    assert has_unsupported_comma(normalize_dictionary_surface("1000万人")) is False


class TestNormalizeTextWithSpanMap:
    """音声合成前の辞書照合で使う、正規化後の文字位置→元テキスト範囲のマッピングのテスト。"""

    def test_span_map_reconstructs_original_span_for_comma_number(self):
        text = "人口は1,000万人ほど"
        normalized, spans = normalize_text_with_span_map(text)
        assert normalized == "人口は1000万人ほど"

        # 正規化後の "1000万人" (index 3-9) が元テキストの "1,000万人" に対応すること
        start_norm = normalized.index("1000万人")
        end_norm = start_norm + len("1000万人")
        orig_start = spans[start_norm][0]
        orig_end = spans[end_norm - 1][1]
        assert text[orig_start:orig_end] == "1,000万人"

    def test_span_map_reconstructs_original_span_for_fullwidth_comma_number(self):
        text = "人口は１，０００万人ほど"
        normalized, spans = normalize_text_with_span_map(text)
        assert normalized == "人口は1000万人ほど"

        start_norm = normalized.index("1000万人")
        end_norm = start_norm + len("1000万人")
        orig_start = spans[start_norm][0]
        orig_end = spans[end_norm - 1][1]
        assert text[orig_start:orig_end] == "１，０００万人"

    def test_span_map_keeps_non_thousands_comma(self):
        text = "パターンはA,Bです"
        normalized, spans = normalize_text_with_span_map(text)
        assert normalized == text
        assert len(spans) == len(text)
