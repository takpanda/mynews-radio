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


def test_review_accepts_rewritten_question_without_inventing_answer(tmp_path):
    """根拠のない料金質問を、根拠に沿う問いへ変えて採用する例。"""
    from app.batch.review_script import review_script

    source_path = tmp_path / "script.json"
    source_path.write_text(
        json.dumps({"title": "ニュースのとなり", "lines": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    summaries_path = tmp_path / "summaries.json"
    summaries_path.write_text(
        json.dumps([{
            "article_id": 1,
            "title": "認証機能の発表",
            "summary": "登録端末で本人確認を行う機能です。料金の記載はありません。",
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
            "lines": [
                _line("news", "要約では料金について何が説明されていますか？", "female"),
                _line("news", "要約には料金の記載がありません。", "male"),
                _line("news", "登録端末で本人確認を行う点は確認できます。", "female"),
            ],
            "revision_summary": "根拠のない料金質問を要約で答えられる問いへ変更しました。",
        }

    client.generate_json.side_effect = generate
    client_factory = MagicMock()
    client_factory.__enter__.return_value = client

    with patch("app.batch.review_script.OllamaClient", return_value=client_factory):
        result = review_script(str(source_path), str(output_dir), summaries_path=str(summaries_path))

    revised = json.loads((output_dir / "script.json").read_text(encoding="utf-8"))
    texts = [line["text"] for line in revised["lines"]]
    assert result["revised"] is True
    assert texts[0] == "要約では料金について何が説明されていますか？"
    assert "1000" not in "".join(texts)
    assert "要約に答えがない質問には事実を補わないこと" in prompts[-1]


def test_dialogue_review_preserves_contract_lines_and_lints_after_merge(tmp_path):
    """レビュー合成が契約行を壊しても、最小限の復元後に lint される。"""
    from app.batch.review_script import review_script

    source_lines = [
        _line("intro", "「朝の番組」の時間です。今日のニュースをお届けします。", "male", None),
        _line("intro", "本日のラインナップを紹介します。", "female", None),
        _line("news", "新しい認証機能が発表されました。", "male", 1),
        _line("news", "登録端末で本人確認を行います。", "female", 1),
        _line("discussion", "料金について要約では何が説明されていますか？", "female", 1),
        _line("discussion", "要約には料金の記載がありません。", "male", 1),
        _line("discussion", "登録端末を使う点は確認できます。", "female", 1),
        _line("discussion", "利用条件を確認して選ぶ必要があります。", "male", 1),
        _line("outro", "今日は認証機能について振り返りました。", "male", None),
        _line("outro", "みなさんはどう感じましたか？", "female", None),
        _line("outro", "それではまた明日、お会いしましょう。", "male", None),
    ]
    source_path = tmp_path / "script.json"
    source_path.write_text(
        json.dumps({"style": "dialogue", "lines": source_lines}, ensure_ascii=False),
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
            "lines": [
                _line("intro", "こんにちは。", "male", None),
                _line("news", "認証機能です。", "male", 1),
                _line("discussion", "レビューで追加された前半の分析です。", "male", 1),
                _line("discussion", "料金はいくらですか？", "female", 1),
                _line("discussion", "別の話題です。", "female", 1),
                _line("discussion", "利用条件も確認する必要があります。", "male", 1),
                _line("outro", "それではまた。", "male", None),
                _line("outro", "最後にどう感じましたか？", "female", None),
            ],
            "revision_summary": "契約を確認しました。",
        }

    client.generate_json.side_effect = generate
    client_factory = MagicMock()
    client_factory.__enter__.return_value = client

    with patch("app.batch.review_script.OllamaClient", return_value=client_factory):
        result = review_script(
            str(source_path), str(output_dir), program_name="朝の番組",
        )

    revised = json.loads((output_dir / "script.json").read_text(encoding="utf-8"))
    intro = next(line for line in revised["lines"] if line["section"] == "intro")
    discussion = [line for line in revised["lines"] if line["section"] == "discussion"]
    outro = [line for line in revised["lines"] if line["section"] == "outro"]

    assert result["revised"] is True
    assert result["post_review_lint_issues"] == []
    assert set(result["contract_repairs"]) == {
        "INTRO_CONTRACT_RESTORED",
        "DISCUSSION_CONTRACT_RESTORED",
        "OUTRO_CONTRACT_RESTORED",
    }
    assert intro["text"].startswith("「朝の番組」の時間です")
    assert discussion[0]["text"] == "レビューで追加された前半の分析です。"
    assert discussion[1]["text"].endswith("？")
    assert discussion[2]["speaker"] != discussion[1]["speaker"]
    assert outro[-1]["text"].endswith("。")
    assert "それではまた" in outro[-1]["text"]
    assert "effective_program_name は「朝の番組」です" in prompts[-1]

    review_json = json.loads((output_dir / "review.json").read_text(encoding="utf-8"))
    assert review_json["post_review_lint_issues"] == []


def test_dialogue_contract_restores_all_broken_discussion_pairs():
    from app.batch.review_script import (
        _restore_dialogue_contract,
        check_question_response_contract,
    )

    source_lines = [
        _line("discussion", "料金について何が説明されていますか？", "female"),
        _line("discussion", "要約には月額1000円とあります。", "male"),
        _line("discussion", "利用条件は確認できますか？", "female"),
        _line("discussion", "登録端末で本人確認を行います。", "male"),
    ]
    revised_lines = [
        _line("discussion", "前半の分析はレビューで改善されました。", "male"),
        _line("discussion", "料金について何が説明されていますか？", "female"),
        _line("discussion", "別の話題へ移ります。", "female"),
        _line("discussion", "利用条件は確認できますか？", "female"),
        _line("discussion", "確認を続けます。", "female"),
    ]

    repaired, repairs = _restore_dialogue_contract(
        source_lines, revised_lines, program_name="ニュースのとなり",
    )

    assert "DISCUSSION_CONTRACT_RESTORED" in repairs
    assert not any(
        "[DIRECT_ANSWER_MISSING]" in issue
        for issue in check_question_response_contract(repaired)
    )
    assert repaired[0]["text"] == "前半の分析はレビューで改善されました。"
    discussion = [line for line in repaired if line.get("section") == "discussion"]
    assert [line["speaker"] for line in discussion[1:]] == [
        "female", "male", "female", "male",
    ]


def test_commentary_review_filters_radio_only_lint_codes(tmp_path):
    from app.batch.review_script import review_script

    source_lines = [
        _line("intro", "今日は記事を解説します。", "male", None),
        _line("news", "登録端末で本人確認を行う機能です。", "male"),
        _line("outro", "解説は以上です。", "male", None),
    ]
    source_path = tmp_path / "script.json"
    source_path.write_text(
        json.dumps({"style": "commentary", "lines": source_lines}, ensure_ascii=False),
        encoding="utf-8",
    )
    output_dir = tmp_path / "review"
    output_dir.mkdir()

    client = MagicMock()
    client.generate_json.side_effect = [
        {"overall_score": 7, "issues": [], "general_feedback": ""}
        for _ in range(5)
    ] + [{"lines": source_lines, "revision_summary": "確認しました。"}]
    client_factory = MagicMock()
    client_factory.__enter__.return_value = client

    with patch("app.batch.review_script.OllamaClient", return_value=client_factory):
        result = review_script(
            str(source_path), str(output_dir), commentary=True,
        )

    assert result["revised"] is True
    assert result["post_review_lint_issues"] == []
    assert json.loads((output_dir / "review.json").read_text(encoding="utf-8"))[
        "post_review_lint_issues"
    ] == []


def test_write_fallback_summaries_normalizes_database_ids(tmp_path):
    from app.services.article_service import write_fallback_summaries

    output_path = tmp_path / "summaries.json"
    write_fallback_summaries(
        str(output_path),
        [{"id": 42, "title": "記事", "summary": "要約"}],
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved == [{"id": 42, "title": "記事", "summary": "要約", "article_id": 42}]
