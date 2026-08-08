"""辞書表記の正規化（NFKC + 3桁区切りカンマ除去）のテスト。"""

import pytest

from app.services.text_normalization import has_unsupported_comma, normalize_dictionary_surface


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
