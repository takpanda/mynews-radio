"""BEE-919: 外部サービスなしで固定9件からWriter品質を再現する。"""

import json
from pathlib import Path

from app.batch import generate_script as generation
from app.batch.generate_script import lint_script


FIXTURE = Path(__file__).parent / "fixtures" / "bee919_summaries.json"


def _line(speaker, text, article_id, section, delivery="neutral"):
    return {
        "speaker": speaker,
        "text": text,
        "article_id": article_id,
        "section": section,
        "delivery": delivery,
    }


def _writer_output(summaries):
    ids = [item["id"] for item in summaries]
    lines = [
        _line("male", "「ニュースのとなり」の時間です。今日のニュースをお届けします。", None, "intro"),
        _line("female", "今回のラインナップはAI、仕事、暮らしの話題です。", None, "intro"),
    ]
    for index, item in enumerate(summaries):
        if index:
            lines.append(_line("female", f"続いては、{item['title']}の話題です。", item["id"], "transition"))
            lines.append(_line("male", f"{item['title']}について、具体的な中身を確認しましょう。", item["id"], "transition"))
        lines.append(_line("male", f"{item['title']}では、要約にある動きを確認しました。", item["id"], "news"))
    lines.extend([
        _line("male", "特にAI障害と運用環境の課題を、もう少し考えます。", ids[0], "discussion", "thoughtful"),
        _line("female", "一方で、使う人の現場の負担も見逃せないと思います。", ids[0], "discussion", "questioning"),
        _line("male", "三つのAIサービスが同じ時間帯に止まり、原因としてデータセンター障害が疑われました。", ids[0], "discussion", "thoughtful"),
        _line("female", "便利さだけでなく、止まったときの備えも必要ですね。", ids[0], "discussion", "thoughtful"),
        _line("male", "今日はAI障害と仕様駆動開発を含む、技術と暮らしの話題を見てきました。", None, "outro", "warm"),
        _line("female", "技術を使う現場の備えを、これからも考えていきましょう。", None, "outro", "warm"),
        _line("male", "それではまた明日、ニュースをお届けします。", None, "outro", "warm"),
    ])
    return {"title": "ニュースのとなり", "subtitle": "固定記事セットの検証", "lines": lines}


class FakeWriterClient:
    """Narrative ArcとWriterだけを返し、ネットワークを一切持たないFake。"""

    instances = []

    def __init__(self, *args, **kwargs):
        self.init_args = args
        self.init_kwargs = kwargs
        self.calls = []
        self.contexts = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def generate_json(self, prompt):
        self.calls.append(prompt)
        self.contexts.append(getattr(self, "_generation_context", {}).copy())
        if len(self.calls) == 1:
            ids = json.loads(FIXTURE.read_text(encoding="utf-8"))
            return {
                "theme": "AIと運用環境",
                "article_order": [item["id"] for item in ids],
                "discussion_article_id": ids[0]["id"],
                "bridges": [],
            }
        summaries = json.loads(FIXTURE.read_text(encoding="utf-8"))
        return _writer_output(summaries)


class FakeRetryClient(FakeWriterClient):
    """初回Writerだけ意図的に壊し、Auto-Lint修正ループも通すFake。"""

    def generate_json(self, prompt):
        if len(self.calls) == 1:
            self.calls.append(prompt)
            self.contexts.append(getattr(self, "_generation_context", {}).copy())
            result = _writer_output(json.loads(FIXTURE.read_text(encoding="utf-8")))
            result["lines"][2]["text"] = "記事53078を確認しました。"
            return result
        return super().generate_json(prompt)


def test_fixed_nine_summaries_run_real_writer_and_lint_without_services(monkeypatch, tmp_path):
    """固定fixtureの配線・JSON・Lintを検証する（自由生成LLMの品質保証ではない）。

    語尾多様性・討論の深さ・エンディングの質はFakeが返す決定的な出力に対して
    検証する。任意の実LLMが同じ品質を保証するテストではないため、実LLM評価は
    別の明示的な統合テストで行う。
    """
    summaries = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(summaries) == 9
    assert [item["id"] for item in summaries] == [53078, 53085, 52624, 53067, 52620, 53093, 53091, 53095, 53092]

    monkeypatch.setattr(generation.ArticleService, "fetch_summaries_for_script", lambda self, **kwargs: json.loads(json.dumps(summaries)))
    monkeypatch.setattr(generation.ArticleService, "mark_articles_used", lambda self, ids: None)
    monkeypatch.setattr(generation, "OllamaClient", FakeWriterClient)
    FakeWriterClient.instances.clear()

    output = tmp_path / "episodes" / "91901" / "script.json"
    count = generation.generate_script(str(output), news_source="fixed_fixture", max_articles=9)

    assert count > 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert all({"speaker", "text", "article_id", "section", "delivery"} <= set(line) for line in result["lines"])
    assert lint_script(result["lines"], expected_discussion_article_id=53078) == []
    assert {line["article_id"] for line in result["lines"] if line["section"] == "news"} == set(item["id"] for item in summaries)
    discussion = [line["text"] for line in result["lines"] if line["section"] == "discussion"]
    assert any("一方で" in text for text in discussion)
    assert any("データセンター障害" in text for text in discussion)
    outro = [line["text"] for line in result["lines"] if line["section"] == "outro"]
    assert any("AI障害" in text for text in outro)
    assert result["lines"][-1]["section"] == "outro"

    client = FakeWriterClient.instances[0]
    assert client.init_args[0] == generation.get_settings().ollama_base_url
    assert client.init_args[1].lower().startswith("qwen")
    assert len(client.calls) == 2
    assert [context["phase"] for context in client.contexts] == ["arc", "script"]
    assert all(item["title"] in client.calls[0] for item in summaries)
    suffixes = ("ですね。", "ですよね。", "ですね", "ですよね")
    endings = [
        next((suffix for suffix in suffixes if line["text"].endswith(suffix)), None)
        for line in result["lines"]
    ]
    assert all(left is None or right is None or left != right for left, right in zip(endings, endings[1:]))


def test_auto_lint_correction_is_exercised_without_external_services(monkeypatch, tmp_path):
    summaries = json.loads(FIXTURE.read_text(encoding="utf-8"))
    monkeypatch.setattr(generation.ArticleService, "fetch_summaries_for_script", lambda self, **kwargs: json.loads(json.dumps(summaries)))
    monkeypatch.setattr(generation.ArticleService, "mark_articles_used", lambda self, ids: None)
    monkeypatch.setattr(generation, "OllamaClient", FakeRetryClient)
    FakeRetryClient.instances.clear()

    output = tmp_path / "episodes" / "91902" / "script.json"
    assert generation.generate_script(str(output), news_source="fixed_fixture", max_articles=9) > 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert lint_script(result["lines"], expected_discussion_article_id=53078) == []
    client = FakeRetryClient.instances[0]
    assert client.init_args[1].lower().startswith("qwen")
    assert [context["phase"] for context in client.contexts] == ["arc", "script", "correction"]
    assert len(client.calls) == 3
    assert "記事IDの参照表記" in client.calls[2]
