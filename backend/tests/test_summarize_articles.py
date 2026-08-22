from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.batch.summarize_articles as summarize_module


MAX_CHARS = 4000


class _FakeClient:
    def __init__(self, prompts):
        self.prompts = prompts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def generate_json(self, prompt):
        self.prompts.append(prompt)
        return {
            "summary": "要約",
            "category": "general",
            "importance_score": 3,
            "difficulty": 1,
        }


@pytest.mark.parametrize("text_length", [100, MAX_CHARS, MAX_CHARS + 1])
def test_summarize_articles_limits_prompt_body(monkeypatch, tmp_path, text_length):
    article_text = "".join(chr(ord("a") + index % 26) for index in range(text_length))
    prompts = []
    service = Mock()
    service.fetch_new_articles.return_value = [
        {
            "id": 1,
            "title": "title",
            "source": "source",
            "url": "https://example.test/article",
            "published_at": "2026-08-22T00:00:00Z",
            "text": article_text,
        }
    ]
    client = _FakeClient(prompts)

    monkeypatch.setattr(
        summarize_module,
        "get_settings",
        lambda: SimpleNamespace(
            summary_article_max_chars=MAX_CHARS,
            ollama_base_url="http://ollama.test",
            ollama_model="test-model",
        ),
    )
    monkeypatch.setattr(summarize_module, "ArticleService", lambda: service)
    monkeypatch.setattr(summarize_module, "OllamaClient", lambda *_args: client)
    monkeypatch.setattr(summarize_module, "_load_prompt_template", lambda: "本文:\n{text}")

    assert summarize_module.summarize_articles(str(tmp_path / "summaries.json")) == 1
    assert prompts == ["本文:\n" + article_text[:MAX_CHARS]]
    service.update_summary.assert_called_once()
