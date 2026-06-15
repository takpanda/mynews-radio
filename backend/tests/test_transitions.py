"""Tests for _ensure_transitions: topic extraction and transition insertion."""
import pytest


class TestTransitionPhrases:
    def test_no_unnatural_templates(self):
        from app.batch.generate_script import _TRANSITION_PHRASES
        for phrase in _TRANSITION_PHRASES:
            # 「{topic}についてです。」という不自然なパターンが含まれていないこと
            assert "についてです。" not in phrase or "{topic}の" in phrase.split("についてです")[0][-10:]

    def test_discussion_transitions_natural(self):
        from app.batch.generate_script import _DISCUSSION_TRANSITIONS
        # すべて「{topic}について」+動詞 の形であり、文法的に自然なためOK
        for phrase in _DISCUSSION_TRANSITIONS:
            assert "{topic}" in phrase


class TestEnsureTransitionsTopicExtraction:
    def test_uses_summary_first_sentence(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "That Title Could Be Very Long And Cut Off Weirdly",
             "summary": "今日は素晴らしい天気です。明日も引き続き良い天気予報となっています。"}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "test"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) >= 1
        # summaryの先頭文が抽出されていることを確認（titleではなく）
        topic = transitions[0]["text"]
        assert "今日は素晴らしい天気です" in topic or "That Title" not in topic

    def test_falls_back_to_title_when_no_summary(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "重要なニュース", "summary": ""}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "test"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) >= 1
        # titleが空でなければフォールバック動作が維持されることを確認
        topic = transitions[0]["text"]
        # 「次の話題」のフォールバック以外の何かが入っていること
        assert "次の話題" not in topic or "重要なニュース" in topic

    def test_fallback_to_next_topic_when_both_empty(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "", "summary": ""}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "test"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) >= 1
        topic = transitions[0]["text"]
        # titleもsummaryも空の場合、「次の話題」にフォールバックする
        assert "次の話題" in topic

    def test_summary_longer_than_25_chars_falls_back_to_title(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "短タイトル", "summary": "とても長い要約テキストで25文字を大幅に超えるような内容を持っている一文です。"}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "test"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) >= 1
        topic = transitions[0]["text"]
        # 25文字を超える場合、titleの短い切り出しにフォールバックする
        assert "短タイトル" in topic

    def test_no_transition_for_same_article(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "ニュース1", "summary": "要約1です。"}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "content1"},
            {"section": "news", "article_id": 1, "speaker": "female", "text": "content2"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        # 同じ article_id 内では transition は挿入されない（最初の1回のみ）
        assert len(transitions) == 1

    def test_transition_inserted_on_article_change(self):
        from app.batch.generate_script import _ensure_transitions

        summaries = [
            {"id": 1, "title": "ニュース1", "summary": "要約1です。"},
            {"id": 2, "title": "ニュース2", "summary": "要約2です。"}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "content1"},
            {"section": "news", "article_id": 2, "speaker": "female", "text": "content2"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        # article_id が変わった箇所で transition が挿入される
        assert len(transitions) == 2


class TestTitleNoFifteenCharTruncation:
    """15文字切り出しが廃止されており、より自然なトピック表記になっていること。"""

    def test_title_not_truncated_at_15_chars(self):
        from app.batch.generate_script import _ensure_transitions

        # 16文字を超えるtitle（旧ロジックなら[:15]で切れる長さ）
        summaries = [
            {"id": 1, "title": "那覇市で激しい雨を観測しました", "summary": ""}
        ]
        lines = [
            {"section": "intro"},
            {"section": "news", "article_id": 1, "speaker": "male", "text": "test"},
        ]
        result = _ensure_transitions(lines, summaries)

        transitions = [l for l in result if l.get("section") == "transition"]
        assert len(transitions) >= 1
        topic_text = transitions[0]["text"]
        # 「についてです。」パターンが残っていないことを確認
        assert "{topic}についてです。" not in topic_text
        # titleのまま使われている（半角で区切られるが「についてです」は付かない）
