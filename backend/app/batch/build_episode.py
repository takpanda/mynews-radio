import json
import os
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.services.ffmpeg_service import combine_wav_files, wav_to_mp3, add_jingles_and_encode
from app.config import get_settings

logger = logging.getLogger(__name__)


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

    # Step 1: Combine all WAVs into one
    combined_wav = os.path.join(directory, "episode_combined.wav")
    try:
        combine_wav_files(wav_files, combined_wav)
    except Exception as exc:
        logger.error("WAV combine failed: %s", exc)
        return {}

    # Step 2: MP3 encode（ジングルがあれば前後に追加）
    mp3_path = os.path.join(directory, "episode.mp3")
    settings = get_settings()
    result = add_jingles_and_encode(
        main_wav_path=combined_wav,
        output_mp3_path=mp3_path,
        opening_path=settings.jingle_opening_path,
        ending_path=settings.jingle_ending_path,
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
