"""
review_script.py — 5-director script review + revision step.

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

_DIRECTOR_KEYS = ("genius", "beginner", "worried", "positive", "radio")

_PROMPT_FILES: dict[str, str] = {
    "genius":   "review_genius_director.md",
    "beginner": "review_beginner_director.md",
    "worried":  "review_worried_director.md",
    "positive": "review_positive_director.md",
    "radio":    "review_radio_director.md",
}

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _build_radio_director_style_guidance(style: str) -> str:
    """Return style-specific evaluation guidance for the radio director prompt.

    Args:
        style: Script style — "solo", "dialogue", or empty string (radio script).

    Returns:
        A Japanese-language guidance string that tells the LLM which evaluation
        axes to use and which to skip based on *style*.
    """
    if style == "solo":
        return (
            "## 本台本の形式\n"
            "この台本は **一人喋り（solo）** のコメンタリー形式です。\n"
            "MC は1人であり、対話・掛け合いは存在しません。\n"
            "\n"
            "### 評価の観点（solo モード）\n"
            "- 一人の語り手としてのテンポ・聞きやすさ・飽きさせない工夫\n"
            "- 「聴く」メディアに適した一文の長さ・語彙レベル\n"
            "- 番組の音楽・間合いを考慮した展開\n"
            "- ナレーションとしての自然な流れ（話題の繋ぎ方）\n"
            "\n"
            "### 評価対象外（solo では成立しない観点）\n"
            "- ❌ MC間の対話バランス（一人なので該当しない）\n"
            "- ❌ 男女交互発話（一人なので成立しない）\n"
            "- ❌ transition での前の話題への言及（Contextual Bridge）\n"
            "  これは必須ではありません。一人語りでは「次は〜についてです」\n"
            "  のような単純な繋ぎで十分な場合があります。\n"
            "  （ただし、自然な話題転換ができているかは引き続き評価してよい）\n"
        )
    # dialogue mode (including radio script without style field)
    return (
        "## 本台本の形式\n"
        "この台本は **二人対談（dialogue）** 形式です。\n"
        "MC（male / female）が交互に発話します。\n"
        "\n"
        "### 評価の観点（dialogue モード）\n"
        "- transition が前の話題に自然に言及しているか（Contextual Bridge の有無）\n"
        "  - 「続いては気象に関する話題です」→ △（前の話題への言及なし）\n"
        "  - 「そういった極限的な脅威から視点を移して、次に〜」→ ○\n"
        "- MC間の対話バランス（片方だけが情報発信していないか）\n"
        "- discussion が対話形式として成立しているか（男女交互に喋っているか）\n"
        "- リスナーが無理なく聴き続けられるテンポ・抑揚・飽きの防止\n"
        "- 「聴く」メディアに適した一文の長さ・語彙レベル\n"
        "- 番組の音楽・間合いを考慮した展開\n"
    )


def _build_output_issue_example(style: str) -> str:
    """Return a style-appropriate output format example for the radio director.

    Args:
        style: Script style — "solo", "dialogue", or empty string (radio script).

    Returns:
        A JSON block string that serves as the output format example in the prompt.
        The example issue is chosen to match the target delivery style so the LLM
        is not biased toward evaluating criteria irrelevant to the style.
    """
    if style == "solo":
        return (
            '{\n'
            '  "character": "ラジオディレクター",\n'
            '  "overall_score": 7,\n'
            '  "issues": [\n'
            '    {\n'
            '      "line_index": 5,\n'
            '      "issue": "一人喋りが単調で同じトーンが続いており、メリハリに欠ける",\n'
            '      "suggestion": "数字を読み上げる箇所で語気を強めたり、意見を述べる前に一拍間を置くなど、強弱をつけると聴きやすい"\n'
            '    }\n'
            '  ],\n'
            '  "general_feedback": "一人喋りとしての聞きやすさについて一言コメント"\n'
            '}'
        )
    return (
        '{\n'
        '  "character": "ラジオディレクター",\n'
        '  "overall_score": 7,\n'
        '  "issues": [\n'
        '    {\n'
        '      "line_index": 3,\n'
        '      "issue": "transitionで前の話題への言及がなく、唐突に次の話題に移っている",\n'
        '      "suggestion": "「そういったリスクを踏まえた上で、次はこちらの話題に目を向けてみましょう」のように前の話題に一言触れてから次に移る"\n'
        '    }\n'
        '  ],\n'
        '  "general_feedback": "音声メディアとしての聴きやすさについて一言コメント"\n'
        '}'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_script(source_script_path: str, output_dir: str) -> dict:
    """Review *source_script_path* with 5 directors and write a revised script.

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
        style = source.get("style", "")  # "solo", "dialogue", or "" (radio)

        for key in _DIRECTOR_KEYS:
            try:
                template = _load_prompt(_PROMPT_FILES[key])
                if key == "radio":
                    style_guidance = _build_radio_director_style_guidance(style)
                    output_issue_example = _build_output_issue_example(style)
                    prompt = template.format(
                        script_json=script_json_str,
                        style_guidance=style_guidance,
                        output_issue_example=output_issue_example,
                    )
                else:
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
            mode = source.get("style", "dialogue")
            mc_gender = source.get("mc_gender", "male")
            synth_prompt = synth_template.format(
                original_script_json=script_json_str,
                mode=mode,
                mc_gender=mc_gender,
                genius_review=json.dumps(reviews.get("genius", {}), ensure_ascii=False, indent=2),
                beginner_review=json.dumps(reviews.get("beginner", {}), ensure_ascii=False, indent=2),
                worried_review=json.dumps(reviews.get("worried", {}), ensure_ascii=False, indent=2),
                positive_review=json.dumps(reviews.get("positive", {}), ensure_ascii=False, indent=2),
                radio_review=json.dumps(reviews.get("radio", {}), ensure_ascii=False, indent=2),
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
    is_commentary = "style" in source
    if is_commentary:
        title = source.get("title", "")
        subtitle = source.get("subtitle", "")
    else:
        title = str(response.get("title", source.get("title", "")))
        subtitle = str(response.get("subtitle", source.get("subtitle", "")))

    style = source.get("style") if is_commentary else None
    mc_gender = source.get("mc_gender") if is_commentary else None

    script: dict = {
        "date": source.get("date", ""),
        "title": title,
        "subtitle": subtitle,
        "lines": [],
    }
    if style:
        script["style"] = style
    if mc_gender:
        script["mc_gender"] = mc_gender

    valid_sections = {"intro", "news", "transition", "discussion", "outro"}

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if style == "solo" and mc_gender:
            speaker = mc_gender
        else:
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
                "delivery": line.get("delivery", "neutral"),
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
