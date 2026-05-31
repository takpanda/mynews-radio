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
        article = {
            "title": block["title"],
            "source": "hatena_bookmark",
            "url": block["url"],
            "text": block["text"],
            "published_at": target_date.isoformat(),
            # Extra metadata stored as part of text for reference
            "_bookmarks": block["bookmarks"],
            "_user_score": block["user_score"],
        }
        logger.info("Parsed hatena article for %s: %s", target_date.isoformat(), article["url"])
        articles.append(article)

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


HATENA_HOTENTRY_ALL_RSS = "https://b.hatena.ne.jp/hotentry/all.rss"
_RSS_NS = "http://purl.org/rss/1.0/"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def fetch_hotentry_all_articles() -> list[dict[str, Any]]:
    """Fetch general news from Hatena Bookmark hotentry/all RSS feed.

    Returns a list of article dicts suitable for ArticleService.upsert_article().
    """
    import xml.etree.ElementTree as ET

    today = date.today()
    logger.info("Fetching hotentry/all RSS from %s", HATENA_HOTENTRY_ALL_RSS)

    req = urllib.request.Request(HATENA_HOTENTRY_ALL_RSS)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; mynews-radio-bot/1.0)")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()
    except urllib.error.HTTPError as e:
        logger.error("Failed to fetch hotentry/all RSS: HTTP %d", e.code)
        return []
    except Exception as e:
        logger.error("Failed to fetch hotentry/all RSS: %s", e)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error("Failed to parse hotentry/all RSS XML: %s", e)
        return []

    articles: list[dict[str, Any]] = []
    for item in root.findall(f"{{{_RSS_NS}}}item"):
        title_el = item.find(f"{{{_RSS_NS}}}title")
        link_el = item.find(f"{{{_RSS_NS}}}link")
        desc_el = item.find(f"{{{_RSS_NS}}}description")
        date_el = item.find(f"{{{_DC_NS}}}date")

        title = (title_el.text or "").strip() if title_el is not None else ""
        url = (link_el.text or "").strip() if link_el is not None else ""
        description = (desc_el.text or "").strip() if desc_el is not None else ""

        if not title or not url:
            continue

        published_at = today.isoformat()
        if date_el is not None and date_el.text:
            try:
                published_at = date_el.text[:10]
            except Exception:
                pass

        articles.append({
            "title": title,
            "source": "hatena_hotentry_all",
            "url": url,
            "text": description,
            "published_at": published_at,
        })

    logger.info("Fetched %d articles from hotentry/all RSS", len(articles))
    return articles


def import_hotentry_all_articles() -> tuple[int, int]:
    """Import general news articles from Hatena hotentry/all RSS into the DB.

    Returns (inserted, duplicated) counts.
    """
    from app.services.article_service import ArticleService

    service = ArticleService()
    articles = fetch_hotentry_all_articles()
    inserted = 0
    duplicated = 0
    for article in articles:
        created = service.upsert_article(article)
        if created:
            inserted += 1
        else:
            duplicated += 1

    logger.info("import_hotentry_all done: inserted=%d duplicated=%d", inserted, duplicated)
    return inserted, duplicated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ins, dup = auto_fetch_hatena_articles()
    print(f"inserted={ins} duplicated={dup}")
