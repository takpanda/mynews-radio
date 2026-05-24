"""Article import module — now uses hatena_bookmark API as the data source.

Replaces the former file-based import (data/articles/articles.json) with
live fetching from news.beeworks.cc API.
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.hatena_fetcher import auto_fetch_hatena_articles  # noqa: E402

logger = logging.getLogger(__name__)


def import_articles(file_path: str | None = None) -> tuple[int, int]:
    """Legacy shim — just delegates to the hatena API fetcher.

    The old `file_path` parameter (local JSON file) is no longer used.
    """
    logger.info("import_articles: using hatena_bookmark API (file_path ignored)")
    return auto_fetch_hatena_articles()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ins, dup = import_articles()
    print(json.dumps({"inserted": ins, "duplicated": dup}, ensure_ascii=False))
