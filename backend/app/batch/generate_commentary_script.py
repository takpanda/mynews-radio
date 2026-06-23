import json
import logging
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_DEFAULT_LINES_SOLO = 6
_DEFAULT_LINES_DIALOGUE = 8


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_commentary_script.md"
    return prompt_path.read_text(encoding="utf-8")


def generate_commentary_script(
    output_path: str,
    article: dict,
    style: str = "solo",
) -> int:
    """Generate a commentary script for a single article.

    Args:
        output_path: Path to write the output script.json.
        article: Article dict with at least id, title, text keys.
        style: "solo" (single narrator) or "dialogue" (two-person discussion).

    Returns:
        Number of lines generated (0 on failure).
    """
    settings = get_settings()
    template = _load_prompt_template()

    suggested_lines = _DEFAULT_LINES_SOLO if style == "solo" else _DEFAULT_LINES_DIALOGUE

    article_json = json.dumps({
        "id": article.get("id"),
        "title": article.get("title", ""),
        "text": article.get("text", ""),
    }, ensure_ascii=False, indent=2)

    prompt = template.format(
        style=style,
        article_id=article.get("id"),
        article_title=article.get("title", ""),
        suggested_lines_count=suggested_lines,
        article_json=article_json,
    )

    response = None

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:
        response = client.generate_json(prompt)

    if response is None or not isinstance(response.get("lines"), list):
        logger.error("Invalid commentary script JSON generated")
        return 0

    script = {
        "date": str(date.today()),
        "title": str(response.get("title", f"解説：{article.get('title', '')}")),
        "subtitle": str(response.get("subtitle", "")),
        "style": style,
        "lines": [],
    }

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if style == "solo":
            if speaker not in {"male"}:
                speaker = "male"
        else:
            if speaker not in {"male", "female"}:
                speaker = "male"
        section = str(line.get("section", "news"))
        if section not in {"intro", "news", "outro"}:
            section = "news"

        text = str(line.get("text", "")).strip()

        script["lines"].append({
            "speaker": speaker,
            "text": text,
            "article_id": line.get("article_id"),
            "section": section,
            "delivery": line.get("delivery", "neutral"),
        })

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(
        json.dumps(script, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "commentary script generated: style=%s lines=%d output=%s",
        style, len(script["lines"]), output_path,
    )

    return len(script["lines"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python generate_commentary_script.py <output_path> [solo|dialogue]")
        sys.exit(1)

    out = sys.argv[1]
    style = sys.argv[2] if len(sys.argv) > 2 else "solo"

    article = {
        "id": 0,
        "title": "テスト記事",
        "text": "これはテスト記事の本文です。",
    }

    count = generate_commentary_script(out, article, style=style)
    print(json.dumps({"lines": count}, ensure_ascii=False))
    sys.exit(0 if count > 0 else 1)
