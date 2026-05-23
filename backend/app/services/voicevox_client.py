import logging
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)


class VoicevoxClient:
    """VOICEVOX Engineとの通信を扱うクライアント"""

    def __init__(self, base_url: str, speaker_male: int = 0, speaker_female: int = 1):
        self._base_url = base_url.rstrip("/")
        self.speaker_male = speaker_male
        self.speaker_female = speaker_female
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=httpx.Timeout(60.0))
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- speaker mapping --

    def get_speaker_id(self, speaker: str) -> int:
        """speaker名話者IDを返す"""
        if speaker == "male":
            return self.speaker_male
        elif speaker == "female":
            return self.speaker_female
        raise ValueError(f"不明なスピーカー種類: {speaker}")

    # -- VOICEVOX API 2-steps: audio_query -> synthesis --

    def get_audio_query(self, text: str, speaker_id: int) -> Optional[str]:
        """
        POST /audio_query — audio queryをJSON文字列として取得する。
        failureの場合、None を返す。
        
        VOICEVOX API: POST with query params (text, speaker)
        """
        try:
            resp = self.client.post(
                "/audio_query",
                params={
                    "text": text,
                    "speaker": speaker_id,
                    "enable_katakana_english": 1,
                },
            )
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError as exc:
            logger.error(
                "/audio_query failed for speaker %d: %s", speaker_id, exc
            )
            return None

    def synthesize(
        self, audio_query: str, speaker_id: int, output_path: str
    ) -> bool:
        """
        POST /synthesis — WAV bytes をファイルに保存する。
        
        VOICEVOX API: POST with query param (speaker) and JSON body (query)
        """
        try:
            resp = self.client.post(
                "/synthesis",
                params={
                    "speaker": speaker_id,
                    "enable_interrogative_upspeak": 1,
                },
                content=audio_query,
                headers={"content-type": "application/json"},
            )
            resp.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(resp.content)

            logger.info("synthesis saved to %s (%d bytes)", output_path, len(resp.content))
            return True

        except httpx.HTTPError as exc:
            logger.error(
                "/synthesis failed for speaker %d: %s", speaker_id, exc
            )
            return False
        except OSError as exc:
            logger.error("ファイル書き込み失敗 %s: %s", output_path, exc)
            return False

    def synthesize_line(
        self, text: str, speaker: str, output_path: str
    ) -> bool:
        """セリフ1行を、audio_query → synthesis の2ステップでWAV生成する"""
        speaker_id = self.get_speaker_id(speaker)

        audio_query = self.get_audio_query(text, speaker_id)
        if audio_query is None:
            logger.error(
                "audio_query 失敗 (speaker=%d, text='%s')", speaker_id, text[:50]
            )
            return False

        return self.synthesize(audio_query, speaker_id, output_path)

    def health_check(self) -> Dict[str, str]:
        """VOICEVOX Engineの起動状態を確認する"""
        try:
            resp = self.client.get("/version")
            if resp.status_code == 200:
                version = resp.text.strip()
                return {"status": "ok", "version": version}
            else:
                return {
                    "status": "error",
                    "detail": f"expected 200, status_code={resp.status_code}",
                }
        except httpx.ConnectError as exc:
            logger.error("VOICEVOX Engine接続不可 (VOICEVOX_BASE_URL=%s): %s", self._base_url, exc)
            return {"status": "error", "detail": str(exc)}
        except Exception as exc:
            return {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        self.close()
