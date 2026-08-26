from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.batch.summarize_articles as summarize_module


MAX_CHARS = 4000


def test_summary_prompt_prioritizes_event_definition_and_impact():
    prompt = summarize_module._load_prompt_template()

    required_rules = (
        "1. 出来事（登場人物、発覚のきっかけ、実際に起きたこと）",
        "2. 仕組み・初出用語の平易な一言定義",
        "専門用語・略語は、初めて出すときに「これは〜」など日常語で説明する",
        "3. 影響・対応（生活への影響、または取られた・必要な対応）",
        "summary は200文字以内です",
        "技術名や制度名の列挙よりも、出来事と初出用語の定義を優先",
        "技術名から書き始めず、何が起きたかを先に書いてください",
    )
    for rule in required_rules:
        assert rule in prompt

    example = "通販アプリが端末を追跡しました。これはAliExpressの「聞こえない音」を使う方法です。利用者は追跡設定を確認したいところです。"
    assert example in prompt
    sentences = [part for part in example.split("。") if part]
    assert len(sentences) == 3
    assert not sentences[0].startswith("AliExpress")
    assert "これは" in sentences[1]
    assert "利用者は追跡設定を確認したいところです" in sentences[2]


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
