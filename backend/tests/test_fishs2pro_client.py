import json

import httpx


def _client(handler):
    from app.services.fishs2pro_client import FishS2ProClient
    client = FishS2ProClient("http://fish.test/")
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://fish.test"
    )
    return client


def test_synthesize_line_posts_text_speaker_delivery_and_saves_wav(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/synthesize"
        assert json.loads(request.content) == {
            "text": "[excited] テスト本文",
            "speaker": "male",
            "delivery": "emphasis",
        }
        return httpx.Response(200, content=b"RIFF-test", headers={"content-type": "audio/wav"})

    output = tmp_path / "line.wav"
    assert _client(handler).synthesize_line("[excited] テスト本文", "male", str(output), "emphasis")
    assert output.read_bytes() == b"RIFF-test"
    assert len(requests) == 1


def test_synthesize_line_posts_female_speaker_and_saves_wav(tmp_path):
    def handler(request):
        assert json.loads(request.content)["speaker"] == "female"
        return httpx.Response(200, content=b"RIFF-female", headers={"content-type": "audio/wav; charset=binary"})

    output = tmp_path / "female.wav"
    assert _client(handler).synthesize_line("女性本文", "female", str(output))
    assert output.read_bytes() == b"RIFF-female"


def test_health_check_requires_ok_and_both_voices():
    client = _client(
        lambda request: httpx.Response(
            200, json={"status": "ok", "voices": ["male", "female"]}
        )
    )
    assert client.health_check() == {"status": "ok", "voices": ["male", "female"]}


def test_health_check_rejects_missing_voice():
    client = _client(
        lambda request: httpx.Response(200, json={"status": "ok", "voices": ["male"]})
    )
    assert client.health_check()["status"] == "error"


def test_health_check_rejects_invalid_json():
    client = _client(lambda request: httpx.Response(200, text="not-json"))
    assert client.health_check()["status"] == "error"


def test_health_check_returns_error_on_http_error():
    client = _client(lambda request: httpx.Response(503, text="unavailable"))
    assert client.health_check()["status"] == "error"


def test_synthesize_line_rejects_non_wav_response(tmp_path):
    client = _client(
        lambda request: httpx.Response(200, content=b"not-wav", headers={"content-type": "application/json"})
    )
    assert not client.synthesize_line("本文", "female", str(tmp_path / "line.wav"))


def test_synthesize_line_rejects_empty_body(tmp_path):
    client = _client(lambda request: httpx.Response(200, content=b"", headers={"content-type": "audio/wav"}))
    assert not client.synthesize_line("本文", "male", str(tmp_path / "line.wav"))


def test_synthesize_line_returns_false_on_timeout(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("timed out")

    client = _client(handler)
    assert not client.synthesize_line("本文", "male", str(tmp_path / "line.wav"))


def test_synthesize_line_returns_false_on_http_error(tmp_path):
    client = _client(lambda request: httpx.Response(503, text="unavailable"))
    assert not client.synthesize_line("本文", "male", str(tmp_path / "line.wav"))
