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


def _silence_frames(duration_seconds: float, n_channels: int, sampwidth: int, framerate: int) -> bytes:
    """指定秒数分の無音フレームを、対象WAVの標本化周波数・チャンネル数・標本幅に合わせて生成する。"""
    n_frames = int(round(duration_seconds * framerate))
    return b"\x00" * (n_frames * n_channels * sampwidth)


def combine_wav_files(
    wav_paths: List[str],
    output_path: str,
    silence_before: Optional[List[float]] = None,
) -> None:
    """
    Combine multiple WAV files into one using the standard library wave module.
    All input WAVs must share the same sample rate, channels, and sampwidth.

    silence_before: wav_paths と同じ長さのリスト。指定した場合、各インデックスの
    秒数だけ対応するファイルの直前に無音を挿入する。省略時（None）は無音を挿入
    せず、従来どおり単純連結する。
    """
    if not wav_paths:
        raise ValueError("wav_pathsは空にできません")

    if silence_before is not None and len(silence_before) != len(wav_paths):
        raise ValueError("silence_beforeはwav_pathsと同じ長さである必要があります")

    with wave.open(wav_paths[0], "rb") as first:
        params = first.getparams()
        n_channels = first.getnchannels()
        sampwidth = first.getsampwidth()
        framerate = first.getframerate()

    combined_frames = b""
    for i, path in enumerate(wav_paths):
        with wave.open(path, "rb") as wf:
            if wf.getparams()[:3] != params[:3]:
                raise ValueError(
                    f"WAVパラメータが一致しません: {path} "
                    f"({wf.getparams()[:3]} vs {params[:3]})"
                )
            if silence_before is not None and silence_before[i] > 0:
                combined_frames += _silence_frames(
                    silence_before[i], n_channels, sampwidth, framerate
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


def _measure_mean_volume_dbfs(input_path: str) -> Optional[float]:
    """ffmpegのvolumedetectフィルタで平均音量(dBFS)を計測する。取得失敗時はNone。"""
    ffmpeg_bin = find_ffmpeg()
    try:
        result = subprocess.run(
            [ffmpeg_bin, "-i", input_path, "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません")
        return None
    except subprocess.TimeoutExpired:
        logger.error("音量計測がタイムアウトしました: %s", input_path)
        return None

    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split(" ")[0])
            except (ValueError, IndexError):
                break
    logger.error("音量計測結果を取得できませんでした: %s", input_path)
    return None


def normalize_mean_volume(
    input_path: str,
    output_path: str,
    target_mean_dbfs: float = -16.0,
    peak_limit_dbfs: float = -1.0,
) -> bool:
    """WAVの平均音量をtarget_mean_dbfs付近へ調整し、ピークをpeak_limit_dbfs以下に抑制する。

    音量計測・ffmpeg実行のいずれかに失敗した場合はFalseを返す
    （呼び出し側は未調整ファイルを成功扱いにしないこと）。
    """
    mean_volume = _measure_mean_volume_dbfs(input_path)
    if mean_volume is None:
        return False

    gain_db = target_mean_dbfs - mean_volume
    peak_limit_linear = 10 ** (peak_limit_dbfs / 20)

    ffmpeg_bin = find_ffmpeg()
    try:
        result = subprocess.run(
            [
                ffmpeg_bin, "-y",
                "-i", input_path,
                "-af", f"volume={gain_db}dB,alimiter=limit={peak_limit_linear}",
                output_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        logger.error("ffmpegが見つかりません")
        return False
    except subprocess.TimeoutExpired:
        logger.error("音量調整がタイムアウトしました: %s", input_path)
        return False

    if result.returncode != 0:
        logger.error(
            "ffmpeg 音量調整失敗: %s -> %s: %s",
            input_path, output_path, result.stderr,
        )
        return False
    return True


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
