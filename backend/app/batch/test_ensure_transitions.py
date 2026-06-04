from app.batch.generate_script import _ensure_transitions, _pick_phrase, _pick_speaker


class TestPickPhraseNoConsecutiveDuplicate:
    def test_never_repeats_immediately(self):
        phrases = ["a", "b", "c", "d"]
        used = {"last": None}
        prev = None
        for _ in range(100):
            phrase = _pick_phrase(phrases, used)
            assert phrase != prev, f"consecutive duplicate: {phrase}"
            prev = phrase

    def test_returns_from_pool(self):
        phrases = ["x", "y"]
        used = {"last": None}
        for _ in range(20):
            phrase = _pick_phrase(phrases, used)
            assert phrase in phrases


class TestEnsureTransitionsDiscussionInsertion:
    def test_transition_inserted_before_discussion(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "discussion", "article_id": 2},
        ]
        summaries = [{"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}]
        result = _ensure_transitions(lines, summaries)
        sections = [r["section"] for r in result]
        assert "transition" in sections, "no transition inserted"

    def test_no_extra_transition_when_already_present(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "transition", "article_id": 2, "speaker": "female"},
            {"section": "news", "article_id": 2},
        ]
        summaries = [{"id": 1, "title": "T1"}, {"id": 2, "title": "T2"}]
        result = _ensure_transitions(lines, summaries)
        # art1 boundary inserts a transition; input transition at art2 is preserved but no extra one inserted before news(art2)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert 1 < trans_count <= 2, f"unexpected transition count: {trans_count}"


class TestEnsureTransitionsArticleBoundary:
    def test_transition_at_each_article_id_change(self):
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 2},
            {"section": "news", "article_id": 3},
        ]
        summaries = [
            {"id": 1, "title": "A"},
            {"id": 2, "title": "B"},
            {"id": 3, "title": "C"},
        ]
        result = _ensure_transitions(lines, summaries)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count >= 2, f"expected at least 2 transitions across 3 articles, got {trans_count}"

    def test_same_article_id_no_extra_transition(self):
        # intro->news(1) inserts 1 transition (first content line)
        # news(1)->news(1) does NOT insert because article_id unchanged
        lines = [
            {"section": "intro", "speaker": "male"},
            {"section": "news", "article_id": 1},
            {"section": "news", "article_id": 1},
        ]
        summaries = [{"id": 1, "title": "Single"}]
        result = _ensure_transitions(lines, summaries)
        trans_count = sum(1 for r in result if r["section"] == "transition")
        assert trans_count == 1, f"expected exactly 1 transition on intro->news boundary, got {trans_count}"


class TestPickSpeaker:
    def test_empty_result_returns_male(self):
        assert _pick_speaker([], "news") == "male"

    def test_alternates_after_single_line(self):
        result = [{"section": "news", "speaker": "male"}]
        speaker = _pick_speaker(result, "news")
        assert speaker == "female", "should alternate from last speaker"

    def test_breaks_consecutive_run_of_two(self):
        result = [
            {"section": "transition", "speaker": "male"},
            {"section": "news", "speaker": "male"},
        ]
        speaker = _pick_speaker(result, "news")
        assert speaker == "female", "should break a 2-run of male"
