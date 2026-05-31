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

_TRANSITION_PHRASES = [
    "続いては{topic}のニュースです。",
    "次のニュースに移りましょう。{topic}についてです。",
    "さて、{topic}の話題はどうでしょうか。",
    "話は変わりまして、{topic}のニュースをどうぞ。",
    "もうひとつ気になるニュースがありました。{topic}の話題です。",
    "それでは{topic}の話題に移ります。",
    "{topic}に関しても注目の動きがありましたね。",
    "では次は{topic}の話題をご紹介します。",
    "{topic}についても最新の情報が入ってきました。",
    "ここで{topic}のニュースもご紹介しましょう。",
]

_DISCUSSION_TRANSITIONS = [
    "ここで{topic}についてもう少し掘り下げてみましょう。",
    "{topic}、少し深堀りして話し合ってみましょう。",
    "ちょっとここで{topic}について、ふたりで語ってみたいと思います。",
    "せっかくなので{topic}、じっくり話してみましょうか。",
]


def _ensure_transitions(lines: list, summaries: list) -> list:
    """LLM が生成した lines を後処理し、article_id 切り替わり境界に
    transition 行を確実に挿入して返す。LLM が既に挿入した transition は保持する。"""
    topic_map: dict = {}
    for art in summaries:
        art_id = art.get("id")
        if art_id is not None:
            raw = art.get("title") or art.get("url", "") or ""
            topic_map[art_id] = raw[:15] if raw else f"記事{art_id}"

    def _topic(article_id) -> str:
        if article_id is None:
            return "次の話題"
        return topic_map.get(article_id, f"記事{article_id}")

    result: list = []
    last_content_aid = None   # 直前の news/discussion の article_id
    trans_count = 0
    disc_trans_count = 0

    for line in lines:
        section = line.get("section", "news")
        article_id = line.get("article_id")

        if section in ("news", "discussion"):
            prev_is_transition = bool(result) and result[-1].get("section") == "transition"

            # article_id が変わった（または intro→news）かつ直前が transition でない場合に挿入
            if not prev_is_transition and article_id != last_content_aid:
                speaker = "female" if (result and result[-1].get("speaker") == "male") else "male"
                if section == "discussion":
                    phrases = _DISCUSSION_TRANSITIONS
                    text = phrases[disc_trans_count % len(phrases)].format(topic=_topic(article_id))
                    disc_trans_count += 1
                else:
                    phrases = _TRANSITION_PHRASES
                    text = phrases[trans_count % len(phrases)].format(topic=_topic(article_id))
                    trans_count += 1
                result.append({
                    "speaker": speaker,
                    "text": text,
                    "article_id": article_id,
                    "section": "transition",
                })
                logger.debug("transition 挿入: article_id=%s text=%s", article_id, text)

            last_content_aid = article_id

        elif section == "intro":
            last_content_aid = None

        result.append(line)

    return result


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_radio_script.md"
    return prompt_path.read_text(encoding="utf-8")


def generate_script(output_path: str, program_name: str = "ニュースのとなり") -> int:
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
    if program_name != "ニュースのとなり":
        template = template.replace("ニュースのとなり", program_name)
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    prompt = template.format(summaries_json=summaries_json)

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:
        response = client.generate_json(prompt)

    if response is None or not isinstance(response.get("lines"), list):
        logger.error("Invalid script JSON generated")
        return 0

    script = {
        "date": str(date.today()),
        "title": str(response.get("title", program_name)),
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

    # LLM が transition を省略した場合に備えてプログラム側で補完する
    script["lines"] = _ensure_transitions(script["lines"], summaries)

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
