"""
review_script.py — 4-director script review + revision step.

Reads an existing script.json (source_script_path), runs four character-based
LLM reviews, then synthesises all feedback into a revised script written to
output_dir/script.json.  A review.json is also written to output_dir.

Returns a plain dict so the caller never needs to catch an exception from this
module; failures are logged and indicated via the "revised" key.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Director definitions
# ---------------------------------------------------------------------------

_DIRECTOR_KEYS = ("genius", "beginner", "worried", "positive")

_PROMPT_FILES: dict[str, str] = {
    "genius":   "review_genius_director.md",
    "beginner": "review_beginner_director.md",
    "worried":  "review_worried_director.md",
    "positive": "review_positive_director.md",
}

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_script(source_script_path: str, output_dir: str) -> dict:
    """Review *source_script_path* with 4 directors and write a revised script.

    Args:
        source_script_path: Path to the original script.json (read-only).
        output_dir:         Directory for output files (script.json, review.json).
                            The directory must already exist.

    Returns:
        dict with keys:
            revised (bool)          – True when a revised script was written.
            review_count (int)      – Number of director reviews that succeeded.
            revision_summary (str)  – LLM-generated summary of changes, or "".
            lines_count (int)       – Number of lines in the revised script, or 0.
    """
    settings = get_settings()

    # --- Load original script ---
    try:
        source: dict = json.loads(Path(source_script_path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("review_script: failed to read source script %s: %s", source_script_path, exc)
        return {"revised": False, "review_count": 0, "revision_summary": "", "lines_count": 0}

    script_json_str = json.dumps(source, ensure_ascii=False, indent=2)

    reviews: dict[str, dict] = {}
    review_count = 0
    revised = False
    revision_summary = ""
    lines_count = 0

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:

        # --- Step 1: collect individual director reviews ---
        for key in _DIRECTOR_KEYS:
            try:
                template = _load_prompt(_PROMPT_FILES[key])
                prompt = template.format(script_json=script_json_str)
                result = client.generate_json(prompt)
                if result and isinstance(result, dict):
                    reviews[key] = result
                    review_count += 1
                    logger.info(
                        "review_script: director=%s score=%s issues=%d",
                        key,
                        result.get("overall_score", "?"),
                        len(result.get("issues", [])),
                    )
                else:
                    logger.warning("review_script: director=%s returned None/invalid", key)
                    reviews[key] = {}
            except Exception as exc:
                logger.warning("review_script: director=%s failed: %s", key, exc)
                reviews[key] = {}

        # --- Step 2: synthesise reviews into a revised script ---
        try:
            synth_template = _load_prompt("review_synthesize.md")
            synth_prompt = synth_template.format(
                original_script_json=script_json_str,
                genius_review=json.dumps(reviews.get("genius", {}), ensure_ascii=False, indent=2),
                beginner_review=json.dumps(reviews.get("beginner", {}), ensure_ascii=False, indent=2),
                worried_review=json.dumps(reviews.get("worried", {}), ensure_ascii=False, indent=2),
                positive_review=json.dumps(reviews.get("positive", {}), ensure_ascii=False, indent=2),
            )
            synth_response = client.generate_json(synth_prompt)

            if synth_response and isinstance(synth_response.get("lines"), list) and synth_response["lines"]:
                revised_script = _build_revised_script(source, synth_response)
                revision_summary = str(synth_response.get("revision_summary", ""))
                lines_count = len(revised_script["lines"])

                output_script_path = os.path.join(output_dir, "script.json")
                Path(output_script_path).write_text(
                    json.dumps(revised_script, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                logger.info(
                    "review_script: revised script written lines=%d path=%s",
                    lines_count,
                    output_script_path,
                )
                revised = True
            else:
                logger.warning("review_script: synthesis returned invalid response; no script written")

        except Exception as exc:
            logger.warning("review_script: synthesis step failed: %s", exc)

    # --- Save review.json ---
    _write_review_json(
        output_dir=output_dir,
        source_script_path=source_script_path,
        reviews=reviews,
        revision_summary=revision_summary,
        revised=revised,
    )

    return {
        "revised": revised,
        "review_count": review_count,
        "revision_summary": revision_summary,
        "lines_count": lines_count,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_revised_script(source: dict, response: dict) -> dict:
    """Construct the final script dict from the LLM synthesis response."""
    script: dict = {
        "date": source.get("date", ""),
        "title": str(response.get("title", source.get("title", ""))),
        "subtitle": str(response.get("subtitle", source.get("subtitle", ""))),
        "lines": [],
    }

    valid_sections = {"intro", "news", "transition", "discussion", "outro"}

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if speaker not in {"male", "female"}:
            speaker = "male"
        section = str(line.get("section", "news"))
        if section not in valid_sections:
            section = "news"
        script["lines"].append(
            {
                "speaker": speaker,
                "text": str(line.get("text", "")).strip(),
                "article_id": line.get("article_id"),
                "section": section,
            }
        )

    return script


def _write_review_json(
    output_dir: str,
    source_script_path: str,
    reviews: dict,
    revision_summary: str,
    revised: bool,
) -> None:
    review_data = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source_script_path": source_script_path,
        "reviews": reviews,
        "revision_summary": revision_summary,
        "revised": revised,
    }
    review_path = os.path.join(output_dir, "review.json")
    try:
        Path(review_path).write_text(
            json.dumps(review_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("review_script: review.json written to %s", review_path)
    except Exception as exc:
        logger.warning("review_script: failed to write review.json: %s", exc)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) < 3:
        print("Usage: review_script.py <source_script_path> <output_dir>", file=sys.stderr)
        sys.exit(1)

    result = review_script(sys.argv[1], sys.argv[2])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["revised"] else 1)
