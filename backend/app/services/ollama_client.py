import json
import logging
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class OllamaClient:
    def __init__(self, base_url: str, model: str, max_retries: int = 2, timeout: float = 600.0):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._max_retries = max_retries
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=httpx.Timeout(self._timeout))
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
        # ornith 系モデルは format:json 指定時に response が空になり、
        # thinking フィールドにのみ出力が入る不具合があるためスキップする。
        # Qwen 系など他のモデルでは従来どおり format:json を送信する。
        is_qwen3_model = self._model.lower().startswith("qwen3")
        use_json_format = "ornith" not in self._model
        if is_qwen3_model:
            endpoint = "/api/chat"
            payload = {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": True,
                "format": "json",
            }
        else:
            endpoint = "/api/generate"
            payload = {
                "model": self._model,
                "prompt": prompt,
                "stream": False,
            }
            if use_json_format:
                payload["format"] = "json"

        options = payload.get("options", {})
        options["num_ctx"] = 65536
        payload["options"] = options

        for attempt in range(1, self._max_retries + 2):
            try:
                resp = self.client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if is_qwen3_model:
                    message = data.get("message", {})
                    if not isinstance(message, dict):
                        message = {}
                    raw = message.get("content", "")
                    thinking_raw = message.get("thinking", data.get("thinking", ""))
                else:
                    raw = data.get("response", "")
                    thinking_raw = data.get("thinking", "")

                logger.info(
                    "Ollama raw response (attempt=%d): response_len=%d, thinking_len=%d, "
                    "response_preview=%s, thinking_preview=%s",
                    attempt,
                    len(raw) if isinstance(raw, str) else -1,
                    len(thinking_raw) if isinstance(thinking_raw, str) else -1,
                    (raw[:120] if isinstance(raw, str) else repr(raw))[:120],
                    (thinking_raw[:120] if isinstance(thinking_raw, str) else repr(thinking_raw))[:120],
                )

                # response フィールドが文字列でない場合（Ollamaが直接dictを返す場合など）は変換
                if not isinstance(raw, str):
                    raw = ""
                content_is_empty = not raw

                # Qwen3.6+ reasoning models may put actual output in 'thinking' field
                # with <|channel|>thought / <|channel|>output tags
                if not raw:
                    if thinking_raw:
                        # Extract text from reasoning tags first
                        extracted = self._extract_output_from_reasoning(thinking_raw)
                        if extracted:
                            raw = extracted

                    if not raw:
                        # Retry once with a more explicit JSON prompt when response is empty
                        if attempt <= self._max_retries:
                            forced_json_prompt = (
                                "Answer with ONLY valid JSON (no markdown, no backticks, no extra text):\n"
                                + prompt
                            )
                            if is_qwen3_model:
                                payload["messages"][0]["content"] = forced_json_prompt
                            else:
                                payload["prompt"] = forced_json_prompt
                            logger.warning(
                                "Empty 'response' field detected, retrying with forced-json prompt (attempt=%d)",
                                attempt,
                            )
                            continue

                parsed = self._parse_json(raw)

                # {"thought": <non-dict>} のような思考アーティファクトは無視して thinking フィールドを優先する
                if parsed is not None and self._is_thinking_artifact(parsed):
                    logger.warning(
                        "Thinking artifact detected in response field (attempt=%d), discarding: keys=%s",
                        attempt,
                        list(parsed.keys()),
                    )
                    parsed = None
                    # アーティファクト検出後は thinking フィールドを優先、なければ強制 JSON でリトライ
                    if thinking_raw and (not is_qwen3_model or content_is_empty):
                        extracted = self._extract_output_from_reasoning(thinking_raw)
                        if extracted:
                            parsed = self._parse_json(extracted)
                            if parsed is not None:
                                return parsed
                    if attempt <= self._max_retries:
                        forced_json_prompt = (
                            "Answer with ONLY valid JSON (no markdown, no backticks, no extra text):\n"
                            + prompt
                        )
                        if is_qwen3_model:
                            payload["messages"][0]["content"] = forced_json_prompt
                        else:
                            payload["prompt"] = forced_json_prompt
                        logger.warning(
                            "Retrying after thinking artifact (attempt=%d)", attempt
                        )
                        continue

                # response が思考アーティファクトだった場合、thinking フィールドから抽出を試みる
                if parsed is None and thinking_raw and (not is_qwen3_model or content_is_empty):
                    extracted = self._extract_output_from_reasoning(thinking_raw)
                    if extracted:
                        parsed = self._parse_json(extracted)
                        if parsed is not None:
                            return parsed

                if parsed is not None:
                    return parsed

                # response フィールドに thinking タグが混入している場合も抽出を試みる
                if raw:
                    extracted = self._extract_output_from_reasoning(raw)
                    if extracted and extracted != raw:
                        parsed = self._parse_json(extracted)
                        if parsed is not None:
                            return parsed

                logger.error(
                    "Ollama response JSON parse failed (attempt=%d, raw_len=%d, raw_preview=%s)",
                    attempt,
                    len(raw),
                    raw[:200] if raw else "(empty)",
                )
            except Exception as exc:
                logger.error("Ollama request failed (attempt=%d): %s", attempt, exc)

        return None


    def _is_thinking_artifact(self, parsed: dict) -> bool:
        """{"thought": <非dict/非list>} のような思考プロセスのアーティファクトかどうかを判定する。"""
        if len(parsed) == 1 and "thought" in parsed:
            val = parsed["thought"]
            return not isinstance(val, (dict, list))
        return False

    def _extract_output_from_reasoning(self, text: str) -> str:
        """Qwen reasoning models output <|channel|>thought ... <|channel|>output ... <|channel|> tags.
        Extract only the content inside <|channel|>output (the actual answer)."""
        if not isinstance(text, str):
            return ""

        text = text.strip()

        # Pattern 1: <|channel|>output ... <|channel|>  (with pipe)
        match = re.search(r"<\|channel\|>output(.*?)<\|channel\|>", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Pattern 2: <|channel>output ... <|channel>  (without pipe)
        match = re.search(r"<\|channel>output(.*?)<\|channel>", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Pattern 3: <channel|> ... (pipe after channel — reversed format)
        match = re.search(r"<channel\|>(.*)", text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Fallback: try <content> tags
        start = text.find("<content>")
        end = text.rfind("</content>")
        if start != -1 and end != -1 and end > start:
            return text[start + len("<content>") : end].strip()

        # Last resort: return as-is for _parse_json to try
        return text

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

        # Qwen reasoning models use <|channel|>thought / <|channel|>output tags
        output_match = re.search(r"<\|channel\|>output(.*?)<\|channel\|>", thinking, re.DOTALL)
        if output_match:
            return output_match.group(1).strip()

        # Also try <|channel>output format (without pipe)
        output_match = re.search(r"<\|channel>output(.*?)<\|channel>", thinking, re.DOTALL)
        if output_match:
            return output_match.group(1).strip()

        # Fallback: look for <content> tags
        start = thinking.find("<content>")
        end = thinking.rfind("</content>")
        if start != -1 and end != -1 and end > start:
            thinking = thinking[start + len("<content>") : end]

        return thinking.strip()

    def _strip_markdown_code_block(self, text: str) -> str:
        """Remove ```json ... ``` or ``` ... ``` wrappers from text."""
        text = text.strip()
        # Match ```json\n...\n``` or ```\n...\n```
        match = re.search(r"^```(?:json)?\s*\n(.*?)\n```\s*$", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    def _parse_json(self, text: str) -> Optional[dict[str, Any]]:
        text = self._strip_markdown_code_block(text).strip()
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
            pass

        # Try fixing common JSON issues: trailing commas
        fixed = re.sub(r",\s*([}\]])", r"\1", text[start : end + 1])
        try:
            value = json.loads(fixed)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

        # テキスト途中に埋め込まれた ```json ブロックを抽出して試みる
        block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if block_match:
            candidate = block_match.group(1).strip()
            try:
                value = json.loads(candidate)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                c_start = candidate.find("{")
                c_end = candidate.rfind("}")
                if c_start != -1 and c_end != -1 and c_end > c_start:
                    try:
                        value = json.loads(candidate[c_start : c_end + 1])
                        if isinstance(value, dict):
                            return value
                    except json.JSONDecodeError:
                        pass

        return None

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()


class OpenAICompatibleClient:
    """LM Studio/vLLM の OpenAI互換APIアダプター。"""
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: float = 600.0):
        self._base_url, self._model, self._api_key, self._timeout = base_url.rstrip("/"), model, api_key, timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
            self._client = httpx.Client(base_url=self._base_url, timeout=httpx.Timeout(self._timeout), headers=headers)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self): return self
    def __exit__(self, *_args): self.close()

    def generate_json(self, prompt: str) -> Optional[dict[str, Any]]:
        try:
            response = self.client.post("/v1/chat/completions", json={"model": self._model,
                "messages": [{"role": "user", "content": prompt}], "temperature": 0,
                "response_format": {"type": "json_object"}})
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]
            content = message.get("content")
            if not content:
                content = message.get("reasoning_content") or message.get("reasoning") or message.get("thinking")
            if isinstance(content, dict):
                return content
            if isinstance(content, list):
                content = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content
                )
            if not isinstance(content, str):
                return None
            extracted = OllamaClient._extract_output_from_reasoning(OllamaClient, content)
            return json.loads(extracted)
        except Exception as exc:
            logger.error("OpenAI-compatible LLM request failed: %s", exc)
            return None


def create_llm_client(provider: str | None = None, model: str | None = None):
    from app.services.llm_provider import validate_provider_model
    config = validate_provider_model(provider, model)
    return OllamaClient(config.base_url, config.model) if config.native else OpenAICompatibleClient(config.base_url, config.model, config.api_key)
