"""ffmpeg_service.combine_wav_files の無音挿入(silence_before)の単体試験。

実ffmpegには依存せず、標準ライブラリ wave のみで完結する combine_wav_files を検証する。
"""

import wave

import pytest

from app.services.ffmpeg_service import combine_wav_files


def _write_wav(path, n_frames, framerate=1000, n_channels=1, sampwidth=2):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        # 無音（全ゼロ）と区別できるよう、非ゼロのダミー音声データを書き込む
        wf.writeframes(b"\x01" * (n_frames * n_channels * sampwidth))


def _read_params(path):
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes(), wf.getframerate(), wf.getnchannels(), wf.getsampwidth()


def test_combine_wav_files_without_silence_before_is_unchanged(tmp_path):
    """silence_before省略時は従来どおり単純連結される（Fish S2 Pro以外の経路の回帰確認）。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, 100)
    _write_wav(b, 200)
    out = tmp_path / "out.wav"

    combine_wav_files([str(a), str(b)], str(out))

    n_frames, framerate, n_channels, sampwidth = _read_params(out)
    assert n_frames == 300
    assert (framerate, n_channels, sampwidth) == (1000, 1, 2)


def test_combine_wav_files_inserts_silence_before_specified_index(tmp_path):
    """silence_before[i] で指定した秒数だけ、対応するファイルの直前に無音が挿入される。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, 100, framerate=1000)
    _write_wav(b, 200, framerate=1000)
    out = tmp_path / "out.wav"

    # bの前に0.45秒（=450フレーム @1000Hz）の無音を追加
    combine_wav_files([str(a), str(b)], str(out), silence_before=[0.0, 0.45])

    n_frames, framerate, n_channels, sampwidth = _read_params(out)
    assert n_frames == 100 + 450 + 200
    assert framerate == 1000

    with wave.open(str(out), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    frame_size = n_channels * sampwidth
    silence_region = frames[100 * frame_size: (100 + 450) * frame_size]
    assert silence_region == b"\x00" * len(silence_region)


def test_combine_wav_files_zero_silence_adds_nothing(tmp_path):
    """silence_before の値が0のインデックスには無音を追加しない（先頭行のケース）。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, 50)
    _write_wav(b, 50)
    out = tmp_path / "out.wav"

    combine_wav_files([str(a), str(b)], str(out), silence_before=[0.0, 0.0])

    n_frames, *_ = _read_params(out)
    assert n_frames == 100


def test_combine_wav_files_silence_before_length_mismatch_raises(tmp_path):
    a = tmp_path / "a.wav"
    _write_wav(a, 10)
    out = tmp_path / "out.wav"

    with pytest.raises(ValueError):
        combine_wav_files([str(a)], str(out), silence_before=[0.0, 0.1])


def test_combine_wav_files_inserts_silence_for_stereo_wavs(tmp_path):
    """stereo（2ch）でも、無音フレームがチャンネル数分の長さで正しく生成されること。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, 100, framerate=1000, n_channels=2, sampwidth=2)
    _write_wav(b, 200, framerate=1000, n_channels=2, sampwidth=2)
    out = tmp_path / "out.wav"

    combine_wav_files([str(a), str(b)], str(out), silence_before=[0.0, 0.25])

    n_frames, framerate, n_channels, sampwidth = _read_params(out)
    assert n_frames == 100 + 250 + 200
    assert (framerate, n_channels, sampwidth) == (1000, 2, 2)

    with wave.open(str(out), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    frame_size = n_channels * sampwidth
    silence_region = frames[100 * frame_size: (100 + 250) * frame_size]
    assert len(silence_region) == 250 * frame_size
    assert silence_region == b"\x00" * len(silence_region)


def test_combine_wav_files_inserts_silence_for_24bit_sample_width(tmp_path):
    """標本幅が16bit以外（24bit=3byte）でも、標本幅に整合した無音フレームが生成されること。"""
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    _write_wav(a, 100, framerate=1000, n_channels=1, sampwidth=3)
    _write_wav(b, 200, framerate=1000, n_channels=1, sampwidth=3)
    out = tmp_path / "out.wav"

    combine_wav_files([str(a), str(b)], str(out), silence_before=[0.0, 0.3])

    n_frames, framerate, n_channels, sampwidth = _read_params(out)
    assert n_frames == 100 + 300 + 200
    assert (framerate, n_channels, sampwidth) == (1000, 1, 3)

    with wave.open(str(out), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    frame_size = n_channels * sampwidth
    silence_region = frames[100 * frame_size: (100 + 300) * frame_size]
    assert len(silence_region) == 300 * frame_size
    assert silence_region == b"\x00" * len(silence_region)
