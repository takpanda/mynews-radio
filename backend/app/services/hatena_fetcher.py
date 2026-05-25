"""Fetcher for hatena_bookmark category from news.beeworks.cc API."""

import logging
import re
import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

BASE_URL = "https://news.beeworks.cc/api/articles"


def _parse_article_blocks(content: str) -> list[dict[str, str]]:
    """Parse API content string into individual article dicts.

    Each block is separated by '\\n---\\n'.
    Within each block, the first line starts with '# ' (title).
    Look for '[元記事](URL)' to extract the original URL.
    """
    blocks = re.split(r'\n---\n', content)
    results: list[dict[str, str]] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        # Extract title (first line starting with '# ')
        title_match = re.match(r'^#\s+(.+)', block, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""
        if not title:
            continue

        # Extract original URL: [元記事](URL)
        url_match = re.search(r'\[元記事\]\(([^)]+)\)', block)
        url = url_match.group(1) if url_match else ""

        # Extract bookmark count: ブックマーク数: N
        bookmark_match = re.search(r'ブックマーク数:\s*(\d+)', block)
        bookmarks = int(bookmark_match.group(1)) if bookmark_match else 0

        # Extract user score: ユーザースコア: X.XX
        score_match = re.search(r'ユーザースコア:\s*([0-9.]+)', block)
        user_score = float(score_match.group(1)) if score_match else 0.0

        results.append({
            "title": title,
            "url": url,
            "text": block,
            "bookmarks": bookmarks,
            "user_score": user_score,
        })

    return results


def fetch_hatena_articles(target_date: date | None = None) -> list[dict[str, Any]]:
    """Fetch hatena_bookmark articles from the API for the given date.

    Returns a list of article dicts suitable for ArticleService.upsert_article().
    """
    if target_date is None:
        target_date = date.today()

    url = f"{BASE_URL}/hatena_bookmark/{target_date.isoformat()}"
    logger.info("Fetching hatena articles from %s", url)

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; mynews-radio-bot/1.0)")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            logger.info("API returned %d for date %s (no data available)", e.code, target_date.isoformat())
            return []
        raise

    content = data.get("content", "")
    if not content:
        logger.warning("No content received for date %s", target_date.isoformat())
        return []

    blocks = _parse_article_blocks(content)
    logger.info("Parsed %d article blocks from API", len(blocks))

    articles: list[dict[str, Any]] = []
    for block in blocks:
        articles.append({
            "title": block["title"],
            "source": "hatena_bookmark",
            "url": block["url"],
            "text": block["text"],
            "published_at": target_date.isoformat(),
            # Extra metadata stored as part of text for reference
            "_bookmarks": block["bookmarks"],
            "_user_score": block["user_score"],
        })

    return articles


def auto_fetch_hatena_articles() -> tuple[int, int]:
    """Fetch hatena_bookmark articles starting from the most recent date with data.

    Walks backwards day by day until no more data is found (max 30 days).
    Returns (inserted, duplicated) counts.
    """
    from app.services.article_service import ArticleService

    service = ArticleService()
    today = date.today()
    inserted = 0
    duplicated = 0
    consecutive_empty = 0
    max_consecutive = 5  # stop after 5 consecutive empty days

    for day_offset in range(max_consecutive * 2):
        target_date = today - timedelta(days=day_offset)
        articles = fetch_hatena_articles(target_date)

        if not articles:
            consecutive_empty += 1
            if consecutive_empty >= max_consecutive:
                logger.info("No articles for %d consecutive days, stopping", max_consecutive)
                break
            continue

        consecutive_empty = 0
        for article in articles:
            created = service.upsert_article(article)
            if created:
                inserted += 1
            else:
                duplicated += 1

        logger.info("Fetched %d articles for %s (total inserted=%d)", len(articles), target_date.isoformat(), inserted)

    logger.info("auto_fetch done: inserted=%d duplicated=%d", inserted, duplicated)
    return inserted, duplicated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ins, dup = auto_fetch_hatena_articles()
    print(f"inserted={ins} duplicated={dup}")
