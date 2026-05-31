import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.article_service import ArticleService
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_radio_script.md"
    return prompt_path.read_text(encoding="utf-8")


def generate_script(output_path: str) -> int:
    settings = get_settings()
    max_articles = int(os.getenv("MAX_SCRIPT_ARTICLES", "10"))
    min_score = int(os.getenv("MIN_IMPORTANCE_SCORE", "3"))

    service = ArticleService()
    summaries = service.fetch_summaries_for_script(max_articles=max_articles, min_importance_score=min_score)
    if not summaries:
        logger.warning("No summaries to generate script from")
        return 0

    article_urls = ", ".join(
        f"{article['id']}:{article.get('url', '<no-url>')}" for article in summaries
    )
    logger.info("Generating script from summaries: %s", article_urls)

    template = _load_prompt_template()
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    prompt = template.format(summaries_json=summaries_json)

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:
        response = client.generate_json(prompt)

    if response is None or not isinstance(response.get("lines"), list):
        logger.error("Invalid script JSON generated")
        return 0

    script = {
        "date": str(date.today()),
        "title": str(response.get("title", "MyNews Radio")),
        "subtitle": str(response.get("subtitle", "")),
        "lines": [],
    }

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if speaker not in {"male", "female"}:
            speaker = "male"
        section = str(line.get("section", "news"))
        if section not in {"intro", "news", "transition", "discussion", "outro"}:
            section = "news"
        script["lines"].append(
            {
                "speaker": speaker,
                "text": str(line.get("text", "")).strip(),
                "article_id": line.get("article_id"),
                "section": section,
            }
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(script, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("script generated lines=%d output=%s", len(script["lines"]), output_path)
    return len(script["lines"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes", "script.json")
    count = generate_script(out)
    print(json.dumps({"lines": count}, ensure_ascii=False))
    sys.exit(0 if count > 0 else 1)
