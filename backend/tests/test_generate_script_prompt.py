from app.batch.generate_script import _load_prompt_template


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
    )

    for marker in expected_markers:
        assert marker in prompt
