"""
既存エピソードの script.json に start_time を追加する移行スクリプト。
MP3 の再エンコードは行わない。

使い方:
  python3 add_timing.py                          # data/episodes/ 以下を全処理
  python3 add_timing.py /app/data/episodes/1     # 特定エピソードのみ
"""
import json
import logging
import os
import sys
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.batch.build_episode import _annotate_start_times
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def annotate_episode(directory: str, settings) -> bool:
    """1エピソードの script.json に start_time を付与して上書き保存する。"""
    script_path = os.path.join(directory, "script.json")
    wav_dir = os.path.join(directory, "lines")

    if not os.path.isfile(script_path):
        logger.warning("script.json が見つかりません: %s", directory)
        return False

    if not os.path.isdir(wav_dir):
        logger.warning("lines/ ディレクトリが見つかりません: %s", directory)
        return False

    wav_files = sorted(
        [os.path.join(wav_dir, f) for f in os.listdir(wav_dir) if f.endswith(".wav")]
    )
    if not wav_files:
        logger.warning("WAV ファイルが見つかりません: %s", wav_dir)
        return False

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    try:
        _annotate_start_times(script, wav_dir, wav_files, settings)
    except Exception as exc:
        logger.error("start_time 計算エラー (%s): %s", directory, exc)
        return False

    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    annotated = sum(1 for line in script.get("lines", []) if "start_time" in line)
    logger.info("完了: %s (%d 行に start_time を付与)", directory, annotated)
    return True


def main() -> None:
    settings = get_settings()

    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        base = os.path.join(os.path.dirname(__file__), "..", "..", "data", "episodes")
        base = os.path.abspath(base)
        targets = [
            os.path.join(base, d)
            for d in sorted(os.listdir(base))
            if os.path.isdir(os.path.join(base, d))
        ]

    ok = 0
    for target in targets:
        if annotate_episode(target, settings):
            ok += 1

    logger.info("処理完了: %d / %d エピソード", ok, len(targets))


if __name__ == "__main__":
    main()
