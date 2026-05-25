import os
from pathlib import Path
from typing import Optional, Dict, List, Any

import wave
import subprocess
import logging

logger = logging.getLogger(__name__)


def find_ffmpeg() -> str:
    """検索ffmpeg binary path"""
    candidates = [
        "ffmpeg",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    ffmpeg_path = subprocess.run(
        ["which", "ffmpeg"], capture_output=True, text=True
    ).stdout.strip()
    if ffmpeg_path:
        return ffmpeg_path
    raise RuntimeError("ffmpegがインストールされていません")


def combine_wav_files(wav_paths: List[str], output_path: str) -> None:
    """
    Combine multiple WAV files into one using the standard library wave module.
    All input WAVs must share the same sample rate, channels, and sampwidth.
    """
    if not wav_paths:
        raise ValueError("wav_pathsは空にできません")

    with wave.open(wav_paths[0], "rb") as first:
        params = first.getparams()
        n_channels = first.getnchannels()
        sampwidth = first.getsampwidth()
        framerate = first.getframerate()

    combined_frames = b""
    for path in wav_paths:
        with wave.open(path, "rb") as wf:
            if wf.getparams()[:3] != params[:3]:
                raise ValueError(
                    f"WAVパラメータが一致しません: {path} "
                    f"({wf.getparams()[:3]} vs {params[:3]})"
                )
            combined_frames += wf.readframes(wf.getnframes())

    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        out.writeframes(combined_frames)

    logger.info(
        "WAV結合完了: %d files -> %s (framerate=%d)",
        len(wav_paths), output_path, framerate,
    )


def wav_to_mp3(
    wav_path: str, mp3_path: str, bitrate: str = "128k"
) -> Optional[tuple[float, str]]:
    """
    WAVファイルをffmpegでMP3に変換する。
    Return (duration_seconds, mp3_output_path) on success, None on error.
    """
    ffmpeg_bin = find_ffmpeg()

    try:
        result = subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", wav_path,
                "-codec:a", "libmp3lame",
                "-b:a", bitrate,
                mp3_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            logger.error("ffmpeg MP3エンコード失敗: %s", result.stderr)
            return None

        duration = _parse_ffmpeg_duration(result.stderr)
        return (duration or 0.0, mp3_path)

    except FileNotFoundError:
        logger.error("ffmpegが見つかりません")
        return None
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg MP3エンコードがタイムアウトしました")
        raise


def _parse_ffmpeg_duration(stderr_text: str) -> Optional[float]:
    """stderrからMP3のduration(sec)を抽出"""
    if not stderr_text:
        return None
    for line in stderr_text.splitlines():
        if "time=" not in line:
            continue
        time_str = line.split("time=")[1].split()[0]
        parts = time_str.split(":")
        try:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
        except (ValueError, IndexError):
            return None
    return None
