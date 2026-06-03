import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, model: str, max_retries: int = 2):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_retries = max_retries
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=httpx.Timeout(120.0))
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def health_check(self) -> dict[str, str]:
        try:
            resp = self.client.get("/api/tags")
            resp.raise_for_status()
            return {"status": "ok"}
        except Exception as exc:
            logger.error("Ollama health check failed: %s", exc)
            return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    def generate_json(self, prompt: str) -> Optional[dict[str, Any]]:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        for attempt in range(1, self._max_retries + 2):
            try:
                resp = self.client.post("/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw = data.get("response", "")

                # Qwen3.6+ returns empty 'response' with JSON in 'thinking'
                if not raw:
                    thinking = data.get("thinking", "")
                    if thinking:
                        # Try extracting content between <content> tags first
                        thinking_stripped = str(thinking).strip()
                        start = thinking_stripped.find("<content>")
                        end = thinking_stripped.rfind("</content>")
                        if start != -1 and end != -1 and end > start:
                            raw = thinking_stripped[start + len("<content>"):end].strip()
                        else:
                            # Parse the thinking as-is
                            parsed = self._parse_json(thinking_stripped)
                            if parsed is not None:
                                return parsed
                    
                    # Retry once with a more explicit JSON prompt when response is empty
                    if attempt == 1:
                        payload["prompt"] = (
                            "Answer with ONLY valid JSON (no markdown, no backticks, no extra text):\n"
                            + prompt
                        )
                        logger.warning(
                            "Empty 'response' field detected, retrying with forced-json prompt (attempt=%d)",
                            attempt,
                        )
                        continue
                else:
                    # Normal case: response contains text, try to extract JSON
                    raw = self._extract_text_from_thinking(raw)

                parsed = self._parse_json(raw)
                if parsed is not None:
                    return parsed

                logger.error(
                    "Ollama response JSON parse failed (attempt=%d, response_head=%s)",
                    attempt,
                    raw[:200],
                )
            except Exception as exc:
                logger.error("Ollama request failed (attempt=%d): %s", attempt, exc)

        return None

    def _extract_text_from_thinking(self, thinking: Any) -> str:
        if thinking is None:
            return ""

        if isinstance(thinking, str):
            try:
                parsed = json.loads(thinking)
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = thinking

        if isinstance(parsed, dict):
            if parsed.get("thought") is not None:
                thinking = parsed.get("thought", "")
            else:
                # If the thinking payload itself is valid JSON output,
                # return it directly.
                return json.dumps(parsed, ensure_ascii=False)

        if not isinstance(thinking, str):
            return ""

        thinking = thinking.strip()
        start = thinking.find("<content>")
        end = thinking.rfind("</content>")
        if start != -1 and end != -1 and end > start:
            thinking = thinking[start + len("<content>") : end]

        return thinking.strip()

    def _parse_json(self, text: str) -> Optional[dict[str, Any]]:
        text = text.strip()
        if not text:
            return None

        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
            return None
        except json.JSONDecodeError:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            value = json.loads(text[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return None

        return None

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()
