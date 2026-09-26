"""Shared radio generation pipeline - used by both Web UI and Batch."""

import json
import logging
import os
import shutil
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from app.batch.build_episode import build_episode
from app.batch.final_validation import (
    FINAL_VALIDATION_PHASE,
    human_review_message,
    should_run_final_validation,
    validate_final_script_file,
)
from app.batch.generate_script import generate_script
from app.batch.import_articles import import_articles_by_source
from app.batch.review_script import review_script
from app.batch.summarize_articles import summarize_articles
from app.batch.synthesize_voicevox import synthesize_episode
from app.config import get_settings
from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService, override_script_title, build_radio_title
from app.services.article_service import ArticleService, write_fallback_summaries
from app.services.episode_category_service import select_episode_categories
from app.services.fishs2pro_client import FishS2ProClient
from app.services.settings_service import (
    ProgramSettings,
    get_settings_or_default,
    resolve_category_female_voice,
    resolve_tts_speakers,
)
from app.services.telegram_notifier import notify_failure, notify_success, notify_review_needed
from app.services.script_review_service import move_episode_to_awaiting_review


def _extract_key_points(script: dict, summaries_path: str) -> list[str]:
    """script.json と summaries.json から最大3件の要点を抽出する。

    優先順:
    1. 台本で参照されている記事の title を活用
    2. 記事タイトルが不足する場合のみ script の subtitle を活用

    intro はナレーション／会話文であり、視聴者向けの要点ではないため、
    key_points の抽出元には使用しない。
    """
    key_points: list[str] = []

    article_ids_in_script = []
    for line in script.get("lines", []):
        article_id = line.get("article_id")
        if article_id is not None and article_id not in article_ids_in_script:
            article_ids_in_script.append(article_id)

    try:
        with open(summaries_path, "r", encoding="utf-8") as f:
            summaries = json.load(f)
        titles_by_article_id = {
            summary.get("article_id"): str(summary.get("title", "")).strip()
            for summary in summaries
            if summary.get("article_id") is not None and summary.get("title")
        }
        for article_id in article_ids_in_script:
            title = titles_by_article_id.get(article_id, "")
            if title and title not in key_points:
                key_points.append(title)
                if len(key_points) >= 3:
                    break
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        pass

    if len(key_points) < 3:
        subtitle = str(script.get("subtitle", "")).strip()
        if subtitle and subtitle not in key_points:
            key_points.append(subtitle)

    return key_points[:3]

logger = logging.getLogger(__name__)

DEFAULT_EPISODES_DIR = os.environ.get("EPISODES_DIR", "data/episodes")

ProgressCallback = Optional[Callable[[str, str], None]]


def _review_state(review_mode: str, passed: bool) -> str:
    """最終チェック結果とepisodeに固定されたreview_modeから次状態を返す。"""
    if review_mode == "always":
        return "awaiting_review"
    if passed:
        return "synthesizing"
    return "failed" if review_mode == "auto" else "awaiting_review"


class PipelineResult(Enum):
    """パイプラインの完了結果（通常の成功 metadata 以外）。"""

    NO_CONTENT = "no_content"
    REVIEW_REQUIRED = "review_required"


def _resolve_max_articles(max_articles: int | None, settings_params: dict[str, Any]) -> int:
    """明示指定を優先し、未指定時だけ保存済み尺の件数を使う。"""
    return settings_params["max_articles"] if max_articles is None else max_articles


def _determine_tts_config(tts_engine: str | None = None) -> dict[str, Any]:
    """接続先とエンジン別の保存済み話者値（未保存時はconfig.py既定値）を返す。"""
    settings = get_settings()
    tts_engines = {"voicevox", "aivispeech", "fishs2pro"}
    engine = tts_engine if tts_engine and tts_engine in tts_engines else settings.default_tts_engine
    base_url = (
        settings.fishs2pro_base_url if engine == "fishs2pro" else
        settings.aivispeech_base_url if engine == "aivispeech" else
        settings.voicevox_base_url
    )
    speaker_male, speaker_female = resolve_tts_speakers(engine)
    return {
        "tts_engine": engine,
        "base_url": base_url,
        "speaker_male": speaker_male,
        "speaker_female": speaker_female,
    }


def _resolve_fishs2pro_category_female_voice(
    categories: list[str], base_url: str, fallback_voice: str
) -> str:
    """カテゴリ割当を現在利用可能なFish S2 Proボイスへ解決する。

    ヘルスチェック失敗は生成失敗にせず、保存済み割当を採用せずに
    全体既定女性MCへフォールバックする。接続先やレスポンス内容はログへ出さない。
    """
    available_voices: set[str] = set()
    client = FishS2ProClient(base_url)
    try:
        available_voices = set(client.list_voices())
    except Exception:
        logger.warning("Fish S2 Proのボイス一覧取得に失敗したため既定女性MCを使用します")
    finally:
        client.close()
    return resolve_category_female_voice(
        categories,
        available_voices=available_voices,
        fallback_voice=fallback_voice,
    )


def run_radio_pipeline(
    episode_id: int,
    *,
    episode_date: str,
    news_source: str = "hatena_bookmark",
    program_name: str | None = None,
    seq: int = 0,
    max_articles: int | None = None,
    program_settings: ProgramSettings | None = None,
    tts_engine: str | None = None,
    tts_base_url: str | None = None,
    tts_speaker_male: int | str | None = None,
    tts_speaker_female: int | str | None = None,
    default_episodes_dir: str | None = None,
    progress_callback: ProgressCallback = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
    summarize_provider: str | None = None,
    summarize_model: str | None = None,
    content_provider: str | None = None,
    content_model: str | None = None,
    generation_job_id: int | None = None,
) -> dict[str, Any] | PipelineResult | None:
    """Run the full radio generation pipeline for an episode.

    Returns metadata dict on success, ``PipelineResult.NO_CONTENT`` when there
    are no script lines, and None on failure.
    Episode status is updated to "completed" on success or "failed" on error.
    """
    service = EpisodeService()
    episode_record = service.get_episode(episode_id) or {}
    review_mode = episode_record.get("review_mode") or "on_failure"
    profile = program_settings or get_settings_or_default()
    from app.services.llm_provider import (
        resolve_pipeline_llm_selection,
        validate_provider_model,
    )
    llm_selection = resolve_pipeline_llm_selection(
        llm_provider=llm_provider,
        llm_model=llm_model,
        summarize_provider=summarize_provider,
        summarize_model=summarize_model,
        content_provider=content_provider,
        content_model=content_model,
    )

    def _validate_phase_llm(provider: str | None, model: str | None, phase: str):
        try:
            return validate_provider_model(provider, model)
        except Exception:
            # Phase-specific configuration is intentionally isolated. A local
            # summary backend failure must not prevent the content backend from
            # being attempted, and vice versa.
            if llm_selection.legacy_common:
                raise
            logger.warning("%s用LLMを利用できないため、そのフェーズを継続可能な形で処理します", phase, exc_info=True)
            return None

    summarize_llm = _validate_phase_llm(
        llm_selection.summarize_provider, llm_selection.summarize_model, "要約"
    )
    content_llm = _validate_phase_llm(
        llm_selection.content_provider, llm_selection.content_model, "台本・レビュー"
    )
    profile_params = profile.generation_params()
    effective_max_articles = _resolve_max_articles(max_articles, profile_params)
    effective_min_score = profile_params["min_importance_score"]
    base_dir = (default_episodes_dir or DEFAULT_EPISODES_DIR)
    base_dir = os.path.join(base_dir, str(episode_id))
    effective_program_name = program_name or (
        "テックニュース" if news_source == "hatena_bookmark" else "ニュースのとなり"
    )

    Path(base_dir).mkdir(parents=True, exist_ok=True)

    def _progress(phase: str, message: str) -> None:
        if progress_callback:
            progress_callback(phase, message)
        logger.info("[%d] phase=%s %s", episode_id, phase, message)

    notification_sent = False

    def _notify_failure(phase: str, error: object) -> None:
        try:
            notify_failure(episode_id=episode_id, phase=phase, error=error)
        except Exception:
            logger.warning("[%d] Telegram failure notification could not be sent", episode_id)

    def _notify_success(title: str) -> None:
        try:
            notify_success(title=title, episode_id=episode_id, seq=seq)
        except Exception:
            logger.warning("[%d] Telegram success notification could not be sent", episode_id)

    def _fail(phase: str, error: object = "処理に失敗しました") -> None:
        """Keep the original failed state and emit at most one notification."""
        nonlocal notification_sent
        service.update_episode_status(episode_id, "failed")
        if not notification_sent:
            notification_sent = True
            _notify_failure(phase, error)

    try:
        _progress("start", "番組の生成を準備しています…")

        # -- IMPORT --
        _progress("import", "ニュース記事を取得しています…")
        try:
            ins, dup = import_articles_by_source(news_source)
            logger.info("RSS import done: inserted=%d duplicated=%d", ins, dup)
        except Exception:
            logger.exception("RSS import failed")
            _fail("import", "ニュース記事の取得に失敗しました")
            return None

        if ins == 0 and dup == 0:
            _fail("import", "処理対象の記事がありません")
            return None

        # -- SUMMARIZE --
        _progress("summarize", "記事を要約しています…")
        try:
            summaries_path = os.path.join(base_dir, "summaries.json")
            if summarize_llm is None:
                raise RuntimeError("summary LLM is unavailable")
            summarized = summarize_articles(
                summaries_path,
                llm_provider=summarize_llm.name,
                llm_model=summarize_llm.model,
            )
            logger.info("summarize done: count=%d", summarized)
            if summarized == 0:
                existing_summaries = ArticleService().fetch_summaries_for_script(
                    max_articles=effective_max_articles,
                    min_importance_score=effective_min_score,
                    source=news_source,
                    priority_themes=profile.priority_themes,
                    excluded_themes=profile.excluded_themes,
                )
                write_fallback_summaries(summaries_path, existing_summaries)
                logger.info(
                    "No new articles to summarize; wrote %d existing summaries for review evidence",
                    len(existing_summaries),
                )
        except Exception:
            logger.exception("summarize failed")
            if llm_selection.legacy_common:
                _fail("summarize", "記事の要約に失敗しました")
                return None
            # フェーズ別設定では、要約が落ちてもDBに残る既存要約を根拠に
            # contentフェーズを続行する。完全に新規記事が無い場合は、
            # generate_script側が0件として安全に終了する。
            try:
                summaries_path = os.path.join(base_dir, "summaries.json")
                existing_summaries = ArticleService().fetch_summaries_for_script(
                    max_articles=effective_max_articles,
                    min_importance_score=effective_min_score,
                    source=news_source,
                    priority_themes=profile.priority_themes,
                    excluded_themes=profile.excluded_themes,
                )
                write_fallback_summaries(summaries_path, existing_summaries)
                logger.warning("要約LLM障害後、既存要約%d件でcontentフェーズを継続します", len(existing_summaries))
            except Exception:
                logger.exception("fallback summaries failed")

        # -- GENERATE SCRIPT --
        old_max = os.environ.get("MAX_SCRIPT_ARTICLES")
        os.environ["MAX_SCRIPT_ARTICLES"] = str(effective_max_articles)
        try:
            _progress("generate_script", "台本を生成しています…")
            if content_llm is None:
                _fail("generate_script", "台本生成用LLMを利用できません")
                return None
            script_path = os.path.join(base_dir, "script.json")
            script_kwargs = dict(
                program_name=effective_program_name,
                news_source=news_source,
                program_settings=profile,
                max_articles=effective_max_articles,
                min_importance_score=effective_min_score,
            )
            script_kwargs.update(llm_provider=content_llm.name, llm_model=content_llm.model)
            line_count = generate_script(script_path, **script_kwargs)
        finally:
            if old_max is None:
                os.environ.pop("MAX_SCRIPT_ARTICLES", None)
            else:
                os.environ["MAX_SCRIPT_ARTICLES"] = old_max

        if line_count <= 0:
            service.delete_episode(episode_id)
            return PipelineResult.NO_CONTENT

        override_script_title(script_path, effective_program_name, episode_date, seq)
        logger.info("Title overridden: %s", build_radio_title(effective_program_name, episode_date, seq))

        # -- KEY POINTS --
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                generated_script = json.load(f)
            summaries_path = os.path.join(base_dir, "summaries.json")
            key_points = _extract_key_points(generated_script, summaries_path)
            if key_points:
                service.update_episode_key_points(episode_id, key_points)
                logger.info("key_points saved: %s", key_points)
        except Exception:
            logger.warning("key_points extraction failed (non-fatal)", exc_info=True)

        # -- TTS SETUP --
        tts_config = _determine_tts_config(tts_engine)
        explicit_tts_speakers = (
            tts_base_url is not None
            and tts_speaker_male is not None
            and tts_speaker_female is not None
        )
        if explicit_tts_speakers:
            effective_tts_base_url = tts_base_url
            effective_tts_male = tts_speaker_male
            effective_tts_female = tts_speaker_female
        else:
            tts_config = _determine_tts_config(tts_engine)
            effective_tts_base_url = tts_config["base_url"]
            effective_tts_male = tts_config["speaker_male"]
            effective_tts_female = tts_config["speaker_female"]

        review_result: dict[str, Any] = {"revised": False, "review_count": 0}

        # -- REVIEW (quality gate) --
        _progress("review", "台本をレビューしています…")
        try:
            reviewed_episode_dir = os.path.join(base_dir, "review")
            Path(reviewed_episode_dir).mkdir(parents=True, exist_ok=True)
            Path(os.path.join(reviewed_episode_dir, "lines")).mkdir(exist_ok=True)
            if content_llm is not None:
                review_result = review_script(
                    script_path, reviewed_episode_dir,
                    program_name=effective_program_name,
                    commentary=False,
                    llm_provider=content_llm.name, llm_model=content_llm.model,
                    summaries_path=summaries_path,
                )
            else:
                logger.warning("review skipped because content LLM is unavailable")
            logger.info(
                "review_script: revised=%s review_count=%d",
                review_result["revised"],
                review_result["review_count"],
            )
            _progress("review_done", "レビューが完了しました…")
        except Exception as exc:
            logger.warning("review_script failed (non-fatal): %s", exc)

        # -- BRANCH based on revised flag --
        if review_result.get("revised"):
            shutil.copy(os.path.join(reviewed_episode_dir, "script.json"), script_path)
            override_script_title(script_path, effective_program_name, episode_date, seq)

        # -- FINAL VALIDATION (after review, before TTS) --
        final_validation = None
        if review_mode == "always" or should_run_final_validation(script_path, review_result):
            _progress(FINAL_VALIDATION_PHASE, "レビュー後の台本を最終確認しています…")
            final_validation = validate_final_script_file(
                script_path,
                summaries_path=summaries_path,
                output_dir=base_dir,
                program_name=effective_program_name,
                prior_review_result=review_result,
            )
        # 最終台本をrevisionとして保持する。revision番号はepisode単位で単調増加。
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_revision = json.load(f)
            with get_db_connection() as conn:
                current = conn.execute("SELECT COALESCE(MAX(revision), 0) AS revision FROM script_revisions WHERE episode_id=?", (episode_id,)).fetchone()["revision"]
                conn.execute(
                    "INSERT INTO script_revisions(episode_id, revision, script_json, source) VALUES (?, ?, ?, ?)",
                    (episode_id, current + 1, json.dumps(script_revision, ensure_ascii=False), "reviewed" if review_result.get("revised") else "generated"),
                )
        except Exception:
            logger.exception("[%d] failed to persist generated script revision", episode_id)
            service.update_episode_status(episode_id, "failed")
            service.update_episode_phase(episode_id, "failed", "生成台本の保存に失敗しました")
            _notify_failure("script_revision", "生成台本の保存に失敗しました")
            return None

        has_validation_errors = bool(final_validation and not final_validation["can_synthesize"])
        next_review_state = _review_state(review_mode, not has_validation_errors)
        if next_review_state == "awaiting_review":
            reason = human_review_message(final_validation) if has_validation_errors else "管理者による台本確認が必要です"
            transitioned = move_episode_to_awaiting_review(episode_id, reason)
            if transitioned:
                try:
                    notify_review_needed(episode_id=episode_id)
                except Exception:
                    logger.warning("[%d] Telegram review notification could not be sent", episode_id)
            logger.info("[%d] awaiting administrator script review", episode_id)
            return PipelineResult.REVIEW_REQUIRED
        if next_review_state == "failed":
            reason = human_review_message(final_validation)
            service.update_episode_status(episode_id, "failed")
            _notify_failure("final_validation", reason)
            return None

        if final_validation:
            if final_validation["warnings"]:
                logger.warning(
                    "[%d] final validation passed with %d warning(s)",
                    episode_id,
                    len(final_validation["warnings"]),
                )
            else:
                logger.info("[%d] final validation passed", episode_id)

        # 台本（レビュー後の最終版）を優先し、失敗しても生成本体は継続する。
        categories: list[str] = []
        try:
            categories = select_episode_categories(script_path, summaries_path)
            service.update_episode_categories(episode_id, categories)
        except Exception:
            logger.warning("episode category persistence failed (non-fatal)", exc_info=True)

        # カテゴリ別女性MCはFish S2 Proの新規生成だけに適用する。
        # 他エンジンは従来どおり、また男性MCの設定は変更しない。
        if tts_config["tts_engine"] == "fishs2pro" and not explicit_tts_speakers:
            effective_tts_female = _resolve_fishs2pro_category_female_voice(
                categories,
                effective_tts_base_url,
                str(effective_tts_female),
            )

        # -- SYNTHESIZE TTS --
        _progress("synthesize", "音声を合成しています…")
        try:
            success_count = synthesize_episode(
                base_dir,
                base_url=effective_tts_base_url,
                speaker_male=effective_tts_male,
                speaker_female=effective_tts_female,
                tts_engine=tts_config["tts_engine"],
                episode_id=episode_id,
                generation_job_id=generation_job_id,
            )
        except Exception:
            logger.exception("tts synthesis failed")
            _fail("synthesize", "音声合成に失敗しました")
            return None

        if success_count <= 0:
            _fail("synthesize", "音声ファイルが生成されませんでした")
            return None

        # 実際の合成に使った女性MCを保存する。Fish S2 Pro以外では
        # female_mc_candidates のMCを使っていないため、表示対象をクリアする。
        service.update_episode_mc_voice_name(
            episode_id,
            effective_tts_female.strip()
            if tts_config["tts_engine"] == "fishs2pro"
            and isinstance(effective_tts_female, str)
            and effective_tts_female.strip()
            else None,
        )

        # -- BUILD MP3 --
        _progress("build", "音声をまとめています…")
        ep_metadata = build_episode(base_dir, episode_id=episode_id, generation_job_id=generation_job_id)
        if not ep_metadata:
            _fail("build", "音声ファイルの統合に失敗しました")
            return None

        # Keep the exact profile used for this episode available to the result
        # display.  Do not expose the SQLite representation to consumers.
        ep_metadata["applied_settings"] = profile.to_dict()
        # 既存のメタデータ項目はcontentフェーズを代表値として維持し、
        # フェーズ別の実設定も追加する。
        ep_metadata["llm_provider"] = content_llm.name if content_llm else None
        ep_metadata["llm_model"] = content_llm.model if content_llm else None
        ep_metadata["summarize_llm_provider"] = summarize_llm.name if summarize_llm else None
        ep_metadata["summarize_llm_model"] = summarize_llm.model if summarize_llm else None
        ep_metadata["content_llm_provider"] = content_llm.name if content_llm else None
        ep_metadata["content_llm_model"] = content_llm.model if content_llm else None
        with open(os.path.join(base_dir, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(ep_metadata, f, ensure_ascii=False, indent=2)

        service.update_episode_audio_path(
            episode_id, ep_metadata.get("audio_path") or ""
        )

        # -- PERSIST ITEMS --
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            for idx, line in enumerate(script.get("lines", []), start=1):
                aid = line.get("article_id")
                audio_generation_id = f"ep{episode_id}-seg{idx}"
                service.add_episode_item(
                    episode_id=episode_id,
                    article_id=int(aid) if aid is not None else None,
                    item_order=idx,
                    segment_text=line.get("text", ""),
                    audio_generation_id=audio_generation_id,
                )
        except Exception:
            logger.exception("failed to persist episode_items")
            _fail("persist", "番組データの保存に失敗しました")
            return None

        service.complete_radio_episode_with_notification(episode_id)
        if not notification_sent:
            notification_sent = True
            _notify_success(str(ep_metadata.get("title") or effective_program_name))
        _progress("complete", "生成が完了しました")
        logger.info("[%d] completed successfully", episode_id)

        return ep_metadata

    except Exception:
        if service is not None:
            current = service.get_episode(episode_id)
            current_status = current["status"] if current else None
            if current_status not in {"completed", "failed"}:
                logger.exception("[%d] generation failed unexpectedly", episode_id)
                _fail("unknown", "予期しないエラーが発生しました")
        else:
            logger.exception("[%d] generation failed before service init", episode_id)
        return None
