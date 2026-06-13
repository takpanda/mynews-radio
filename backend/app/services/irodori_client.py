import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class IrodoriClient:
    """Irodori-TTS-Server (OpenAI互換API) との通信を扱うクライアント。

    Irodori-TTS-Server: https://github.com/Aratako/Irodori-TTS-Server
    エンドポイント: POST /v1/audio/speech
    """

    def __init__(
        self,
        base_url: str,
        voice_male: str = "male",
        voice_female: str = "female",
        caption_male: str = "",
        caption_female: str = "",
        num_steps: int = 40,
        cfg_scale_text: float = 3.0,
        cfg_scale_speaker: float = 5.0,
        duration_scale: float = 1.0,
        model: str = "irodori-tts",
        response_format: str = "wav",
    ):
        self._base_url = base_url.rstrip("/")
        self.voice_male = voice_male
        self.voice_female = voice_female
        self.caption_male = caption_male
        self.caption_female = caption_female
        self.num_steps = num_steps
        self.cfg_scale_text = cfg_scale_text
        self.cfg_scale_speaker = cfg_scale_speaker
        self.duration_scale = duration_scale
        self._model = model
        self._response_format = response_format
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self._base_url,
                timeout=httpx.Timeout(120.0),
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "IrodoriClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def get_voice_id(self, speaker: str) -> str:
        """speaker名 ("male" / "female") を Irodori-TTS のボイスIDに変換する。"""
        if speaker == "male":
            return self.voice_male
        elif speaker == "female":
            return self.voice_female
        raise ValueError(f"不明なスピーカー種類: {speaker}")

    def get_caption(self, speaker: str) -> str:
        """speaker名 ("male" / "female") に対応するキャプションを返す。"""
        if speaker == "male":
            return self.caption_male
        elif speaker == "female":
            return self.caption_female
        raise ValueError(f"不明なスピーカー種類: {speaker}")

    def synthesize_line(self, text: str, speaker: str, output_path: str) -> bool:
        """テキスト1行を音声合成して WAV ファイルに保存する。

        POST /v1/audio/speech を呼び出し、レスポンスのバイト列をファイルに書き込む。

        Args:
            text: 合成するテキスト
            speaker: "male" または "female"
            output_path: 出力 WAV ファイルのパス

        Returns:
            成功した場合 True、失敗した場合 False
        """
        voice_id = self.get_voice_id(speaker)
        payload: dict = {
            "model": self._model,
            "input": text,
            "voice": "none",
            "response_format": self._response_format,
        }

        # --caption / 推論パラメータを irodori オブジェクトとして追加
        irodori: dict = {
            "num_steps": self.num_steps,
            "cfg_scale_text": self.cfg_scale_text,
            "cfg_scale_speaker": self.cfg_scale_speaker,
            "duration_scale": self.duration_scale,
        }
        caption = self.get_caption(speaker)
        if caption:
            irodori["caption"] = caption
        payload["irodori"] = irodori

        try:
            resp = self.client.post("/v1/audio/speech", json=payload)
            resp.raise_for_status()

            with open(output_path, "wb") as f:
                f.write(resp.content)

            logger.info(
                "Irodori-TTS synthesis saved to %s (%d bytes)",
                output_path,
                len(resp.content),
            )
            return True

        except httpx.HTTPStatusError as exc:
            logger.error(
                "Irodori-TTS /v1/audio/speech failed (status=%d, voice=%s): %s",
                exc.response.status_code,
                voice_id,
                exc,
            )
            return False
        except httpx.HTTPError as exc:
            logger.error(
                "Irodori-TTS /v1/audio/speech failed (voice=%s): %s",
                voice_id,
                exc,
            )
            return False
        except OSError as exc:
            logger.error("ファイル書き込み失敗 %s: %s", output_path, exc)
            return False

    def health_check(self) -> dict:
        """GET /health を呼び出してサーバーの稼働状態を確認する。

        Returns:
            {"status": "ok", "detail": "..."} または {"status": "error", "detail": "..."}
        """
        try:
            resp = self.client.get("/health")
            resp.raise_for_status()
            data = resp.json()
            # Irodori-TTS-Server の /health レスポンスからバージョン情報などを取得
            detail = data.get("checkpoint", data.get("status", "ok"))
            return {"status": "ok", "detail": str(detail)}
        except httpx.HTTPError as exc:
            return {"status": "error", "detail": str(exc)}
        except Exception as exc:
            return {"status": "error", "detail": str(exc)}
