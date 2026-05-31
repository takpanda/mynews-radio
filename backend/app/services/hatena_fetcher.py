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

YAHOO_NEWS_TOP_PICKS_RSS = "https://news.yahoo.co.jp/rss/topics/top-picks.xml"
YAHOO_NEWS_DOMESTIC_RSS = "https://news.yahoo.co.jp/rss/categories/domestic.xml"

# Both feeds are fetched together when using the yahoo_news source.
YAHOO_NEWS_RSS_FEEDS = [YAHOO_NEWS_TOP_PICKS_RSS, YAHOO_NEWS_DOMESTIC_RSS]


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


def _fetch_article_text(url: str, timeout: int = 10) -> str:
    """Fetch article body text from the given URL.

    Uses trafilatura (readability-style extraction) as the primary method.
    It reliably extracts main article content while ignoring ads, navigation,
    user comments, and other boilerplate — regardless of the source site's
    HTML structure.

    Falls back to og:description / meta description when trafilatura
    cannot extract meaningful content.

    Returns empty string on failure.
    """
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; mynews-radio-bot/1.0)")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(512 * 1024)  # max 512 KB
            charset = resp.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        logger.debug("_fetch_article_text: failed to fetch %s: %s", url, exc)
        return ""

    try:
        html_text = raw.decode(charset, errors="replace")
    except LookupError:
        html_text = raw.decode("utf-8", errors="replace")

    # Primary: trafilatura extracts main article body
    # (ignores ads, nav, user comments, expert annotations, etc.)
    try:
        import trafilatura
        extracted = trafilatura.extract(
            html_text,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        if extracted and len(extracted.strip()) >= 50:
            return extracted.strip()[:1500]
    except Exception as exc:
        logger.debug("_fetch_article_text: trafilatura failed for %s: %s", url, exc)

    # Fallback: extract og:description / meta description
    import html.parser

    class _MetaExtractor(html.parser.HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.og_description: str = ""
            self.meta_description: str = ""

        def handle_starttag(self, tag: str, attrs: list) -> None:  # type: ignore[override]
            if tag != "meta":
                return
            attrs_d = dict(attrs)
            prop = attrs_d.get("property", "")
            name = attrs_d.get("name", "").lower()
            content = attrs_d.get("content", "")
            if prop == "og:description" and content:
                self.og_description = content
            elif name == "description" and content and not self.meta_description:
                self.meta_description = content

    ext = _MetaExtractor()
    try:
        ext.feed(html_text)
    except Exception:
        pass

    if ext.og_description:
        return ext.og_description[:1500]
    if ext.meta_description:
        return ext.meta_description[:1500]
    return ""


def _parse_yahoo_rss_feed(
    rss_url: str,
    today: "date",
    seen_article_urls: set[str],
) -> list[dict[str, Any]]:
    """Fetch and parse a single Yahoo! News RSS 2.0 feed.

    Returns parsed item dicts with an extra ``_article_url`` key.
    Items whose canonical article URL is already in *seen_article_urls* are skipped
    (deduplication across multiple feeds).  Newly seen URLs are added to the set.
    """
    import email.utils
    import xml.etree.ElementTree as ET

    logger.info("Fetching Yahoo! News RSS from %s", rss_url)
    req = urllib.request.Request(rss_url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; mynews-radio-bot/1.0)")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read()
    except urllib.error.HTTPError as e:
        logger.error("Failed to fetch Yahoo! News RSS %s: HTTP %d", rss_url, e.code)
        return []
    except Exception as e:
        logger.error("Failed to fetch Yahoo! News RSS %s: %s", rss_url, e)
        return []

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as e:
        logger.error("Failed to parse Yahoo! News RSS XML %s: %s", rss_url, e)
        return []

    channel = root.find("channel")
    if channel is None:
        logger.error("Yahoo! News RSS %s: no <channel> element found", rss_url)
        return []

    items: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pub_date_el = item.find("pubDate")
        comments_el = item.find("comments")

        title = (title_el.text or "").strip() if title_el is not None else ""
        url = (link_el.text or "").strip() if link_el is not None else ""

        if not title or not url:
            continue

        published_at = today.isoformat()
        if pub_date_el is not None and pub_date_el.text:
            try:
                parsed_dt = email.utils.parsedate_to_datetime(pub_date_el.text.strip())
                published_at = parsed_dt.date().isoformat()
            except Exception:
                pass

        # <comments> holds the Yahoo News article comment page URL.
        # Strip the trailing "/comments" suffix to get the article body page.
        article_url = (comments_el.text or "").strip() if comments_el is not None else ""
        if article_url.endswith("/comments"):
            article_url = article_url[: -len("/comments")]
        if not article_url:
            article_url = url

        # Skip duplicates already seen in an earlier feed.
        if article_url in seen_article_urls:
            continue
        seen_article_urls.add(article_url)

        items.append({
            "title": title,
            "source": "yahoo_news",
            "url": url,
            "text": "",
            "published_at": published_at,
            "_article_url": article_url,
        })

    return items


def fetch_yahoo_news_articles() -> list[dict[str, Any]]:
    """Fetch news from all Yahoo! Japan News RSS feeds defined in YAHOO_NEWS_RSS_FEEDS.

    Currently fetches:
    - Top-picks (https://news.yahoo.co.jp/rss/topics/top-picks.xml)
    - Domestic news (https://news.yahoo.co.jp/rss/categories/domestic.xml)

    Article text is fetched from each item's canonical article URL in parallel
    using trafilatura for reliable body extraction.  Duplicate articles across
    feeds are deduplicated by canonical URL.

    Returns a list of article dicts suitable for ArticleService.upsert_article().
    """
    import concurrent.futures

    today = date.today()
    seen_article_urls: set[str] = set()
    raw_items: list[dict[str, Any]] = []

    for rss_url in YAHOO_NEWS_RSS_FEEDS:
        feed_items = _parse_yahoo_rss_feed(rss_url, today, seen_article_urls)
        raw_items.extend(feed_items)
        logger.info("Parsed %d items from %s", len(feed_items), rss_url)

    # Fetch article text in parallel (max 4 concurrent requests)
    logger.info("Fetching article text for %d Yahoo! News items", len(raw_items))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_idx = {
            executor.submit(_fetch_article_text, item["_article_url"]): idx
            for idx, item in enumerate(raw_items)
        }
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                raw_items[idx]["text"] = future.result()
            except Exception as exc:
                logger.warning("Failed to fetch text for item %d: %s", idx, exc)

    articles: list[dict[str, Any]] = []
    for item in raw_items:
        item.pop("_article_url", None)
        articles.append(item)
        logger.debug("Yahoo! News article: title=%s text_len=%d", item["title"], len(item["text"]))

    logger.info("Fetched %d articles from Yahoo! News RSS", len(articles))
    return articles


def import_yahoo_news_articles() -> tuple[int, int]:
    """Import general news articles from Yahoo! Japan News top-picks RSS into the DB.

    Returns (inserted, duplicated) counts.
    """
    from app.services.article_service import ArticleService

    service = ArticleService()
    articles = fetch_yahoo_news_articles()
    inserted = 0
    duplicated = 0
    for article in articles:
        created = service.upsert_article(article)
        if created:
            inserted += 1
        else:
            duplicated += 1

    logger.info("import_yahoo_news done: inserted=%d duplicated=%d", inserted, duplicated)
    return inserted, duplicated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ins, dup = auto_fetch_hatena_articles()
    print(f"inserted={ins} duplicated={dup}")
