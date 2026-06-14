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


def convert_to_wav(
    input_path: str,
    output_path: str,
    sample_rate: int = 24000,
    channels: int = 1,
    sample_format: str = "s16",
) -> bool:
    """Convert an audio file to WAV with fixed params using ffmpeg."""
    ffmpeg_bin = find_ffmpeg()
    try:
        result = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                input_path,
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                f"pcm_{sample_format}le",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(
                "ffmpeg WAV変換失敗: %s -> %s: %s",
                input_path,
                output_path,
                result.stderr,
            )
            return False
        return True
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません")
        return False
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg WAV変換がタイムアウトしました")
        return False


def add_jingles_and_encode(
    main_wav_path: str,
    output_mp3_path: str,
    opening_path: Optional[str] = None,
    ending_path: Optional[str] = None,
    jingle_duration: float = 10.0,
    fade_duration: float = 1.0,
    bitrate: str = "128k",
) -> Optional[tuple[float, str]]:
    """
    メインWAVの前後にジングルMP3を付けてMP3エンコードする。
    opening_path / ending_path が None またはファイル不在の場合はスキップ。
    フェードイン/アウト（fade_duration秒）付きで jingle_duration 秒分だけ使用。

    Returns (duration_seconds, output_mp3_path) or None on error.
    """
    ffmpeg_bin = find_ffmpeg()

    has_opening = bool(opening_path and os.path.isfile(opening_path))
    has_ending = bool(ending_path and os.path.isfile(ending_path))

    if not has_opening and not has_ending:
        # ジングルなし → 従来の wav_to_mp3 にフォールバック
        return wav_to_mp3(main_wav_path, output_mp3_path, bitrate=bitrate)

    # --- ffmpeg 入力リストを構築 ---
    inputs: list[str] = []
    if has_opening:
        inputs += ["-i", opening_path]
    inputs += ["-i", main_wav_path]
    if has_ending:
        inputs += ["-i", ending_path]

    # --- filter_complex を構築 ---
    idx = 0
    filter_parts: list[str] = []
    concat_labels: list[str] = []

    if has_opening:
        # 先頭にフェードインのみ（ファイルをフルで使用）
        filter_parts.append(
            f"[{idx}:a]"
            f"afade=t=in:st=0:d={fade_duration}"
            f"[open]"
        )
        concat_labels.append("[open]")
        idx += 1

    # メイン（WAV）はフィルターなし
    concat_labels.append(f"[{idx}:a]")
    idx += 1

    if has_ending:
        # 先頭にフェードインのみ（ファイルをフルで使用）
        filter_parts.append(
            f"[{idx}:a]"
            f"afade=t=in:st=0:d={fade_duration}"
            f"[end]"
        )
        concat_labels.append("[end]")

    n_segments = len(concat_labels)
    concat_str = "".join(concat_labels)
    # aformat でフレームを再アロケートし libmp3lame に必要なパディングを確保する
    filter_parts.append(f"{concat_str}concat=n={n_segments}:v=0:a=1,aformat=sample_fmts=s16p[out]")

    filter_complex = ";".join(filter_parts)

    cmd = (
        [ffmpeg_bin, "-y"]
        + inputs
        + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-codec:a", "libmp3lame",
            "-b:a", bitrate,
            output_mp3_path,
        ]
    )

    logger.info("ffmpeg jingle concat: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0:
            logger.error("ffmpeg jingle concat 失敗: %s", result.stderr)
            return None

        duration = _parse_ffmpeg_duration(result.stderr)
        return (duration or 0.0, output_mp3_path)

    except FileNotFoundError:
        logger.error("ffmpegが見つかりません")
        return None
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg jingle concat がタイムアウトしました")
        raise


def _parse_ffmpeg_duration(stderr_text: str) -> Optional[float]:
    """stderrからMP3のduration(sec)を抽出（最後の time= を使用）"""
    if not stderr_text:
        return None
    last_duration: Optional[float] = None
    for line in stderr_text.splitlines():
        if "time=" not in line:
            continue
        time_str = line.split("time=")[1].split()[0]
        parts = time_str.split(":")
        try:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            last_duration = h * 3600 + m * 60 + s
        except (ValueError, IndexError):
            pass
    return last_duration
