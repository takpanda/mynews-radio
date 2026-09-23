"""Client for the ChatGPT Codex OAuth Responses API."""

from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, Optional

import httpx

from app.services.llm_call_log_service import record_llm_call
from app.services.codex_token_store import CodexTokenStore

logger = logging.getLogger(__name__)

CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_REFRESH_SKEW_SECONDS = 120
JSON_INSTRUCTION = "Return only valid JSON. Do not use Markdown code fences or add any explanation."


def _record_llm_call(*args, **kwargs) -> None:
    """ログ保存障害を生成処理へ伝播させない。"""
    try:
        record_llm_call(*args, **kwargs)
    except Exception:
        logger.warning("LLM call log write failed (ignored)")


def _jwt_claims(token: str) -> dict[str, Any]:
    """JWT payloadを署名検証なしで読む（expとアカウントIDの参照専用）。"""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


class CodexClient:
    """ChatGPT Plus/Pro の Codex OAuth を使う Responses API クライアント。

    OAuth token pairは共有storeから読み込み、refresh後は原子的にstoreへ保存する。
    APIとcronは同じ``/app/data`` volume上のstoreを参照する。
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        access_token: str,
        refresh_token: str,
        timeout: float = 600.0,
        token_store_path: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._access_token = access_token.strip()
        self._refresh_token = refresh_token.strip()
        self._timeout = timeout
        self._provider = "codex"
        self._client: Optional[httpx.Client] = None
        self._refresh_lock = threading.Lock()
        self._token_store = CodexTokenStore(token_store_path) if token_store_path else None
        self._load_canonical_tokens()

    def _load_canonical_tokens(self) -> None:
        if self._token_store is None:
            return
        try:
            tokens = self._token_store.load_or_initialize(self._access_token, self._refresh_token)
        except Exception:
            logger.warning("Codex token store could not be read")
            return
        if tokens:
            self._set_tokens(tokens["access_token"], tokens["refresh_token"])

    def _adopt_canonical_tokens(self) -> None:
        if self._token_store is None:
            return
        try:
            tokens = self._token_store.read()
        except Exception:
            logger.warning("Codex token store could not be read")
            return
        if tokens and (
            tokens["access_token"] != self._access_token
            or tokens["refresh_token"] != self._refresh_token
        ):
            self._set_tokens(tokens["access_token"], tokens["refresh_token"])

    def _set_tokens(self, access_token: str, refresh_token: str) -> None:
        self._access_token = access_token.strip()
        self._refresh_token = refresh_token.strip()
        self._sync_request_headers()

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                headers=self._request_headers(),
            )
        return self._client

    def _request_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "mynews-radio",
            "originator": "mynews-radio",
        }
        auth_claims = _jwt_claims(self._access_token).get("https://api.openai.com/auth", {})
        if isinstance(auth_claims, dict) and auth_claims.get("chatgpt_account_id"):
            headers["ChatGPT-Account-ID"] = str(auth_claims["chatgpt_account_id"])
        return headers

    def _sync_request_headers(self) -> None:
        if self._client is not None:
            self._client.headers.clear()
            self._client.headers.update(self._request_headers())

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "CodexClient":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _token_is_expiring(self) -> bool:
        exp = _jwt_claims(self._access_token).get("exp")
        return isinstance(exp, (int, float)) and exp <= time.time() + CODEX_REFRESH_SKEW_SECONDS

    def _refresh_access_token(self) -> bool:
        """OAuth refreshを行い、rotationされたrefresh_tokenも同時に更新する。"""
        if not self._refresh_token:
            return False
        with self._refresh_lock:
            try:
                if self._token_store is not None:
                    with self._token_store.locked() as stored:
                        # Another process may have rotated the pair while this
                        # client was alive. Adopt it instead of replaying the
                        # now-invalid refresh token.
                        if stored and (
                            stored["access_token"] != self._access_token
                            or stored["refresh_token"] != self._refresh_token
                        ):
                            self._set_tokens(stored["access_token"], stored["refresh_token"])
                            return True
                        return self._refresh_and_persist_unlocked()
                return self._refresh_and_persist_unlocked()
            except Exception:
                # 認証情報やレスポンス本文を例外メッセージへ出さない。
                logger.warning("Codex OAuth refresh failed")
                return False

    def _refresh_and_persist_unlocked(self) -> bool:
        with httpx.Client(timeout=httpx.Timeout(self._timeout)) as refresh_client:
            response = refresh_client.post(
                CODEX_OAUTH_TOKEN_URL,
                headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                },
            )
        if response.status_code != 200:
            logger.warning("Codex OAuth refresh failed (status=%d)", response.status_code)
            return False
        payload = response.json()
        next_access = payload.get("access_token") if isinstance(payload, dict) else None
        if not isinstance(next_access, str) or not next_access.strip():
            logger.warning("Codex OAuth refresh returned no access token")
            return False
        next_refresh = payload.get("refresh_token") if isinstance(payload, dict) else None
        next_refresh = next_refresh.strip() if isinstance(next_refresh, str) and next_refresh.strip() else self._refresh_token
        self._set_tokens(next_access, next_refresh)
        if self._token_store is not None:
            self._token_store.write_unlocked(self._access_token, self._refresh_token)
        return True

    @staticmethod
    def _response_text(data: Any) -> str:
        chunks: list[str] = []
        output = data.get("output", []) if isinstance(data, dict) else []
        if isinstance(output, list):
            for item in output:
                content = item.get("content", []) if isinstance(item, dict) else []
                if not isinstance(content, list):
                    continue
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
        if chunks:
            return "".join(chunks)
        # Hosted Responses implementations may expose the same text as a convenience field.
        return data.get("output_text", "") if isinstance(data, dict) and isinstance(data.get("output_text"), str) else ""

    def generate_json(self, prompt: str) -> Optional[dict[str, Any]]:
        started = time.monotonic()
        self._adopt_canonical_tokens()
        if not self._access_token:
            logger.error("Codex request skipped because credentials are not configured")
            _record_llm_call(self, attempt=1, status="error", prompt_text=prompt, latency_ms=0)
            return None

        if self._token_is_expiring():
            self._refresh_access_token()

        payload = {
            "model": self._model,
            "instructions": JSON_INSTRUCTION,
            "input": f"{prompt}\n\n{JSON_INSTRUCTION}",
            "store": False,
        }
        attempt = 1
        try:
            response = self.client.post("/responses", json=payload)
            if response.status_code == 401:
                _record_llm_call(
                    self,
                    attempt=1,
                    status="retry",
                    prompt_text=prompt,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                if not self._refresh_access_token():
                    _record_llm_call(self, attempt=2, status="error", prompt_text=prompt,
                                     latency_ms=int((time.monotonic() - started) * 1000))
                    return None
                attempt = 2
                response = self.client.post("/responses", json=payload)
            if response.status_code >= 400:
                _record_llm_call(self, attempt=attempt, status="error",
                                 prompt_text=prompt, latency_ms=int((time.monotonic() - started) * 1000))
                return None

            raw = self._response_text(response.json())
            from app.services.ollama_client import OllamaClient

            # 既存クライアントのJSON抽出・パース規則（コードフェンス、埋め込みJSON、
            # trailing comma）を共有する。パーサー生成だけでHTTP接続は発生しない。
            parser = OllamaClient("", "")
            parsed = parser._parse_json(parser._extract_output_from_reasoning(raw))
            if parsed is None:
                _record_llm_call(
                    self, attempt=attempt,
                    status="json_parse_failed", prompt_text=prompt, response_text=raw,
                    latency_ms=int((time.monotonic() - started) * 1000),
                )
                return None
            _record_llm_call(
                self, attempt=attempt,
                status="success", prompt_text=prompt, response_text=raw,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return parsed
        except Exception:
            # トークン・レスポンス本文・URLをログへ出さず、既存生成フローへはNoneで返す。
            logger.error("Codex Responses request failed")
            _record_llm_call(
                self, attempt=1, status="error", prompt_text=prompt,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
            return None
