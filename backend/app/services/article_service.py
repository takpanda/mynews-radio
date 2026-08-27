import os
import re
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from typing import Any
import unicodedata

from app.db.connection import get_db_connection


JST = timezone(timedelta(hours=9))

# タイトルの表記揺れだけを吸収する閾値。本文やURLを使わず、かなり似た
# タイトルだけを対象にすることで、別イベントの誤除外を避ける。
_TITLE_SIMILARITY_THRESHOLD = 0.92
_CROSS_LANGUAGE_TOKEN_THRESHOLD = 0.68

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
    if kana_token[:1] == "ノ":
        # 「AのB」のように、Bがカタカナ語だと先頭の助詞がBへ付着する。
        kana_token = kana_token[1:]
    if kana_token[-1:] in {"ガ", "ハ", "ニ", "ヘ", "ヲ", "ノ", "ト", "デ", "モ", "ヤ"}:
        # 日本語の助詞がカタカナ語に連結した場合も、語幹同士を比較する。
        kana_token = kana_token[:-1]
    romanized = _romanize_katakana(kana_token)
    if len(romanized) < 5 or len(latin_token) < 5:
        return 0.0
    return SequenceMatcher(None, romanized, latin_token, autojunk=False).ratio()


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
    cross_matches = [
        similarity
        for left_token in left_tokens
        for right_token in right_tokens
        if (similarity := _cross_language_similarity(left_token, right_token))
        >= _CROSS_LANGUAGE_TOKEN_THRESHOLD
    ]
    if not cross_matches:
        return False

    # 「ハラペーニョ」と「Jalapeño」のような翻字は、単語単体なら採用する。
    # 長いタイトルでは同一言及のアンカー語も要求し、偶然似た音の除外を抑える。
    exact_anchors = {
        token for token, _ in left_tokens if len(token) >= 4
    } & {
        token for token, _ in right_tokens if len(token) >= 4
    }
    meaningful_left = [token for token, _ in left_tokens if len(token) >= 4]
    meaningful_right = [token for token, _ in right_tokens if len(token) >= 4]
    return bool(exact_anchors) or (len(meaningful_left) <= 2 and len(meaningful_right) <= 2)


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

    def fetch_new_articles(self) -> list[dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, title, source, url, text, published_at
                FROM articles
                WHERE status = 'new'
                ORDER BY published_at DESC, id ASC
                """
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

    def fetch_summaries_for_script(
        self,
        max_articles: int,
        min_importance_score: int,
        source: str | None = None,
        priority_themes: list[str] | tuple[str, ...] | None = None,
        excluded_themes: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        _raw_lookback = os.getenv("SUMMARY_LOOKBACK_DAYS")
        try:
            lookback_days = int(_raw_lookback) if _raw_lookback else 3
            if lookback_days < 1:
                lookback_days = 3
        except (ValueError, TypeError):
            lookback_days = 3
        since_date = (datetime.now(JST).date() - timedelta(days=lookback_days)).isoformat()
        priority = list(priority_themes or [])
        excluded = list(excluded_themes or [])
        where = [
            "status = 'summarized'",
            "summary IS NOT NULL",
            "summary != ''",
            "importance_score >= ?",
            "published_at >= ?",
        ]
        params: list[Any] = [min_importance_score, since_date]
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
        order = "importance_score DESC, published_at DESC, id DESC"
        if priority:
            placeholders = ",".join("?" for _ in priority)
            order = f"CASE WHEN category IN ({placeholders}) THEN 0 ELSE 1 END, {order}"
            params.extend(priority)
        params.append(max_articles)
        query = (
            "SELECT id, title, source, url, summary, category, importance_score, difficulty "
            f"FROM articles WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
        )
        with get_db_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            # SQLの選定順（importance_score、published_at、id）を保ったまま、
            # URLの重複判定とは独立してタイトルの高類似候補だけを落とす。
            return _filter_similar_articles([dict(row) for row in rows])

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
