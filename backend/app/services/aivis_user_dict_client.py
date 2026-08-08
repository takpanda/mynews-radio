"""AIVIS Speech user dictionary API client."""

from typing import Any

import httpx

from app.services.text_normalization import normalize_dictionary_surface


def _to_katakana(reading: str) -> str:
    return reading.translate(
        {codepoint: codepoint + 0x60 for codepoint in range(ord("ぁ"), ord("ゖ") + 1)}
    )


class AivisUserDictClient:
    def __init__(self, base_url: str):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=20.0)

    def close(self) -> None:
        self._client.close()

    def list_words(self) -> list[dict[str, Any]]:
        response = self._client.get("/user_dict")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return [dict(value, uuid=key) for key, value in payload.items()]
        if not isinstance(payload, list):
            raise ValueError("invalid user dictionary response")
        return payload

    def add_word(self, surface: str, reading: str) -> str | None:
        response = self._client.post(
            "/user_dict_word",
            params={
                "surface": normalize_dictionary_surface(surface),
                "pronunciation": _to_katakana(reading),
                "accent_type": 0,
                "word_type": "PROPER_NOUN",
                "priority": 5,
            },
        )
        response.raise_for_status()
        value = response.json()
        return str(value) if value is not None else None

    def update_word(self, uuid: str, surface: str, reading: str) -> None:
        response = self._client.put(
            f"/user_dict_word/{uuid}",
            params={
                "surface": normalize_dictionary_surface(surface),
                "pronunciation": _to_katakana(reading),
                "accent_type": 0,
                "word_type": "PROPER_NOUN",
                "priority": 5,
            },
        )
        response.raise_for_status()
