"""週末ダイジェスト回（過去1週間の総集編）の選定・台本生成・パイプライン。

通常回で放送済みの記事とその要約（articles.summary）を再利用し、記事の再取得・
再要約は行わない。音声合成・MP3統合は通常回と同じパイプライン部品を使う。
"""

import json
import logging
import math
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.build_episode import build_episode  # noqa: E402
from app.batch.radio_pipeline import DEFAULT_EPISODES_DIR, PipelineResult, _determine_tts_config  # noqa: E402
from app.batch.synthesize_voicevox import synthesize_episode  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db.connection import get_db_connection  # noqa: E402
from app.programs.profiles import (  # noqa: E402
    ProgramProfile,
    format_cast_personas,
    get_default_profile,
    profile_voice_overrides,
    segment_snapshots,
)
from app.prompts.service import render_prompt  # noqa: E402
from app.services.article_service import _importance_of, normalize_title, titles_are_similar  # noqa: E402
from app.services.dgx_busy import run_with_dgx_busy  # noqa: E402
from app.services.episode_service import EpisodeService  # noqa: E402
from app.services.llm_call_log_service import infer_episode_id, set_llm_context  # noqa: E402
from app.services.ollama_client import OllamaClient, create_llm_client  # noqa: E402
from app.services.telegram_notifier import notify_failure, notify_success  # noqa: E402
from app.services.thumbnail_service import start_thumbnail_generation  # noqa: E402

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
DIGEST_EPISODE_TYPE = "digest"
WEEKLY_DIGEST_OPERATION = "weekly_digest"
DIGEST_PROGRAM_NAME = "ニュースのとなり"
DIGEST_TITLE_LABEL = "週末ダイジェスト"

# 選定: 1回で扱う記事数と、単一カテゴリの上限(max_articles に対する割合)。
DIGEST_MAX_ARTICLES = 12
DIGEST_MIN_ARTICLES = 3
DIGEST_CATEGORY_MAX_RATIO = 0.4
# カテゴリ上限で候補が足りなくなる場合に、上限を緩めてでも確保する最低件数。
DIGEST_CATEGORY_RELAX_MIN = 6

# 尺: 読み上げ約330文字/分として 10〜12分 ≒ 3300〜4000文字。1行は平均80文字前後を目安にする。
DIGEST_TARGET_CHARS_MIN = 3300
DIGEST_TARGET_CHARS_MAX = 4000
DIGEST_AVG_CHARS_PER_LINE = 80

_ALLOWED_SECTIONS = {"intro", "news", "outro"}


# ---------------------------------------------------------------------------
# ISO週
# ---------------------------------------------------------------------------


def iso_week_bounds(target: date) -> tuple[date, date]:
    """target を含むISO週の (月曜, 日曜) を返す。"""
    monday = target - timedelta(days=target.weekday())
    return monday, monday + timedelta(days=6)


def iso_week_label(target: date) -> str:
    """ISO週ラベル（例: 2026-W47）。年またぎはISO年で表す。"""
    iso_year, iso_week, _ = target.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def digest_today() -> date:
    """cronの実行環境TZに依らず、JSTの今日を返す。"""
    return datetime.now(JST).date()


def completion_window_utc(target: date) -> tuple[str, str]:
    """ISO週の月曜0:00 JST 〜 target日の翌0:00 JST を、DBのUTC時刻文字列で返す。

    通常回のepisode_dateは実行環境TZの日付で付くため、日付ではなく完成時刻(updated_at)で
    「その週に放送済み」を判定する。月曜朝の通常回も、その週の総集編に含まれる。
    """
    monday, _ = iso_week_bounds(target)
    start = datetime.combine(monday, time.min, tzinfo=JST)
    end = datetime.combine(target + timedelta(days=1), time.min, tzinfo=JST)
    fmt = "%Y-%m-%d %H:%M:%S"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def find_week_digest(target: date) -> dict[str, Any] | None:
    """target と同じISO週に、失敗していないダイジェストがあれば返す。

    生成中・待機中・確認待ちも「既にある」として扱い、二重生成を防ぐ。
    """
    monday, sunday = iso_week_bounds(target)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, status FROM episodes "
            "WHERE type = ? AND episode_date BETWEEN ? AND ? AND status != 'failed' "
            "ORDER BY id ASC LIMIT 1",
            (DIGEST_EPISODE_TYPE, monday.isoformat(), sunday.isoformat()),
        ).fetchone()
    return dict(row) if row else None


def count_failed_week_digests(target: date) -> int:
    monday, sunday = iso_week_bounds(target)
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM episodes "
            "WHERE type = ? AND episode_date BETWEEN ? AND ? AND status = 'failed'",
            (DIGEST_EPISODE_TYPE, monday.isoformat(), sunday.isoformat()),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def build_digest_title(target: date) -> str:
    return f"{DIGEST_PROGRAM_NAME} {DIGEST_TITLE_LABEL} {iso_week_label(target)}"


# ---------------------------------------------------------------------------
# 記事選定
# ---------------------------------------------------------------------------


def fetch_broadcast_articles(target: date) -> list[dict[str, Any]]:
    """target を含むISO週に完成した通常回(type='radio')で放送された記事を重複なく返す。

    未完成・失敗した回、解説回(commentary)の記事は含めない。要約が無い記事は
    再要約せず除外する。
    """
    window_start, window_end = completion_window_utc(target)
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT a.id, a.title, a.source, a.url, a.summary, a.category,
                   a.importance_score
            FROM episodes e
            JOIN episode_items i ON i.episode_id = e.id
            JOIN articles a ON a.id = i.article_id
            WHERE e.type = 'radio'
              AND e.status = 'completed'
              AND e.updated_at >= ? AND e.updated_at < ?
              AND a.summary IS NOT NULL AND TRIM(a.summary) != ''
            """,
            (window_start, window_end),
        ).fetchall()
    return [dict(row) for row in rows]


def _category_key(article: dict[str, Any]) -> str:
    return str(article.get("category") or "").strip().casefold()


def _is_duplicate_topic(article: dict[str, Any], selected: list[dict[str, Any]]) -> bool:
    title = article.get("title")
    for chosen in selected:
        if article.get("url") and article.get("url") == chosen.get("url"):
            return True
        if normalize_title(title) == normalize_title(chosen.get("title")) or titles_are_similar(
            title, chosen.get("title")
        ):
            return True
    return False


def pick_digest_articles(
    candidates: list[dict[str, Any]],
    *,
    max_articles: int = DIGEST_MAX_ARTICLES,
) -> list[dict[str, Any]]:
    """重要度順に、重複トピックを除き、単一カテゴリに偏らないよう選ぶ。

    カテゴリごとの上限は max_articles の一定割合。上限で件数が足りない場合に限り、
    DIGEST_CATEGORY_RELAX_MIN 件まで上限を超えて補充する。
    """
    ordered = sorted(candidates, key=lambda a: (-_importance_of(a), a["id"]))
    category_cap = max(2, math.ceil(max_articles * DIGEST_CATEGORY_MAX_RATIO))
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []

    for article in ordered:
        if len(selected) >= max_articles:
            break
        if _is_duplicate_topic(article, selected):
            continue
        key = _category_key(article)
        if counts.get(key, 0) >= category_cap:
            deferred.append(article)
            continue
        selected.append(article)
        counts[key] = counts.get(key, 0) + 1

    for article in deferred:
        if len(selected) >= min(DIGEST_CATEGORY_RELAX_MIN, max_articles):
            break
        if _is_duplicate_topic(article, selected):
            continue
        selected.append(article)

    return sorted(selected, key=lambda a: (-_importance_of(a), a["id"]))


def select_digest_articles(
    target: date, *, max_articles: int = DIGEST_MAX_ARTICLES
) -> list[dict[str, Any]]:
    return pick_digest_articles(fetch_broadcast_articles(target), max_articles=max_articles)


# ---------------------------------------------------------------------------
# 台本生成
# ---------------------------------------------------------------------------


def suggested_lines_count() -> int:
    target_mid = (DIGEST_TARGET_CHARS_MIN + DIGEST_TARGET_CHARS_MAX) // 2
    return round(target_mid / DIGEST_AVG_CHARS_PER_LINE)


def script_char_count(script: dict[str, Any]) -> int:
    return sum(len(str(line.get("text", ""))) for line in script.get("lines", []))


def _summary_payload(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": article["id"],
        "title": article.get("title", ""),
        "source": article.get("source", ""),
        "category": article.get("category", ""),
        "importance_score": article.get("importance_score"),
        "summary": article.get("summary", ""),
    }


def generate_digest_script(
    output_path: str,
    articles: list[dict[str, Any]],
    target_date: date,
    *,
    program_profile: ProgramProfile | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> int:
    """選定済み記事の要約からダイジェスト台本を生成し、行数を返す(失敗時0)。"""
    settings = get_settings()
    profile = program_profile or get_default_profile(kind="radio")
    speaker_keys = tuple(member.key for member in profile.cast)
    if len(speaker_keys) != 2:
        raise ValueError("digest script requires a two-person program profile")
    episode_id = infer_episode_id(output_path)
    article_ids = {article["id"] for article in articles}

    summaries = [_summary_payload(article) for article in articles]
    variables = {
        "week_label": iso_week_label(target_date),
        "article_count": len(summaries),
        "suggested_lines_count": suggested_lines_count(),
        "target_chars_min": DIGEST_TARGET_CHARS_MIN,
        "target_chars_max": DIGEST_TARGET_CHARS_MAX,
        "summaries_json": json.dumps(summaries, ensure_ascii=False, indent=2),
    }
    rendered = render_prompt(
        "generate_digest_script", variables,
        program_id=profile.id if episode_id is not None else None,
    )
    prompt = "\n\n".join((rendered.text, format_cast_personas(profile)))

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    # 管理画面のプロンプト確認(保存済みの入力変数での再レンダリング)用。
    output_file.with_name("summaries.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_file.with_name("prompt_context.json").write_text(
        json.dumps(variables, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    client_factory = (
        (lambda: create_llm_client(llm_provider, llm_model))
        if (llm_provider or llm_model)
        else (lambda: OllamaClient(settings.ollama_base_url, settings.ollama_model))
    )
    with client_factory() as client:
        set_llm_context(
            client, phase="script", episode_id=episode_id, prompt_version_id=rendered.version_id
        )
        response = client.generate_json(prompt)

    if response is None or not isinstance(response.get("lines"), list):
        logger.error("Invalid digest script JSON generated")
        return 0

    script: dict[str, Any] = {
        "date": target_date.isoformat(),
        "title": build_digest_title(target_date),
        "subtitle": str(response.get("subtitle", "")),
        "style": "dialogue",
        "program_profile_id": profile.id,
        "segments": segment_snapshots(profile),
        "lines": [],
    }
    for line in response["lines"]:
        if not isinstance(line, dict):
            continue
        text = str(line.get("text", "")).strip()
        if not text:
            continue
        speaker = str(line.get("speaker", speaker_keys[0]))
        if speaker not in speaker_keys:
            speaker = speaker_keys[0]
        section = str(line.get("section", "news"))
        if section not in _ALLOWED_SECTIONS:
            section = "news"
        article_id = line.get("article_id")
        script["lines"].append({
            "speaker": speaker,
            "text": text,
            # 選定外の記事IDは episode_items のFK違反になるため落とす。
            "article_id": article_id if article_id in article_ids else None,
            "section": section,
            "delivery": line.get("delivery", "neutral"),
        })

    total_chars = script_char_count(script)
    if not DIGEST_TARGET_CHARS_MIN * 0.8 <= total_chars <= DIGEST_TARGET_CHARS_MAX * 1.2:
        logger.warning(
            "digest script length is outside the target: chars=%d target=%d-%d lines=%d",
            total_chars, DIGEST_TARGET_CHARS_MIN, DIGEST_TARGET_CHARS_MAX, len(script["lines"]),
        )

    Path(output_path).write_text(
        json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    logger.info(
        "digest script generated: lines=%d chars=%d output=%s",
        len(script["lines"]), total_chars, output_path,
    )
    return len(script["lines"])


# ---------------------------------------------------------------------------
# パイプライン
# ---------------------------------------------------------------------------


def run_digest_pipeline(
    episode_id: int,
    *,
    episode_date: str,
    tts_engine: str | None = None,
    default_episodes_dir: str | None = None,
) -> dict[str, Any] | PipelineResult | None:
    """ダイジェスト回を生成する。成功時はmetadata、記事不足時は NO_CONTENT、失敗時は None。"""
    service = EpisodeService()
    target_date = date.fromisoformat(episode_date)
    base_dir = os.path.join(default_episodes_dir or DEFAULT_EPISODES_DIR, str(episode_id))
    title = build_digest_title(target_date)
    notification_sent = False

    def _fail(phase: str, error: object) -> None:
        nonlocal notification_sent
        service.update_episode_status(episode_id, "failed")
        if notification_sent:
            return
        notification_sent = True
        try:
            notify_failure(episode_id=episode_id, phase=phase, error=error)
        except Exception:
            logger.warning("[%d] Telegram failure notification could not be sent", episode_id)

    try:
        service.update_episode_status(episode_id, "generating")
        service.update_episode_phase(episode_id, "start", "ダイジェストの生成を準備しています…")
        Path(base_dir).mkdir(parents=True, exist_ok=True)

        # -- SELECT --
        service.update_episode_phase(episode_id, "select_articles", "放送済み記事を選定しています…")
        articles = select_digest_articles(target_date)
        logger.info(
            "[%d] digest articles selected: %d (%s)",
            episode_id, len(articles), iso_week_label(target_date),
        )
        if len(articles) < DIGEST_MIN_ARTICLES:
            logger.info("[%d] digest skipped: not enough broadcast articles", episode_id)
            service.delete_episode(episode_id)
            return PipelineResult.NO_CONTENT

        # -- GENERATE SCRIPT --
        from app.services.llm_provider import resolve_pipeline_llm_selection, validate_provider_model

        service.update_episode_phase(episode_id, "generate_script", "ダイジェスト台本を生成しています…")
        llm_selection = resolve_pipeline_llm_selection()
        try:
            content_llm = validate_provider_model(
                llm_selection.content_provider, llm_selection.content_model
            )
        except Exception:
            logger.exception("[%d] digest content LLM is unavailable", episode_id)
            _fail("generate_script", "台本生成用LLMを利用できません")
            return None
        profile = get_default_profile(kind="radio")
        script_path = os.path.join(base_dir, "script.json")
        line_count = run_with_dgx_busy(
            "generate_digest", generate_digest_script, script_path, articles, target_date,
            program_profile=profile, llm_provider=content_llm.name, llm_model=content_llm.model,
        )
        if line_count <= 0:
            _fail("generate_script", "ダイジェスト台本を生成できませんでした")
            return None
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        service.update_episode_key_points(episode_id, [a["title"] for a in articles[:3]])

        # -- SYNTHESIZE TTS --
        tts_config = _determine_tts_config(tts_engine)
        speaker_male = tts_config["speaker_male"]
        speaker_female = tts_config["speaker_female"]
        speaker_overrides = profile_voice_overrides(profile, tts_config["tts_engine"])
        if speaker_overrides:
            speaker_male = speaker_overrides.get("male", speaker_male)
            speaker_female = speaker_overrides.get("female", speaker_female)

        service.update_episode_phase(episode_id, "synthesize", "音声を合成しています…")
        job_id = _active_job_id(episode_id)
        try:
            success_count = run_with_dgx_busy(
                "synthesize", synthesize_episode, base_dir,
                base_url=tts_config["base_url"],
                speaker_male=speaker_male,
                speaker_female=speaker_female,
                tts_engine=tts_config["tts_engine"],
                episode_id=episode_id,
                generation_job_id=job_id,
                speaker_overrides=speaker_overrides,
            )
        except Exception:
            logger.exception("[%d] digest tts synthesis failed", episode_id)
            _fail("synthesize", "音声合成に失敗しました")
            return None
        if success_count <= 0:
            _fail("synthesize", "音声ファイルが生成されませんでした")
            return None

        service.update_episode_mc_voice_name(
            episode_id,
            speaker_female.strip()
            if tts_config["tts_engine"] == "fishs2pro"
            and isinstance(speaker_female, str) and speaker_female.strip()
            else None,
        )

        # -- BUILD MP3 --
        service.update_episode_phase(episode_id, "build", "音声をまとめています…")
        metadata = build_episode(base_dir, episode_id=episode_id, generation_job_id=job_id)
        if not metadata:
            _fail("build", "音声ファイルの統合に失敗しました")
            return None
        service.update_episode_audio_path(episode_id, metadata.get("audio_path") or "")

        # -- PERSIST ITEMS --
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                final_script = json.load(f)
            for idx, line in enumerate(final_script.get("lines", []), start=1):
                article_id = line.get("article_id")
                service.add_episode_item(
                    episode_id=episode_id,
                    article_id=int(article_id) if article_id is not None else None,
                    item_order=idx,
                    segment_text=line.get("text", ""),
                    audio_generation_id=f"ep{episode_id}-seg{idx}",
                )
        except Exception:
            logger.exception("[%d] failed to persist digest episode_items", episode_id)
            _fail("persist", "番組データの保存に失敗しました")
            return None

        service.complete_radio_episode_with_notification(episode_id)
        try:
            start_thumbnail_generation(
                episode_id, title=title, topic=str(script.get("subtitle") or ""),
            )
        except Exception:
            logger.exception("[%d] failed to start thumbnail generation", episode_id)
        try:
            notify_success(title=str(metadata.get("title") or title), episode_id=episode_id, seq=0)
        except Exception:
            logger.warning("[%d] Telegram success notification could not be sent", episode_id)
        service.update_episode_phase(episode_id, "complete", "ダイジェストの生成が完了しました")
        logger.info("[%d] digest completed successfully", episode_id)
        return metadata

    except Exception:
        current = service.get_episode(episode_id)
        if current is not None and current["status"] not in {"completed", "failed"}:
            logger.exception("[%d] digest generation failed unexpectedly", episode_id)
            _fail("unknown", "予期しないエラーが発生しました")
        return None


def _active_job_id(episode_id: int) -> int | None:
    """詳細ログ用に、episodeへ紐づく直近の生成ジョブIDを返す(best-effort)。"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id FROM generation_jobs WHERE episode_id = ? ORDER BY id DESC LIMIT 1",
                (episode_id,),
            ).fetchone()
            return row["id"] if row else None
    except Exception:
        logger.exception("generation_job_idの取得に失敗しました episode_id=%d", episode_id)
        return None


def run_digest_job(job) -> bool:
    """ジョブキューから実行される本体。記事不足で生成しない場合も成功扱い。"""
    payload = json.loads(job["payload"] or "{}")
    result = run_digest_pipeline(
        job["episode_id"],
        episode_date=payload["date"],
        tts_engine=payload.get("tts_engine"),
    )
    return result is not None
