import json
import math
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import unicodedata

from app.db.connection import get_db_connection
from app.services.settings_service import TopicSetting, topic_fingerprint

logger = logging.getLogger(__name__)


JST = timezone(timedelta(hours=9))

# タイトルの表記揺れだけを吸収する閾値。本文やURLを使わず、かなり似た
# タイトルだけを対象にすることで、別イベントの誤除外を避ける。
_TITLE_SIMILARITY_THRESHOLD = 0.92
_CROSS_LANGUAGE_TOKEN_THRESHOLD = 0.68
_MIN_SEMANTIC_TOKEN_COVERAGE = 0.5

# 同じカテゴリの記事が一つのエピソードに偏りすぎないための上限。
# 要約時に保存している category はLLMの分類結果であり、追加のクラスタリングを
# 行わずに利用できる唯一の安定したテーマ情報なので、初期値は2件に限定する。
_MAX_ARTICLES_PER_TOPIC = 2
_KNOWN_TOPIC_CATEGORIES = {
    "technology", "business", "society", "sports", "entertainment", "general",
}
_HIGH_IMPACT_SCORE_THRESHOLD = 4
_CANDIDATE_POOL_MULTIPLIER = 5
_MAX_CANDIDATE_POOL_SIZE = 100


def write_fallback_summaries(output_path: str, summaries: list[dict[str, Any]]) -> None:
    """Persist DB-backed summaries in the file format consumed by reviewers.

    ``fetch_summaries_for_script`` returns the DB column as ``id`` while
    ``summarize_articles`` writes the same value as ``article_id``. Keeping the
    normalization and serialization here prevents the batch and web pipelines
    from drifting apart.
    """
    # 審査の根拠ファイルもLLMへ渡るため、トピック関連のキーは含めない。
    normalized = [
        {**summary, "article_id": summary.get("article_id", summary.get("id"))}
        for summary in without_topic_fields([item for item in summaries if isinstance(item, dict)])
    ]
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

# 要約プロンプトの category には天気・災害の専用値がないため、category/title/summary
# の既存テキストに現れる明示語を連続抑制用の一つのグループとして扱う。
_WEATHER_DISASTER_CATEGORIES = {"weather", "disaster", "防災", "災害", "気象"}
_WEATHER_DISASTER_KEYWORDS = (
    "天気", "気象", "降雨", "雨量", "大雨", "雨雲", "雨天", "雷雨", "大雪", "雪害",
    "積雪", "降雪", "豪雪", "雪崩", "雪解け", "雪道", "落雷", "雷雲", "雷鳴",
    "猛暑", "酷暑", "熱波", "台風", "豪雨",
    "洪水", "浸水", "土砂", "線状降水帯", "地震", "震度", "津波", "火山", "噴火",
    "竜巻", "災害", "防災", "避難", "警報", "注意報", "警戒", "被災",
    "weather", "disaster", "earthquake", "typhoon", "flood", "landslide",
)

# 社名と一緒に頻出する定型語は、アンカー以外の意味的な一致とはみなさない。
# 日本語カタカナ語はローマ字形も登録し、security／セキュリティ等を同じ扱いにする。
_GENERIC_TITLE_TERMS = {
    "announce", "announced", "announces", "announcement", "announcements",
    "model", "models", "news", "product", "products", "review", "reviews",
    "security", "response", "responses", "update", "updates",
    "対応", "公開", "発表", "sekyuriti", "moderu", "nyusu", "purodaku", "rebyu",
}

# カタカナを標準ライブラリだけで比較用のローマ字へ変換するための表。
# 翻訳ではなく音の近さを見る目的なので、未収録の文字はそのまま残す。
_KATAKANA_ROMAJI = {
    "イェ": "ye", "ウィ": "wi", "ウェ": "we", "ウォ": "wo",
    "ヴァ": "va", "ヴィ": "vi", "ヴェ": "ve", "ヴォ": "vo",
    "ヴュ": "vyu", "クァ": "kwa", "クィ": "kwi", "クェ": "kwe", "クォ": "kwo",
    "グァ": "gwa", "グィ": "gwi", "グェ": "gwe", "グォ": "gwo",
    "シェ": "she", "ジェ": "je", "チェ": "che", "ティ": "ti", "トゥ": "tu",
    "ディ": "di", "ドゥ": "du", "ニェ": "nye", "ヒェ": "hye", "ビェ": "bye",
    "ピェ": "pye", "ミェ": "mye", "リェ": "rye",
    "キャ": "kya", "キュ": "kyu", "キョ": "kyo", "ギャ": "gya", "ギュ": "gyu", "ギョ": "gyo",
    "シャ": "sha", "シュ": "shu", "ショ": "sho", "ジャ": "ja", "ジュ": "ju", "ジョ": "jo",
    "チャ": "cha", "チュ": "chu", "チョ": "cho", "ニャ": "nya", "ニュ": "nyu", "ニョ": "nyo",
    "ヒャ": "hya", "ヒュ": "hyu", "ヒョ": "hyo", "ビャ": "bya", "ビュ": "byu", "ビョ": "byo",
    "ピャ": "pya", "ピュ": "pyu", "ピョ": "pyo", "ミャ": "mya", "ミュ": "myu", "ミョ": "myo",
    "リャ": "rya", "リュ": "ryu", "リョ": "ryo",
    "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
    "カ": "ka", "キ": "ki", "ク": "ku", "ケ": "ke", "コ": "ko",
    "ガ": "ga", "ギ": "gi", "グ": "gu", "ゲ": "ge", "ゴ": "go",
    "サ": "sa", "シ": "shi", "ス": "su", "セ": "se", "ソ": "so",
    "ザ": "za", "ジ": "ji", "ズ": "zu", "ゼ": "ze", "ゾ": "zo",
    "タ": "ta", "チ": "chi", "ツ": "tsu", "テ": "te", "ト": "to",
    "ダ": "da", "ヂ": "ji", "ヅ": "zu", "デ": "de", "ド": "do",
    "ナ": "na", "ニ": "ni", "ヌ": "nu", "ネ": "ne", "ノ": "no",
    "ハ": "ha", "ヒ": "hi", "フ": "fu", "ヘ": "he", "ホ": "ho",
    "バ": "ba", "ビ": "bi", "ブ": "bu", "ベ": "be", "ボ": "bo",
    "パ": "pa", "ピ": "pi", "プ": "pu", "ペ": "pe", "ポ": "po",
    "マ": "ma", "ミ": "mi", "ム": "mu", "メ": "me", "モ": "mo",
    "ヤ": "ya", "ユ": "yu", "ヨ": "yo", "ラ": "ra", "リ": "ri", "ル": "ru", "レ": "re", "ロ": "ro",
    "ワ": "wa", "ヲ": "wo", "ン": "n", "ヮ": "wa", "ヵ": "ka", "ヶ": "ke",
    "ァ": "a", "ィ": "i", "ゥ": "u", "ェ": "e", "ォ": "o", "ャ": "ya", "ュ": "yu", "ョ": "yo",
}


def _hiragana_to_katakana(value: str) -> str:
    return "".join(
        chr(ord(char) + (ord("ァ") - ord("ぁ")))
        if "ぁ" <= char <= "ゖ" else char
        for char in value
    )


def _remove_combining_marks(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    result: list[str] = []
    for char in decomposed:
        # NFKDは「ペ」「デ」などの濁点も分解するため、日本語の結合文字は
        # 残す。ラテン文字のアクセントだけを落として jalapeño を jalapeno
        # と比較できるようにする。
        if unicodedata.combining(char):
            previous = result[-1] if result else ""
            if "ぁ" <= previous <= "ゖ" or "ァ" <= previous <= "ヿ":
                result.append(char)
            continue
        result.append(char)
    return unicodedata.normalize("NFC", "".join(result))


def normalize_title(title: str | None) -> str:
    """タイトル比較用に、幅・大小文字・アクセント・記号の揺れをそろえる。"""
    normalized = _remove_combining_marks(unicodedata.normalize("NFKC", title or "").casefold())
    normalized = _hiragana_to_katakana(normalized)
    return "".join(char for char in normalized if char.isalnum())


def _title_tokens(title: str | None) -> list[tuple[str, str]]:
    """タイトルを文字種の切り替わりでも分け、(token, script) を返す。"""
    normalized = _hiragana_to_katakana(
        _remove_combining_marks(unicodedata.normalize("NFKC", title or "").casefold())
    )
    tokens: list[tuple[str, str]] = []
    current: list[str] = []
    current_script: str | None = None

    def flush() -> None:
        nonlocal current, current_script
        if current:
            tokens.append(("".join(current), current_script or "other"))
            current = []
            current_script = None

    for char in normalized:
        if "ァ" <= char <= "ヿ":
            script = "kana"
        elif "一" <= char <= "鿿":
            script = "cjk"
        elif char.isalnum():
            script = "latin"
        else:
            flush()
            continue
        if current_script is not None and script != current_script:
            flush()
        current.append(char)
        current_script = script
    flush()
    return tokens


def _romanize_katakana(value: str) -> str:
    romanized: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "ッ":
            next_value = ""
            for length in (2, 1):
                next_value = _KATAKANA_ROMAJI.get(value[index + 1:index + 1 + length], "")
                if next_value:
                    break
            if next_value and next_value[0] not in "aeiouyn":
                romanized.append(next_value[0])
            index += 1
            continue
        matched = ""
        for length in (2, 1):
            matched = _KATAKANA_ROMAJI.get(value[index:index + length], "")
            if matched:
                index += length
                break
        if matched:
            romanized.append(matched)
        elif char != "ー":
            romanized.append(char)
            index += 1
        else:
            index += 1
    return "".join(romanized)


def _cross_language_similarity(left: tuple[str, str], right: tuple[str, str]) -> float:
    left_token, left_script = left
    right_token, right_script = right
    if left_script == right_script or {left_script, right_script} != {"kana", "latin"}:
        return 0.0
    kana_token = left_token if left_script == "kana" else right_token
    latin_token = left_token if left_script == "latin" else right_token
    kana_token = _strip_kana_particles(kana_token)
    romanized = _romanize_katakana(kana_token)
    if len(romanized) < 5 or len(latin_token) < 5:
        return 0.0
    return SequenceMatcher(None, romanized, latin_token, autojunk=False).ratio()


def _strip_kana_particles(token: str) -> str:
    """カタカナ語に付着した「の／を」等を比較用に取り除く。"""
    if token[:1] == "ノ":
        # 「AのB」のように、Bがカタカナ語だと先頭の助詞がBへ付着する。
        token = token[1:]
    if token[-1:] in {"ガ", "ハ", "ニ", "ヘ", "ヲ", "ノ", "ト", "デ", "モ", "ヤ"}:
        # 日本語の助詞がカタカナ語に連結した場合も、語幹同士を比較する。
        token = token[:-1]
    return token


def _meaningful_title_tokens(
    tokens: list[tuple[str, str]], excluded: set[str]
) -> list[tuple[str, str]]:
    meaningful: list[tuple[str, str]] = []
    for token, script in tokens:
        comparison_token = _strip_kana_particles(token) if script == "kana" else token
        minimum_length = 2 if script == "cjk" else 4
        generic_key = (
            _romanize_katakana(comparison_token)
            if script == "kana" else comparison_token
        )
        if (
            len(comparison_token) >= minimum_length
            and comparison_token not in excluded
            and generic_key not in _GENERIC_TITLE_TERMS
        ):
            meaningful.append((comparison_token, script))
    return meaningful


def titles_are_similar(left: str | None, right: str | None) -> bool:
    """高類似タイトルかを判定する（記事本文やURLは判定に使わない）。"""
    normalized_left = normalize_title(left)
    normalized_right = normalize_title(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    # 数字の差は版数・日付・順位などイベントを分けることが多いため、
    # 「2DaysAgo」と「3DaysAgo」のような合成テスト／実タイトルを保護する。
    if re.findall(r"\d+", normalized_left) != re.findall(r"\d+", normalized_right):
        return False
    if SequenceMatcher(None, normalized_left, normalized_right, autojunk=False).ratio() >= _TITLE_SIMILARITY_THRESHOLD:
        return True

    left_tokens = _title_tokens(left)
    right_tokens = _title_tokens(right)
    exact_anchors = {
        token for token, _ in left_tokens if len(token) >= 4
    } & {
        token for token, _ in right_tokens if len(token) >= 4
    }
    meaningful_left = _meaningful_title_tokens(left_tokens, exact_anchors)
    meaningful_right = _meaningful_title_tokens(right_tokens, exact_anchors)
    if not meaningful_left or not meaningful_right:
        return False

    # アンカー語（社名など）は補助情報に留め、アンカーを除いた意味語を
    # 一対一で照合する。片側だけの一般語の偶然一致を防ぐため、両側で
    # 少なくとも半数の意味語が一致または翻字類似する場合だけ採用する。
    candidates = sorted(
        (
            similarity,
            left_index,
            right_index,
        )
        for left_index, left_token in enumerate(meaningful_left)
        for right_index, right_token in enumerate(meaningful_right)
        if (
            (similarity := (
                1.0
                if left_token == right_token
                else _cross_language_similarity(left_token, right_token)
            ))
            >= _CROSS_LANGUAGE_TOKEN_THRESHOLD
        )
    )
    matched_left: set[int] = set()
    matched_right: set[int] = set()
    for _, left_index, right_index in reversed(candidates):
        if left_index not in matched_left and right_index not in matched_right:
            matched_left.add(left_index)
            matched_right.add(right_index)
    return (
        len(matched_left) / len(meaningful_left) >= _MIN_SEMANTIC_TOKEN_COVERAGE
        and len(matched_right) / len(meaningful_right) >= _MIN_SEMANTIC_TOKEN_COVERAGE
    )


def _filter_similar_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """選定順を保ったまま、高類似タイトルの記事を後続候補から除外する。"""
    selected: list[dict[str, Any]] = []
    for article in articles:
        if any(
            titles_are_similar(article.get("title"), selected_article.get("title"))
            for selected_article in selected
        ):
            continue
        selected.append(article)
    return selected


def _article_topic_key(article: dict[str, Any]) -> str | None:
    """記事の後段フィルタ用テーマキーを返す。

    要約時に保存された既知の category を使う。未知・空の category は判定不能
    として上限を適用しない（異なる話題を誤ってまとめないため）。天気・災害の
    連続抑制は category/title/summary を使う別判定で行う。
    """
    category = str(article.get("category") or "").strip().casefold()
    if category in _KNOWN_TOPIC_CATEGORIES:
        return category
    return None


def _is_weather_disaster_article(article: dict[str, Any]) -> bool:
    category = str(article.get("category") or "").strip().casefold()
    searchable_text = " ".join(
        str(article.get(field) or "") for field in ("category", "title", "summary")
    ).casefold()
    return (
        category in _WEATHER_DISASTER_CATEGORIES
        or any(keyword in searchable_text for keyword in _WEATHER_DISASTER_KEYWORDS)
    )


def _filter_topic_concentration(
    articles: list[dict[str, Any]], max_articles: int
) -> list[dict[str, Any]]:
    """カテゴリ上限と天気・災害の連続抑制を適用して選定数を満たす。

    候補をSQLで先に ``max_articles`` 件へ切り詰めず、後続候補まで見てから
    フィルタすることで、偏りを除外した分だけ件数が不必要に減ることを防ぐ。
    天気・災害の3件目は一旦保留し、通常記事が後続にあればその後へ回す。
    代替候補がない場合は、件数充足のため保留候補を最後に採用する。
    """
    if max_articles <= 0:
        return []

    selected: list[dict[str, Any]] = []
    deferred_weather: list[dict[str, Any]] = []
    topic_counts: dict[str, int] = {}

    def can_select(article: dict[str, Any], *, allow_weather_run: bool = False) -> bool:
        topic = _article_topic_key(article)
        # 天気・災害は category が society/general に寄りやすく、別々の事象を
        # 同一テーマと誤認しやすい。ここではカテゴリ上限の対象から外し、専用の
        # 連続抑制だけを適用する。
        if (
            topic is not None
            and not _is_weather_disaster_article(article)
            and topic_counts.get(topic, 0) >= _MAX_ARTICLES_PER_TOPIC
        ):
            return False
        if (
            not allow_weather_run
            and _is_weather_disaster_article(article)
            and len(selected) >= 2
            and all(_is_weather_disaster_article(item) for item in selected[-2:])
        ):
            return False
        return True

    def select(article: dict[str, Any]) -> None:
        selected.append(article)
        topic = _article_topic_key(article)
        if topic is not None and not _is_weather_disaster_article(article):
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

    def flush_deferred_weather() -> None:
        if not deferred_weather:
            return
        remaining: list[dict[str, Any]] = []
        while deferred_weather and len(selected) < max_articles:
            article = deferred_weather.pop(0)
            if can_select(article):
                select(article)
            else:
                remaining.append(article)
        deferred_weather.extend(remaining)

    for article in articles:
        if len(selected) >= max_articles:
            break
        if _is_weather_disaster_article(article) and not can_select(article):
            deferred_weather.append(article)
            continue
        if can_select(article):
            select(article)
            # 通常記事を差し込めた時点で、保留していた天気・災害記事を再評価する。
            if not _is_weather_disaster_article(article):
                flush_deferred_weather()

    # 代替候補がなかった場合だけ、連続抑制を解除して件数を充足する。
    while deferred_weather and len(selected) < max_articles:
        article = deferred_weather.pop(0)
        if can_select(article, allow_weather_run=True):
            select(article)

    return selected


def _prioritize_high_impact_articles(
    articles: list[dict[str, Any]], priority_themes: list[str] | tuple[str, ...] | None
) -> list[dict[str, Any]]:
    """多様性フィルタ後の候補から高インパクト記事を先頭へ安定移動する。

    高インパクトは、優先テーマに一致し、かつ既存の重要度スコアが4以上の
    記事とする。記事の入れ替えはフィルタ後に行うため、カテゴリ上限は変わら
    ない。天気・災害の連続抑制だけは並び替え後にも満たすよう、3件目以降を
    次の通常記事の後ろへ繰り下げる。
    """
    priority = {
        str(theme).strip().casefold()
        for theme in (priority_themes or ())
        if str(theme).strip()
    }
    if not priority:
        return list(articles)

    high_impact: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for article in articles:
        category = str(article.get("category") or "").strip().casefold()
        try:
            importance_score = int(article.get("importance_score"))
        except (TypeError, ValueError):
            importance_score = 0
        if category in priority and importance_score >= _HIGH_IMPACT_SCORE_THRESHOLD:
            high_impact.append(article)
        else:
            fallback.append(article)

    # 非該当時は元の重要度・公開日時順（SQL選定順）をそのまま返す。
    if not high_impact:
        return list(articles)

    reordered = high_impact + fallback
    result: list[dict[str, Any]] = []
    deferred_weather: list[dict[str, Any]] = []

    def would_create_weather_run(article: dict[str, Any]) -> bool:
        return (
            _is_weather_disaster_article(article)
            and len(result) >= 2
            and all(_is_weather_disaster_article(item) for item in result[-2:])
        )

    def flush_deferred_weather() -> None:
        while deferred_weather and not would_create_weather_run(deferred_weather[0]):
            result.append(deferred_weather.pop(0))

    for article in reordered:
        if would_create_weather_run(article):
            deferred_weather.append(article)
            continue
        result.append(article)
        if not _is_weather_disaster_article(article):
            flush_deferred_weather()

    # 通常記事が存在しない場合は、元のフィルタと同様に件数充足を優先する。
    result.extend(deferred_weather)
    return result


# ---------------------------------------------------------------------------
# 関心トピックによる選定（BEEW-540 仕様 §4・§7）。トピックが空のときは使わない。
# 数値は環境変数で上書きでき、不正な値は既定値に戻す（SUMMARY_LOOKBACK_DAYS と同じ流儀）。
# ---------------------------------------------------------------------------

_TOPIC_TIERS = ("high", "medium", "low")
_TOPIC_WEIGHT_RANK = {"high": 3, "medium": 2, "low": 1}
# トピック単位の上限（同一トピックから採用する記事の最大数）。
_TOPIC_TIER_CAPS = {"high": 3, "medium": 2, "low": 1}
# 台本・レビューのLLM入力へ流さないキー（生成側の語り口に反映させないため）。
_TOPIC_PROMPT_EXCLUDED_FIELDS = ("topic_tier", "matched_topics")


def _read_topic_number(name: str, default, cast, is_valid):
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        return default
    return value if is_valid(value) else default


def _topic_relevance_threshold() -> int:
    return _read_topic_number("TOPIC_RELEVANCE_THRESHOLD", 2, int, lambda v: 0 <= v <= 3)


def _topic_high_min_importance() -> int:
    return _read_topic_number("TOPIC_HIGH_MIN_IMPORTANCE", 2, int, lambda v: 1 <= v <= 5)


def _topic_general_reserve_ratio() -> float:
    return _read_topic_number("TOPIC_GENERAL_RESERVE_RATIO", 0.2, float, lambda v: 0 < v < 1)


def _round_half_up(value: float) -> int:
    # Python の round() は .5 を偶数側へ丸めるため、件数計算では四捨五入に揃える。
    return math.floor(value + 0.5)


def without_topic_fields(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """LLMへ渡す要約から、トピック関連のキーを外したコピーを返す。"""
    return [
        {key: value for key, value in summary.items() if key not in _TOPIC_PROMPT_EXCLUDED_FIELDS}
        for summary in summaries
    ]


def _importance_of(article: dict[str, Any]) -> int:
    try:
        return int(article.get("importance_score") or 0)
    except (TypeError, ValueError):
        return 0


def _can_arrange_weather_run(weather_left: int, normal_left: int, run: int) -> bool:
    """残りの記事を、天気・災害の3件連続を作らずに並べ切れるかを返す。

    末尾に run 件の天気・災害が連なっているとき、先頭の隙間は 2 - run 件、
    通常記事1件ごとに後ろの隙間は 2 件まで置ける。
    """
    return weather_left <= max(0, 2 - run) + 2 * normal_left


def _enforce_weather_run(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """最終並びで天気・災害の3件連続を防ぐ。

    各位置で、残りを並べ切れる候補のうち元の順に最も近いものを採用する。前方の
    通常記事も候補になるため、通常記事が後ろにまとまっている場合も連続を解消できる。
    連続を作らずに並べられない入力では、元の順を保つ。
    """
    flags = [(article, _is_weather_disaster_article(article)) for article in articles]
    result: list[dict[str, Any]] = []
    run = 0
    while flags:
        weather_left = sum(1 for _, is_weather in flags if is_weather)
        normal_left = len(flags) - weather_left
        chosen = 0
        for index, (_, is_weather) in enumerate(flags):
            if is_weather and run >= 2:
                continue
            next_run = run + 1 if is_weather else 0
            if is_weather:
                arrangeable = _can_arrange_weather_run(weather_left - 1, normal_left, next_run)
            else:
                arrangeable = _can_arrange_weather_run(weather_left, normal_left - 1, next_run)
            if arrangeable:
                chosen = index
                break
        article, is_weather = flags.pop(chosen)
        result.append(article)
        run = run + 1 if is_weather else 0
    return result


_SUMMARY_COLUMNS = (
    "id, title, source, url, summary, category, importance_score, difficulty"
)
_TOPIC_SUMMARY_COLUMNS = f"{_SUMMARY_COLUMNS}, published_at"


def _summary_since_date() -> str:
    _raw_lookback = os.getenv("SUMMARY_LOOKBACK_DAYS")
    try:
        lookback_days = int(_raw_lookback) if _raw_lookback else 3
        if lookback_days < 1:
            lookback_days = 3
    except (ValueError, TypeError):
        lookback_days = 3
    return (datetime.now(JST).date() - timedelta(days=lookback_days)).isoformat()


def _select_summary_rows(
    conn,
    *,
    min_importance: int,
    since_date: str,
    source: str | None,
    priority: list[str],
    excluded: list[str],
    limit: int | None = None,
    article_ids: list[int] | None = None,
    columns: str = _SUMMARY_COLUMNS,
) -> list:
    where = [
        "status = 'summarized'",
        "summary IS NOT NULL",
        "summary != ''",
        "importance_score >= ?",
        "published_at >= ?",
    ]
    params: list[Any] = [min_importance, since_date]
    if source is not None:
        where.append("source = ?")
        params.append(source)
    if excluded:
        placeholders = ",".join("?" for _ in excluded)
        # Safety valve B: critical technology/society news remains eligible.
        where.append(
            f"(category NOT IN ({placeholders}) OR "
            "(importance_score >= 5 AND category IN ('technology', 'society')) OR category IS NULL)"
        )
        params.extend(excluded)
    if article_ids is not None:
        placeholders = ",".join("?" for _ in article_ids)
        where.append(f"id IN ({placeholders})")
        params.extend(article_ids)
    order = "importance_score DESC, published_at DESC, id DESC"
    if priority:
        placeholders = ",".join("?" for _ in priority)
        order = f"CASE WHEN category IN ({placeholders}) THEN 0 ELSE 1 END, {order}"
        params.extend(priority)
    query = f"SELECT {columns} FROM articles WHERE {' AND '.join(where)} ORDER BY {order}"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)
    return conn.execute(query, params).fetchall()


def _load_topic_matches(conn, topics: list[TopicSetting]) -> dict[int, list[tuple[TopicSetting, int]]]:
    """指紋が現行のトピックと一致し、閾値以上の判定だけを記事ごとに返す。"""
    threshold = _topic_relevance_threshold()
    by_id = {topic.id: topic for topic in topics}
    fingerprints = {topic.id: topic_fingerprint(topic.name, topic.description) for topic in topics}
    placeholders = ",".join("?" for _ in topics)
    rows = conn.execute(
        "SELECT article_id, topic_id, relevance, fingerprint FROM article_topic_matches "
        f"WHERE topic_id IN ({placeholders})",
        [topic.id for topic in topics],
    ).fetchall()
    matches: dict[int, list[tuple[TopicSetting, int]]] = {}
    for row in rows:
        topic_id = row["topic_id"]
        if row["fingerprint"] != fingerprints[topic_id] or row["relevance"] < threshold:
            continue
        matches.setdefault(row["article_id"], []).append((by_id[topic_id], row["relevance"]))
    return matches


def _select_topic_summaries(
    conn,
    topics: list[TopicSetting],
    max_articles: int,
    min_importance: int,
    since_date: str,
    source: str | None,
    priority: list[str],
    excluded: list[str],
) -> list[dict[str, Any]]:
    """比重（高・中・低）と一般ニュース枠に従って記事を選ぶ（仕様 §7.2）。"""
    total = max(0, max_articles)
    if total == 0:
        return []
    high_min = _topic_high_min_importance()
    base_min = min(min_importance, high_min)
    # published_at は段階内の並びに使うだけで、返す要約には含めない（後段で外す）。
    pool_rows = _select_summary_rows(
        conn, min_importance=base_min, since_date=since_date, source=source,
        priority=priority, excluded=excluded, limit=_MAX_CANDIDATE_POOL_SIZE,
        columns=_TOPIC_SUMMARY_COLUMNS,
    )
    articles: dict[int, dict[str, Any]] = {row["id"]: dict(row) for row in pool_rows}
    matches = _load_topic_matches(conn, topics)
    # 候補プールの切り捨てで外れた一致記事も、判定があれば対象に加える。
    missing = [article_id for article_id in matches if article_id not in articles]
    if missing:
        extra_rows = _select_summary_rows(
            conn, min_importance=base_min, since_date=since_date, source=source,
            priority=priority, excluded=excluded, article_ids=missing,
            columns=_TOPIC_SUMMARY_COLUMNS,
        )
        for row in extra_rows:
            articles.setdefault(row["id"], dict(row))

    # 段階分け。一致トピックのうち最も高い比重を記事の段階にする。
    tiers: dict[str, list[tuple[dict[str, Any], int, int]]] = {tier: [] for tier in _TOPIC_TIERS}
    general: list[dict[str, Any]] = []
    for article in articles.values():
        importance = _importance_of(article)
        matched = matches.get(article["id"], [])
        article["matched_topics"] = [
            {"id": topic.id, "name": topic.name, "weight": topic.weight} for topic, _ in matched
        ]
        article["topic_tier"] = "general"
        if matched:
            topic, _ = max(matched, key=lambda item: (_TOPIC_WEIGHT_RANK[item[0].weight], item[1]))
            floor = high_min if topic.weight == "high" else min_importance
            if importance >= floor:
                article["topic_tier"] = topic.weight
                max_relevance = max(relevance for _, relevance in matched)
                tiers[topic.weight].append((article, max_relevance, topic.id))
                continue
        if importance >= min_importance:
            general.append(article)

    # 段階内は「最大関連度 → 重要度 → 公開日時」の降順。SQL の優先カテゴリ順は使わない。
    ordered_topic = []
    for tier in _TOPIC_TIERS:
        ordered_topic.extend(
            sorted(
                tiers[tier],
                key=lambda entry: (
                    entry[1],
                    _importance_of(entry[0]),
                    entry[0].get("published_at") or "",
                    entry[0]["id"],
                ),
                reverse=True,
            )
        )
    # 重複除外は上位の段階が残るように、段階順に連結してから適用する。
    deduped_ids = {
        article["id"]
        for article in _filter_similar_articles([entry[0] for entry in ordered_topic] + general)
    }
    topic_entries = [entry for entry in ordered_topic if entry[0]["id"] in deduped_ids]
    general = [article for article in general if article["id"] in deduped_ids]

    general_reserve = max(1, _round_half_up(total * _topic_general_reserve_ratio()))
    topic_slots = total - general_reserve
    low_limit = 1 if total < 10 else 2
    chosen_topic: list[dict[str, Any]] = []
    chosen_ids: set[int] = set()
    topic_counts: dict[int, int] = {}
    low_count = 0

    def take_topic_articles(limit: int, *, enforce_topic_cap: bool) -> None:
        # 比重の順に採用する。低比重の上限は常に守る。トピック単位の上限は通常の枠だけに適用し、
        # 件数の補充では外す（既存の天気・災害の連続抑制と同じく、件数充足を優先する）。
        nonlocal low_count
        for article, _, topic_id in topic_entries:
            if len(chosen_topic) >= limit:
                break
            if article["id"] in chosen_ids:
                continue
            tier = article["topic_tier"]
            if enforce_topic_cap and topic_counts.get(topic_id, 0) >= _TOPIC_TIER_CAPS[tier]:
                continue
            if tier == "low" and low_count >= low_limit:
                continue
            chosen_topic.append(article)
            chosen_ids.add(article["id"])
            topic_counts[topic_id] = topic_counts.get(topic_id, 0) + 1
            if tier == "low":
                low_count += 1

    take_topic_articles(topic_slots, enforce_topic_cap=True)
    general_pick = _prioritize_high_impact_articles(
        _filter_topic_concentration(general, total - len(chosen_topic)), priority
    )
    # 一般記事が足りない場合だけ、未採用のトピック記事を段階順に補充する。
    take_topic_articles(total - len(general_pick), enforce_topic_cap=False)
    topic_part = sorted(
        chosen_topic, key=lambda article: _TOPIC_TIERS.index(article["topic_tier"])
    )
    for article in topic_part + general_pick:
        article.pop("published_at", None)
    logger.info(
        "topic selection: tiers=%s general=%d total=%d",
        {tier: sum(1 for a in chosen_topic if a["topic_tier"] == tier) for tier in _TOPIC_TIERS},
        len(general_pick),
        len(topic_part) + len(general_pick),
    )
    return _enforce_weather_run(topic_part + general_pick)


class ArticleService:
    def upsert_article(self, article: dict[str, Any]) -> bool:
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO articles (
                    title, source, url, text, published_at, status
                ) VALUES (?, ?, ?, ?, ?, 'new')
                """,
                (
                    article.get("title", ""),
                    article.get("source"),
                    article.get("url"),
                    article.get("text", ""),
                    article.get("published_at"),
                ),
            )
            return cursor.rowcount > 0

    def fetch_new_articles(self, source: str | None = None) -> list[dict[str, Any]]:
        where = "status = 'new'"
        params = ()
        if source is not None:
            where += " AND source = ?"
            params = (source,)
        with get_db_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT id, title, source, url, text, published_at
                FROM articles
                WHERE {where}
                ORDER BY published_at DESC, id ASC
                """, params
            ).fetchall()
            return [dict(row) for row in rows]

    def update_summary(
        self,
        article_id: int,
        summary: str,
        category: str,
        importance_score: int,
        status: str,
        difficulty: int = 1,
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE articles
                SET summary = ?,
                    category = ?,
                    importance_score = ?,
                    difficulty = ?,
                    status = ?
                WHERE id = ?
                """,
                (summary, category, importance_score, difficulty, status, article_id),
            )

    def fetch_topic_judge_candidates(
        self,
        min_importance_score: int,
        source: str | None = None,
        priority_themes: list[str] | tuple[str, ...] | None = None,
        excluded_themes: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        """関心トピックの判定対象。選定時の候補プールと同じ範囲（重要度順・上限あり）を読む。"""
        base_min = min(min_importance_score, _topic_high_min_importance())
        with get_db_connection() as conn:
            rows = _select_summary_rows(
                conn, min_importance=base_min, since_date=_summary_since_date(), source=source,
                priority=list(priority_themes or []), excluded=list(excluded_themes or []),
                limit=_MAX_CANDIDATE_POOL_SIZE, columns="id, title, summary",
            )
        return [dict(row) for row in rows]

    def fetch_summaries_for_script(
        self,
        max_articles: int,
        min_importance_score: int,
        source: str | None = None,
        priority_themes: list[str] | tuple[str, ...] | None = None,
        excluded_themes: list[str] | tuple[str, ...] | None = None,
        topics: list[TopicSetting] | tuple[TopicSetting, ...] | None = None,
    ) -> list[dict[str, Any]]:
        since_date = _summary_since_date()
        priority = list(priority_themes or [])
        excluded = list(excluded_themes or [])
        with get_db_connection() as conn:
            if topics:
                return _select_topic_summaries(
                    conn, list(topics), max_articles, min_importance_score,
                    since_date, source, priority, excluded,
                )
            candidate_limit = min(
                max(0, max_articles) * _CANDIDATE_POOL_MULTIPLIER,
                _MAX_CANDIDATE_POOL_SIZE,
            )
            rows = _select_summary_rows(
                conn, min_importance=min_importance_score, since_date=since_date,
                source=source, priority=priority, excluded=excluded, limit=candidate_limit,
            )
            # SQLの選定順を保ったまま、タイトル重複とテーマ集中を後段で除外する。
            # max_articlesの5倍（最大100件）を候補として取得し、除外後に後続候補で
            # 件数を補充する。無制限取得による計算量増加も避ける。
            candidates = _filter_similar_articles([dict(row) for row in rows])
            filtered = _filter_topic_concentration(candidates, max_articles)
            return _prioritize_high_impact_articles(filtered, priority)

    def fetch_and_store_article_by_url(self, url: str, timeout: int = 10) -> bool:
        """Fetch article from URL and store in DB with source='url_commentary'.

        Args:
            url: HTTP(S) URL of the article to fetch.
            timeout: Request timeout in seconds.

        Returns:
            True if inserted, False if duplicate (url UNIQUE constraint).

        Raises:
            ValueError: Invalid URL.
            urllib.error.URLError: Network error.
            RuntimeError: Extraction failure.
        """
        from app.services.url_fetcher import fetch_article_by_url

        article = fetch_article_by_url(url, timeout=timeout)
        return self.upsert_article(article)

    def mark_articles_used(self, article_ids: list[int]) -> None:
        """Mark articles as 'used' so they are not reused in future episode scripts."""
        if not article_ids:
            return
        placeholders = ",".join("?" * len(article_ids))
        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE articles SET status = 'used' WHERE id IN ({placeholders}) AND status = 'summarized'",
                article_ids,
            )
