"""Fish S2 Pro 経路限定の発話間無音付与と start_time 整合の試験（BEE-629 / BEE-626）。

- combine_wav_files への無音区間の受け渡し（_compute_fishs2pro_silence_before）は
  実WAVファイルを必要としない純粋ロジックとして単体試験する。
- build_episode() の結合〜start_time計算までは標準ライブラリ wave のみに依存するため、
  実ffmpegを使わずに統合試験できる（MP3エンコード段のみ add_jingles_and_encode をモックする）。
"""

import json
import wave
from types import SimpleNamespace
from unittest.mock import patch

from app.batch.build_episode import (
    FISHS2PRO_SAME_SPEAKER_SILENCE_SEC,
    FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC,
    _compute_fishs2pro_silence_before,
    build_episode,
)


def _fake_settings():
    return SimpleNamespace(
        jingle_opening_path="",
        jingle_ending_path="",
        jingle_news_no_tonari_opening_path="",
        jingle_news_no_tonari_ending_path="",
        jingle_duration=10.0,
        jingle_fade_duration=1.0,
    )


def _write_wav(path, n_frames, framerate=1000, n_channels=1, sampwidth=2):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(framerate)
        wf.writeframes(b"\x01\x00" * n_frames)


class TestComputeFishs2ProSilenceBefore:
    """_compute_fishs2pro_silence_before の純粋ロジック試験（WAV実体不要）。"""

    def test_first_line_gets_no_leading_silence(self):
        script = {"lines": [{"speaker": "male", "wav_file": "001.wav"}]}
        result = _compute_fishs2pro_silence_before(script, ["001.wav"])
        assert result == [0.0]

    def test_same_speaker_consecutive_lines_get_short_silence(self):
        script = {
            "lines": [
                {"speaker": "male", "wav_file": "001.wav"},
                {"speaker": "male", "wav_file": "002.wav"},
            ]
        }
        result = _compute_fishs2pro_silence_before(script, ["001.wav", "002.wav"])
        assert result == [0.0, FISHS2PRO_SAME_SPEAKER_SILENCE_SEC]

    def test_speaker_change_gets_long_silence(self):
        script = {
            "lines": [
                {"speaker": "male", "wav_file": "001.wav"},
                {"speaker": "female", "wav_file": "002.wav"},
            ]
        }
        result = _compute_fishs2pro_silence_before(script, ["001.wav", "002.wav"])
        assert result == [0.0, FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC]

    def test_jingle_boundary_wav_is_excluded_from_silence_rules(self):
        """台本行に紐付かないWAV（transition挿入ジングル）の前後には無音を追加しない。"""
        script = {
            "lines": [
                {"speaker": "male", "wav_file": "001.wav"},
                {"speaker": "female", "wav_file": "003.wav", "section": "transition"},
            ]
        }
        # 002.wav は transition 用に挿入されたジングル/無音ファイルで、台本行に紐付かない
        result = _compute_fishs2pro_silence_before(script, ["001.wav", "002.wav", "003.wav"])
        assert result == [0.0, 0.0, 0.0]

    def test_wav_file_fallback_reconstruction_matches_synthesize_counter_logic(self):
        """wav_file未設定の台本でも synthesize_voicevox.py と同じ file_counter規則で対応付けられる。"""
        script = {
            "lines": [
                {"speaker": "male"},
                {"speaker": "male"},
                {"speaker": "female", "section": "transition"},
            ]
        }
        # 期待される割当: 001.wav(male), 002.wav(male), 003.wav=jingle予約, 004.wav(female/transition行)
        result = _compute_fishs2pro_silence_before(
            script, ["001.wav", "002.wav", "003.wav", "004.wav"]
        )
        assert result == [0.0, FISHS2PRO_SAME_SPEAKER_SILENCE_SEC, 0.0, 0.0]
        assert script["lines"][0]["wav_file"] == "001.wav"
        assert script["lines"][1]["wav_file"] == "002.wav"
        assert script["lines"][2]["wav_file"] == "004.wav"


class TestBuildEpisodeFishs2ProIntegration:
    """build_episode() の結合処理・start_time計算の統合試験（MP3段のみモック）。"""

    def _build_episode_dir(self, tmp_path, lines, wav_frame_counts, tts_engine=None):
        episode_dir = tmp_path / "episode"
        wav_dir = episode_dir / "lines"
        wav_dir.mkdir(parents=True)

        script = {"title": "テックニュース 2026.06.27", "date": "2026-06-27", "lines": lines}
        if tts_engine is not None:
            script["tts_engine"] = tts_engine
        (episode_dir / "script.json").write_text(
            json.dumps(script, ensure_ascii=False), encoding="utf-8"
        )

        for filename, n_frames in wav_frame_counts.items():
            _write_wav(wav_dir / filename, n_frames, framerate=1000)

        return episode_dir

    def test_fishs2pro_adds_silence_and_keeps_start_time_consistent(self, tmp_path):
        # L1(male)-L2(male, 同一話者)-L3(female, 話者交代)-[transitionジングル]-L4(female, 継続)
        lines = [
            {"text": "L1", "speaker": "male"},
            {"text": "L2", "speaker": "male"},
            {"text": "L3", "speaker": "female"},
            {"text": "L4", "speaker": "female", "section": "transition"},
        ]
        wav_frame_counts = {
            "001.wav": 100,
            "002.wav": 100,
            "003.wav": 100,
            "004.wav": 100,  # transition挿入ジングル（台本行に紐付かない）
            "005.wav": 100,
        }
        episode_dir = self._build_episode_dir(
            tmp_path, lines, wav_frame_counts, tts_engine="fishs2pro"
        )

        with patch("app.batch.build_episode.get_settings", return_value=_fake_settings()), \
             patch(
                 "app.batch.build_episode.add_jingles_and_encode",
                 return_value=(1.2, str(episode_dir / "episode.mp3")),
             ):
            metadata = build_episode(str(episode_dir))

        assert metadata

        combined_wav = episode_dir / "episode_combined.wav"
        with wave.open(str(combined_wav), "rb") as wf:
            combined_frames = wf.getnframes()
        # 5ファイル分(500) + 同一話者無音(250) + 話者交代無音(450)
        expected_extra_frames = int(round(FISHS2PRO_SAME_SPEAKER_SILENCE_SEC * 1000)) + int(
            round(FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC * 1000)
        )
        assert combined_frames == 500 + expected_extra_frames

        with open(episode_dir / "script.json", "r", encoding="utf-8") as f:
            updated_script = json.load(f)
        start_times = [line["start_time"] for line in updated_script["lines"]]
        assert start_times[0] == 0.0
        assert start_times[1] == round(0.1 + FISHS2PRO_SAME_SPEAKER_SILENCE_SEC, 3)
        assert start_times[2] == round(
            start_times[1] + 0.1 + FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC, 3
        )
        # L4はtransitionジングルの直後 = ジングル境界のため追加無音なし
        assert start_times[3] == round(start_times[2] + 0.1 + 0.1, 3)

    def test_non_fishs2pro_route_is_unaffected(self, tmp_path):
        """tts_engineがfishs2pro以外（または未設定）の場合、無音追加もstart_time計算も従来どおり。"""
        lines = [
            {"text": "L1", "speaker": "male"},
            {"text": "L2", "speaker": "female"},
        ]
        wav_frame_counts = {"001.wav": 100, "002.wav": 100}
        episode_dir = self._build_episode_dir(
            tmp_path, lines, wav_frame_counts, tts_engine="aivispeech"
        )

        with patch("app.batch.build_episode.get_settings", return_value=_fake_settings()), \
             patch(
                 "app.batch.build_episode.add_jingles_and_encode",
                 return_value=(0.2, str(episode_dir / "episode.mp3")),
             ):
            metadata = build_episode(str(episode_dir))

        assert metadata

        combined_wav = episode_dir / "episode_combined.wav"
        with wave.open(str(combined_wav), "rb") as wf:
            combined_frames = wf.getnframes()
        # 無音追加なし: 2ファイル分の合計フレーム数のみ
        assert combined_frames == 200

        with open(episode_dir / "script.json", "r", encoding="utf-8") as f:
            updated_script = json.load(f)
        start_times = [line["start_time"] for line in updated_script["lines"]]
        assert start_times == [0.0, 0.1]

    def test_missing_tts_engine_field_defaults_to_no_silence(self, tmp_path):
        """script.json に tts_engine が無い（過去のエピソード等）場合も無音追加なしの従来動作を維持する。"""
        lines = [
            {"text": "L1", "speaker": "male"},
            {"text": "L2", "speaker": "female"},
        ]
        wav_frame_counts = {"001.wav": 100, "002.wav": 100}
        episode_dir = self._build_episode_dir(tmp_path, lines, wav_frame_counts, tts_engine=None)

        with patch("app.batch.build_episode.get_settings", return_value=_fake_settings()), \
             patch(
                 "app.batch.build_episode.add_jingles_and_encode",
                 return_value=(0.2, str(episode_dir / "episode.mp3")),
             ):
            metadata = build_episode(str(episode_dir))

        assert metadata
        combined_wav = episode_dir / "episode_combined.wav"
        with wave.open(str(combined_wav), "rb") as wf:
            assert wf.getnframes() == 200

    def test_fishs2pro_start_time_includes_opening_jingle_offset(self, tmp_path):
        """開始ジングルが存在する場合、その実尺(opening_offset)を含めてstart_timeが計算されること。"""
        lines = [
            {"text": "L1", "speaker": "male"},
            {"text": "L2", "speaker": "female"},
        ]
        wav_frame_counts = {"001.wav": 100, "002.wav": 100}
        episode_dir = self._build_episode_dir(
            tmp_path, lines, wav_frame_counts, tts_engine="fishs2pro"
        )

        opening_jingle = tmp_path / "opening.mp3"
        opening_jingle.write_bytes(b"dummy-opening-jingle")

        settings = _fake_settings()
        settings.jingle_opening_path = str(opening_jingle)

        with patch("app.batch.build_episode.get_settings", return_value=settings), \
             patch("app.batch.build_episode._get_audio_duration", return_value=3.0), \
             patch(
                 "app.batch.build_episode.add_jingles_and_encode",
                 return_value=(5.0, str(episode_dir / "episode.mp3")),
             ):
            metadata = build_episode(str(episode_dir))

        assert metadata
        with open(episode_dir / "script.json", "r", encoding="utf-8") as f:
            updated_script = json.load(f)
        start_times = [line["start_time"] for line in updated_script["lines"]]

        # opening_offset(3.0秒) + L1の直前無音(先頭行=0) から L1 が開始する
        assert start_times[0] == 3.0
        # L2はL1(0.1秒)の後、話者交代のため0.45秒の無音を挟んで開始する
        assert start_times[1] == round(
            3.0 + 0.1 + FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC, 3
        )

        # 開始ジングル自体はcombine_wav_files（lines/配下のWAV結合）には含まれない
        combined_wav = episode_dir / "episode_combined.wav"
        with wave.open(str(combined_wav), "rb") as wf:
            combined_frames = wf.getnframes()
        assert combined_frames == 100 + int(round(FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC * 1000)) + 100

    def test_fishs2pro_regular_last_line_start_time_matches_final_cumulative_position(
        self, tmp_path
    ):
        """ジングル等を挟まない通常の最終行のstart_timeが、直前までの累積位置と一致すること。

        また、結合音声の総尺が「最終行の開始位置＋最終行自体の長さ」と一致し、
        末尾に余分な無音が付与されていないことを確認する。
        """
        lines = [
            {"text": "L1", "speaker": "male"},
            {"text": "L2", "speaker": "male"},
            {"text": "L3", "speaker": "female"},
        ]
        wav_frame_counts = {"001.wav": 100, "002.wav": 150, "003.wav": 200}
        episode_dir = self._build_episode_dir(
            tmp_path, lines, wav_frame_counts, tts_engine="fishs2pro"
        )

        with patch("app.batch.build_episode.get_settings", return_value=_fake_settings()), \
             patch(
                 "app.batch.build_episode.add_jingles_and_encode",
                 return_value=(1.0, str(episode_dir / "episode.mp3")),
             ):
            metadata = build_episode(str(episode_dir))

        assert metadata
        with open(episode_dir / "script.json", "r", encoding="utf-8") as f:
            updated_script = json.load(f)
        start_times = [line["start_time"] for line in updated_script["lines"]]

        expected_last_start = round(
            0.1 + FISHS2PRO_SAME_SPEAKER_SILENCE_SEC + 0.15 + FISHS2PRO_SPEAKER_CHANGE_SILENCE_SEC,
            3,
        )
        assert start_times[-1] == expected_last_start

        combined_wav = episode_dir / "episode_combined.wav"
        with wave.open(str(combined_wav), "rb") as wf:
            combined_frames = wf.getnframes()
            combined_duration = combined_frames / float(wf.getframerate())
        # 最終行(200フレーム=0.2秒)の後に余分な無音が付与されていないこと
        assert round(start_times[-1] + 0.2, 3) == round(combined_duration, 3)
