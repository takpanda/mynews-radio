import json
import os
import struct
import sys
import time
import wave
import logging
from pathlib import Path

# Ensure the backend root is on sys.path so `app.config` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services import generation_log_service as log_service
from app.services.ffmpeg_service import convert_to_wav
from app.services.fishs2pro_client import FishS2ProClient
from app.services.voicevox_client import DELIVERY_PARAMS, VoicevoxClient
from app.services.replacement_table import apply_replacements

logger = logging.getLogger(__name__)

# VOICEVOX が出力する WAV の標準パラメータ（無音挿入時に使用）
_SILENCE_SAMPLE_RATE = 24000
_SILENCE_CHANNELS = 1
_SILENCE_SAMPLE_WIDTH = 2  # 16-bit

# Fish S2 Pro はシングルプロセス・同期処理のため、他クライアントとの順番待ちで
# 一時的に応答が遅れてタイムアウトすることがある（BEE-707）。タイムアウト値
# （60秒固定・設定化は対象外）を延ばす代わりに、同じ行だけを有限回再試行する。
# 上限は「初回 + 再試行2回 = 最大3回」とし、既存の60秒タイムアウトと合わせて
# BEE-707 で検討されたタイムアウト延長案（180秒程度）と同程度の総待ち時間に
# 収まるようにした。待機はサーバーが混雑を解消するまでの猶予として、指数
# バックオフではなく固定5秒（既存の `retry_on_busy` の指数バックオフはDBロック
# 用途向けで今回の一時的な混雑には不要と判断）を採用する。
_FISHS2PRO_MAX_RETRIES = 2
_FISHS2PRO_RETRY_WAIT_SECONDS = 5.0


def _synthesize_line_with_retry(
    client: FishS2ProClient,
    text: str,
    speaker: str,
    filepath: str,
    delivery: str,
    idx: int,
    max_retries: int = _FISHS2PRO_MAX_RETRIES,
    wait_seconds: float = _FISHS2PRO_RETRY_WAIT_SECONDS,
) -> tuple[bool, int]:
    """Fish S2 Pro で1行を合成する。失敗時は同じ行だけを最大 max_retries 回再試行する。

    Returns (成否, 実際に行った再試行回数)。
    """
    total_attempts = max_retries + 1
    attempt = 1
    while True:
        ok = client.synthesize_line(text, speaker, filepath, delivery=delivery)
        if ok and os.path.isfile(filepath):
            if attempt > 1:
                logger.info(
                    "Line %d synthesis succeeded on retry (attempt=%d/%d)",
                    idx, attempt, total_attempts,
                )
            return True, attempt - 1
        if attempt >= total_attempts:
            logger.error(
                "Line %d synthesis failed after %d attempt(s), giving up",
                idx, attempt,
            )
            return False, attempt - 1
        logger.warning(
            "Line %d synthesis failed (attempt=%d/%d), retrying in %.1fs",
            idx, attempt, total_attempts, wait_seconds,
        )
        time.sleep(wait_seconds)
        attempt += 1


def _create_silence_wav(
    path: str,
    duration_seconds: float = 1.0,
    sample_rate: int = _SILENCE_SAMPLE_RATE,
) -> bool:
    """指定した長さの無音 WAV ファイルを生成する。"""
    try:
        n_frames = int(sample_rate * duration_seconds)
        with wave.open(path, "w") as wf:
            wf.setnchannels(_SILENCE_CHANNELS)
            wf.setsampwidth(_SILENCE_SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))
        return True
    except Exception as exc:
        logger.error("無音 WAV の生成に失敗しました: %s", exc)
        return False


def _normalize_wavs_to_speech_rate(wav_dir: str, target_rate: int | None = None) -> None:
    """lines/ 以下の全 WAV を TTS 出力のサンプリングレートに統一する。

    TTS エンジン（VOICEVOX: 24000Hz / AivisSpeech: 44100Hz 等）によって
    出力レートが異なり、手動生成した silence/jingle と不一致になる場合がある。
    最多数のレートを「正解」とし、異なるファイルを ffmpeg でリサンプルする。
    """
    import collections
    wav_files = sorted(
        [os.path.join(wav_dir, f) for f in os.listdir(wav_dir) if f.endswith(".wav")]
    )
    if len(wav_files) < 2:
        return

    rates: dict[str, int] = {}
    for p in wav_files:
        try:
            with wave.open(p, "rb") as wf:
                rates[p] = wf.getframerate()
        except Exception:
            pass

    if not rates:
        return

    # エンジン固有のレートが指定されていない場合は最多数のレートを使う。
    target_rate = target_rate or collections.Counter(rates.values()).most_common(1)[0][0]

    for path, rate in rates.items():
        if rate == target_rate:
            continue
        tmp = path + "._norm.wav"
        if convert_to_wav(path, tmp, sample_rate=target_rate):
            os.replace(tmp, path)
            logger.info(
                "WAV リサンプル: %s (%dHz -> %dHz)",
                os.path.basename(path), rate, target_rate,
            )
        else:
            logger.warning("WAV リサンプル失敗: %s", os.path.basename(path))
            if os.path.isfile(tmp):
                os.remove(tmp)


def synthesize_episode(
    directory: str,
    base_url: str | None = None,
    speaker_male: int | str | None = None,
    speaker_female: int | str | None = None,
    tts_engine: str | None = None,
    episode_id: int | None = None,
    generation_job_id: int | None = None,
) -> int:
    """
    Read script.json from *directory*, generate a WAV for each line,
    and write both display_text and spoken_text back into the lines.

    base_url / speaker_male / speaker_female override the settings values
    (useful for switching between VOICEVOX and AivisSpeech at runtime).
    Fish S2 Pro の場合、speaker_male / speaker_female はボイス名（例: morigawa）。

    episode_id が指定された場合、行単位・工程単位の詳細ログ（BEE-718）を永続化する。
    episode_id が None の場合はログ記録をスキップし、従来どおりの動作のみ行う
    （日次自動生成のように generation_job_id を持たない経路にも対応するため
    episode_id は任意、generation_job_id はさらに任意）。

    Returns total number of lines successfully synthesized.
    """
    settings = get_settings()
    engine = tts_engine or settings.default_tts_engine
    default_engine_is_aivispeech = engine == "aivispeech"
    is_fishs2pro = engine == "fishs2pro"
    effective_base_url = base_url if base_url is not None else (
        settings.fishs2pro_base_url if is_fishs2pro else
        settings.aivispeech_base_url if default_engine_is_aivispeech else settings.voicevox_base_url
    )
    effective_speaker_male = speaker_male if speaker_male is not None else (
        settings.fishs2pro_voice_male if is_fishs2pro else
        settings.aivispeech_speaker_male if default_engine_is_aivispeech else settings.voicevox_speaker_male
    )
    effective_speaker_female = speaker_female if speaker_female is not None else (
        settings.fishs2pro_voice_female if is_fishs2pro else
        settings.aivispeech_speaker_female if default_engine_is_aivispeech else settings.voicevox_speaker_female
    )

    phase_log_id = log_service.start_phase_log(
        episode_id, "synthesize", generation_job_id=generation_job_id, tts_engine=engine,
    ) if episode_id is not None else None

    script_path = os.path.join(directory, "script.json")

    if not os.path.isfile(script_path):
        logger.error("script.json not found at %s", directory)
        log_service.finalize_phase_log(
            phase_log_id, result="failure", line_success_count=0, line_total_count=0,
            failure_reason="script_missing",
        )
        return 0

    # script.json の読み込み、TTSクライアント初期化を含め、phase log 確定前に
    # 例外が呼び出し元へ伝播しないよう try/except/finally でまとめて扱う
    # （壊れたJSON・権限エラー・クライアント初期化失敗も対象）。
    client = None
    success_count = 0
    lines: list = []
    try:
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        lines = script.get("lines", [])
        if not lines:
            logger.warning("No lines in script.json")
            log_service.finalize_phase_log(
                phase_log_id, result="failure", line_success_count=0, line_total_count=0,
                failure_reason="tts_no_lines_succeeded",
            )
            return 0

        wav_dir = os.path.join(directory, "lines")
        os.makedirs(wav_dir, exist_ok=True)

        client = FishS2ProClient(
            effective_base_url,
            voice_male=effective_speaker_male,
            voice_female=effective_speaker_female,
        ) if is_fishs2pro else VoicevoxClient(
            effective_base_url,
            speaker_male=effective_speaker_male,
            speaker_female=effective_speaker_female,
        )
        file_counter = 1  # WAV ファイルの通し番号（無音挿入分も含む）
        prev_section: str | None = None

        for idx, line in enumerate(lines, start=1):
            section = line.get("section", "news")

            # transition ブロックの先頭でのみケルト風ジングル（なければ無音）を挿入する。
            # 記事境界のtransitionは両MCの短い掛け合い（複数行）になりうるため、
            # ブロック内の2行目以降には挿入せず、境界につき1回に保つ。
            if section == "transition" and prev_section != "transition":
                insert_path = os.path.join(wav_dir, f"{file_counter:03d}.wav")
                transition_wav = settings.jingle_transition_path
                if transition_wav and os.path.isfile(transition_wav):
                    # 拡張子に関わらず ffmpeg で 24000Hz/mono/s16 に正規化してからコピーする
                    # （shutil.copy2 では元ファイルのサンプリングレートがそのまま使われ、
                    #   VOICEVOX 出力の 24000Hz と不一致になる場合がある）
                    if convert_to_wav(transition_wav, insert_path):
                        logger.info("ケルトジングルを WAV に変換して挿入: %s", insert_path)
                        file_counter += 1
                    elif _create_silence_wav(insert_path, duration_seconds=1.0):
                        logger.info("1秒の無音を挿入（ジングル変換失敗）: %s", insert_path)
                        file_counter += 1
                    else:
                        logger.warning("無音挿入スキップ (line %d)", idx)
                elif _create_silence_wav(insert_path, duration_seconds=1.0):
                    logger.info("1秒の無音を挿入（ジングル未生成）: %s", insert_path)
                    file_counter += 1
                else:
                    logger.warning("無音挿入スキップ (line %d)", idx)

            filename = f"{file_counter:03d}.wav"
            filepath = os.path.join(wav_dir, filename)

            original_text = line.get("text", "") or ""
            spoken_text = apply_replacements(original_text)
            speaker = line.get("speaker", "male")
            delivery = line.get("delivery", "neutral")
            # VOICEVOX Engine 使用時は delivery を neutral 固定（安全のため）
            if not default_engine_is_aivispeech:
                delivery = "neutral"

            logger.info(
                "Line %s (speaker=%s, section=%s, delivery=%s): '%s' -> WAV: %s",
                idx, speaker, section, delivery, original_text[:50], filepath,
            )

            line_started = time.perf_counter()
            if is_fishs2pro:
                ok, retry_count = _synthesize_line_with_retry(client, spoken_text, speaker, filepath, delivery, idx)
            else:
                ok = client.synthesize_line(
                    spoken_text, speaker, filepath, delivery=delivery,
                    kana_text=spoken_text if spoken_text != original_text else None,
                )
                retry_count = 0
            processing_duration_ms = int((time.perf_counter() - line_started) * 1000)

            line_succeeded = ok and os.path.isfile(filepath)
            if line_succeeded:
                success_count += 1
                # Store both display and spoken text back into line object
                line["display_text"] = original_text
                line["spoken_text"] = spoken_text
                line["wav_file"] = filename
                line_failure_reason = None
            else:
                logger.error("Failed to synthesize line %d", idx)
                line_failure_reason = "tts_request_failed" if not ok else "tts_output_missing"

            speaking_rate = None if is_fishs2pro else (
                DELIVERY_PARAMS.get(delivery, DELIVERY_PARAMS["neutral"])["speedScale"]
            )
            log_service.record_line_log(
                phase_log_id, episode_id, idx,
                generation_job_id=generation_job_id,
                speaker=speaker, section=section, delivery=delivery, tts_engine=engine,
                synth_result="success" if line_succeeded else "failure",
                retry_count=retry_count,
                wav_file=filename if line_succeeded else None,
                speaking_rate=speaking_rate,
                processing_duration_ms=processing_duration_ms,
                failure_reason=line_failure_reason,
            )

            file_counter += 1
            prev_section = section

        # すべての WAV を同一サンプリングレートに正規化（TTS エンジン切替時のレート不一致を解消）
        _normalize_wavs_to_speech_rate(wav_dir, target_rate=44100 if is_fishs2pro else None)

        # Write updated script.json with display/spoken separation
        script["lines"] = lines
        # build_episode 側で Fish S2 Pro 限定の無音付与を判定するために使用エンジンを記録する。
        script["tts_engine"] = engine
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
    except Exception:
        log_service.finalize_phase_log(
            phase_log_id, result="failure",
            line_success_count=success_count, line_total_count=len(lines),
            failure_reason="tts_synthesis_exception",
        )
        raise
    finally:
        # close()自体の例外で、直前のexcept節によるphase log確定（または成功時の
        # 確定処理）が妨げられないよう、close失敗はここで抑止しログのみ残す。
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.exception("TTSクライアントのcloseに失敗しました")

    logger.info("Synthesized %d/%d lines -> %s/lines/", success_count, len(lines), directory)
    log_service.finalize_phase_log(
        phase_log_id,
        result="success" if success_count > 0 else "failure",
        line_success_count=success_count, line_total_count=len(lines),
        failure_reason=None if success_count > 0 else "tts_no_lines_succeeded",
    )
    return success_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    episode_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes")
    result = synthesize_episode(episode_dir)
    print(f"Synthesized {result} lines")
    sys.exit(0 if result > 0 else 1)
