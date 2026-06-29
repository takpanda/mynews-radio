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


def _calc_suggested_lines(text_length: int, style: str) -> int:
    """Calculate suggested number of lines based on article text length and style.

    Args:
        text_length: Length of the article text in characters.
        style: "solo" or "dialogue".

    Returns:
        Suggested number of lines.
    """
    # 50文字未満は記事が空/ほぼ空の場合の安全マージン → 最低保証値
    if text_length < 50:
        return _DEFAULT_LINES_DIALOGUE if style == "dialogue" else _DEFAULT_LINES_SOLO

    if text_length < 2000:
        base = 6
    elif text_length <= 4000:
        base = 8 + (text_length - 2000) // 1000
    else:
        base = min(15, 12 + (text_length - 4000) * 3 // 4000)

    if style == "dialogue" and text_length <= 4000:
        return base + 2
    return base


def _build_section_details(suggested_lines_count: int) -> str:
    """Build dynamic section composition guidance based on suggested line count.

    Args:
        suggested_lines_count: Calculated suggested line count.

    Returns:
        Section guidance string for the prompt template.
    """
    if suggested_lines_count <= 8:
        intro_range = "1〜2"
        news_range = "3〜6"
    elif suggested_lines_count <= 12:
        intro_range = "2"
        news_range = "6〜9"
    else:
        intro_range = "2〜3"
        news_range = "8〜12"

    return (
        "解説は以下の流れで構成してください：\n\n"
        f"1. **導入（intro、{intro_range}行）**\n"
        "   - このエピソードで取り上げるテーマを簡潔に紹介\n"
        "   - なぜこのニュースが気になるのか、一言添える\n"
        "   - リスナーの興味を引く導入\n\n"
        f"2. **本文解説（news、{news_range}行）**\n"
        "   - 何が起きたか・何が発表されたかを具体的に伝える\n"
        "   - 背景・経緯を補足する\n"
        "   - 影響・意義を解説する\n"
        "   - 複数の視点からバランスよく伝える\n"
        "   - dialogueの場合は田村と山口が掛け合い形式で進行\n\n"
        "3. **まとめ（outro、1〜2行）**\n"
        "   - 内容を一言で振り返る\n"
        "   - リスナーへのメッセージや今後の展望に触れてもよい"
    )


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_commentary_script.md"
    return prompt_path.read_text(encoding="utf-8")


def generate_commentary_script(
    output_path: str,
    article: dict,
    style: str = "solo",
    mc_gender: str = "male",
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

    text_length = len(article.get("text", "") or "")
    suggested_lines = _calc_suggested_lines(text_length, style)
    section_details = _build_section_details(suggested_lines)

    article_json = json.dumps({
        "id": article.get("id"),
        "title": article.get("title", ""),
        "text": article.get("text", ""),
    }, ensure_ascii=False, indent=2)

    prompt = template.format(
        style=style,
        mc_gender=mc_gender,
        article_id=article.get("id"),
        article_title=article.get("title", ""),
        suggested_lines_count=suggested_lines,
        section_details=section_details,
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
        "title": str(response.get("title", article.get("title", ""))),
        "subtitle": str(response.get("subtitle", "")),
        "style": style,
        "mc_gender": mc_gender,
        "lines": [],
    }

    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        speaker = str(line.get("speaker", "male"))
        if style == "solo":
            if speaker != mc_gender:
                speaker = mc_gender
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
