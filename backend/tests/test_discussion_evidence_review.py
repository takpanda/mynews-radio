"""BEE-936: 討論の質問応答を根拠ベースで検証するテスト。"""

import json
from unittest.mock import MagicMock, patch


def _line(section, text, speaker, article_id=1):
    return {
        "section": section,
        "text": text,
        "speaker": speaker,
        "article_id": article_id,
        "delivery": "neutral",
    }


def test_question_response_contract_detects_missing_answer_and_repetition():
    from app.batch.review_script import check_question_response_contract

    issues = check_question_response_contract([
        _line("news", "料金はいくらですか？", "female"),
        _line("transition", "次の話題です。", "male"),
        _line("discussion", "料金は月額1000円です。", "male"),
        _line("discussion", "料金は月額1000円です。", "female"),
    ])

    assert any("[DIRECT_ANSWER_MISSING]" in issue for issue in issues)
    assert any("[EXPLANATION_REPEAT]" in issue for issue in issues)


def test_question_response_contract_accepts_direct_answer_then_new_viewpoint():
    from app.batch.review_script import check_question_response_contract

    lines = [
        _line("discussion", "料金について要約では何が説明されていますか？", "female"),
        _line("discussion", "要約にある料金は月額1000円です。", "male"),
        _line("discussion", "一方で、利用条件も選ぶときの確認点になりそうです。", "female"),
    ]

    assert check_question_response_contract(lines) == []


def test_review_prompts_include_episode_summaries(tmp_path):
    from app.batch.review_script import review_script

    source_path = tmp_path / "script.json"
    source_path.write_text(
        json.dumps({
            "title": "ニュースのとなり",
            "lines": [_line("intro", "開始します。", "male")],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    summaries_path = tmp_path / "summaries.json"
    summaries_path.write_text(
        json.dumps([{
            "article_id": 1,
            "title": "認証機能の発表",
            "summary": "登録端末で本人確認を行う機能です。料金は月額1000円です。",
        }], ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "review"
    output_dir.mkdir()

    prompts = []
    client = MagicMock()

    def generate(prompt, **_kwargs):
        prompts.append(prompt)
        if len(prompts) <= 5:
            return {"overall_score": 7, "issues": [], "general_feedback": ""}
        return {
            "lines": [_line("intro", "開始します。", "male")],
            "revision_summary": "根拠を確認しました。",
        }

    client.generate_json.side_effect = generate
    client_factory = MagicMock()
    client_factory.__enter__.return_value = client

    with patch("app.batch.review_script.OllamaClient", return_value=client_factory):
        result = review_script(str(source_path), str(output_dir), summaries_path=str(summaries_path))

    assert result["review_count"] == 5
    assert len(prompts) == 6
    assert all("登録端末で本人確認を行う機能です" in prompt for prompt in prompts)
    assert all("料金は月額1000円です" in prompt for prompt in prompts)
