import json
import os
import subprocess
import sys
import logging
import wave
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.ffmpeg_service import combine_wav_files, wav_to_mp3, add_jingles_and_encode
from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_audio_duration(path: str) -> float:
    """ffprobe でオーディオファイルの実際の長さ（秒）を返す。取得失敗時は 0.0。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return 0.0
        data = json.loads(result.stdout)
        return float(data["streams"][0].get("duration", 0))
    except Exception:
        return 0.0


def jingle_paths_for_title(script: dict, settings) -> tuple[str, str]:
    """script title に応じた (opening_path, ending_path) を返す。"""
    program_title = script.get("title", "")
    if program_title.startswith("ニュースのとなり"):
        return settings.jingle_news_no_tonari_opening_path, settings.jingle_news_no_tonari_ending_path
    return settings.jingle_opening_path, settings.jingle_ending_path


def _get_opening_path(script: dict, settings) -> str:
    """script title に応じた開口ジングルパスを返す。"""
    opening_path, _ = jingle_paths_for_title(script, settings)
    return opening_path


def _annotate_start_times(script: dict, wav_dir: str, wav_files_sorted: list, settings) -> tuple[float, str]:
    """各 script line に start_time (秒) を付与する。

    Returns (opening_offset, opening_path_used).
    """
    # script title に応じたジングルパスを取得
    opening_path = _get_opening_path(script, settings)

    # 開口ジングルが存在する場合、その実際の長さをオフセットとする
    opening_offset = 0.0
    if opening_path and os.path.isfile(opening_path):
        actual_dur = _get_audio_duration(opening_path)
        opening_offset = actual_dur if actual_dur > 0 else float(settings.jingle_duration)

    # wav_file が未設定の行がある場合、file_counter ロジックを再現して推定する
    lines = script.get("lines", [])
    if any("wav_file" not in line for line in lines):
        file_counter = 1
        for line in lines:
            if line.get("section") == "transition":
                file_counter += 1  # jingle WAV が先に挿入される
            line.setdefault("wav_file", f"{file_counter:03d}.wav")
            file_counter += 1

    # WAV ファイル名 → 累積開始時刻マップを構築
    cumulative = opening_offset
    wav_start: dict[str, float] = {}
    for wav_path in wav_files_sorted:
        basename = os.path.basename(wav_path)
        wav_start[basename] = cumulative
        with wave.open(wav_path, "rb") as wf:
            duration = wf.getnframes() / float(wf.getframerate())
        cumulative += duration

    # 各 line に start_time を付与
    for line in lines:
        wav_file = line.get("wav_file")
        if wav_file and wav_file in wav_start:
            line["start_time"] = round(wav_start[wav_file], 3)

    logger.info(
        "start_time を %d 行に付与しました (opening_offset=%.1fs, jingle=%s)",
        sum(1 for line in lines if "start_time" in line),
        opening_offset,
        opening_path or "none",
    )
    return opening_offset, opening_path


def build_episode(directory: str) -> dict:
    """
    Combine all WAV lines into episode.mp3 and write metadata.json.

    Returns a dict with metadata (id, title, date, duration_seconds, audio_path, created_at).
    """
    script_path = os.path.join(directory, "script.json")

    if not os.path.isfile(script_path):
        logger.error("script.json not found in %s", directory)
        return {}

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    wav_dir = os.path.join(directory, "lines")
    wav_files = sorted(
        [os.path.join(wav_dir, p) for p in os.listdir(wav_dir) if p.endswith(".wav")]
    )

    if not wav_files:
        logger.error("No WAV files found in %s", wav_dir)
        return {}

    settings = get_settings()

    # Step 1: Combine all WAVs into one
    combined_wav = os.path.join(directory, "episode_combined.wav")
    try:
        combine_wav_files(wav_files, combined_wav)
    except Exception as exc:
        logger.error("WAV combine failed: %s", exc)
        return {}

    # Step 1.5: Calculate per-line start_time and write back to script.json
    try:
        _annotate_start_times(script, wav_dir, wav_files, settings)
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("start_time の計算に失敗しました（スキップ）: %s", exc)

    # Step 2: MP3 encode（ジングルがあれば前後に追加）
    opening_jingle, ending_jingle = jingle_paths_for_title(script, settings)

    mp3_path = os.path.join(directory, "episode.mp3")
    result = add_jingles_and_encode(
        main_wav_path=combined_wav,
        output_mp3_path=mp3_path,
        opening_path=opening_jingle,
        ending_path=ending_jingle,
        jingle_duration=settings.jingle_duration,
        fade_duration=settings.jingle_fade_duration,
        bitrate="128k",
    )
    if result is None:
        logger.error("wav_to_mp3 returned None for %s", combined_wav)
        return {}

    duration, _ = result

    # Step 3: Write metadata.json
    episode_date = script.get("date", "unknown").replace("/", "-")
    metadata = {
        "id": episode_date,
        "title": script.get("title", ""),
        "date": episode_date,
        "duration_seconds": round(duration, 2),
        "audio_path": "episode.mp3",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    metadata_path = os.path.join(directory, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    logger.info(
        "Episode built: %s (duration=%.1fs, lines=%d)",
        mp3_path, duration, len(wav_files),
    )

    return metadata


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    episode_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("data", "episodes")
    metadata = build_episode(episode_dir)

    if metadata:
        print("Episode metadata:")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
