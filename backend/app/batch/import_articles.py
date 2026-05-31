"""Article import module — supports hatena_bookmark API and hotentry/all RSS.

Replaces the former file-based import (data/articles/articles.json) with
live fetching from news.beeworks.cc API (tech news) or Hatena RSS (general news).
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.hatena_fetcher import auto_fetch_hatena_articles, import_hotentry_all_articles, import_yahoo_news_articles  # noqa: E402

logger = logging.getLogger(__name__)


def import_articles(file_path: str | None = None) -> tuple[int, int]:
    """Legacy shim — delegates to the hatena API fetcher (tech news).

    The old `file_path` parameter (local JSON file) is no longer used.
    """
    logger.info("import_articles: using hatena_bookmark API (file_path ignored)")
    return auto_fetch_hatena_articles()


def import_articles_by_source(news_source: str = "hatena_bookmark") -> tuple[int, int]:
    """Import articles from the specified news source.

    Args:
        news_source: "hatena_bookmark" (tech news via API),
                     "hatena_hotentry_all" (general news via Hatena RSS), or
                     "yahoo_news" (general news via Yahoo! Japan RSS).
    Returns:
        (inserted, duplicated) counts.
    """
    if news_source == "hatena_hotentry_all":
        logger.info("import_articles_by_source: using hotentry/all RSS")
        return import_hotentry_all_articles()
    if news_source == "yahoo_news":
        logger.info("import_articles_by_source: using Yahoo! News RSS")
        return import_yahoo_news_articles()
    logger.info("import_articles_by_source: using hatena_bookmark API")
    return auto_fetch_hatena_articles()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ins, dup = import_articles()
    print(json.dumps({"inserted": ins, "duplicated": dup}, ensure_ascii=False))
