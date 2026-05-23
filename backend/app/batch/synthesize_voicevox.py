import json
import os
import sys
import logging
from pathlib import Path

# Ensure the backend root is on sys.path so `app.config` resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.config import get_settings
from app.services.voicevox_client import VoicevoxClient
from app.services.replacement_table import apply_replacements

logger = logging.getLogger(__name__)


def synthesize_episode(directory: str) -> int:
    """
    Read script.json from *directory*, generate a WAV for each line,
    and write both display_text and spoken_text back into the lines.

    Returns total number of lines successfully synthesized.
    """
    settings = get_settings()
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
        settings.voicevox_base_url,
        speaker_male=settings.voicevox_speaker_male,
        speaker_female=settings.voicevox_speaker_female,
    )
    success_count = 0

    for idx, line in enumerate(lines, start=1):
        filename = f"{idx:03d}.wav"
        filepath = os.path.join(wav_dir, filename)

        original_text = line.get("text", "")
        spoken_text = apply_replacements(original_text)
        speaker = line.get("speaker", "male")

        logger.info(
            "Line %s (speaker=%s): '%s' -> WAV: %s",
            idx, speaker, original_text[:50], filepath,
        )

        ok = client.synthesize_line(spoken_text, speaker, filepath)
        if ok and os.path.isfile(filepath):
            success_count += 1
            # Store both display and spoken text back into line object
            line["display_text"] = original_text
            line["spoken_text"] = spoken_text
        else:
            logger.error("Failed to synthesize line %d", idx)

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
