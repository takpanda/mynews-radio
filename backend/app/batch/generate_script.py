import json
import logging
import os
import random
import re as _re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.article_service import ArticleService
from app.services.ollama_client import OllamaClient, create_llm_client
from app.services.settings_service import ProgramSettings, get_settings_or_default

logger = logging.getLogger(__name__)

_TRANSITION_PHRASES = [
    "続いては{topic}のニュースです。",
    "さて、{topic}の話題はどうでしょうか。",
    "話は変わりまして、{topic}のニュースをどうぞ。",
    "もうひとつ気になるニュースがありました。{topic}の話題です。",
    "それでは{topic}の話題に移ります。",
    "{topic}に関しても注目の動きがありましたね。",
    "では次は{topic}の話題をご紹介します。",
    "{topic}についても最新の情報が入ってきました。",
    "ここで{topic}のニュースもご紹介しましょう。",
    "さて、次のトピックです。{topic}についてお伝えします。",
    "ここからは{topic}の話題に入っていきましょう。",
    "続いてお届けするのは{topic}のニュースです。",
    "次の項目は{topic}のお話です。",
    "では、{topic}の最新の動きをご報告します。",
    "ここで視点を変えて、{topic}を見てみましょう。",
    "{topic}についても触れておきましょう。",
    "次は{topic}の話題です。ご注眼ください。",
    "さて、みんなが注目している{topic}の情報ですよ。",
    "少し話題を変えて、{topic}について紹介しましょう。",
    "{topic}に関して気になるニュースが届いていますね。",
    "では、次のコーナーへ。{topic}の最新情報をどうぞ。",

    "お次は{topic}です。どうなっているのでしょうか。",
    "ここからが本題。{topic}に迫ります。",
    "{topic}には次のような動きがあるようです。",
    "引き続き、{topic}の話題をお届けします。",
    "そのほか、{topic}についての情報も集まりました。",
    "さてさて、{topic}はどう動いているのでしょうか。",
    "次にご紹介する{topic}も要チェックです。",
    "ここからはちょっと違う切り口で、{topic}を考えます。",
    "{topic}についても忘れてはいけないニュースがありますよ。",
    "では、もう少し先を見てみましょうか。{topic}の話題でございます。",
]

_BRIDGE_TRANSITION_PHRASES = [
    "{bridge} さて、{topic}の話題です。",
    "{bridge} それでは、{topic}のニュースをどうぞ。",
    "{bridge} そんな中、{topic}についても見ていきましょう。",
    "{bridge} では次は{topic}の話題をご紹介します。",
    "{bridge} 続いては{topic}の最新情報です。",
    "{bridge} ここで視点を変えて、{topic}を見てみましょう。",
]

# トピック抽出がフォールバックした場合（_topic が _FALLBACK_TOPIC を返す
# 場合）に使う専用テンプレート。_TRANSITION_PHRASES / _BRIDGE_TRANSITION_PHRASES
# は {topic} の直後に「の話題」「のニュース」等の固定接尾辞を伴うため、その
# まま _FALLBACK_TOPIC を差し込むと「次の話題の話題」「次の話題のニュース」
# のような重複表現になってしまう（BEE-697）。{topic} プレースホルダを持たない
# 完結した文を用意することで、この重複を構造的に防ぐ。
_FALLBACK_TRANSITION_PHRASES = [
    "さて、次の話題です。",
    "それでは、次の話題に移りましょう。",
    "続いて、次の話題です。",
    "では、次の話題をご紹介します。",
    "ここで、次の話題に移ります。",
]

_FALLBACK_BRIDGE_TRANSITION_PHRASES = [
    "{bridge} さて、次の話題です。",
    "{bridge} それでは、次の話題に移りましょう。",
    "{bridge} 続いて、次の話題です。",
]

_DISCUSSION_TRANSITIONS = [
    "ここで{topic}についてもう少し掘り下げてみましょう。",
    "{topic}、少し深堀りして話し合ってみましょう。",
    "ちょっとここで{topic}について、ふたりで語ってみたいと思います。",
    "ここでは{topic}を、じっくり話してみましょうか。",

    "{topic}、私も気になっているんですよ。どう思います？",
    "ここで一旦立ち止まって{topic}を議論しましょうか。",
    "{topic}について、二人で頭を絞ってみますよ。",
]

# 記事境界のtransitionは両MCの短い掛け合い（橋渡し＋短い受け）にする必要がある（BEE-630）。
# LLMがtransitionを省略しプログラム側で補完する場合も、この「短い受け」を橋渡しの直後に
# 挿入し、単独1行の告知にならないようにする。次の記事の内容は先取りしない。
_TRANSITION_REACTION_PHRASES = [
    "気になりますね。",
    "それは見逃せません。",
    "楽しみですね。",
    "詳しく聞きたいです。",
    "早速聞いてみましょう。",
    "そちらも気になっていました。",
    "続けてお願いします。",
    "興味深いですね。",
]

# 災害・重大事故のニュースでは、記事境界の定型的な短い受けであっても
# 期待や祝意を表す表現は不適切になる。カテゴリは提供元ごとに揺れるため、
# title / summary / category のいずれにも現れうる明示的な語で判定する。
_SENSITIVE_NEWS_KEYWORDS = (
    "災害", "地震", "津波", "台風", "豪雨", "大雨", "洪水", "土砂",
    "避難", "警報", "警戒", "被災", "火災", "噴火", "行方不明", "死亡", "負傷",
)
_SENSITIVE_TRANSITION_REACTION_PHRASES = [
    "状況を確認しましょう。",
    "詳しくお伝えします。",
    "落ち着いて見ていきましょう。",
]
_SENSITIVE_INAPPROPRIATE_TRANSITION_MARKERS = (
    "楽しみ", "わくわく", "待ち遠し", "嬉しい", "お祝い", "めでたい", "せっかくなので",
)


def _is_sensitive_news(summary: dict) -> bool:
    """災害・重大事故を扱う記事かを、生成に渡される記事情報から判定する。"""
    text = " ".join(str(summary.get(key, "") or "") for key in ("category", "title", "summary"))
    return any(keyword in text for keyword in _SENSITIVE_NEWS_KEYWORDS)


def _has_inappropriate_sensitive_transition_text(text: str) -> bool:
    return any(marker in (text or "") for marker in _SENSITIVE_INAPPROPRIATE_TRANSITION_MARKERS)


def _pick_phrase(phrases: list, used_indices: dict):
    """乱択でフレーズを選んで返す。直前に使用した同じプレースホルダー位置のものを回避する。"""
    n = len(phrases)
    last_idx = used_indices.get("last")
    cands = list(range(n))
    if last_idx is not None and n > 1:
        cands = [i for i in cands if i != last_idx]
    chosen = random.choice(cands)
    used_indices["last"] = chosen
    return phrases[chosen]


def _pick_speaker(result: list, section: str):
    """遷移行の話者を選ぶ。

    直前の news / discussion のみを取り出し、以下のルールで決定：
    - 同一話者の連続が 2 回以上 → 強制的に相手側
    - 同じ article_id 内のコンテンツ行の話者パターンがあればそれと交互に
    - それ以外は直前の最後の話者と交互
    """
    if not result:
        return "male"

    # transition は除く（自分の挿入結果に引っ張られないよう）
    content_speakers = [
        prev_line.get("speaker")
        for prev_line in reversed(result)
        if prev_line.get("section") in ("news", "discussion")
    ][:3]

    if not content_speakers:
        return "male"

    last_spk = content_speakers[0]
    alternate = "female" if last_spk == "male" else "male"

    # 直前のコンテンツ行（news/discussionのみ）が同じ話者で2回以上連続している場合
    run = 1
    for sp in content_speakers[1:]:
        if sp == last_spk:
            run += 1
        else:
            break
    if run >= 2:
        return alternate

    # 前後のセクション内容を見る：直前の news が female ばかりのときは male を選ぶ等
    # content_speakers の内訳を見て、バランスが偏っている場合は少数側を選ぶ
    male_count = sum(1 for s in content_speakers if s == "male")
    female_count = len(content_speakers) - male_count
    if male_count > female_count + 1:
        return "female"
    if female_count > male_count + 1:
        return "male"

    # news 遷移：直前のコンテンツと交互（バランスも考慮済みなので自然に）
    if section == "news":
        return alternate

    # discussion 遷移：同様に交互
    return alternate


_SENTENCE_END_CHARS = "。！？"

_TEMPLATE_PLACEHOLDER_RE = _re.compile(r"\{(bridge|topic)\}")


def _compile_template_pattern(template: str):
    """テンプレート文字列（{bridge}/{topic} プレースホルダ入り）を、実際に
    差し込まれた文字列を named group として捕捉できる正規表現に変換する。
    プレースホルダ以外の部分はリテラルとして厳密一致させる。"""
    parts = ["^"]
    last = 0
    for m in _TEMPLATE_PLACEHOLDER_RE.finditer(template):
        parts.append(_re.escape(template[last:m.start()]))
        parts.append(f"(?P<{m.group(1)}>.+?)")
        last = m.end()
    parts.append(_re.escape(template[last:]))
    parts.append("$")
    return _re.compile("".join(parts), _re.DOTALL)


# _TRANSITION_PHRASES / _BRIDGE_TRANSITION_PHRASES はプログラムが差し込む固定
# テンプレートであり、その一部（BEE-630のContextual Bridgeを含む）は意図的に
# 複文構成（前置きの一文＋告知の一文）になっている（BEE-664）。テンプレート
# 形状そのものに一致するかを構造的に確認することで、句点の個数だけに頼らず
# これらの安全な複文を「壊れたtransition」と誤判定しないようにする。
_KNOWN_TRANSITION_TEMPLATE_PATTERNS = [
    _compile_template_pattern(t)
    for t in (
        _TRANSITION_PHRASES
        + _BRIDGE_TRANSITION_PHRASES
        + _FALLBACK_TRANSITION_PHRASES
        + _FALLBACK_BRIDGE_TRANSITION_PHRASES
    )
]


def _is_single_clean_sentence(segment: str) -> bool:
    """{bridge}/{topic} に実際に差し込まれた文字列自体が、末尾以外に句点等を
    含む複文になっていないかを判定する（テンプレート一致の追加保証）。"""
    stripped = segment.strip()
    if not stripped:
        return True
    body = stripped[:-1] if stripped[-1] in _SENTENCE_END_CHARS else stripped
    return not any(ch in _SENTENCE_END_CHARS for ch in body)


def _matches_known_transition_template(text: str) -> bool:
    """text が既知の安全なtransitionテンプレート（_TRANSITION_PHRASES /
    _BRIDGE_TRANSITION_PHRASES）の形状に一致し、かつ {bridge}/{topic} に
    差し込まれた文字列自体も単文であるかを確認する。

    後半の単文チェックが必要な理由（BEE-664）: {bridge} は任意の文字列に
    一致しうるため、この確認がないと「前の記事の締め文＋それでは、＋次の
    記事の告知」のように壊れたtransition（BEE-661のエピソード355の実例）が
    たまたま「{bridge} それでは、{topic}のニュースをどうぞ。」のような
    テンプレート形状と一致してしまい、壊れた文を安全と誤判定しうる。
    {bridge}に差し込まれた文字列自体が複文（＝それ自体に前の記事の締め文が
    混在している）でないことも合わせて確認することで、この誤判定を防ぐ。
    """
    for pattern in _KNOWN_TRANSITION_TEMPLATE_PATTERNS:
        m = pattern.match(text)
        if m and all(_is_single_clean_sentence(v) for v in m.groupdict().values()):
            return True
    return False


# 記事境界transitionが「次の話題へ移る」ことだけを告げる自然な繋ぎ語
# （前の記事の内容には一切触れない、テンプレートと同種の一般的な言い回し）
_TRANSITION_LEAD_IN_OPENERS = ("それでは", "では", "続いて", "次は", "さて", "ここで")

# 繋ぎ語で始まる1文目がこの文字数を超える場合、前の記事の具体的な内容を
# 語る長い締め文である可能性が高いとみなし、安全側に倒す
_LEAD_IN_FIRST_SENTENCE_MAX_LEN = 20

# 前の記事の内容を要約・振り返る表現。1文目（繋ぎ語に続く前置きの文）が
# これらの表現を含む場合は、前の記事の内容（の結論・要約）が混在している
# 疑いがあるとみなし、安全なリード文として除外しない（BEE-672 再指摘: 「続いて
# 前の記事の結論です。次は経済ニュースです。」のように、繋ぎ語＋短い1文目
# という形だけでは前記事内容の混在を排除できないため、明示的な後方参照語を
# 追加のガードとして併用する）。
_BACKWARD_REFERENCE_MARKERS = (
    "前の記事",
    "前の話",
    "前のニュース",
    "先ほどの",
    "先程の",
    "今の記事",
    "今の話",
    "ここまでの",
    "結論",
    "まとめる",
    "まとめ",
    "振り返",
)


def _is_generic_two_sentence_lead_in(text: str) -> bool:
    """text が、前の記事の内容に触れず次の話題へ移ることだけを告げる、
    既知の短い繋ぎ語で始まる自然な2文構成のtransitionかどうかを判定する
    （BEE-672 レビュー指摘）。

    _is_broken_transition_text は既知テンプレート（_TRANSITION_PHRASES /
    _BRIDGE_TRANSITION_PHRASES）に一致しない複文を一律に壊れた文として扱う
    ため、「続いて経済ニュースです。詳しく見ていきましょう。」のような、
    前の記事の内容を一切含まない正常な2文構成の遷移まで誤って壊れた文と
    判定してしまう。

    これまでに確認された壊れたtransition（BEE-661/BEE-662/BEE-671）は、
    いずれも前の記事の具体的な内容を語る文から始まり、既知の繋ぎ語では
    始まらない。そのため、(1) 既知の繋ぎ語で始まる、(2) 文がちょうど2つで
    どちらも句点等で正しく終端している（スペース区切りの連結のような
    文法破綻がない）、(3) 1文目が短い、の3条件を満たす場合に限り、複文で
    あっても安全とみなす。ただし「続いて前の記事の結論です。」のように
    繋ぎ語＋短い1文目という形状だけでは前記事内容の混在を排除しきれない
    ため、(4) 1文目に前の記事を要約・振り返る表現
    （_BACKWARD_REFERENCE_MARKERS）を含まないことも合わせて要求する。

    後方参照マーカーの判定は1文目（繋ぎ語に続く前置きの文）のみを対象と
    し、2文目には適用しない。2文目は次の話題の具体的な内容を説明する文で
    あり、「市場の動きをまとめて確認しましょう」のように、後方参照マーカー
    と同じ語（「まとめ」等）を前の記事とは無関係な文脈で含みうる。全文に
    対する部分一致では、こうした正常な2文目まで誤って壊れた文と判定して
    しまうため（CodeReviewer再指摘、BEE-672）、1文目に限定する。
    """
    if not any(text.startswith(opener) for opener in _TRANSITION_LEAD_IN_OPENERS):
        return False
    sentences = [s for s in _re.split(r"(?<=[。！？])", text) if s]
    if len(sentences) != 2:
        return False
    first_sentence = sentences[0]
    if len(first_sentence) > _LEAD_IN_FIRST_SENTENCE_MAX_LEN:
        return False
    if any(marker in first_sentence for marker in _BACKWARD_REFERENCE_MARKERS):
        return False
    return all(s[-1] in _SENTENCE_END_CHARS for s in sentences)


def _is_broken_transition_text(text: str) -> bool:
    """記事境界のtransition行に、独立した文が複数連結されていないかを判定する。

    記事境界のtransitionは次の記事だけを告知する単一の短い文であるべき
    （BEE-630）。前の記事の締め文と次の記事の告知が1つのtransition行に
    混在すると、句点（。！？）で区切られた文が2つ以上連結された形になる
    （BEE-661: エピソード355で「…社会構造の歪みを象徴する それでは、
    カンボジアで息子が行方不明になり8ヶ月経ったが、息のニュースをどうぞ。」
    のように、前記事の締め文＋次記事告知が1行に混在し、次記事のキーワード
    （行方不明→息）も欠落する形で再現された）。

    単純な部分文字列・単語一致ではなく句読点構造のみで判定することで、
    比喩的な言い換えや文脈を踏まえた自然なtransition（Contextual Bridge）を
    誤って壊れた文とみなさないようにする（末尾の句点1個は単文として許容）。

    ただし_TRANSITION_PHRASES/_BRIDGE_TRANSITION_PHRASESには意図的に複文の
    テンプレートが含まれる（BEE-664）。句読点の数だけで判定すると、これらの
    プログラム生成の正常な複文まで誤検知してしまうため、既知のテンプレート
    形状に一致する場合は複文であっても壊れていないとみなす
    （_matches_known_transition_template）。同様に、既知の繋ぎ語で始まる
    自然な2文構成のリード文も誤検知しないようにする
    （_is_generic_two_sentence_lead_in、BEE-672）。

    さらに、トピック抽出がフォールバックした「次の話題」がテンプレートの
    固定接尾辞と結合すると「次の話題の話題」「次の話題のニュース」のような
    重複表現になる（BEE-697）。この重複は句読点構造上は単文のままのため、
    既知テンプレート一致チェックをすり抜けてしまう。そのため他のどの判定
    よりも先に、この重複表現を明示的に不正として検出する。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if any(pattern in stripped for pattern in _DUPLICATE_FALLBACK_TOPIC_PATTERNS):
        return True
    if _matches_known_transition_template(stripped):
        return False
    if _is_generic_two_sentence_lead_in(stripped):
        return False
    body = stripped[:-1] if stripped[-1] in _SENTENCE_END_CHARS else stripped
    return any(ch in _SENTENCE_END_CHARS for ch in body)


# トピック名を抽出できなかった場合の汎用フォールバック値。_TRANSITION_PHRASES
# 等の通常テンプレートは末尾に「の話題」「のニュース」等の固定接尾辞を伴う
# ため、この値をそのまま差し込むと「次の話題の話題」のような重複表現に
# なる（BEE-697）。フォールバック時はこの値と等しいかどうかで判定し、
# 専用テンプレート（_FALLBACK_TRANSITION_PHRASES等）に切り替える。
_FALLBACK_TOPIC = "次の話題"

# _is_broken_transition_text が不正として検出すべき、フォールバック話題名の
# 重複表現（BEE-697）。
_DUPLICATE_FALLBACK_TOPIC_PATTERNS = (
    f"{_FALLBACK_TOPIC}の話題",
    f"{_FALLBACK_TOPIC}のニュース",
)

_TOPIC_MAX_LEN = 25

# 話題名の切り詰めに使う境界文字。この文字の直後でのみ切ることで、
# 「事実があっ（た）」「口から吐き出（す）」のような語中切断を防ぐ（BEE-676）。
_TOPIC_BOUNDARY_CHARS = "、,;：・"

# 話題名の末尾がこれらの助詞で終わっていると、テンプレート側の助詞と
# 連結した際に「個別接種にを」のような助詞の二重連結が生じる（BEE-676）。
# 長い助詞から先に判定する（「から」を「は」等より先に判定しないと、
# 「から」の「は」部分だけが誤って一致することはないが、意図を明確にする
# ため長い順に並べる）。
_TOPIC_TRAILING_PARTICLES = ("から", "まで", "より", "は", "が", "を", "に", "へ", "で", "と", "も", "や")


def _strip_trailing_particle(text: str) -> str:
    """話題名の末尾の助詞を取り除き、テンプレート側の助詞との二重連結
    （「個別接種にを」等）を防ぐ（BEE-676）。"""
    stripped = text
    for _ in range(2):  # 助詞が連続するケースに備えて最大2回まで
        for particle in _TOPIC_TRAILING_PARTICLES:
            if len(stripped) > len(particle) and stripped.endswith(particle):
                stripped = stripped[: -len(particle)]
                break
        else:
            break
    return stripped


def _truncate_topic_at_boundary(text: str, max_len: int = _TOPIC_MAX_LEN) -> str | None:
    """text を max_len 文字以内に切り詰める。固定位置での機械的な切り詰めは
    語の途中で切れる（BEE-676: 「事実があっ」「口から吐き出」）ため、
    区切り文字（、・等）の直後でのみ切る。max_len 以内に区切り文字が
    見つからない場合は None を返し、呼び出し側で安全な代替に
    フォールバックさせる。"""
    stripped = text.strip()
    if len(stripped) <= max_len:
        return stripped
    boundary = -1
    for i, ch in enumerate(stripped[:max_len]):
        if ch in _TOPIC_BOUNDARY_CHARS:
            boundary = i
    if boundary <= 0:
        return None
    return stripped[:boundary]


def _safe_topic_from_title(raw_title: str) -> str:
    """タイトルから安全な話題名を作る。語中切断になる場合は汎用の代替語へ
    フォールバックする（不完全な話題名は生成しない、BEE-676）。"""
    if not raw_title:
        return _FALLBACK_TOPIC
    truncated = _truncate_topic_at_boundary(raw_title)
    if not truncated:
        return _FALLBACK_TOPIC
    finalized = _strip_trailing_particle(truncated.strip())
    return finalized or _FALLBACK_TOPIC


# 口語で読み上げるMCの短い橋渡しひとことを想定した上限文字数。Narrative Arc
# の bridge_text は本来「文脈・対比・共通点」を示す分析的な説明文として
# 生成されることがあり、そのまま読み上げ用のtransitionに差し込むと
# 「Aの〜から、Bの〜へ。」のような冗長なメタ注記になる（BEE-676, episode362）。
_BRIDGE_TEXT_MAX_LEN = 40

# 「安全への警戒から、秩序の変化へ。」のように、40文字以下・単文であっても
# 「Aの〜から、Bの〜へ」型の分析的な対比表現になっているbridge_textを検出する
# パターン（BEE-676 must指摘、CodeReviewer）。文字数・単文チェックだけでは、
# この種の短い分析的メタ注記を弾けず、前記事の分析と次記事告知が同一行に
# 混在した状態のまま既知テンプレートに一致してしまう。
_ANALYTICAL_CONTRAST_BRIDGE_RE = _re.compile(r"から[、,]?.*へ[。！？]?$")


def _is_usable_bridge_text(bridge_text: str) -> bool:
    """bridge_text が、そのままMCの短い橋渡し1文として読み上げるのに適した
    品質かどうかを判定する。既知テンプレートの形状に一致していても、
    差し込まれる bridge_text 自体が長い・複文・分析的な対比表現・前記事への
    後方参照であれば安全な通常テンプレートへフォールバックさせる（BEE-676:
    既知テンプレート一致だけでは壊れた遷移文を安全と判定してしまう問題への
    対策）。"""
    stripped = (bridge_text or "").strip()
    if not stripped:
        return False
    if len(stripped) > _BRIDGE_TEXT_MAX_LEN:
        return False
    if not _is_single_clean_sentence(stripped):
        return False
    if _ANALYTICAL_CONTRAST_BRIDGE_RE.search(stripped):
        return False
    if any(marker in stripped for marker in _BACKWARD_REFERENCE_MARKERS):
        return False
    return True


def _ensure_transitions(lines: list, summaries: list, arc: dict | None = None) -> list:
    """LLM が生成した lines を後処理し、article_id 切り替わり境界に
    transition 行を確実に挿入して返す。LLM が既に挿入した transition は保持する。

    arc が与えられた場合、bridges 情報を参照して Contextual Bridge を
    考慮した transition 文を生成する。"""
    bridge_map: dict = {}
    if arc and isinstance(arc, dict):
        for b in arc.get("bridges", []):
            if not isinstance(b, dict):
                continue
            from_id = b.get("from_article_id")
            to_id = b.get("to_article_id")
            bridge_text = b.get("bridge_text", "")
            if from_id is not None and to_id is not None and bridge_text:
                bridge_map.setdefault(from_id, {})[to_id] = bridge_text

    topic_map: dict = {}
    sensitive_article_ids: set = set()
    for art in summaries:
        art_id = art.get("id")
        if art_id is not None:
            if _is_sensitive_news(art):
                sensitive_article_ids.add(art_id)
            raw_summary = art.get("summary", "") or ""
            raw_title = art.get("title") or art.get("url", "") or ""
            candidate = ""
            if raw_summary:
                sentence_end = -1
                for sep in ("。", "…", "..."):
                    idx = raw_summary.find(sep)
                    if idx >= 0 and (sentence_end < 0 or idx < sentence_end):
                        sentence_end = idx + len(sep)
                if sentence_end > 0:
                    candidate = raw_summary[:sentence_end]
                else:
                    candidate = _re.split(r"[、,;：]", raw_summary)[0].strip()
            if candidate and len(candidate) <= _TOPIC_MAX_LEN:
                topic_map[art_id] = _strip_trailing_particle(candidate) or _safe_topic_from_title(raw_title)
            elif raw_title:
                title_clean = _re.split(r"[、,;：・]", raw_title)[0].strip()
                if title_clean and 3 <= len(title_clean) <= _TOPIC_MAX_LEN:
                    topic_map[art_id] = _strip_trailing_particle(title_clean) or _safe_topic_from_title(raw_title)
                else:
                    topic_map[art_id] = _safe_topic_from_title(raw_title)
            else:
                topic_map[art_id] = _FALLBACK_TOPIC

    def _topic(article_id) -> str:
        if article_id is None:
            return _FALLBACK_TOPIC
        return topic_map.get(article_id, _FALLBACK_TOPIC)

    result: list = []
    last_content_aid = None   # 直前の news/discussion の article_id
    trans_phrase_used = {"last": None}  # 乱択重複回避用状態
    reaction_phrase_used = {"last": None}  # 短い受けフレーズの乱択重複回避用状態

    for line in lines:
        section = line.get("section", "news")
        article_id = line.get("article_id")

        if section in ("news", "discussion"):
            prev_is_transition = bool(result) and result[-1].get("section") == "transition"

            # LLM が transition を出力していても、その article_id が現在の記事と
            # 一致しない場合は誤った帰属とみなし、LLM の transition を削除して
            # プログラム側の transition で置き換える
            if prev_is_transition:
                llm_trans_aid = result[-1].get("article_id")
                if llm_trans_aid is not None and llm_trans_aid != article_id:
                    removed = result.pop()
                    logger.debug("LLM transition 削除(article_id不一致): article_id=%s text=%s", removed.get("article_id"), removed.get("text", "")[:60])
                    # 削除後もブロックの残り（同じ記事境界に属する他のtransition行）
                    # が続く場合は、直後の複文混在チェックで漏れなく再検査できる
                    # よう prev_is_transition を結果の実状態から再評価する
                    # （直前の実装は無条件で False に落としており、article_id
                    # 不一致行の下に隠れた壊れたtransitionを見逃していた。BEE-672）
                    prev_is_transition = bool(result) and result[-1].get("section") == "transition"

            # LLM が記事境界を出力済みの場合も、次の記事が災害・重大事故なら
            # 肯定的な相槌や軽い導入を中立表現へ置換する。これによりテンプレート
            # だけでなく、LLM が生成した「楽しみですね。」も残さない。
            if prev_is_transition and article_id in sensitive_article_ids:
                for index in range(len(result) - 1, -1, -1):
                    transition_line = result[index]
                    if transition_line.get("section") != "transition":
                        break
                    if _has_inappropriate_sensitive_transition_text(transition_line.get("text", "")):
                        replacement = dict(transition_line)
                        replacement["text"] = _pick_phrase(
                            _SENSITIVE_TRANSITION_REACTION_PHRASES, reaction_phrase_used
                        )
                        result[index] = replacement
                        logger.info(
                            "災害・重大事故ニュース直前の不適切なtransitionを置換: article_id=%s",
                            article_id,
                        )

            # article_id は次の記事と一致していても、前の記事の締め文と次の記事の
            # 告知が1行に混在した壊れたtransitionは記事境界（news）でのみ検知して
            # 破棄する（BEE-661/BEE-662）。discussion直前のtransitionはテンプレート
            # 自体が複文（「気になりますね。どう思います？」等）を前提とするため対象外。
            # last_content_aid is None（intro直後で前の記事が存在しない）場合も対象外。
            #
            # 直前1行だけでなく、直前から連続する transition 行（同じ記事境界に
            # 属するブロック）全体を検査する。壊れた遷移文の直後に正常な短い
            # 反応行が続く場合、直前1行のみの検査ではその反応行に隠れて壊れた
            # 遷移文を見逃すため（BEE-672）。
            if prev_is_transition and section == "news" and last_content_aid is not None:
                block_start = len(result)
                while block_start > 0 and result[block_start - 1].get("section") == "transition":
                    block_start -= 1
                if any(_is_broken_transition_text(line.get("text", "")) for line in result[block_start:]):
                    removed = result[block_start:]
                    del result[block_start:]
                    for r in removed:
                        logger.debug("LLM transition 削除(複文混在): article_id=%s text=%s", r.get("article_id"), r.get("text", "")[:60])
                    prev_is_transition = False

            # article_id が変わった（または intro→news）かつ直前が transition でない場合に挿入
            if not prev_is_transition and article_id != last_content_aid:
                speaker = _pick_speaker(result, section)
                topic = _topic(article_id)
                # トピック抽出がフォールバックした場合、通常テンプレートの固定
                # 接尾辞（「の話題」「のニュース」）と結合すると重複表現になる
                # ため、専用テンプレートに切り替える（BEE-697）。
                is_fallback_topic = topic == _FALLBACK_TOPIC
                if section == "discussion":
                    phrases = _DISCUSSION_TRANSITIONS
                    text = _pick_phrase(phrases, trans_phrase_used).format(topic=topic)
                elif (
                    last_content_aid is not None
                    and last_content_aid in bridge_map
                    and article_id in bridge_map[last_content_aid]
                    and _is_usable_bridge_text(bridge_map[last_content_aid][article_id])
                ):
                    bridge_text = bridge_map[last_content_aid][article_id]
                    if is_fallback_topic:
                        text = _pick_phrase(_FALLBACK_BRIDGE_TRANSITION_PHRASES, trans_phrase_used).format(bridge=bridge_text)
                    else:
                        text = _pick_phrase(_BRIDGE_TRANSITION_PHRASES, trans_phrase_used).format(bridge=bridge_text, topic=topic)
                elif is_fallback_topic:
                    text = _pick_phrase(_FALLBACK_TRANSITION_PHRASES, trans_phrase_used)
                else:
                    phrases = _TRANSITION_PHRASES
                    text = _pick_phrase(phrases, trans_phrase_used).format(topic=topic)

                # 既知テンプレートへの一致だけでは安全と判定できない（BEE-676）ため、
                # プログラム自身が生成したtransitionも念のため同じ判定条件で
                # 検査し、万一壊れていれば bridge を使わない通常テンプレートへ
                # 差し替える最終防衛ラインとする。discussion直前のtransitionは
                # テンプレート自体が意図的な複文構成のため対象外（既存仕様どおり）。
                if section == "news" and _is_broken_transition_text(text):
                    logger.warning("生成したtransitionが壊れているため通常テンプレートへ差し替え: article_id=%s text=%s", article_id, text[:60])
                    if is_fallback_topic:
                        text = _pick_phrase(_FALLBACK_TRANSITION_PHRASES, trans_phrase_used)
                    else:
                        text = _pick_phrase(_TRANSITION_PHRASES, trans_phrase_used).format(topic=topic)
                result.append({
                    "speaker": speaker,
                    "text": text,
                    "article_id": article_id,
                    "section": "transition",
                    "delivery": "neutral",
                })
                logger.debug("transition 挿入: article_id=%s text=%s", article_id, text)

                # 記事境界（news）のtransitionは両MCの短い掛け合い（2行）にする（BEE-630）。
                # discussion直前のtransitionは従来どおり1行のまま維持する。
                if section == "news":
                    reaction_speaker = "female" if speaker == "male" else "male"
                    reaction_phrases = (
                        _SENSITIVE_TRANSITION_REACTION_PHRASES
                        if article_id in sensitive_article_ids
                        else _TRANSITION_REACTION_PHRASES
                    )
                    reaction_text = _pick_phrase(reaction_phrases, reaction_phrase_used)
                    result.append({
                        "speaker": reaction_speaker,
                        "text": reaction_text,
                        "article_id": article_id,
                        "section": "transition",
                        "delivery": "neutral",
                    })
                    logger.debug("transition 短い受け挿入: article_id=%s text=%s", article_id, reaction_text)

            last_content_aid = article_id

        elif section == "intro":
            last_content_aid = None

        result.append(line)

    return result


# ---------------------------------------------------------------------------
# Auto-Linter
# ---------------------------------------------------------------------------

# 禁止フレーズ（プロンプトの Forbidden Phrases と同期すること）
_FORBIDDEN_PHRASES = [
    "ここで大事なのは、背景ですよね",
    "ここで大事なのは背景ですよね",
    "といったところです。",
    "といった内容です。",
    "一見シンプルに見えますが、実は構造的な問題があります",
    "これは感情論だけでは片づけられません",
    "これ、普通に暮らしている人からするとかなり大きいですよね",
    "正直、そこが一番気になります",
    "視聴者の方も、ここはモヤっとすると思います",
]

# 数字なしで使うと問題になる表現（単体検出用）
_REQUIRES_DIGITS = [
    "数字で見ると",
    "数字だけ見ると分かるんですけど",
]


def _has_digits(text: str) -> bool:
    """テキスト中に数字（全角・半角）または具体的な量を示す単語が含まれるか。"""
    import re
    return bool(re.search(r"[0-9０-９]|[一二三四五六七八九十百千万億兆](?:人|件|回|社|倍|円|割|%|パーセント)", text))


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """2つの文字列の正規化Levenshtein類似度を返す（0.0〜1.0）。"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    len1, len2 = len(s1), len(s2)
    prev = list(range(len1 + 1))
    for i, ch2 in enumerate(s2, 1):
        curr = [i]
        for j, ch1 in enumerate(s1, 1):
            cost = 0 if ch1 == ch2 else 1
            curr.append(min(
                curr[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    distance = prev[len1]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


def lint_script(
    lines: list,
    program_name: str = "ニュースのとなり",
    bridges: list[dict] | None = None,
    expected_discussion_article_id=None,
) -> list[str]:
    """生成済み lines に対して品質チェックを行い、問題点のリストを返す。
    返値が空リストなら合格。

    expected_discussion_article_id: Narrative Arc で選定された discussion 対象記事の
    article_id。指定した場合、discussion内のarticle_idがこれと一致するかも検査する
    （BEE-630 レビュー指摘: 内部的に統一されていても、選定記事と異なる記事に統一されて
    しまうケースを検出できていなかった）。
    """
    errors: list[str] = []

    seen_texts: set[str] = set()

    # --- ルール1: introフォーマットチェック [INTRO_FORMAT] (ERROR) ---
    intro_lines = [(i, line) for i, line in enumerate(lines) if line.get("section") == "intro"]
    if intro_lines:
        first_intro_text = intro_lines[0][1].get("text", "").strip()
        expected_prefix = f"「{program_name}」の時間です"
        if not first_intro_text.startswith(expected_prefix):
            errors.append(
                f"[INTRO_FORMAT] introの1行目が「{expected_prefix}」で始まっていません: "
                f"「{first_intro_text[:50]}」"
            )
    else:
        errors.append("[INTRO_FORMAT] introセクションが存在しません")

    # --- ルール2: introラインアップチェック [INTRO_LINEUP] (WARN) ---
    intro_texts = [line.get("text", "") for line in lines if line.get("section") == "intro"]
    if intro_texts:
        combined = "".join(intro_texts)
        lineup_keywords = ["ラインナップ", "ラインアップ", "トピック", "本日", "今日", "今回", "ニュース"]
        found = [kw for kw in lineup_keywords if kw in combined]
        if len(found) < 2:
            errors.append(
                f"[INTRO_LINEUP] introにラインアップを示唆する表現が不足しています "
                f"(検出されたキーワード: {found})"
            )

    # --- ルール3: outro充実度チェック [OUTRO_LENGTH] (ERROR) ---
    outro_count = sum(1 for line in lines if line.get("section") == "outro")
    if outro_count < 2:
        errors.append(
            f"[OUTRO_LENGTH] outroセクションが{outro_count}行しかありません（最低2行必要）"
        )

    # --- ルール4: transitionバリエーションチェック [TRANS_VARIATION] (ERROR) ---
    trans_lines = [
        (i, line.get("text", "").strip())
        for i, line in enumerate(lines)
        if line.get("section") == "transition" and line.get("text", "").strip()
    ]
    _TRANS_SIMILARITY_THRESHOLD = float(os.getenv("LINT_TRANS_SIMILARITY", "0.7"))
    for idx_a in range(len(trans_lines)):
        for idx_b in range(idx_a + 1, len(trans_lines)):
            i, text_i = trans_lines[idx_a]
            j, text_j = trans_lines[idx_b]
            ratio = _levenshtein_ratio(text_i, text_j)
            if ratio >= _TRANS_SIMILARITY_THRESHOLD:
                errors.append(
                    f"[TRANS_VARIATION] transition行 {i} と {j} の類似度が {ratio:.2f} です: "
                    f"「{text_i[:30]}...」「{text_j[:30]}...」"
                )

    # --- ルール5: transitionコンテキストチェック [TRANS_CONTEXT] (ERROR) ---
    if bridges:
        first_trans_idx: int | None = None
        for i, line in enumerate(lines):
            if line.get("section") == "transition":
                first_trans_idx = i
                break
        for i, line in enumerate(lines):
            if line.get("section") != "transition":
                continue
            if i == first_trans_idx:
                continue
            text = line.get("text", "").strip()
            if not text:
                continue
            if _re.search(r"次の話題|次のトピック", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"^続いては", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"^次は", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"では次", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")

    # discussion が全 news の後に来ているか確認
    sections = [line.get("section") for line in lines]
    discussion_indices = [i for i, s in enumerate(sections) if s == "discussion"]
    news_indices = [i for i, s in enumerate(sections) if s == "news"]
    if discussion_indices and news_indices:
        last_news = max(news_indices)
        first_discussion = min(discussion_indices)
        if first_discussion < last_news:
            errors.append(
                f"discussion が全 news より前に挿入されています "
                f"(discussion 最初の行インデックス={first_discussion}, 最後の news インデックス={last_news})"
            )

    # --- ルール6: discussion行数チェック [DISCUSSION_LENGTH] (ERROR) ---
    # 対象記事の根拠のみで4〜8行の対話にする受入条件（BEE-630 QA指摘）を検査する
    if discussion_indices:
        discussion_count = len(discussion_indices)
        if not (4 <= discussion_count <= 8):
            errors.append(
                f"[DISCUSSION_LENGTH] discussionが{discussion_count}行です（4〜8行である必要があります）"
            )

        # --- ルール7: discussion記事逸脱チェック [DISCUSSION_ARTICLE_DRIFT] (ERROR) ---
        # discussion は選んだ1本の記事のみを深掘りする前提のため、article_id が
        # 混在している場合は他記事の話題が紛れ込んでいる兆候として検出する
        discussion_article_ids = {
            lines[i].get("article_id") for i in discussion_indices
        }
        if len(discussion_article_ids) > 1:
            errors.append(
                f"[DISCUSSION_ARTICLE_DRIFT] discussion内でarticle_idが複数混在しています: "
                f"{sorted(str(a) for a in discussion_article_ids)}（1本の記事に統一してください）"
            )
        elif (
            expected_discussion_article_id is not None
            and discussion_article_ids != {expected_discussion_article_id}
        ):
            actual_aid = next(iter(discussion_article_ids))
            errors.append(
                f"[DISCUSSION_ARTICLE_DRIFT] discussionのarticle_id={actual_aid} が"
                f"選定記事(article_id={expected_discussion_article_id})と一致しません"
                "（別記事の話題を深掘りしている可能性があります）"
            )

    # --- ルール8: 記事境界transitionの単独告知チェック [TRANSITION_SOLO] (ERROR) ---
    # discussion直前のtransitionを除き、記事境界のtransitionは両MCの短い掛け合い
    # （2行以上・話者が異なる）である必要がある（BEE-630 QA指摘）
    transition_blocks: list[list[int]] = []
    _current_block: list[int] = []
    for i, s in enumerate(sections):
        if s == "transition":
            _current_block.append(i)
        elif _current_block:
            transition_blocks.append(_current_block)
            _current_block = []
    if _current_block:
        transition_blocks.append(_current_block)

    discussion_precursor_block = None
    if discussion_indices:
        first_discussion = min(discussion_indices)
        for block in transition_blocks:
            if block[-1] == first_discussion - 1:
                discussion_precursor_block = block
                break

    for block in transition_blocks:
        if block is discussion_precursor_block:
            continue
        if len(block) < 2:
            errors.append(
                f"[TRANSITION_SOLO] transition行 {block} が1行の単独告知になっています"
                "（記事境界のtransitionは両MCの短い掛け合い2行にしてください）"
            )
        elif lines[block[0]].get("speaker") == lines[block[-1]].get("speaker"):
            errors.append(
                f"[TRANSITION_SOLO] transition行 {block} の話者が同一です"
                "（記事境界のtransitionはもう一方のMCが短く受ける構成にしてください）"
            )

    for i, line in enumerate(lines):
        text = line.get("text", "").strip()
        section = line.get("section", "")
        speaker = line.get("speaker", "")

        # 重複テキスト検出
        if text and text in seen_texts:
            errors.append(f"行 {i}: テキストが重複しています: 「{text[:40]}...」")
        if text:
            seen_texts.add(text)

        # 禁止フレーズ検出
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in text:
                errors.append(f"行 {i} ({speaker}): 禁止フレーズ「{phrase}」が含まれています")

        # 「数字で見ると」系フレーズで数字がない場合
        for req in _REQUIRES_DIGITS:
            if req in text and not _has_digits(text):
                errors.append(
                    f"行 {i} ({speaker}): 「{req}」を使っているが具体的な数字・データが含まれていません"
                )

        # transition行の不完全チェック（WARN: 演出上の「間」意図の可能性を考慮し警告レベル）
        if section == "transition":
            if _re.search(r"[……‥]{2,}$", text):
                errors.append(f"[WARN][TRUNCATED_TRANS] transition行 {i} が不完全な文で終わっています: 「{text[:40]}...」")
            elif len(text) < 5:
                errors.append(f"[WARN][TRUNCATED_TRANS] transition行 {i} が短すぎます: 「{text[:40]}...」")

        # 記事IDのトピック表記（「記事XX」「（ID: XX）」など）を検出
        id_refs = [
            r"(?:^|[^a-zA-Z0-9])(?:記事)\d+",
            r"\(ID:\s*\d+\)",
            r"article_id[=：:]\s*\d+",
        ]
        for pattern in id_refs:
            for m in _re.finditer(pattern, text):
                errors.append(f"行 {i} ({speaker}): 記事IDの参照表記が検出されました: 「{m.group(0).strip()}」")

        # 全角ブラケット〔...〕（U+3014/U+3015）がtextに含まれていないかチェック
        if _re.search(r"〔[^〕]*〕", text):
            errors.append(
                f"行 {i} ({speaker}): textにプレースホルダー表記〔...〕が含まれています: "
                f"「{text[:50]}」"
            )

    return errors


def _build_correction_prompt(original_prompt: str, lines: list, errors: list[str]) -> str:
    """Linter エラーに基づいて修正指示付きプロンプトを生成する。"""
    errors_text = "\n".join(f"- {e}" for e in errors)
    lines_json = json.dumps(lines, ensure_ascii=False, indent=2)
    return (
        f"{original_prompt}\n\n"
        "# ⚠️ 前回の生成で以下の品質問題が検出されました。これらをすべて修正して再生成してください。\n\n"
        f"{errors_text}\n\n"
        "## 前回生成した lines（修正対象）:\n"
        f"```json\n{lines_json}\n```\n\n"
        "上記の問題を修正した完全な台本 JSON を出力してください。"
    )


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_radio_script.md"
    return prompt_path.read_text(encoding="utf-8")


def _load_arc_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_narrative_arc.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_narrative_arc_section(arc: dict, summaries: list) -> str:
    """Narrative Arc の情報をプロンプトに注入するセクション文字列を生成する。"""
    id_to_title = {s["id"]: (s.get("title") or s.get("url", ""))[:40] for s in summaries}

    lines = [
        "# 今回のエピソード設計（Narrative Arc）\n",
        f"**共通テーマ**: {arc.get('theme', '')}",
        f"**テーマ概要**: {arc.get('theme_description', '')}",
        "",
        "**記事の紹介順序**（この順番で全記事を紹介すること）:",
    ]
    for i, aid in enumerate(arc.get("article_order", []), 1):
        title = id_to_title.get(aid, f"記事{aid}")
        lines.append(f"  {i}. 記事ID={aid}：{title}")

    bridges = arc.get("bridges", [])
    if bridges:
        lines.append("")
        lines.append("**記事間の橋渡し（Contextual Bridge）**（transition行でこの文脈を活かすこと）:")
        for b in bridges:
            if not isinstance(b, dict):
                continue
            from_id = b.get("from_article_id")
            to_id = b.get("to_article_id")
            bridge = b.get("bridge_text", "")
            lines.append(f"  - 記事{from_id} → 記事{to_id}: {bridge}")

    disc_id = arc.get("discussion_article_id")
    disc_reason = arc.get("discussion_reason", "")
    if disc_id:
        lines.append("")
        lines.append(f"**discussion で深掘りする記事**: 記事ID={disc_id}（{id_to_title.get(disc_id, '')}）")
        lines.append(f"  理由: {disc_reason}")

    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Step 1: Architect — Narrative Arc 生成
# ---------------------------------------------------------------------------

def _generate_arc(client: OllamaClient, summaries: list) -> dict | None:
    """Narrative Arc を生成して返す。失敗時は None。"""
    template = _load_arc_prompt_template()
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    prompt = template.format(summaries_json=summaries_json)

    arc = client.generate_json(prompt)
    if not arc or not isinstance(arc.get("article_order"), list):
        logger.warning("Narrative Arc generation failed or returned invalid structure; skipping arc")
        return None

    logger.info(
        "Narrative Arc generated: theme=%s order=%s discussion=%s",
        arc.get("theme", ""),
        arc.get("article_order", []),
        arc.get("discussion_article_id"),
    )
    return arc


# ---------------------------------------------------------------------------
# Step 2: Writer — 台本生成
# ---------------------------------------------------------------------------

def _reorder_summaries(summaries: list, article_order: list) -> list:
    """arc の article_order に従って summaries を並べ替える。未収録 ID はそのまま末尾に追加。"""
    id_map = {s["id"]: s for s in summaries}
    reordered = [id_map[aid] for aid in article_order if aid in id_map]
    seen = set(article_order)
    reordered += [s for s in summaries if s["id"] not in seen]
    return reordered


def generate_script(
    output_path: str,
    program_name: str = "ニュースのとなり",
    news_source: str | None = None,
    program_settings: ProgramSettings | None = None,
    max_articles: int | None = None,
    min_importance_score: int | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> int:
    settings = get_settings()
    profile = program_settings or get_settings_or_default()
    generation_params = profile.generation_params()
    max_articles = max_articles if max_articles is not None else int(
        os.getenv("MAX_SCRIPT_ARTICLES", str(generation_params["max_articles"]))
    )
    min_score = min_importance_score if min_importance_score is not None else int(
        os.getenv("MIN_IMPORTANCE_SCORE", str(generation_params["min_importance_score"]))
    )

    if news_source is None and program_name == "テックニュース":
        news_source = "hatena_bookmark"

    service = ArticleService()
    summaries = service.fetch_summaries_for_script(
        max_articles=max_articles,
        min_importance_score=min_score,
        source=news_source,
        priority_themes=profile.priority_themes,
        excluded_themes=profile.excluded_themes,
    )
    if not summaries:
        logger.warning("No summaries to generate script from")
        return 0

    article_urls = ", ".join(
        f"{article['id']}:{article.get('url', '<no-url>')}" for article in summaries
    )
    logger.info("Generating script from summaries: %s", article_urls)

    response = None
    ordered_summaries = summaries  # デフォルトは元の順序

    client_factory = (lambda: create_llm_client(llm_provider, llm_model)) if (llm_provider or llm_model) else (lambda: OllamaClient(settings.ollama_base_url, settings.ollama_model))
    with client_factory() as client:

        # --- Step 1: Architect — Narrative Arc 生成 ---
        logger.info("=== Script Step 1/2: Narrative Arc (Architect) ===")
        arc = _generate_arc(client, summaries)

        # Arc に基づいて記事の順序を確定
        if arc and arc.get("article_order"):
            ordered_summaries = _reorder_summaries(summaries, arc["article_order"])
            narrative_arc_section = _build_narrative_arc_section(arc, summaries)
        else:
            narrative_arc_section = ""

        # --- Step 2: Writer — 台本生成 + Auto-Lint 再生成ループ ---
        logger.info("=== Script Step 2/2: Script generation (Writer) ===")
        template = _load_prompt_template()
        if program_name != "ニュースのとなり":
            template = template.replace("ニュースのとなり", program_name)
        summaries_json = json.dumps(ordered_summaries, ensure_ascii=False, indent=2)
        base_prompt = template.format(
            narrative_arc_section=narrative_arc_section,
            summaries_json=summaries_json,
        )

        _MAX_LINT_RETRIES = int(os.getenv("SCRIPT_LINT_RETRIES", "3"))
        current_prompt = base_prompt

        for lint_attempt in range(1, _MAX_LINT_RETRIES + 1):
            response = client.generate_json(current_prompt)
            if response is None or not isinstance(response.get("lines"), list):
                logger.error("Invalid script JSON generated (attempt=%d). Raw response: %s", lint_attempt, response)
                break

            lint_errors = lint_script(
                response["lines"],
                program_name=program_name,
                bridges=arc.get("bridges", []) if arc else None,
                expected_discussion_article_id=arc.get("discussion_article_id") if arc else None,
            )
            if not lint_errors:
                logger.info("Auto-Lint PASSED (attempt=%d)", lint_attempt)
                break

            logger.warning(
                "Auto-Lint FAILED (attempt=%d/%d): %d issues found:\n%s",
                lint_attempt,
                _MAX_LINT_RETRIES,
                len(lint_errors),
                "\n".join(f"  - {e}" for e in lint_errors),
            )
            if lint_attempt < _MAX_LINT_RETRIES:
                current_prompt = _build_correction_prompt(base_prompt, response["lines"], lint_errors)
            # 最終試行で失敗してもそのまま使用（最善の結果を保持）

    if response is None or not isinstance(response.get("lines"), list):
        logger.error("Invalid script JSON generated")
        return 0

    script = {
        "date": str(date.today()),
        "title": str(response.get("title", program_name)),
        "subtitle": str(response.get("subtitle", "")),
        "lines": [],
    }

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if speaker not in {"male", "female"}:
            speaker = "male"
        section = str(line.get("section", "news"))
        if section not in {"intro", "news", "transition", "discussion", "outro"}:
            section = "news"
        
        text = str(line.get("text", "")).strip()
        text = _re.sub(r"〔[^〕]*〕", "", text).strip()

        script["lines"].append(
            {
                "speaker": speaker,
                "text": text,
                "article_id": line.get("article_id"),
                "section": section,
                "delivery": line.get("delivery", "neutral"),
            }
        )

    # LLM が transition を省略した場合に備えてプログラム側で補完する
    script["lines"] = _ensure_transitions(script["lines"], ordered_summaries, arc=arc)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(script, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("script generated lines=%d output=%s", len(script["lines"]), output_path)

    # 使用した記事を 'used' にマーク → 次エピソードで重複使用されないようにする
    used_ids = [a["id"] for a in summaries]
    service.mark_articles_used(used_ids)
    logger.info("marked %d articles as used", len(used_ids))

    return len(script["lines"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes", "script.json")
    count = generate_script(out)
    print(json.dumps({"lines": count}, ensure_ascii=False))
    sys.exit(0 if count > 0 else 1)
