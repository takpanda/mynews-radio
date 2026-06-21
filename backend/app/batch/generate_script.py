import json
import logging
import os
import random
import re as _re
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
]

_BRIDGE_TRANSITION_PHRASES = [
    "{bridge} さて、{topic}の話題です。",
    "{bridge} それでは、{topic}のニュースをどうぞ。",
    "{bridge} そんな中、{topic}についても見ていきましょう。",
    "{bridge} では次は{topic}の話題をご紹介します。",
    "{bridge} 続いては{topic}の最新情報です。",
    "{bridge} ここで視点を変えて、{topic}を見てみましょう。",
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
    """遷移行の話者を選ぶ。

    直前の news / discussion のみを取り出し、以下のルールで決定：
    - 同一話者の連続が 2 回以上 → 強制的に相手側
    - 同じ article_id 内のコンテンツ行の話者パターンがあればそれと交互に
    - それ以外は直前の最後の話者と交互
    """
    if not result:
        return "male"

    # transition は除く（自分の挿入結果に引っ張られないよう）
    content_speakers = [
        prev_line.get("speaker")
        for prev_line in reversed(result)
        if prev_line.get("section") in ("news", "discussion")
    ][:3]

    if not content_speakers:
        return "male"

    last_spk = content_speakers[0]
    alternate = "female" if last_spk == "male" else "male"

    # 直前のコンテンツ行（news/discussionのみ）が同じ話者で2回以上連続している場合
    run = 1
    for sp in content_speakers[1:]:
        if sp == last_spk:
            run += 1
        else:
            break
    if run >= 2:
        return alternate

    # 前後のセクション内容を見る：直前の news が female ばかりのときは male を選ぶ等
    # content_speakers の内訳を見て、バランスが偏っている場合は少数側を選ぶ
    male_count = sum(1 for s in content_speakers if s == "male")
    female_count = len(content_speakers) - male_count
    if male_count > female_count + 1:
        return "female"
    if female_count > male_count + 1:
        return "male"

    # news 遷移：直前のコンテンツと交互（バランスも考慮済みなので自然に）
    if section == "news":
        return alternate

    # discussion 遷移：同様に交互
    return alternate


def _ensure_transitions(lines: list, summaries: list, arc: dict | None = None) -> list:
    """LLM が生成した lines を後処理し、article_id 切り替わり境界に
    transition 行を確実に挿入して返す。LLM が既に挿入した transition は保持する。

    arc が与えられた場合、bridges 情報を参照して Contextual Bridge を
    考慮した transition 文を生成する。"""
    bridge_map: dict = {}
    if arc and isinstance(arc, dict):
        for b in arc.get("bridges", []):
            if not isinstance(b, dict):
                continue
            from_id = b.get("from_article_id")
            to_id = b.get("to_article_id")
            bridge_text = b.get("bridge_text", "")
            if from_id is not None and to_id is not None and bridge_text:
                bridge_map.setdefault(from_id, {})[to_id] = bridge_text

    topic_map: dict = {}
    for art in summaries:
        art_id = art.get("id")
        if art_id is not None:
            raw_summary = art.get("summary", "") or ""
            raw_title = art.get("title") or art.get("url", "") or ""
            if raw_summary:
                sentence_end = -1
                for sep in ("。", "…", "..."):
                    idx = raw_summary.find(sep)
                    if idx >= 0 and (sentence_end < 0 or idx < sentence_end):
                        sentence_end = idx + len(sep)
                if sentence_end > 0:
                    candidate = raw_summary[:sentence_end]
                    topic_map[art_id] = candidate if len(candidate) <= 25 else raw_title[:25] or "次の話題"
                else:
                    segment = _re.split(r"[、,;：]", raw_summary)[0].strip()
                    topic_map[art_id] = segment if segment and len(segment) <= 25 else raw_title[:25] or "次の話題"
            elif raw_title:
                title_clean = _re.split(r"[、,;：・]", raw_title)[0].strip()
                topic_map[art_id] = title_clean if len(title_clean) >= 3 else raw_title[:25] or "次の話題"
            else:
                topic_map[art_id] = "次の話題"

    def _topic(article_id) -> str:
        if article_id is None:
            return "次の話題"
        return topic_map.get(article_id, "次の話題")

    result: list = []
    last_content_aid = None   # 直前の news/discussion の article_id
    trans_phrase_used = {"last": None}  # 乱択重複回避用状態

    for line in lines:
        section = line.get("section", "news")
        article_id = line.get("article_id")

        if section in ("news", "discussion"):
            prev_is_transition = bool(result) and result[-1].get("section") == "transition"

            # LLM が transition を出力していても、その article_id が現在の記事と
            # 一致しない場合は誤った帰属とみなし、LLM の transition を削除して
            # プログラム側の transition で置き換える
            if prev_is_transition:
                llm_trans_aid = result[-1].get("article_id")
                if llm_trans_aid is not None and llm_trans_aid != article_id:
                    removed = result.pop()
                    logger.debug("LLM transition 削除: article_id=%s text=%s", removed.get("article_id"), removed.get("text", "")[:60])
                    prev_is_transition = False

            # article_id が変わった（または intro→news）かつ直前が transition でない場合に挿入
            if not prev_is_transition and article_id != last_content_aid:
                speaker = _pick_speaker(result, section)
                if section == "discussion":
                    phrases = _DISCUSSION_TRANSITIONS
                    text = _pick_phrase(phrases, trans_phrase_used).format(topic=_topic(article_id))
                elif last_content_aid is not None and last_content_aid in bridge_map and article_id in bridge_map[last_content_aid]:
                    bridge_text = bridge_map[last_content_aid][article_id]
                    bridge_topic = _topic(article_id)
                    text = _pick_phrase(_BRIDGE_TRANSITION_PHRASES, trans_phrase_used).format(bridge=bridge_text, topic=bridge_topic)
                else:
                    phrases = _TRANSITION_PHRASES
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


# ---------------------------------------------------------------------------
# Auto-Linter
# ---------------------------------------------------------------------------

# 禁止フレーズ（プロンプトの Forbidden Phrases と同期すること）
_FORBIDDEN_PHRASES = [
    "ここで大事なのは、背景ですよね",
    "ここで大事なのは背景ですよね",
    "といったところです。",
    "といった内容です。",
    "一見シンプルに見えますが、実は構造的な問題があります",
    "これは感情論だけでは片づけられません",
    "これ、普通に暮らしている人からするとかなり大きいですよね",
    "正直、そこが一番気になります",
    "視聴者の方も、ここはモヤっとすると思います",
]

# 数字なしで使うと問題になる表現（単体検出用）
_REQUIRES_DIGITS = [
    "数字で見ると",
    "数字だけ見ると分かるんですけど",
]


def _has_digits(text: str) -> bool:
    """テキスト中に数字（全角・半角）または具体的な量を示す単語が含まれるか。"""
    import re
    return bool(re.search(r"[0-9０-９]|[一二三四五六七八九十百千万億兆](?:人|件|回|社|倍|円|割|%|パーセント)", text))


def _levenshtein_ratio(s1: str, s2: str) -> float:
    """2つの文字列の正規化Levenshtein類似度を返す（0.0〜1.0）。"""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    len1, len2 = len(s1), len(s2)
    prev = list(range(len1 + 1))
    for i, ch2 in enumerate(s2, 1):
        curr = [i]
        for j, ch1 in enumerate(s1, 1):
            cost = 0 if ch1 == ch2 else 1
            curr.append(min(
                curr[-1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            ))
        prev = curr
    distance = prev[len1]
    max_len = max(len1, len2)
    return 1.0 - (distance / max_len) if max_len > 0 else 1.0


def lint_script(
    lines: list,
    program_name: str = "ニュースのとなり",
    bridges: list[dict] | None = None,
) -> list[str]:
    """生成済み lines に対して品質チェックを行い、問題点のリストを返す。
    返値が空リストなら合格。"""
    errors: list[str] = []

    seen_texts: set[str] = set()
    phrase_counts: dict[str, int] = {}

    # --- ルール1: introフォーマットチェック [INTRO_FORMAT] (ERROR) ---
    intro_lines = [(i, line) for i, line in enumerate(lines) if line.get("section") == "intro"]
    if intro_lines:
        first_intro_text = intro_lines[0][1].get("text", "").strip()
        expected_prefix = f"「{program_name}」の時間です"
        if not first_intro_text.startswith(expected_prefix):
            errors.append(
                f"[INTRO_FORMAT] introの1行目が「{expected_prefix}」で始まっていません: "
                f"「{first_intro_text[:50]}」"
            )
    else:
        errors.append("[INTRO_FORMAT] introセクションが存在しません")

    # --- ルール2: introラインアップチェック [INTRO_LINEUP] (WARN) ---
    intro_texts = [line.get("text", "") for line in lines if line.get("section") == "intro"]
    if intro_texts:
        combined = "".join(intro_texts)
        lineup_keywords = ["ラインナップ", "ラインアップ", "トピック", "本日", "今日", "今回", "ニュース"]
        found = [kw for kw in lineup_keywords if kw in combined]
        if len(found) < 2:
            errors.append(
                f"[INTRO_LINEUP] introにラインアップを示唆する表現が不足しています "
                f"(検出されたキーワード: {found})"
            )

    # --- ルール3: outro充実度チェック [OUTRO_LENGTH] (ERROR) ---
    outro_count = sum(1 for line in lines if line.get("section") == "outro")
    if outro_count < 2:
        errors.append(
            f"[OUTRO_LENGTH] outroセクションが{outro_count}行しかありません（最低2行必要）"
        )

    # --- ルール4: transitionバリエーションチェック [TRANS_VARIATION] (ERROR) ---
    trans_lines = [
        (i, line.get("text", "").strip())
        for i, line in enumerate(lines)
        if line.get("section") == "transition" and line.get("text", "").strip()
    ]
    _TRANS_SIMILARITY_THRESHOLD = float(os.getenv("LINT_TRANS_SIMILARITY", "0.7"))
    for idx_a in range(len(trans_lines)):
        for idx_b in range(idx_a + 1, len(trans_lines)):
            i, text_i = trans_lines[idx_a]
            j, text_j = trans_lines[idx_b]
            ratio = _levenshtein_ratio(text_i, text_j)
            if ratio >= _TRANS_SIMILARITY_THRESHOLD:
                errors.append(
                    f"[TRANS_VARIATION] transition行 {i} と {j} の類似度が {ratio:.2f} です: "
                    f"「{text_i[:30]}...」「{text_j[:30]}...」"
                )

    # --- ルール5: transitionコンテキストチェック [TRANS_CONTEXT] (ERROR) ---
    if bridges:
        first_trans_idx: int | None = None
        for i, line in enumerate(lines):
            if line.get("section") == "transition":
                first_trans_idx = i
                break
        for i, line in enumerate(lines):
            if line.get("section") != "transition":
                continue
            if i == first_trans_idx:
                continue
            text = line.get("text", "").strip()
            if not text:
                continue
            if _re.search(r"次の話題|次のトピック", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"^続いては", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"^次は", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")
            elif _re.search(r"では次", text):
                errors.append(f"[TRANS_CONTEXT] transition行 {i} に汎用表記が含まれています: 「{text[:40]}...」")

    # discussion が全 news の後に来ているか確認
    sections = [line.get("section") for line in lines]
    discussion_indices = [i for i, s in enumerate(sections) if s == "discussion"]
    news_indices = [i for i, s in enumerate(sections) if s == "news"]
    if discussion_indices and news_indices:
        last_news = max(news_indices)
        first_discussion = min(discussion_indices)
        if first_discussion < last_news:
            errors.append(
                f"discussion が全 news より前に挿入されています "
                f"(discussion 最初の行インデックス={first_discussion}, 最後の news インデックス={last_news})"
            )

    for i, line in enumerate(lines):
        text = line.get("text", "").strip()
        section = line.get("section", "")
        speaker = line.get("speaker", "")

        # 重複テキスト検出
        if text and text in seen_texts:
            errors.append(f"行 {i}: テキストが重複しています: 「{text[:40]}...」")
        if text:
            seen_texts.add(text)

        # 禁止フレーズ検出
        for phrase in _FORBIDDEN_PHRASES:
            if phrase in text:
                errors.append(f"行 {i} ({speaker}): 禁止フレーズ「{phrase}」が含まれています")

        # 口癖フレーズの出現回数カウント（1回超でエラー）
        all_catchphrases = [
            "一見シンプルに見えますが、実は構造的な問題があります",
            "これは感情論だけでは片づけられません",
            "これ、普通に暮らしている人からするとかなり大きいですよね",
            "正直、そこが一番気になります",
            "視聴者の方も、ここはモヤっとすると思います",
        ]
        for cp in all_catchphrases:
            if cp in text:
                phrase_counts[cp] = phrase_counts.get(cp, 0) + 1
                if phrase_counts[cp] > 1:
                    errors.append(f"行 {i}: 口癖「{cp[:20]}...」が2回以上使われています")

        # 「数字で見ると」系フレーズで数字がない場合
        for req in _REQUIRES_DIGITS:
            if req in text and not _has_digits(text):
                errors.append(
                    f"行 {i} ({speaker}): 「{req}」を使っているが具体的な数字・データが含まれていません"
                )

        # transition行の不完全チェック（WARN: 演出上の「間」意図の可能性を考慮し警告レベル）
        if section == "transition":
            if _re.search(r"[……‥]{2,}$", text):
                errors.append(f"[WARN][TRUNCATED_TRANS] transition行 {i} が不完全な文で終わっています: 「{text[:40]}...」")
            elif len(text) < 5:
                errors.append(f"[WARN][TRUNCATED_TRANS] transition行 {i} が短すぎます: 「{text[:40]}...」")

        # 記事IDのトピック表記（「記事XX」「（ID: XX）」など）を検出
        id_refs = [
            r"(?:^|[^a-zA-Z0-9])(?:記事)\d+",
            r"\(ID:\s*\d+\)",
            r"article_id[=：:]\s*\d+",
        ]
        for pattern in id_refs:
            for m in _re.finditer(pattern, text):
                errors.append(f"行 {i} ({speaker}): 記事IDの参照表記が検出されました: 「{m.group(0).strip()}」")

    return errors


def _build_correction_prompt(original_prompt: str, lines: list, errors: list[str]) -> str:
    """Linter エラーに基づいて修正指示付きプロンプトを生成する。"""
    errors_text = "\n".join(f"- {e}" for e in errors)
    lines_json = json.dumps(lines, ensure_ascii=False, indent=2)
    return (
        f"{original_prompt}\n\n"
        "# ⚠️ 前回の生成で以下の品質問題が検出されました。これらをすべて修正して再生成してください。\n\n"
        f"{errors_text}\n\n"
        "## 前回生成した lines（修正対象）:\n"
        f"```json\n{lines_json}\n```\n\n"
        "上記の問題を修正した完全な台本 JSON を出力してください。"
    )


def _load_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_radio_script.md"
    return prompt_path.read_text(encoding="utf-8")


def _load_arc_prompt_template() -> str:
    prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "generate_narrative_arc.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_narrative_arc_section(arc: dict, summaries: list) -> str:
    """Narrative Arc の情報をプロンプトに注入するセクション文字列を生成する。"""
    id_to_title = {s["id"]: (s.get("title") or s.get("url", ""))[:40] for s in summaries}

    lines = [
        "# 今回のエピソード設計（Narrative Arc）\n",
        f"**共通テーマ**: {arc.get('theme', '')}",
        f"**テーマ概要**: {arc.get('theme_description', '')}",
        "",
        "**記事の紹介順序**（この順番で全記事を紹介すること）:",
    ]
    for i, aid in enumerate(arc.get("article_order", []), 1):
        title = id_to_title.get(aid, f"記事{aid}")
        lines.append(f"  {i}. 記事ID={aid}：{title}")

    bridges = arc.get("bridges", [])
    if bridges:
        lines.append("")
        lines.append("**記事間の橋渡し（Contextual Bridge）**（transition行でこの文脈を活かすこと）:")
        for b in bridges:
            if not isinstance(b, dict):
                continue
            from_id = b.get("from_article_id")
            to_id = b.get("to_article_id")
            bridge = b.get("bridge_text", "")
            lines.append(f"  - 記事{from_id} → 記事{to_id}: {bridge}")

    disc_id = arc.get("discussion_article_id")
    disc_reason = arc.get("discussion_reason", "")
    if disc_id:
        lines.append("")
        lines.append(f"**discussion で深掘りする記事**: 記事ID={disc_id}（{id_to_title.get(disc_id, '')}）")
        lines.append(f"  理由: {disc_reason}")

    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Step 1: Architect — Narrative Arc 生成
# ---------------------------------------------------------------------------

def _generate_arc(client: OllamaClient, summaries: list) -> dict | None:
    """Narrative Arc を生成して返す。失敗時は None。"""
    template = _load_arc_prompt_template()
    summaries_json = json.dumps(summaries, ensure_ascii=False, indent=2)
    prompt = template.format(summaries_json=summaries_json)

    arc = client.generate_json(prompt)
    if not arc or not isinstance(arc.get("article_order"), list):
        logger.warning("Narrative Arc generation failed or returned invalid structure; skipping arc")
        return None

    logger.info(
        "Narrative Arc generated: theme=%s order=%s discussion=%s",
        arc.get("theme", ""),
        arc.get("article_order", []),
        arc.get("discussion_article_id"),
    )
    return arc


# ---------------------------------------------------------------------------
# Step 2: Writer — 台本生成
# ---------------------------------------------------------------------------

def _reorder_summaries(summaries: list, article_order: list) -> list:
    """arc の article_order に従って summaries を並べ替える。未収録 ID はそのまま末尾に追加。"""
    id_map = {s["id"]: s for s in summaries}
    reordered = [id_map[aid] for aid in article_order if aid in id_map]
    seen = set(article_order)
    reordered += [s for s in summaries if s["id"] not in seen]
    return reordered


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

    response = None
    ordered_summaries = summaries  # デフォルトは元の順序

    with OllamaClient(settings.ollama_base_url, settings.ollama_model) as client:

        # --- Step 1: Architect — Narrative Arc 生成 ---
        logger.info("=== Script Step 1/2: Narrative Arc (Architect) ===")
        arc = _generate_arc(client, summaries)

        # Arc に基づいて記事の順序を確定
        if arc and arc.get("article_order"):
            ordered_summaries = _reorder_summaries(summaries, arc["article_order"])
            narrative_arc_section = _build_narrative_arc_section(arc, summaries)
        else:
            narrative_arc_section = ""

        # --- Step 2: Writer — 台本生成 + Auto-Lint 再生成ループ ---
        logger.info("=== Script Step 2/2: Script generation (Writer) ===")
        template = _load_prompt_template()
        if program_name != "ニュースのとなり":
            template = template.replace("ニュースのとなり", program_name)
        summaries_json = json.dumps(ordered_summaries, ensure_ascii=False, indent=2)
        base_prompt = template.format(
            narrative_arc_section=narrative_arc_section,
            summaries_json=summaries_json,
        )

        _MAX_LINT_RETRIES = int(os.getenv("SCRIPT_LINT_RETRIES", "3"))
        current_prompt = base_prompt

        for lint_attempt in range(1, _MAX_LINT_RETRIES + 1):
            response = client.generate_json(current_prompt)
            if response is None or not isinstance(response.get("lines"), list):
                logger.error("Invalid script JSON generated (attempt=%d). Raw response: %s", lint_attempt, response)
                break

            lint_errors = lint_script(
                response["lines"],
                program_name=program_name,
                bridges=arc.get("bridges", []) if arc else None,
            )
            if not lint_errors:
                logger.info("Auto-Lint PASSED (attempt=%d)", lint_attempt)
                break

            logger.warning(
                "Auto-Lint FAILED (attempt=%d/%d): %d issues found:\n%s",
                lint_attempt,
                _MAX_LINT_RETRIES,
                len(lint_errors),
                "\n".join(f"  - {e}" for e in lint_errors),
            )
            if lint_attempt < _MAX_LINT_RETRIES:
                current_prompt = _build_correction_prompt(base_prompt, response["lines"], lint_errors)
            # 最終試行で失敗してもそのまま使用（最善の結果を保持）

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
        
        text = str(line.get("text", "")).strip()

        script["lines"].append(
            {
                "speaker": speaker,
                "text": text,
                "article_id": line.get("article_id"),
                "section": section,
            }
        )

    # LLM が transition を省略した場合に備えてプログラム側で補完する
    script["lines"] = _ensure_transitions(script["lines"], ordered_summaries, arc=arc)

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
