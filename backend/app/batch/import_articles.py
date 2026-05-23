import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.article_service import ArticleService

logger = logging.getLogger(__name__)


def import_articles(file_path: str) -> tuple[int, int]:
    service = ArticleService()

    with open(file_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, list):
        raise ValueError("articles json must be an array")

    inserted = 0
    duplicated = 0

    for item in payload:
        if not isinstance(item, dict):
            logger.warning("Skip non-object item in input")
            continue

        if not item.get("url"):
            logger.warning("Skip article without url: %s", item.get("title", ""))
            continue

        created = service.upsert_article(item)
        if created:
            inserted += 1
        else:
            duplicated += 1

    logger.info("import done inserted=%d duplicated=%d", inserted, duplicated)
    return inserted, duplicated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "articles", "articles.json")
    ins, dup = import_articles(path)
    print(json.dumps({"inserted": ins, "duplicated": dup}, ensure_ascii=False))
