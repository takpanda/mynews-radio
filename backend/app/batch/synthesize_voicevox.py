import json
import os
import struct
import sys
import wave
import logging
from pathlib import Path

# Ensure the backend root is on sys.path so `app.config` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.ffmpeg_service import convert_to_wav
from app.services.voicevox_client import VoicevoxClient
from app.services.replacement_table import apply_replacements

logger = logging.getLogger(__name__)

# VOICEVOX が出力する WAV の標準パラメータ（無音挿入時に使用）
_SILENCE_SAMPLE_RATE = 24000
_SILENCE_CHANNELS = 1
_SILENCE_SAMPLE_WIDTH = 2  # 16-bit


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


def _normalize_wavs_to_speech_rate(wav_dir: str) -> None:
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

    # 最多数のレートをターゲットとする
    target_rate: int = collections.Counter(rates.values()).most_common(1)[0][0]

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
    speaker_male: int | None = None,
    speaker_female: int | None = None,
) -> int:
    """
    Read script.json from *directory*, generate a WAV for each line,
    and write both display_text and spoken_text back into the lines.

    base_url / speaker_male / speaker_female override the settings values
    (useful for switching between VOICEVOX and AivisSpeech at runtime).

    Returns total number of lines successfully synthesized.
    """
    settings = get_settings()
    default_engine_is_aivispeech = settings.default_tts_engine == "aivispeech"
    effective_base_url = base_url if base_url is not None else (
        settings.aivispeech_base_url if default_engine_is_aivispeech else settings.voicevox_base_url
    )
    effective_speaker_male = speaker_male if speaker_male is not None else (
        settings.aivispeech_speaker_male if default_engine_is_aivispeech else settings.voicevox_speaker_male
    )
    effective_speaker_female = speaker_female if speaker_female is not None else (
        settings.aivispeech_speaker_female if default_engine_is_aivispeech else settings.voicevox_speaker_female
    )

    script_path = os.path.join(directory, "script.json")

    if not os.path.isfile(script_path):
        logger.error("script.json not found at %s", directory)
        return 0

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    lines = script.get("lines", [])
    if not lines:
        logger.warning("No lines in script.json")
        return 0

    wav_dir = os.path.join(directory, "lines")
    os.makedirs(wav_dir, exist_ok=True)

    client = VoicevoxClient(
        effective_base_url,
        speaker_male=effective_speaker_male,
        speaker_female=effective_speaker_female,
    )
    success_count = 0
    file_counter = 1  # WAV ファイルの通し番号（無音挿入分も含む）

    for idx, line in enumerate(lines, start=1):
        section = line.get("section", "news")

        # transition 行の前にケルト風ジングル（なければ無音）を挿入する
        if section == "transition":
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

        original_text = line.get("text", "")
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

        ok = client.synthesize_line(spoken_text, speaker, filepath, delivery=delivery)
        if ok and os.path.isfile(filepath):
            success_count += 1
            # Store both display and spoken text back into line object
            line["display_text"] = original_text
            line["spoken_text"] = spoken_text
            line["wav_file"] = filename
        else:
            logger.error("Failed to synthesize line %d", idx)

        file_counter += 1

    # すべての WAV を同一サンプリングレートに正規化（TTS エンジン切替時のレート不一致を解消）
    _normalize_wavs_to_speech_rate(wav_dir)

    # Write updated script.json with display/spoken separation
    script["lines"] = lines
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    client.close()
    logger.info("Synthesized %d/%d lines -> %s/lines/", success_count, len(lines), directory)
    return success_count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    episode_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes")
    result = synthesize_episode(episode_dir)
    print(f"Synthesized {result} lines")
    sys.exit(0 if result > 0 else 1)
