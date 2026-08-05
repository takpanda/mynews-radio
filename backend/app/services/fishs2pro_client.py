"""Fish S2 Pro TTS HTTP API client."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class FishS2ProClient:
    """Fish S2 Pro の1行合成APIとヘルスチェックを扱うクライアント。

    既存の TTS クライアントと同じく、合成メソッドは成功時 ``True``、
    通信・レスポンス・ファイル書き込み失敗時 ``False`` を返す。
    """

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(60.0),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def synthesize_line(
        self,
        text: str,
        speaker: str,
        output_path: str,
        delivery: str = "neutral",
    ) -> bool:
        """1行を合成し、audio/wavレスポンスを指定先へ保存する。"""
        if speaker not in {"male", "female"}:
            raise ValueError(f"不明なスピーカー種類: {speaker}")

        try:
            response = self.client.post(
                "/synthesize",
                json={"text": text, "speaker": speaker, "delivery": delivery},
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "audio/wav":
                logger.error(
                    "Fish S2 Pro synthesis returned unexpected Content-Type: %s",
                    content_type or "<missing>",
                )
                return False
            if not response.content:
                logger.error("Fish S2 Pro synthesis returned an empty response")
                return False

            with open(output_path, "wb") as output_file:
                output_file.write(response.content)
            logger.info(
                "Fish S2 Pro synthesis saved to %s (%d bytes)",
                output_path,
                len(response.content),
            )
            return True
        except httpx.HTTPError as exc:
            logger.error("Fish S2 Pro /synthesize failed (speaker=%s): %s", speaker, exc)
            return False
        except OSError as exc:
            logger.error("ファイル書き込み失敗 %s: %s", output_path, exc)
            return False

    def health_check(self) -> dict:
        """Fish S2 Pro の稼働状態と male/female 声の提供状態を確認する。"""
        try:
            response = self.client.get("/health")
            response.raise_for_status()
            data = response.json()
            voices = data.get("voices")
            if data.get("status") != "ok":
                return {"status": "error", "detail": "health status is not ok"}
            if not isinstance(voices, list) or not {"male", "female"}.issubset(voices):
                return {
                    "status": "error",
                    "detail": "health response does not provide male and female voices",
                }
            return {"status": "ok", "voices": voices}
        except (httpx.HTTPError, ValueError) as exc:
            logger.error("Fish S2 Pro /health failed: %s", exc)
            return {"status": "error", "detail": str(exc)}
        except Exception as exc:
            logger.error("Fish S2 Pro health response is invalid: %s", exc)
            return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    def __enter__(self) -> "FishS2ProClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()
