import logging
import urllib.error
import urllib.request
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def fetch_article_by_url(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch article from an arbitrary HTTP(S) URL using trafilatura.

    Extracts title, published date, and body text from the given URL.

    Args:
        url: HTTP(S) URL of the article to fetch.
        timeout: Request timeout in seconds (default 10).

    Returns:
        dict with keys: title, url, text, source (="url_commentary"), published_at.

    Raises:
        ValueError: If url is empty or not HTTP(S).
        urllib.error.URLError: On network errors (unreachable, DNS, timeout, 4xx, 5xx).
        RuntimeError: If trafilatura extraction fails or no meaningful content found.
    """
    if not url or not url.startswith(("http://", "https://")):
        raise ValueError(f"Invalid URL: {url}")

    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0 (compatible; mynews-radio-bot/1.0)")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(512 * 1024)
            charset = resp.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        logger.error("fetch_article_by_url: failed to fetch %s: %s", url, exc)
        raise

    try:
        html_text = raw.decode(charset, errors="replace")
    except LookupError:
        html_text = raw.decode("utf-8", errors="replace")

    import trafilatura

    try:
        extracted = trafilatura.extract(
            html_text,
            url=url,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
            output_format="python",
        )
    except Exception as exc:
        logger.error("fetch_article_by_url: trafilatura extraction failed for %s: %s", url, exc)
        raise RuntimeError(f"Failed to extract article: {exc}")

    if extracted is None:
        logger.error("fetch_article_by_url: trafilatura returned None for %s", url)
        raise RuntimeError(f"Could not extract article content from {url}")

    if isinstance(extracted, dict):
        text = (extracted.get("text") or "").strip()
        title = (extracted.get("title") or "").strip()
        raw_date = (extracted.get("date") or "").strip()
    else:
        text = extracted.strip()
        title = ""
        raw_date = ""

    if not text or len(text) < 50:
        logger.error(
            "fetch_article_by_url: insufficient content from %s (text_len=%d)", url, len(text)
        )
        raise RuntimeError(f"Insufficient article content from {url}")

    if not title:
        logger.warning("fetch_article_by_url: no title found for %s, using URL fallback", url)

    published_at = raw_date[:10] if raw_date else date.today().isoformat()

    return {
        "title": title or f"Article from {url}",
        "url": url,
        "text": text,
        "source": "url_commentary",
        "published_at": published_at,
    }
