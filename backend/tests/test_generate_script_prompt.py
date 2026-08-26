import json

from app.batch.generate_script import _load_prompt_template
from app.batch.generate_script import lint_script


def test_radio_script_prompt_guides_female_mc_toward_natural_partner_talk():
    prompt = _load_prompt_template()

    expected_markers = (
        "打ち解けた相棒",
        "質問、短い相槌、日常語、具体例",
        "抽象的な結論を総括し切らず",
        "リスナーへ話題を返す",
        "同じ文末表現を連続させず",
        "文法が成立しない日本語",
        "状況が気になる限りあります",
        "生成結果の扱い",
        "正常なtransitionを上書きしてはならない",
        "既存検証で不正となる場合だけ",
        "質問・驚き・興味・確認",
    )

    for marker in expected_markers:
        assert marker in prompt


def test_radio_script_prompt_explains_events_before_terms_and_defines_model_terms():
    prompt = _load_prompt_template()

    required_rules = (
        "説明の順序と粒度は、次の3段階に統一すること",
        "①出来事（登場人物・発覚のきっかけ・実際に起きたこと）→②仕組み・用語定義",
        "専門用語・略語の初出は必ず「これは〜」形式で平易に定義",
        "③影響・対応（生活への影響、または取られた・必要な対応）",
        "①出来事より前に技術名・制度名を出さず",
        "解説文は口語にし、一文60字以内",
    )
    model_examples = (
        (
            "AliExpress",
            "通販アプリが端末を追跡しました",
            "利用者は追跡設定を確認したいところです",
            "通販アプリが端末を追跡しました。これはAliExpressの「聞こえない音」を使う方法です。利用者は追跡設定を確認したいところです。",
        ),
        (
            "CVSS",
            "ソフトの弱点の危険度を評価しました",
            "点数をもとに対応の優先度を決めます",
            "ソフトの弱点の危険度を評価しました。これはCVSSという点数で深刻さを表す基準です。点数をもとに対応の優先度を決めます。",
        ),
        (
            "Denuvo",
            "ゲームの不正コピーが問題になりました",
            "開発元は正規利用を守る対応を取ります",
            "ゲームの不正コピーが問題になりました。これはDenuvoという不正利用を防ぐ仕組みです。開発元は正規利用を守る対応を取ります。",
        ),
    )

    for rule in required_rules:
        assert rule in prompt
    assert "田村（male）が担当する説明文のモデル" in prompt
    assert "山口（female）の疑問・生活影響の発言は別に続ける" in prompt
    for technical_name, event, impact_or_response, example in model_examples:
        assert example in prompt
        sentences = [part for part in example.split("。") if part]
        assert len(sentences) == 3
        assert event in sentences[0]
        assert not sentences[0].startswith(technical_name)
        assert "これは" in sentences[1]
        assert impact_or_response in sentences[2]
        assert all(len(sentence) <= 60 for sentence in sentences)


def test_representative_dialogue_output_can_be_checked_without_external_llm():
    """外部LLMなしで受入条件を確認するための代表出力例。"""
    script = {
        "title": "ニュースのとなり",
        "subtitle": "暮らしと技術の身近な変化",
        "lines": [
            {"speaker": "male", "text": "「ニュースのとなり」の時間です。今日も身近な話題をお届けします。", "article_id": None, "section": "intro", "delivery": "neutral"},
            {"speaker": "female", "text": "今日のラインナップは、暮らしと技術の2つです。", "article_id": None, "section": "intro", "delivery": "neutral"},
            {"speaker": "male", "text": "まずは、食品価格の動きから見ていきます。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "これ、毎日の買い物にはどう響くんですか？", "article_id": 1, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "店頭価格への反映には時間差があるようです。", "article_id": 1, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "家計を預かる側としては、変化の時期を知りたいところです。", "article_id": 1, "section": "news", "delivery": "thoughtful"},
            {"speaker": "female", "text": "暮らしの変化に続いて、次は技術の話題です。", "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "こちらも聞いてみましょう。", "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "新しい認証機能が発表されました。", "article_id": 2, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "便利そうですが、設定は難しくないですか？", "article_id": 2, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "登録した端末を使って本人確認を行う仕組みです。", "article_id": 2, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "使う人が迷わない案内も、同じくらい大切ですね。", "article_id": 2, "section": "news", "delivery": "thoughtful"},
            {"speaker": "male", "text": "今日は暮らしと技術の話題をお届けしました。", "article_id": None, "section": "outro", "delivery": "warm"},
            {"speaker": "female", "text": "みなさんの身近な変化も、ぜひ聞かせてください。", "article_id": None, "section": "outro", "delivery": "warm"},
        ],
    }

    # script.json と同じ JSON 往復ができることを確認する。
    loaded = json.loads(json.dumps(script, ensure_ascii=False))
    assert all({"speaker", "text", "article_id", "section", "delivery"} <= set(line) for line in loaded["lines"])

    errors = lint_script(loaded["lines"])
    assert errors == []

    female_news = [
        line["text"]
        for line in loaded["lines"]
        if line["speaker"] == "female" and line["section"] == "news"
    ]
    assert any(text.endswith("？") for text in female_news)
    assert any(not text.endswith("？") for text in female_news)
    assert "状況が気になる限りあります" not in "".join(female_news)
    assert all(a[-1:] != b[-1:] for a, b in zip(female_news, female_news[1:]))
