"""BEE-725: 話者・スタイル一覧取得（VoicevoxClient.list_speakers / FishS2ProClient.list_voices）のテスト。"""

import httpx
import pytest


def _voicevox_client(handler):
    from app.services.voicevox_client import VoicevoxClient
    client = VoicevoxClient("http://tts.test/")
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://tts.test")
    return client


def _fishs2pro_client(handler):
    from app.services.fishs2pro_client import FishS2ProClient
    client = FishS2ProClient("http://fish.test/")
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://fish.test")
    return client


class TestVoicevoxClientListSpeakers:
    def test_flattens_speakers_and_styles_using_style_id_as_value(self):
        def handler(request):
            assert request.url.path == "/speakers"
            return httpx.Response(200, json=[
                {
                    "name": "阿井田 茂",
                    "speaker_uuid": "uuid-1",
                    "styles": [
                        {"name": "ノーマル", "id": 1310138976, "type": "talk"},
                        {"name": "落ち着き", "id": 1310138977, "type": "talk"},
                    ],
                },
                {
                    "name": "湊音エル",
                    "speaker_uuid": "uuid-2",
                    "styles": [{"name": "ノーマル", "id": 1388823424, "type": "talk"}],
                },
            ])

        options = _voicevox_client(handler).list_speakers()
        assert options == [
            {"speaker_name": "阿井田 茂", "style_name": "ノーマル", "value": 1310138976},
            {"speaker_name": "阿井田 茂", "style_name": "落ち着き", "value": 1310138977},
            {"speaker_name": "湊音エル", "style_name": "ノーマル", "value": 1388823424},
        ]

    def test_skips_styles_without_id(self):
        def handler(request):
            return httpx.Response(200, json=[
                {"name": "話者A", "styles": [{"name": "スタイルA"}]},
            ])

        assert _voicevox_client(handler).list_speakers() == []

    def test_raises_on_non_list_response(self):
        def handler(request):
            return httpx.Response(200, json={"unexpected": "shape"})

        with pytest.raises(ValueError):
            _voicevox_client(handler).list_speakers()

    def test_raises_on_http_error(self):
        def handler(request):
            return httpx.Response(503, text="unavailable")

        with pytest.raises(httpx.HTTPError):
            _voicevox_client(handler).list_speakers()


class TestFishS2ProClientListVoices:
    def test_returns_voices_from_health_response(self):
        def handler(request):
            assert request.url.path == "/health"
            return httpx.Response(200, json={"status": "ok", "voices": ["male", "morigawa"]})

        assert _fishs2pro_client(handler).list_voices() == ["male", "morigawa"]

    def test_raises_when_status_is_not_ok(self):
        def handler(request):
            return httpx.Response(200, json={"status": "error", "voices": ["male"]})

        with pytest.raises(ValueError):
            _fishs2pro_client(handler).list_voices()

    def test_raises_when_voices_missing(self):
        def handler(request):
            return httpx.Response(200, json={"status": "ok"})

        with pytest.raises(ValueError):
            _fishs2pro_client(handler).list_voices()

    def test_raises_on_http_error(self):
        def handler(request):
            return httpx.Response(503, text="unavailable")

        with pytest.raises(httpx.HTTPError):
            _fishs2pro_client(handler).list_voices()
