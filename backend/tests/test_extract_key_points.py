"""Tests for _extract_key_points in radio_pipeline.py (LLM による要点生成)."""

import json

import pytest

from app.batch import radio_pipeline
from app.batch.radio_pipeline import _extract_key_points


class FakeClient:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """LLM クライアントと busy ゲートを差し替え、(script, summaries_path, holder) を返す。"""
    holder: dict = {}

    def fake_create(provider, model):
        holder["provider"], holder["model"] = provider, model
        return holder["client"]

    monkeypatch.setattr("app.services.ollama_client.create_llm_client", fake_create)
    monkeypatch.setattr(
        radio_pipeline, "run_with_dgx_busy", lambda stage, op, *a, **k: op(*a, **k)
    )
    script = {
        "subtitle": "ゼロデイ対策とAI規制",
        "lines": [
            {"text": "x", "article_id": 1},
            {"text": "y", "article_id": 2},
        ],
    }
    path = tmp_path / "summaries.json"
    path.write_text(
        json.dumps(
            [
                {"article_id": 1, "title": "NGINX CVE Analysis", "summary": "NGINXの脆弱性の解説"},
                {"article_id": 2, "title": "AI規制の最新動向", "summary": "各国のAI規制の比較"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return script, str(path), holder


def _run(setup, client):
    script, path, holder = setup
    holder["client"] = client
    return _extract_key_points(script, path, llm_provider="p", llm_model="m")


def test_generates_points_from_llm_and_passes_same_llm(setup):
    client = FakeClient({"key_points": ["脆弱性の影響範囲が分かる", "AI規制の違いが分かる"]})
    assert _run(setup, client) == ["脆弱性の影響範囲が分かる", "AI規制の違いが分かる"]
    assert (setup[2]["provider"], setup[2]["model"]) == ("p", "m")
    assert "NGINXの脆弱性の解説" in client.prompts[0]
    assert "ゼロデイ対策とAI規制" in client.prompts[0]


def test_limits_to_three_and_dedups(setup):
    client = FakeClient({"key_points": ["A", "A", "B", "C", "D"]})
    assert _run(setup, client) == ["A", "B", "C"]


def test_points_equal_to_article_title_are_dropped(setup):
    client = FakeClient({"key_points": ["NGINX CVE Analysis", "AI規制の最新動向", "脆弱性への備えが分かる"]})
    assert _run(setup, client) == ["脆弱性への備えが分かる"]


def test_llm_error_returns_empty(setup):
    assert _run(setup, FakeClient(error=RuntimeError("boom"))) == []


@pytest.mark.parametrize(
    "response",
    [None, {}, {"key_points": "文字列"}, {"key_points": [1, None, "  "]}, ["list"]],
)
def test_invalid_output_returns_empty(setup, response):
    assert _run(setup, FakeClient(response)) == []


def test_missing_summaries_file_returns_empty(setup):
    script, _, holder = setup
    holder["client"] = FakeClient({"key_points": ["A"]})
    assert _extract_key_points(script, "/nonexistent/summaries.json") == []
    assert holder["client"].prompts == []
