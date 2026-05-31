import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.article_service import ArticleService
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "summarize_article.md"
    return prompt_path.read_text(encoding="utf-8")


def summarize_articles(output_path: str) -> int:
    settings = get_settings()
    service = ArticleService()

    articles = service.fetch_new_articles()
    if not articles:
        logger.info("No new articles found")
        Path(output_path).write_text("[]\n", encoding="utf-8")
        return 0

    template = _load_prompt_template()
    results: list[dict] = []

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:
        for article in articles:
            prompt = template.format(
                title=article.get("title", ""),
                source=article.get("source", ""),
                url=article.get("url", ""),
                published_at=article.get("published_at", ""),
                text=article.get("text", ""),
            )
            response = client.generate_json(prompt)
            if response is None:
                logger.error("Skip article id=%s due to invalid json response", article["id"])
                service.update_summary(article["id"], "", "unknown", 0, "error")
                continue

            summary = str(response.get("summary", "")).strip()
            category = str(response.get("category", "general")).strip() or "general"
            try:
                importance_score = int(response.get("importance_score", 3))
            except (TypeError, ValueError):
                importance_score = 3
            importance_score = max(1, min(5, importance_score))
            try:
                difficulty = int(response.get("difficulty", 1))
            except (TypeError, ValueError):
                difficulty = 1
            difficulty = max(1, min(3, difficulty))

            service.update_summary(article["id"], summary, category, importance_score, "summarized", difficulty)
            results.append(
                {
                    "article_id": article["id"],
                    "title": article.get("title"),
                    "summary": summary,
                    "category": category,
                    "importance_score": importance_score,
                    "difficulty": difficulty,
                }
            )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("summarized articles=%d output=%s", len(results), output_path)
    return len(results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "summaries", "summaries.json")
    count = summarize_articles(out)
    print(json.dumps({"summarized": count}, ensure_ascii=False))
