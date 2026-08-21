"""台本全体の前後関係を検査する非致命的な構造スキャナ。"""

import re
from typing import Any


# 文脈なしで記事紹介を開始する応答形。末尾の「ですね」は独立した感想を
# 誤検出しやすいため、文頭の相槌・応答形だけを対象にする。
_RESPONSE_OPENERS = (
    "そうです", "そうなんです", "そうですね", "なるほど", "たしかに", "確かに",
)
_QUESTION_RE = re.compile(r"(?:[?？]|ですか(?:ね)?|でしょうか|ませんか)[。！？!？]?\s*$")
_TOKEN_RE = re.compile(r"[一-龥々〆ヵ]{2,}|[ぁ-んァ-ヶ]{3,}|[A-Za-z][A-Za-z0-9+#.-]{2,}|[0-9０-９]{2,}")
_TOKEN_STOPWORDS = {
    "ニュース", "話題", "情報", "発表", "最新", "について", "こと", "もの", "今回",
    "そして", "また", "これ", "それ", "ため", "など", "日本", "国内",
}


def _line_number(index: int) -> int:
    """人間向けの1始まり行番号。"""
    return index + 1


def _is_response(text: str) -> bool:
    normalized = (text or "").strip().lstrip("「『（(").replace("　", " ")
    return any(normalized.startswith(opener) for opener in _RESPONSE_OPENERS)


def _is_question(text: str) -> bool:
    return bool(_QUESTION_RE.search((text or "").strip()))


def _article_tokens(article: dict[str, Any]) -> set[str]:
    source = " ".join(str(article.get(key, "") or "") for key in ("title", "summary", "category"))
    return {
        token.lower()
        for token in _TOKEN_RE.findall(source)
        if token not in _TOKEN_STOPWORDS and len(token) >= 2
    }


def scan_script_structure(
    lines: list[dict[str, Any]],
    summaries: list[dict[str, Any]] | None = None,
    *,
    expected_discussion_article_id: Any = None,
) -> list[str]:
    """構造上の要確認候補を ``[STRUCTURE_*]`` 警告として返す。

    判定不能・類似候補は警告に留め、生成・レビューの成功可否は変更しない。
    ``summaries`` がない場合、ニュース重複検査はスキップする。
    """
    warnings: list[str] = []
    content_sections = {"news", "discussion"}

    # 応答形: 同一のニュース/討論ブロック内で、直前に問いがなければ候補。
    for index, line in enumerate(lines):
        section = line.get("section")
        if section not in content_sections or not _is_response(str(line.get("text", ""))):
            continue
        has_question = False
        for previous in reversed(lines[max(0, index - 4):index]):
            if previous.get("section") == "transition" or (
                previous.get("section") in content_sections
                and previous.get("article_id") != line.get("article_id")
            ):
                break
            if previous.get("section") in content_sections and _is_question(str(previous.get("text", ""))):
                has_question = True
                break
        if not has_question:
            warnings.append(
                f"[STRUCTURE_RESPONSE_WITHOUT_QUESTION] 台本行 {_line_number(index)} "
                f"(article_id={line.get('article_id')}) が応答形「{str(line.get('text', '')).strip()[:30]}」で始まっていますが、"
                "直前に対応する問いがありません"
            )

    # 隣接ニュース: 同一カテゴリ、またはタイトル・要約の有意味語が重複する組。
    if summaries:
        summary_by_id = {item.get("id", item.get("article_id")): item for item in summaries if isinstance(item, dict)}
        news_blocks: list[tuple[int, int, Any]] = []
        for index, line in enumerate(lines):
            if line.get("section") != "news":
                continue
            article_id = line.get("article_id")
            if news_blocks and news_blocks[-1][2] == article_id:
                news_blocks[-1] = (news_blocks[-1][0], index, article_id)
            else:
                news_blocks.append((index, index, article_id))
        for left, right in zip(news_blocks, news_blocks[1:]):
            left_article = summary_by_id.get(left[2], {})
            right_article = summary_by_id.get(right[2], {})
            if not left_article or not right_article or left[2] == right[2]:
                continue
            left_tokens = _article_tokens(left_article)
            right_tokens = _article_tokens(right_article)
            overlap = sorted(left_tokens & right_tokens)
            same_category = bool(left_article.get("category") and left_article.get("category") == right_article.get("category"))
            if overlap or same_category:
                evidence = []
                if overlap:
                    evidence.append(f"キーワード={','.join(overlap[:5])}")
                if same_category:
                    evidence.append(f"カテゴリ={left_article.get('category')}")
                warnings.append(
                    f"[STRUCTURE_ADJACENT_NEWS_SIMILAR] 隣接ニュース article_id={left[2]} "
                    f"(台本行 {_line_number(left[0])}) と article_id={right[2]} "
                    f"(台本行 {_line_number(right[0])}) が類似候補です（{'、'.join(evidence)}）"
                )

    # 討論対象: 直前のニュースと一致しない候補。Arcの期待値もあれば併記する。
    discussion_indices = [i for i, line in enumerate(lines) if line.get("section") == "discussion"]
    news_indices = [i for i, line in enumerate(lines) if line.get("section") == "news"]
    if discussion_indices and news_indices:
        discussion_ids = {lines[i].get("article_id") for i in discussion_indices}
        preceding_id = lines[news_indices[-1]].get("article_id")
        if len(discussion_ids) == 1:
            discussion_id = next(iter(discussion_ids))
            if discussion_id != preceding_id:
                warnings.append(
                    f"[STRUCTURE_DISCUSSION_TARGET_MISMATCH] discussion対象 article_id={discussion_id} "
                    f"(台本行 {_line_number(discussion_indices[0])}) が直前ニュース article_id={preceding_id} "
                    f"(台本行 {_line_number(news_indices[-1])}) と一致しません"
                )
            if expected_discussion_article_id is not None and discussion_id != expected_discussion_article_id:
                warnings.append(
                    f"[STRUCTURE_DISCUSSION_TARGET_MISMATCH] discussion対象 article_id={discussion_id} が "
                    f"Narrative Arc選定 article_id={expected_discussion_article_id} と一致しません"
                )

    return warnings
