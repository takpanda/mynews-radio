import json
import logging
import os
import random
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
    "さて、次のトピックです。{topic}についてお伝えします。",
    "ここからは{topic}の話題に入っていきましょう。",
    "続いてお届けするのは{topic}のニュースです。",
    "次の項目は{topic}のお話です。",
    "では、{topic}の最新の動きをご報告します。",
    "ここで視点を変えて、{topic}を見てみましょう。",
    "{topic}についても触れておきましょう。",
    "次は{topic}の話題です。ご注眼ください。",
    "さて、みんなが注目している{topic}の情報ですよ。",
    "少し話題を変えて、{topic}について紹介しましょう。",
    "{topic}に関して気になるニュースが届いていますね。",
    "では、次のコーナーへ。{topic}の最新情報をどうぞ。",

    "お次は{topic}です。どうなっているのでしょうか。",
    "ここからが本題。{topic}に迫ります。",
    "{topic}には次のような動きがあるようです。",
    "引き続き、{topic}の話題をお届けします。",
    "そのほか、{topic}についての情報も集まりました。",
    "さてさて、{topic}はどう動いているのでしょうか。",
    "次にご紹介する{topic}も要チェックです。",
    "ここからはちょっと違う切り口で、{topic}を考えます。",
    "{topic}についても忘れてはいけないニュースがありますよ。",
    "では、もう少し先を見てみましょうか。{topic}の話題でございます。",
    "さあ、次にしましょうか。{topic}についてです。",
]

_DISCUSSION_TRANSITIONS = [
    "ここで{topic}についてもう少し掘り下げてみましょう。",
    "{topic}、少し深堀りして話し合ってみましょう。",
    "ちょっとここで{topic}について、ふたりで語ってみたいと思います。",
    "せっかくなので{topic}、じっくり話してみましょうか。",

    "{topic}、私も気になっているんですよ。どう思います？",
    "ここで一旦立ち止まって{topic}を議論しましょうか。",
    "{topic}について、二人で頭を絞ってみますよ。",
]


def _pick_phrase(phrases: list, used_indices: dict):
    """乱択でフレーズを選んで返す。直前に使用した同じプレースホルダー位置のものを回避する。"""
    n = len(phrases)
    last_idx = used_indices.get("last")
    cands = list(range(n))
    if last_idx is not None and n > 1:
        cands = [i for i in cands if i != last_idx]
    chosen = random.choice(cands)
    used_indices["last"] = chosen
    return phrases[chosen]


def _pick_speaker(result: list, section: str):
    """遷移行の話者を選ぶ。直前のコンテンツ行の話者パターンを確認し、
    同一話者の連続が3回以上にならないよう調整する。"""
    if not result:
        return "male"

    # 直後のcontent行(N個)の話者順列を取り出し、同じ話者が何回連続しているか判定する
    content_speakers = []
    for prev_line in reversed(result):
        if prev_line.get("section") in ("news", "discussion", "transition"):
            content_speakers.append(prev_line.get("speaker"))
        if len(content_speakers) >= 3:
            break

    if not content_speakers:
        return "male"

    # 末尾の話者(直前のもの)
    last_spk = content_speakers[0]

    # 同じ話者が2分以上連続している場合は強制的に相手側を選ぶ
    run = 1
    for sp in content_speakers[1:]:
        if sp == last_spk:
            run += 1
        else:
            break

    alternate = "female" if last_spk == "male" else "male"
    if run >= 2:
        return alternate

    # news遷移では直後のcontentの話者と交互にする(自然な受け答え)
    if section == "news":
        # 直後に行こうとしているニュース記事の担当話者が予測できればそれとは違うものを選ぶが、
        # ここでは単純に「2回連続していない」という条件だけで十分なので交互で返す
        return alternate

    # discussion遷移では同じく交互にするが、前回の議論終了時の担当とは逆側にする
    last_content_spk = None
    for sp in content_speakers:
        if sp is not None:
            last_content_spk = sp
            break
    if last_content_spk:
        return "female" if last_content_spk == "male" else "male"

    return alternate


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
    trans_phrase_used = {"last": None}  # 乱択重複回避用状態

    for line in lines:
        section = line.get("section", "news")
        article_id = line.get("article_id")

        if section in ("news", "discussion"):
            prev_is_transition = bool(result) and result[-1].get("section") == "transition"

            # article_id が変わった（または intro→news）かつ直前が transition でない場合に挿入
            if not prev_is_transition and article_id != last_content_aid:
                speaker = _pick_speaker(result, section)
                phrases = _DISCUSSION_TRANSITIONS if section == "discussion" else _TRANSITION_PHRASES
                text = _pick_phrase(phrases, trans_phrase_used).format(topic=_topic(article_id))
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


def generate_script(output_path: str, program_name: str = "ニュースのとなり", news_source: str | None = None) -> int:
    settings = get_settings()
    max_articles = int(os.getenv("MAX_SCRIPT_ARTICLES", "10"))
    min_score = int(os.getenv("MIN_IMPORTANCE_SCORE", "3"))

    if news_source is None and program_name == "テックニュース":
        news_source = "hatena_bookmark"

    service = ArticleService()
    summaries = service.fetch_summaries_for_script(max_articles=max_articles, min_importance_score=min_score, source=news_source)
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

    # 使用した記事を 'used' にマーク → 次エピソードで重複使用されないようにする
    used_ids = [a["id"] for a in summaries]
    service.mark_articles_used(used_ids)
    logger.info("marked %d articles as used", len(used_ids))

    return len(script["lines"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes", "script.json")
    count = generate_script(out)
    print(json.dumps({"lines": count}, ensure_ascii=False))
    sys.exit(0 if count > 0 else 1)
