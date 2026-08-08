from unittest.mock import Mock, patch

from app.services.aivis_user_dict_client import AivisUserDictClient


def test_add_word_sends_katakana_pronunciation_without_changing_other_values():
    response = Mock()
    response.json.return_value = "remote-1"
    with patch("app.services.aivis_user_dict_client.httpx.Client") as client_class:
        client = AivisUserDictClient("http://aivis.example")
        client.add_word("語", "すこし・ABCー")

    client_class.return_value.post.assert_called_once_with(
        "/user_dict_word",
        params={
            "surface": "語",
            "pronunciation": "スコシ・ABCー",
            "accent_type": 0,
            "word_type": "PROPER_NOUN",
            "priority": 5,
        },
    )


def test_update_word_sends_katakana_pronunciation():
    with patch("app.services.aivis_user_dict_client.httpx.Client") as client_class:
        client = AivisUserDictClient("http://aivis.example")
        client.update_word("remote-1", "語", "すこしカナー")

    client_class.return_value.put.assert_called_once_with(
        "/user_dict_word/remote-1",
        params={
            "surface": "語",
            "pronunciation": "スコシカナー",
            "accent_type": 0,
            "word_type": "PROPER_NOUN",
            "priority": 5,
        },
    )


def test_add_word_normalizes_thousands_separator_comma_before_sending():
    response = Mock()
    response.json.return_value = "remote-1"
    with patch("app.services.aivis_user_dict_client.httpx.Client") as client_class:
        client = AivisUserDictClient("http://aivis.example")
        client.add_word("1,000万人", "いっせんまんにん")

    client_class.return_value.post.assert_called_once_with(
        "/user_dict_word",
        params={
            "surface": "1000万人",
            "pronunciation": "イッセンマンニン",
            "accent_type": 0,
            "word_type": "PROPER_NOUN",
            "priority": 5,
        },
    )


def test_update_word_normalizes_fullwidth_comma_and_digits_before_sending():
    with patch("app.services.aivis_user_dict_client.httpx.Client") as client_class:
        client = AivisUserDictClient("http://aivis.example")
        client.update_word("remote-1", "１，０００万人", "いっせんまんにん")

    client_class.return_value.put.assert_called_once_with(
        "/user_dict_word/remote-1",
        params={
            "surface": "1000万人",
            "pronunciation": "イッセンマンニン",
            "accent_type": 0,
            "word_type": "PROPER_NOUN",
            "priority": 5,
        },
    )
