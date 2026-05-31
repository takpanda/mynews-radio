"""
ラジオ番組用ジングルを生成するスクリプト。
標準ライブラリのみ使用。
"""
import math
import struct
import subprocess
import wave
import os
import tempfile

SAMPLE_RATE = 44100
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

# --- 音符周波数テーブル ---
NOTES = {
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61,
    "G3": 196.00, "A3": 220.00, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23,
    "G4": 392.00, "A4": 440.00, "B4": 493.88,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "F5": 698.46,
    "G5": 783.99, "A5": 880.00, "B5": 987.77,
    "C6": 1046.50,
}


def synthesize_note(freqs: list[float], duration: float, volume: float = 0.45,
                    attack: float = 0.02, decay_rate: float = 2.5) -> list[float]:
    """
    複数の周波数（コード）を重ねたベル風の音符を生成する。
    """
    n = int(SAMPLE_RATE * duration)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        # 複数周波数を合成（倍音付き）
        s = 0.0
        for freq in freqs:
            s += math.sin(2 * math.pi * freq * t)
            s += 0.4 * math.sin(4 * math.pi * freq * t)   # 第2倍音
            s += 0.15 * math.sin(6 * math.pi * freq * t)  # 第3倍音
        s /= len(freqs) * 1.55  # 正規化
        # アタック
        if i < int(SAMPLE_RATE * attack):
            s *= i / (SAMPLE_RATE * attack)
        # ディケイ（自然な減衰）
        s *= math.exp(-decay_rate * t)
        samples.append(s * volume)
    return samples


def mix(*sample_lists: list[float]) -> list[float]:
    """複数のサンプルリストをミックスする（長さは最大に合わせる）"""
    max_len = max(len(s) for s in sample_lists)
    result = [0.0] * max_len
    for sl in sample_lists:
        for i, v in enumerate(sl):
            result[i] += v
    # クリッピング防止
    peak = max(abs(v) for v in result) or 1.0
    if peak > 0.95:
        result = [v / peak * 0.95 for v in result]
    return result


def append_silence(samples: list[float], duration: float) -> list[float]:
    return samples + [0.0] * int(SAMPLE_RATE * duration)


def build_melody(sequence: list[tuple]) -> list[float]:
    """
    sequence: [(note_or_chord, duration_sec, volume), ...]
      note_or_chord: str（単音）または list[str]（コード）
      volume はオプション（省略時 0.45）
    """
    result: list[float] = []
    for item in sequence:
        if len(item) == 3:
            note, dur, vol = item
        else:
            note, dur = item
            vol = 0.45

        if note == "REST":
            result = append_silence(result, dur)
            continue

        freqs = [NOTES[n] for n in (note if isinstance(note, list) else [note])]
        result.extend(synthesize_note(freqs, dur, volume=vol))
    return result


def fade_in_out(samples: list[float], fade_sec: float = 1.0) -> list[float]:
    n = len(samples)
    f = int(SAMPLE_RATE * fade_sec)
    out = list(samples)
    for i in range(min(f, n)):
        out[i] *= i / f
    for i in range(min(f, n)):
        out[n - 1 - i] *= i / f
    return out


def write_wav(samples: list[float], path: str) -> None:
    with wave.open(path, "w") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(SAMPLE_RATE)
        data = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            data += struct.pack("<h", v)
        wf.writeframes(bytes(data))


def to_mp3(wav_path: str, mp3_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-b:a", "192k", mp3_path],
        check=True,
        capture_output=True,
    )


# ============================================================
# オープニングジングル（明るく元気な Cメジャー上昇）
# 10秒
# ============================================================
opening_seq = [
    # 冒頭のコード
    (["C4", "E4", "G4"], 0.6, 0.55),
    # 上昇メロディ
    ("E4", 0.25, 0.50),
    ("G4", 0.25, 0.50),
    ("C5", 0.25, 0.50),
    ("E5", 0.50, 0.55),
    # キラキラコード
    (["C5", "E5", "G5"], 0.5, 0.55),
    ("REST", 0.10),
    # 第2フレーズ
    ("G4", 0.20, 0.45),
    ("A4", 0.20, 0.45),
    ("B4", 0.20, 0.45),
    ("C5", 0.60, 0.55),
    # 締め
    (["E5", "G5", "C6"], 0.7, 0.60),
    ("REST", 0.15),
    ("C5", 0.30, 0.40),
    ("E5", 0.30, 0.40),
    (["C5", "E5", "G5", "C6"], 1.5, 0.58),
    # 余韻
    ("REST", 1.5),
]

# ============================================================
# エンディングジングル（穏やかな Cメジャー着地）
# 10秒
# ============================================================
ending_seq = [
    # 静かなスタート
    ("E5", 0.30, 0.40),
    ("D5", 0.30, 0.40),
    ("C5", 0.60, 0.48),
    # コードで広がり
    (["C4", "E4", "G4", "C5"], 0.70, 0.52),
    ("REST", 0.10),
    # 下降フレーズ
    ("G4", 0.25, 0.42),
    ("F4", 0.25, 0.42),
    ("E4", 0.25, 0.42),
    ("D4", 0.25, 0.42),
    # 最後のコード
    ("C4", 0.50, 0.48),
    (["C4", "E4", "G4"], 0.80, 0.55),
    ("REST", 0.15),
    # フィナーレ
    (["C3", "G3", "C4", "E4", "G4", "C5"], 2.0, 0.52),
    # 余韻
    ("REST", 1.5),
]


def synthesize_tin_whistle(freqs: list[float], duration: float, volume: float = 0.50,
                           attack: float = 0.01, decay_rate: float = 0.6,
                           sample_rate: int = SAMPLE_RATE) -> list[float]:
    """
    ティンホイッスル風の音色を生成する。
    ケルト音楽らしい高倍音・ゆっくりした減衰が特徴。
    """
    n = int(sample_rate * duration)
    samples = []
    for i in range(n):
        t = i / sample_rate
        s = 0.0
        for freq in freqs:
            s += math.sin(2 * math.pi * freq * t)            # 基音
            s += 0.55 * math.sin(4 * math.pi * freq * t)    # 第2倍音
            s += 0.30 * math.sin(6 * math.pi * freq * t)    # 第3倍音
            s += 0.15 * math.sin(8 * math.pi * freq * t)    # 第4倍音
            s += 0.06 * math.sin(10 * math.pi * freq * t)   # 第5倍音
        s /= len(freqs) * 2.1
        # アタック
        if i < int(sample_rate * attack):
            s *= i / (sample_rate * attack)
        # ゆっくりした減衰（ティンホイッスルらしい持続感）
        s *= math.exp(-decay_rate * t)
        samples.append(s * volume)
    return samples


def build_celtic_melody(sequence: list[tuple], sample_rate: int = SAMPLE_RATE) -> list[float]:
    """
    ティンホイッスル音色でケルトメロディを生成。
    sequence: [(note_or_chord, duration_sec, volume), ...]
    """
    result: list[float] = []
    for item in sequence:
        if len(item) == 3:
            note, dur, vol = item
        else:
            note, dur = item
            vol = 0.50

        if note == "REST":
            result = result + [0.0] * int(sample_rate * dur)
            continue

        freqs = [NOTES[n] for n in (note if isinstance(note, list) else [note])]
        result.extend(synthesize_tin_whistle(freqs, dur, volume=vol, sample_rate=sample_rate))
    return result


def write_wav_sr(samples: list[float], path: str, sample_rate: int) -> None:
    """任意のサンプルレートでWAVを書き出す。"""
    with wave.open(path, "w") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        data = bytearray()
        for s in samples:
            v = int(max(-1.0, min(1.0, s)) * 32767)
            data += struct.pack("<h", v)
        wf.writeframes(bytes(data))


# ============================================================
# トランジションジングル（ケルト風 Dドリアン、約3秒）
# カテゴリー移行時に挿入する短いモチーフ
# ============================================================
# Dドリアンスケール: D-E-F-G-A-B-C-D
# ティンホイッスルで弾くようなリフ
transition_seq = [
    ("REST", 0.05),
    # 上昇フレーズ（ケルト的な付点リズム）
    ("G4", 0.12, 0.52),
    ("A4", 0.12, 0.52),
    ("B4", 0.18, 0.55),
    ("D5", 0.28, 0.60),
    ("REST", 0.06),
    # ターン（折り返し）
    ("E5", 0.14, 0.55),
    ("D5", 0.14, 0.50),
    ("B4", 0.14, 0.50),
    ("A4", 0.20, 0.48),
    ("REST", 0.06),
    # 締め（ハーモニー付き）
    ("G4", 0.16, 0.50),
    ("A4", 0.16, 0.50),
    (["G4", "B4", "D5"], 0.65, 0.55),
    # 余韻
    ("REST", 0.50),
]


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "data", "jingles")
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, seq in [("opening", opening_seq), ("ending", ending_seq)]:
            print(f"Generating {name}...")
            samples = build_melody(seq)
            samples = fade_in_out(samples, fade_sec=0.8)
            wav_path = os.path.join(tmpdir, f"{name}.wav")
            mp3_path = os.path.join(out_dir, f"{name}.mp3")
            write_wav(samples, wav_path)
            to_mp3(wav_path, mp3_path)
            size_kb = os.path.getsize(mp3_path) / 1024
            duration = len(samples) / SAMPLE_RATE
            print(f"  -> {mp3_path} ({duration:.1f}s, {size_kb:.0f} KB)")

        # ケルト風トランジションジングル
        # VoiceVox と同じ 24000Hz / mono / 16-bit で WAV を生成
        VOICEVOX_SR = 24000
        print("Generating transition (Celtic jingle)...")
        samples_celtic = build_celtic_melody(transition_seq, sample_rate=VOICEVOX_SR)
        samples_celtic = fade_in_out(samples_celtic, fade_sec=0.15)
        wav_vv_path = os.path.join(out_dir, "transition.wav")
        write_wav_sr(samples_celtic, wav_vv_path, sample_rate=VOICEVOX_SR)
        # MP3版（参考用）
        mp3_path = os.path.join(out_dir, "transition.mp3")
        to_mp3(wav_vv_path, mp3_path)
        duration = len(samples_celtic) / VOICEVOX_SR
        wav_kb = os.path.getsize(wav_vv_path) / 1024
        mp3_kb = os.path.getsize(mp3_path) / 1024
        print(f"  -> {wav_vv_path} ({duration:.1f}s, {wav_kb:.0f} KB WAV)")
        print(f"  -> {mp3_path} ({mp3_kb:.0f} KB MP3)")

    print("Done! data/jingles/ に opening.mp3 / ending.mp3 / transition.wav が生成されました。")


if __name__ == "__main__":
    main()
