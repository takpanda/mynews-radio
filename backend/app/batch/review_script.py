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
import re as _re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.generate_script import _is_broken_transition_text
from app.batch.structure_scan import scan_script_structure
from app.config import get_settings
from app.services.ollama_client import OllamaClient, create_llm_client
from app.services.llm_call_log_service import infer_episode_id, set_llm_context

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


def _load_structure_scan_inputs(source_script_path: str, source: dict) -> tuple[list[dict], object]:
    """レビュー後スキャン用の要約とArc選定記事IDを読み込む。"""
    summaries_path = Path(source_script_path).with_name("summaries.json")
    summaries: list[dict] = []
    try:
        loaded = json.loads(summaries_path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            summaries = [item for item in loaded if isinstance(item, dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        logger.info("review_script: summaries.json unavailable for structure scan: %s", exc)
    return summaries, source.get("discussion_article_id")


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
        "- **記事境界の transition が両MCの短い掛け合い（2行）になっているか。**\n"
        "  片方のMCの単独告知1行だけで終わっている場合は指摘すること（discussion直前のtransitionは1行でよい）\n"
        "- MC間の対話バランス（片方だけが情報発信していないか）\n"
        "- discussion が対話形式として成立しているか（男女交互に喋っているか）\n"
        "- **discussion が選んだ1本の記事の内容だけで構成され、他の記事の話題が混ざっていないか**\n"
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
# Dialogue balance check — 山口(female)の質問偏重・一問一答の連続を検知する
#
# generate_radio_script.md / review_synthesize.md の「山口の非質問文の義務化」
# 「一問一答の連続を避ける」要件（BEE-631）が守られているかを news セクション
# 単位で検査する。transition・discussion の構造やプロンプト本文は対象外。
# ---------------------------------------------------------------------------

_QUESTION_SUFFIX_RE = _re.compile(r"(?:[?？]|か)[。!！]?\s*$")


def _is_question(text: str) -> bool:
    """text が疑問文かどうかを判定する。

    末尾が「?」「？」の場合に加えて、「〜ですか。」「〜でしょうか。」のような
    句点付きの疑問終助詞「か」で終わる自然な日本語の疑問文も疑問文として扱う。
    """
    return bool(_QUESTION_SUFFIX_RE.search(text.strip()))


def _news_blocks(lines: list) -> list:
    """section が連続する "news" 行を記事単位のブロックへまとめて返す。

    transition・discussion など他セクションを挟むとブロックが区切られる。
    各ブロックは (行インデックス, 行dict) のタプルのリスト。
    """
    blocks: list = []
    current: list = []
    for i, line in enumerate(lines):
        if line.get("section") == "news":
            current.append((i, line))
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def check_dialogue_balance(lines: list) -> list[str]:
    """山口(female)の発言が質問のみに偏っていないか、newsブロック単位で検査する。

    既存の lint_script（app/batch/generate_script.py）と同じ
    「[TAG] メッセージ」形式でリストを返す。空リストなら合格。

    - [YAMAGUCHI_QUESTION_ONLY]: newsブロック内の山口の発言が全て疑問文
    - [QA_RELAY]: 山口の発言がブロック内で唯一・末尾の質問だけで、
      田村の回答を受けた掛け合いの続き（山口の感想・意見や田村の補足）が無い
      （山口の非質問発言や複数往復を経た上での質問→回答は対象外）
    """
    issues: list[str] = []

    for block in _news_blocks(lines):
        female_entries = [
            (i, line.get("text", "")) for i, line in block
            if line.get("speaker") == "female" and line.get("text", "").strip()
        ]
        if not female_entries:
            continue

        if all(_is_question(text) for _, text in female_entries):
            indices = [i for i, _ in female_entries]
            issues.append(
                f"[YAMAGUCHI_QUESTION_ONLY] news行 {indices} の山口(female)発言が全て疑問文です。"
                "感想・分析・別角度の提起など疑問文以外の発言を1行以上含めてください"
            )

        if len(block) >= 2 and len(female_entries) == 1:
            (prev_idx, prev_line), (last_idx, last_line) = block[-2], block[-1]
            if (
                prev_line.get("speaker") == "female"
                and _is_question(prev_line.get("text", ""))
                and last_line.get("speaker") == "male"
            ):
                issues.append(
                    f"[QA_RELAY] news行 {prev_idx}〜{last_idx} が山口の質問→田村の回答の1往復だけで終わっています。"
                    "田村の回答の後に山口の感想・意見などの掛け合いを続けてください"
                )

    return issues


# ---------------------------------------------------------------------------
# Transition integrity check — 前の記事の締め文と次の記事の告知が1行に
# 混在した壊れたtransition（BEE-661/BEE-662）がレビュー後の最終台本に
# 残っていないかを検査する。
#
# 生成工程（generate_script.py の _ensure_transitions()）は同じ判定条件で
# 壊れたtransitionを検知し、安全なテンプレート文へ置換済みの script.json を
# 本関数の入力とする前提。一方でこのレビュー工程はLLMによる台本再統合
# （review_synthesize.md）を経るため、レビューLLMが新たに複文混在の
# transitionを生成し直す可能性はゼロではない。しかしレビュー工程は次の記事の
# 正しいトピック（記事タイトル・要約）を持たないため、生成工程と同様の
# 安全な置換文を再構成できない。そのため本関数は検知のみを行い review.json
# に記録する（非fatal）。置換が必要な場合は台本を再生成するか、後続の
# レビューサイクルでの修正に委ねる。
# ---------------------------------------------------------------------------

def check_transition_integrity(lines: list) -> list[str]:
    """記事境界のtransition行に、前の記事の締め文と次の記事の告知が混在した
    壊れた文が残っていないかを検査する。

    lint_script（app/batch/generate_script.py）の [TRANSITION_SOLO] と同様に
    連続するtransition行をブロック単位でまとめ、直後がnews行であるブロック
    （＝記事境界のtransition）のみを対象とする。discussion直前のtransitionは
    複文スタイルが正常なため対象外。
    """
    issues: list[str] = []
    sections = [line.get("section") for line in lines]

    blocks: list[list[int]] = []
    current: list[int] = []
    for i, s in enumerate(sections):
        if s == "transition":
            current.append(i)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)

    for block in blocks:
        next_idx = block[-1] + 1
        if next_idx >= len(sections) or sections[next_idx] != "news":
            continue
        for i in block:
            text = lines[i].get("text", "")
            if _is_broken_transition_text(text):
                issues.append(
                    f"[TRANSITION_MIXED] transition行 {i} に前の記事の締め文と次の記事の"
                    f"告知が混在している可能性があります: 「{text[:40]}...」"
                )

    return issues


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_script(source_script_path: str, output_dir: str, *, llm_provider: str | None = None, llm_model: str | None = None) -> dict:
    """Review *source_script_path* with 5 directors and write a revised script.

    Args:
        source_script_path: Path to the original script.json (read-only).
        output_dir:         Directory for output files (script.json, review.json).
                            The directory must already exist.

    Returns:
        dict with keys:
            revised (bool)                    – True when a revised script was written AND
                                                 safe to adopt. 呼び出し元（orchestrate.py /
                                                 radio_pipeline.py / app/api/generate.py）は
                                                 全てこのフラグのみを見て output_dir/script.json
                                                 を本番の script.json へ上書きコピーするため、
                                                 transition_integrity_issues を検出した場合は
                                                 revised が書き出されていても False に強制し、
                                                 呼び出し元に生成工程で既に安全化済みの
                                                 script.json を維持させる（BEE-661/BEE-662,
                                                 CodeReviewer must指摘）。output_dir/script.json
                                                 自体は診断用にそのまま残る。
            review_count (int)                – Number of director reviews that succeeded.
            revision_summary (str)            – LLM-generated summary of changes, or "".
            lines_count (int)                 – Number of lines in the revised script, or 0.
            dialogue_balance_issues (list[str]) – 山口(female)の質問偏重・一問一答の
                                                   連続を検出した警告。空リストなら合格。
                                                   (style="solo" の台本では常に空)
            transition_integrity_issues (list[str]) – 記事境界のtransitionに前の記事の
                                                   締め文と次の記事の告知が混在した壊れた
                                                   文（BEE-661/BEE-662）を検出した警告。
                                                   空リストなら合格。検知した場合、次の記事の
                                                   正しいトピックを持たないため自動置換は
                                                   行わず、代わりに revised を False に落とす
                                                   ことでレビュー版の採用自体を止める
                                                   （生成工程の _ensure_transitions() が同じ
                                                   判定条件で検知・置換済みの安全な
                                                   script.json が既に存在する前提）。
    """
    settings = get_settings()

    # --- Load original script ---
    try:
        source: dict = json.loads(Path(source_script_path).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("review_script: failed to read source script %s: %s", source_script_path, exc)
        return {
            "revised": False,
            "review_count": 0,
            "revision_summary": "",
            "lines_count": 0,
            "dialogue_balance_issues": [],
            "transition_integrity_issues": [],
            "structure_scan_warnings": [],
        }

    script_json_str = json.dumps(source, ensure_ascii=False, indent=2)

    reviews: dict[str, dict] = {}
    review_count = 0
    revised = False
    revision_summary = ""
    lines_count = 0
    revised_script: dict | None = None

    client_factory = (lambda: create_llm_client(llm_provider, llm_model)) if (llm_provider or llm_model) else (lambda: OllamaClient(settings.ollama_base_url, settings.ollama_model))
    with client_factory() as client:

        # --- Step 1: collect individual director reviews ---
        style = source.get("style", "")  # "solo", "dialogue", or "" (radio)

        for key in _DIRECTOR_KEYS:
            try:
                set_llm_context(client, phase="review", episode_id=infer_episode_id(source_script_path))
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
            set_llm_context(client, phase="correction", episode_id=infer_episode_id(source_script_path))
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

    # --- Step 3: 掛け合いバランスの自動検査（非fatal）---
    # revised が書き出す最終行を対象に、山口(female)の質問偏重・一問一答の
    # 連続を検査する。solo（一人喋り）は対話が成立しないため対象外。
    dialogue_balance_issues: list[str] = []
    if style != "solo":
        dialogue_check_lines = revised_script["lines"] if (revised and revised_script) else source.get("lines", [])
        dialogue_balance_issues = check_dialogue_balance(dialogue_check_lines)
        if dialogue_balance_issues:
            logger.warning(
                "review_script: dialogue balance check found %d issue(s):\n%s",
                len(dialogue_balance_issues),
                "\n".join(f"  - {issue}" for issue in dialogue_balance_issues),
            )

    # --- Step 4: 記事境界transitionの複文混入チェック（BEE-661/BEE-662）---
    # レビューLLMの再統合（review_synthesize.md）が新たに複文混在のtransitionを
    # 生成し直した場合、そのままでは呼び出し元（orchestrate.py / radio_pipeline.py /
    # app/api/generate.py）が全て「revised=True なら output_dir/script.json を
    # 本番の script.json へ上書きコピーする」という同一の判定パターンで動いており、
    # 壊れたtransitionを含むレビュー後台本がそのまま最終成果物として採用されて
    # しまう（CodeReviewer must指摘）。
    #
    # レビュー工程は次の記事の正しいトピックを持たないため安全な置換文を
    # 再構成できない（check_transition_integrity のコメント参照）。そのため
    # ここでは「壊れたレビュー版を採用させない」安全策として revised を False に
    # 落とし、呼び出し元に生成工程が既に安全化済みの script.json（_ensure_transitions()
    # 適用済み）を維持させる。output_dir/script.json 自体は診断用にそのまま残す。
    transition_check_lines = revised_script["lines"] if (revised and revised_script) else source.get("lines", [])
    transition_integrity_issues = check_transition_integrity(transition_check_lines)
    if transition_integrity_issues:
        logger.warning(
            "review_script: transition integrity check found %d issue(s):\n%s",
            len(transition_integrity_issues),
            "\n".join(f"  - {issue}" for issue in transition_integrity_issues),
        )
        if revised:
            logger.warning(
                "review_script: rejecting reviewed script due to transition integrity "
                "issues; forcing revised=False so callers keep the pre-review "
                "script.json instead of adopting %s",
                os.path.join(output_dir, "script.json"),
            )
            revised = False

    structure_summaries, expected_discussion_article_id = _load_structure_scan_inputs(
        source_script_path, source
    )
    structure_scan_warnings = scan_script_structure(
        transition_check_lines,
        structure_summaries,
        expected_discussion_article_id=expected_discussion_article_id,
    )
    if structure_scan_warnings:
        logger.warning(
            "review_script: 台本構造スキャンで%d件の警告:\n%s",
            len(structure_scan_warnings),
            "\n".join(f"  - {warning}" for warning in structure_scan_warnings),
        )

    # --- Save review.json ---
    _write_review_json(
        output_dir=output_dir,
        source_script_path=source_script_path,
        reviews=reviews,
        revision_summary=revision_summary,
        revised=revised,
        dialogue_balance_issues=dialogue_balance_issues,
        transition_integrity_issues=transition_integrity_issues,
        structure_scan_warnings=structure_scan_warnings,
    )

    return {
        "revised": revised,
        "review_count": review_count,
        "revision_summary": revision_summary,
        "lines_count": lines_count,
        "dialogue_balance_issues": dialogue_balance_issues,
        "transition_integrity_issues": transition_integrity_issues,
        "structure_scan_warnings": structure_scan_warnings,
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
    if source.get("discussion_article_id") is not None:
        script["discussion_article_id"] = source["discussion_article_id"]

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
    dialogue_balance_issues: list[str] | None = None,
    transition_integrity_issues: list[str] | None = None,
    structure_scan_warnings: list[str] | None = None,
) -> None:
    review_data = {
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "source_script_path": source_script_path,
        "reviews": reviews,
        "revision_summary": revision_summary,
        "revised": revised,
        "dialogue_balance_issues": dialogue_balance_issues or [],
        "transition_integrity_issues": transition_integrity_issues or [],
        "structure_scan_warnings": structure_scan_warnings or [],
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
