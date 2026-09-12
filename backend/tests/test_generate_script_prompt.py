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
        "番組全体の緩急と反復抑制",
        "`importance_score`（1〜5）",
        "感情温度の山谷",
        "同じ語尾パターン",
        "固定の回数上限は設けず",
        "当日の最重要記事または discussion で扱った話題",
        "一般的な天気・安全注意だけで終わらせず",
        "締めの挨拶と当日の最重要記事",
        "一般的な挨拶を最後の行に単独で置かない",
        "outro 最終行の絶対条件",
        "別角度・反論・生活者視点の突っ込み",
        "「一方で」「ただし」「別の立場では」などの転換",
        "具体的な事実・数字・仕組みに基づいて答える",
        "山口が具体的な別角度を提示する行",
        "田村が選んだ記事の要約にある具体的な事実・数字・仕組みに基づいて答える行",
        "入力要約に実際に記載された語句・数字・仕組みの言い換えに限定",
        "要約にない専門用語、背景、因果関係、生活影響を補ってはならない",
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
            {"speaker": "male", "text": "認証機能の手順も確認したいですね。", "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "新しい認証機能が発表されました。", "article_id": 2, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "便利そうですが、設定は難しくないですか？", "article_id": 2, "section": "news", "delivery": "questioning"},
            {"speaker": "male", "text": "登録した端末を使って本人確認を行う仕組みです。", "article_id": 2, "section": "news", "delivery": "neutral"},
            {"speaker": "female", "text": "使う人が迷わない案内も、同じくらい大切ですね。", "article_id": 2, "section": "news", "delivery": "thoughtful"},
            {"speaker": "female", "text": "では、新しい認証機能について、もう少し考えてみましょう。", "article_id": 2, "section": "transition", "delivery": "neutral"},
            {"speaker": "male", "text": "登録端末で本人確認を行うため、仕組み自体ははっきりしています。", "article_id": 2, "section": "discussion", "delivery": "thoughtful"},
            {"speaker": "female", "text": "一方で、設定に迷う人には便利さが届きにくいかもしれません。", "article_id": 2, "section": "discussion", "delivery": "questioning"},
            {"speaker": "male", "text": "要約にあるとおり、本人確認には登録した端末を使います。", "article_id": 2, "section": "discussion", "delivery": "thoughtful"},
            {"speaker": "female", "text": "使う側には、導入時の案内があるかどうかも大きな分かれ目になりそうです。", "article_id": 2, "section": "discussion", "delivery": "thoughtful"},
            {"speaker": "male", "text": "今日は食品価格の動きと、新しい認証機能を見てきました。", "article_id": None, "section": "outro", "delivery": "warm"},
            {"speaker": "female", "text": "新しい認証機能、みなさんは案内の分かりやすさをどう感じますか？", "article_id": None, "section": "outro", "delivery": "warm"},
            {"speaker": "male", "text": "また明日も、暮らしに関わる話題を取り上げます。", "article_id": None, "section": "outro", "delivery": "warm"},
            {"speaker": "female", "text": "それではまた明日、新しい認証機能を選ぶなら、どんな案内があると安心できますか？", "article_id": None, "section": "outro", "delivery": "warm"},
        ],
    }

    # script.json と同じ JSON 往復ができることを確認する。
    loaded = json.loads(json.dumps(script, ensure_ascii=False))
    assert all({"speaker", "text", "article_id", "section", "delivery"} <= set(line) for line in loaded["lines"])

    errors = lint_script(loaded["lines"])
    assert errors == []

    content_lines = [line["text"] for line in loaded["lines"] if line["text"]]
    assert any(text.endswith("？") for text in content_lines)
    assert any(not text.endswith("？") for text in content_lines)
    assert "状況が気になる限りあります" not in "".join(content_lines)

    def ending_pattern(text):
        for ending in ("ですね。", "ですよね。", "と思います。", "と感じました。"):
            if text.endswith(ending):
                return ending
        return None

    content_endings = [ending_pattern(text) for text in content_lines]
    assert all(
        a is None or b is None or a != b
        for a, b in zip(content_endings, content_endings[1:])
    )

    sections = [line["section"] for line in loaded["lines"]]
    news_indices = [i for i, section in enumerate(sections) if section == "news"]
    discussion_indices = [i for i, section in enumerate(sections) if section == "discussion"]
    outro_indices = [i for i, section in enumerate(sections) if section == "outro"]
    assert max(news_indices) < min(discussion_indices) < min(outro_indices)
    discussion_lines = [loaded["lines"][i] for i in discussion_indices]
    assert [line["speaker"] for line in discussion_lines] == ["male", "female", "male", "female"]
    assert {line["article_id"] for line in discussion_lines} == {2}
    assert "一方で" in discussion_lines[1]["text"]
    assert "登録した端末" in discussion_lines[2]["text"]
    assert "新しい認証機能" in loaded["lines"][-1]["text"]
    assert loaded["lines"][-1]["text"].endswith("？")
    assert "天気" not in loaded["lines"][-1]["text"]
