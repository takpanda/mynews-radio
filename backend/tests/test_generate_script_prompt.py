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
        "登場人物、発覚のきっかけ、実際に起きたこと、対応または影響の順",
        "出来事→仕組み→影響・対応",
        "専門用語・略語は初出の行で、必ず「これは〜」形式の平易な一言定義",
        "解説文は口語にし、一文60字以内",
    )
    model_sentences = (
        "AliExpressのアプリが端末を追跡しました。これは「聞こえない音」を使う方法です。",
        "CVSS、これは脆弱性の危険度を点数で表す基準です。",
        "Denuvo、これはゲームの不正コピーを防ぐ仕組みです。",
    )

    for rule in required_rules:
        assert rule in prompt
    for sentence in model_sentences:
        assert sentence in prompt
        assert all(len(part) <= 60 for part in sentence.split("。") if part)


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
