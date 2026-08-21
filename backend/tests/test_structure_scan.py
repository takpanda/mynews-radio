from app.batch.structure_scan import scan_script_structure


def line(section, text, article_id=None, speaker="male"):
    return {"section": section, "text": text, "article_id": article_id, "speaker": speaker}


def test_response_without_question_reports_line():
    warnings = scan_script_structure([
        line("news", "そうです。最初の記事です。", 1),
    ])
    assert any("STRUCTURE_RESPONSE_WITHOUT_QUESTION" in warning and "行 1" in warning for warning in warnings)


def test_response_after_question_is_allowed():
    warnings = scan_script_structure([
        line("news", "このニュースは重要ですか？", 1, "male"),
        line("news", "そうですね。重要なポイントです。", 1, "female"),
    ])
    assert not any("STRUCTURE_RESPONSE_WITHOUT_QUESTION" in warning for warning in warnings)


def test_adjacent_same_category_news_reports_pair():
    warnings = scan_script_structure(
        [line("news", "記事A", 1), line("transition", "次です", 2), line("news", "記事B", 2)],
        [{"id": 1, "title": "AIモデル発表", "summary": "AIの新機能", "category": "technology"},
         {"id": 2, "title": "AIサービス更新", "summary": "AIの更新", "category": "technology"}],
    )
    assert any("STRUCTURE_ADJACENT_NEWS_SIMILAR" in warning and "1" in warning and "2" in warning for warning in warnings)


def test_discussion_target_mismatch_reports_both_ids():
    warnings = scan_script_structure([
        line("news", "前のニュース", 10),
        line("discussion", "別の記事を討論", 20),
    ])
    assert any("STRUCTURE_DISCUSSION_TARGET_MISMATCH" in warning and "20" in warning and "10" in warning for warning in warnings)


def test_unrelated_adjacent_news_and_discussion_are_clean():
    warnings = scan_script_structure(
        [line("news", "宇宙の話", 1), line("news", "料理の話", 2), line("discussion", "料理を討論", 2)],
        [{"id": 1, "title": "宇宙探査", "summary": "月面", "category": "science"},
         {"id": 2, "title": "料理レシピ", "summary": "野菜", "category": "lifestyle"}],
    )
    assert warnings == []
