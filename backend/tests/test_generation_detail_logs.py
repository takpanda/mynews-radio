"""BEE-718: エピソード生成の行単位・工程別詳細ログのテスト。

- synthesize_voicevox.synthesize_episode() / build_episode.build_episode() が
  episode_id 指定時に episode_generation_phase_logs / episode_generation_line_logs
  へ正しく記録すること（正常系・部分失敗・全体失敗・工程途中の例外）。
- 90日保持境界での削除、エピソード削除時の連動削除を確認する。
"""

import json
import wave
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.db.connection import get_db_connection
from app.services.episode_service import EpisodeService
from app.services.generation_log_service import cleanup_generation_logs


def _voicevox_settings():
    return SimpleNamespace(
        default_tts_engine="voicevox",
        voicevox_base_url="http://voicevox.test",
        voicevox_speaker_male=11,
        voicevox_speaker_female=2,
        aivispeech_base_url="http://aivispeech.test",
        aivispeech_speaker_male=10,
        aivispeech_speaker_female=20,
        fishs2pro_base_url="http://fish.test",
        fishs2pro_voice_male="male",
        fishs2pro_voice_female="morigawa",
        jingle_transition_path="",
    )


def _write_wav(output_path: str) -> None:
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\0\0" * 10)


def _make_episode_dir(tmp_path, lines):
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text(
        json.dumps({"lines": lines}, ensure_ascii=False), encoding="utf-8",
    )
    return episode_dir


def _create_episode() -> int:
    return EpisodeService().create_episode(episode_date="2026-08-14")


def _phase_logs(episode_id: int, phase: str) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM episode_generation_phase_logs WHERE episode_id = ? AND phase = ? "
            "ORDER BY attempt_no",
            (episode_id, phase),
        ).fetchall()
        return [dict(r) for r in rows]


def _line_logs(episode_id: int) -> list[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM episode_generation_line_logs WHERE episode_id = ? "
            "ORDER BY script_line_index",
            (episode_id,),
        ).fetchall()
        return [dict(r) for r in rows]


class FakeVoicevoxClient:
    """成功/失敗行をテキストで指定できるVOICEVOXクライアントのフェイク。"""

    def __init__(self, base_url, speaker_male=None, speaker_female=None, failing_texts=None):
        self._failing_texts = failing_texts or set()

    def synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
        if text in self._failing_texts:
            return False
        _write_wav(output_path)
        return True

    def close(self):
        pass


def _patched_client(failing_texts=None):
    def factory(base_url, speaker_male=None, speaker_female=None):
        return FakeVoicevoxClient(base_url, speaker_male, speaker_female, failing_texts)
    return factory


# ---------------------------------------------------------------------------
# synthesize_episode: 正常系
# ---------------------------------------------------------------------------

def test_synthesize_success_records_phase_and_line_logs(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = _make_episode_dir(tmp_path, [
        {"text": "1行目", "speaker": "male", "section": "news"},
        {"text": "2行目", "speaker": "female", "section": "news"},
    ])

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch("app.batch.synthesize_voicevox.VoicevoxClient", _patched_client()):
        result = synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id, generation_job_id=42)

    assert result == 2

    phases = _phase_logs(episode_id, "synthesize")
    assert len(phases) == 1
    assert phases[0]["result"] == "success"
    assert phases[0]["line_success_count"] == 2
    assert phases[0]["line_total_count"] == 2
    assert phases[0]["failure_reason"] is None
    assert phases[0]["generation_job_id"] == 42
    assert phases[0]["attempt_no"] == 1

    lines = _line_logs(episode_id)
    assert len(lines) == 2
    assert [l["script_line_index"] for l in lines] == [1, 2]
    assert all(l["synth_result"] == "success" for l in lines)
    assert all(l["failure_reason"] is None for l in lines)
    assert all(l["wav_file"] is not None for l in lines)
    # VOICEVOX(非aivispeech)は delivery を neutral 固定するため speedScale=1.0
    assert all(l["speaking_rate"] == 1.0 for l in lines)
    assert all(l["retry_count"] == 0 for l in lines)
    assert all(l["generation_job_id"] == 42 for l in lines)


def test_synthesize_without_episode_id_skips_logging(tmp_path):
    """既存呼び出し（episode_id未指定）はログを書かず、従来どおり動作すること（回帰防止）。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_dir = _make_episode_dir(tmp_path, [{"text": "1行目", "speaker": "male"}])

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch("app.batch.synthesize_voicevox.VoicevoxClient", _patched_client()):
        result = synthesize_episode(str(episode_dir), tts_engine="voicevox")

    assert result == 1
    with get_db_connection() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM episode_generation_phase_logs").fetchone()["c"]
    assert count == 0


# ---------------------------------------------------------------------------
# synthesize_episode: 部分失敗
# ---------------------------------------------------------------------------

def test_synthesize_partial_failure_records_line_failure_reason(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = _make_episode_dir(tmp_path, [
        {"text": "成功行", "speaker": "male"},
        {"text": "失敗行", "speaker": "female"},
    ])

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch("app.batch.synthesize_voicevox.VoicevoxClient", _patched_client(failing_texts={"失敗行"})):
        result = synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id)

    assert result == 1

    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "success"  # 1件でも成功していればresultはsuccess
    assert phases[0]["line_success_count"] == 1
    assert phases[0]["line_total_count"] == 2

    lines = {l["script_line_index"]: l for l in _line_logs(episode_id)}
    assert lines[1]["synth_result"] == "success"
    assert lines[1]["failure_reason"] is None
    assert lines[2]["synth_result"] == "failure"
    assert lines[2]["failure_reason"] == "tts_request_failed"
    assert lines[2]["wav_file"] is None


# ---------------------------------------------------------------------------
# synthesize_episode: 全体失敗
# ---------------------------------------------------------------------------

def test_synthesize_all_lines_fail_records_phase_failure(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = _make_episode_dir(tmp_path, [
        {"text": "失敗行1", "speaker": "male"},
        {"text": "失敗行2", "speaker": "female"},
    ])

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch(
             "app.batch.synthesize_voicevox.VoicevoxClient",
             _patched_client(failing_texts={"失敗行1", "失敗行2"}),
         ):
        result = synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id)

    assert result == 0

    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "tts_no_lines_succeeded"
    assert phases[0]["line_success_count"] == 0
    assert phases[0]["line_total_count"] == 2

    lines = _line_logs(episode_id)
    assert all(l["synth_result"] == "failure" for l in lines)


def test_synthesize_script_missing_records_phase_failure(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    empty_dir = tmp_path / "empty_episode"
    empty_dir.mkdir()

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()):
        result = synthesize_episode(str(empty_dir), tts_engine="voicevox", episode_id=episode_id)

    assert result == 0
    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "script_missing"


# ---------------------------------------------------------------------------
# synthesize_episode: 工程途中の例外
# ---------------------------------------------------------------------------

def test_synthesize_unexpected_exception_finalizes_phase_and_reraises(tmp_path):
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = _make_episode_dir(tmp_path, [{"text": "1行目", "speaker": "male"}])

    class RaisingClient:
        def __init__(self, *args, **kwargs):
            pass

        def synthesize_line(self, *args, **kwargs):
            raise RuntimeError("boom")

        def close(self):
            pass

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch("app.batch.synthesize_voicevox.VoicevoxClient", RaisingClient):
        with pytest.raises(RuntimeError, match="boom"):
            synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id)

    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "tts_synthesis_exception"


def test_synthesize_corrupt_script_json_finalizes_phase_and_reraises(tmp_path):
    """script.json がJSONとして壊れている場合も、phase logをtts_synthesis_exceptionで
    確定してから例外を呼び出し元へ伝えること（json.load()はphase log開始後・try内で行われる）。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = tmp_path / "episode"
    episode_dir.mkdir()
    (episode_dir / "script.json").write_text("{not valid json", encoding="utf-8")

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()):
        with pytest.raises(ValueError):
            synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id)

    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "tts_synthesis_exception"


def test_synthesize_client_construction_exception_finalizes_phase_and_reraises(tmp_path):
    """TTSクライアントの初期化自体が例外を送出した場合も、phase logを
    tts_synthesis_exceptionで確定してから例外を呼び出し元へ伝えること。"""
    from app.batch.synthesize_voicevox import synthesize_episode

    episode_id = _create_episode()
    episode_dir = _make_episode_dir(tmp_path, [{"text": "1行目", "speaker": "male"}])

    def raising_client_factory(*args, **kwargs):
        raise ConnectionError("client init boom")

    with patch("app.batch.synthesize_voicevox.get_settings", return_value=_voicevox_settings()), \
         patch("app.batch.synthesize_voicevox.VoicevoxClient", raising_client_factory):
        with pytest.raises(ConnectionError, match="client init boom"):
            synthesize_episode(str(episode_dir), tts_engine="voicevox", episode_id=episode_id)

    phases = _phase_logs(episode_id, "synthesize")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "tts_synthesis_exception"


# ---------------------------------------------------------------------------
# build_episode: 正常系（wav_combine / mp3_encode の記録、行ログへのタイミング反映）
# ---------------------------------------------------------------------------

def _build_settings():
    return SimpleNamespace(
        jingle_opening_path="",
        jingle_ending_path="",
        jingle_news_no_tonari_opening_path="",
        jingle_news_no_tonari_ending_path="",
        jingle_duration=10.0,
        jingle_fade_duration=1.0,
    )


def _prepare_built_episode_dir(tmp_path, lines):
    episode_dir = tmp_path / "episode"
    wav_dir = episode_dir / "lines"
    wav_dir.mkdir(parents=True)
    script = {"title": "テックニュース 2026.08.14", "date": "2026-08-14", "lines": lines, "tts_engine": "voicevox"}
    (episode_dir / "script.json").write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    for line in lines:
        with wave.open(str(wav_dir / line["wav_file"]), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(1000)
            wf.writeframes(b"\x01\x00" * 100)
    return episode_dir


def test_build_episode_records_phases_and_updates_line_timing(tmp_path):
    from app.batch.build_episode import build_episode
    from app.services import generation_log_service as log_service

    episode_id = _create_episode()

    # synthesize済みの行ログを事前に用意する（build工程がこれを更新する対象）
    synth_phase_id = log_service.start_phase_log(episode_id, "synthesize", generation_job_id=7)
    log_service.record_line_log(
        synth_phase_id, episode_id, 1, generation_job_id=7,
        speaker="male", section="news", delivery="neutral", tts_engine="voicevox",
        synth_result="success", wav_file="001.wav",
    )
    log_service.record_line_log(
        synth_phase_id, episode_id, 2, generation_job_id=7,
        speaker="female", section="news", delivery="neutral", tts_engine="voicevox",
        synth_result="success", wav_file="002.wav",
    )
    log_service.finalize_phase_log(synth_phase_id, result="success", line_success_count=2, line_total_count=2)

    lines = [
        {"text": "L1", "speaker": "male", "wav_file": "001.wav"},
        {"text": "L2", "speaker": "female", "wav_file": "002.wav"},
    ]
    episode_dir = _prepare_built_episode_dir(tmp_path, lines)

    with patch("app.batch.build_episode.get_settings", return_value=_build_settings()), \
         patch(
             "app.batch.build_episode.add_jingles_and_encode",
             return_value=(1.0, str(episode_dir / "episode.mp3")),
         ):
        metadata = build_episode(str(episode_dir), episode_id=episode_id, generation_job_id=7)

    assert metadata

    combine_phases = _phase_logs(episode_id, "wav_combine")
    assert len(combine_phases) == 1
    assert combine_phases[0]["result"] == "success"
    assert combine_phases[0]["generation_job_id"] == 7

    mp3_phases = _phase_logs(episode_id, "mp3_encode")
    assert len(mp3_phases) == 1
    assert mp3_phases[0]["result"] == "success"

    lines_after = {l["script_line_index"]: l for l in _line_logs(episode_id)}
    assert lines_after[1]["start_time_sec"] == 0.0
    assert lines_after[2]["start_time_sec"] == pytest.approx(0.1)


def test_build_episode_wav_combine_failure_records_failure_reason(tmp_path):
    from app.batch.build_episode import build_episode

    episode_id = _create_episode()
    lines = [{"text": "L1", "speaker": "male", "wav_file": "001.wav"}]
    episode_dir = _prepare_built_episode_dir(tmp_path, lines)

    with patch("app.batch.build_episode.get_settings", return_value=_build_settings()), \
         patch("app.batch.build_episode.combine_wav_files", side_effect=RuntimeError("combine boom")):
        metadata = build_episode(str(episode_dir), episode_id=episode_id)

    assert metadata == {}
    phases = _phase_logs(episode_id, "wav_combine")
    assert phases[0]["result"] == "failure"
    assert phases[0]["failure_reason"] == "wav_combine_failed"


def test_build_episode_mp3_encode_failure_records_failure_reason(tmp_path):
    from app.batch.build_episode import build_episode

    episode_id = _create_episode()
    lines = [{"text": "L1", "speaker": "male", "wav_file": "001.wav"}]
    episode_dir = _prepare_built_episode_dir(tmp_path, lines)

    with patch("app.batch.build_episode.get_settings", return_value=_build_settings()), \
         patch("app.batch.build_episode.add_jingles_and_encode", return_value=None):
        metadata = build_episode(str(episode_dir), episode_id=episode_id)

    assert metadata == {}
    combine_phases = _phase_logs(episode_id, "wav_combine")
    assert combine_phases[0]["result"] == "success"
    mp3_phases = _phase_logs(episode_id, "mp3_encode")
    assert mp3_phases[0]["result"] == "failure"
    assert mp3_phases[0]["failure_reason"] == "mp3_encode_failed"


def test_build_episode_start_time_calculation_failure_fails_generation(tmp_path):
    """start_time計算(_annotate_start_times)が失敗した場合、無音時間・開始時刻が
    実際の結合結果と一致しないまま成功扱いにしてはならない。生成失敗として返し、
    wav_combine工程ログをbuild_exceptionでfailure確定すること。"""
    from app.batch.build_episode import build_episode

    episode_id = _create_episode()
    lines = [{"text": "L1", "speaker": "male", "wav_file": "001.wav"}]
    episode_dir = _prepare_built_episode_dir(tmp_path, lines)

    with patch("app.batch.build_episode.get_settings", return_value=_build_settings()), \
         patch("app.batch.build_episode._annotate_start_times", side_effect=RuntimeError("annotate boom")), \
         patch("app.batch.build_episode.add_jingles_and_encode") as mock_encode:
        metadata = build_episode(str(episode_dir), episode_id=episode_id)

    assert metadata == {}
    mock_encode.assert_not_called()
    combine_phases = _phase_logs(episode_id, "wav_combine")
    assert combine_phases[0]["result"] == "failure"
    assert combine_phases[0]["failure_reason"] == "build_exception"
    assert _phase_logs(episode_id, "mp3_encode") == []


def test_build_episode_line_timing_save_failure_fails_generation(tmp_path):
    """行タイミングのDB保存(update_line_timing)が失敗した場合、start_time計算自体は
    成功していても成功扱いにしてはならない。生成失敗として返し、wav_combine工程ログを
    build_exceptionでfailure確定すること。"""
    from app.batch.build_episode import build_episode

    episode_id = _create_episode()
    lines = [
        {"text": "L1", "speaker": "male", "wav_file": "001.wav"},
        {"text": "L2", "speaker": "female", "wav_file": "002.wav"},
    ]
    episode_dir = _prepare_built_episode_dir(tmp_path, lines)

    with patch("app.batch.build_episode.get_settings", return_value=_build_settings()), \
         patch("app.batch.build_episode.log_service.update_line_timing", return_value=False), \
         patch("app.batch.build_episode.add_jingles_and_encode") as mock_encode:
        metadata = build_episode(str(episode_dir), episode_id=episode_id)

    assert metadata == {}
    mock_encode.assert_not_called()
    combine_phases = _phase_logs(episode_id, "wav_combine")
    assert combine_phases[0]["result"] == "failure"
    assert combine_phases[0]["failure_reason"] == "build_exception"
    assert _phase_logs(episode_id, "mp3_encode") == []


# ---------------------------------------------------------------------------
# 削除処理: エピソード削除との連動、90日保持境界
# ---------------------------------------------------------------------------

def test_delete_episode_removes_generation_logs():
    from app.services import generation_log_service as log_service

    episode_id = _create_episode()
    phase_id = log_service.start_phase_log(episode_id, "synthesize")
    log_service.record_line_log(
        phase_id, episode_id, 1, synth_result="success", wav_file="001.wav",
    )
    log_service.finalize_phase_log(phase_id, result="success", line_success_count=1, line_total_count=1)

    assert _phase_logs(episode_id, "synthesize")
    assert _line_logs(episode_id)

    deleted = EpisodeService().delete_episode(episode_id)
    assert deleted is True

    assert _phase_logs(episode_id, "synthesize") == []
    assert _line_logs(episode_id) == []


def test_cleanup_generation_logs_respects_90_day_boundary():
    reference = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
    before_boundary = (reference - timedelta(days=89, hours=23, minutes=59)).isoformat()
    exact_boundary = (reference - timedelta(days=90)).isoformat()
    after_boundary = (reference - timedelta(days=90, seconds=1)).isoformat()

    episode_id = _create_episode()

    with get_db_connection() as conn:
        for label, ended_at in (
            ("before_boundary", before_boundary),
            ("exact_boundary", exact_boundary),
            ("after_boundary", after_boundary),
        ):
            cursor = conn.execute(
                "INSERT INTO episode_generation_phase_logs "
                "(episode_id, phase, attempt_no, result, started_at, ended_at) "
                "VALUES (?, 'synthesize', ?, 'success', ?, ?)",
                (episode_id, {"before_boundary": 1, "exact_boundary": 2, "after_boundary": 3}[label],
                 ended_at, ended_at),
            )
            conn.execute(
                "INSERT INTO episode_generation_line_logs "
                "(phase_log_id, episode_id, script_line_index, synth_result) "
                "VALUES (?, ?, 1, 'success')",
                (cursor.lastrowid, episode_id),
            )

    deleted = cleanup_generation_logs(now=reference)
    assert deleted == 1

    with get_db_connection() as conn:
        remaining_phases = {
            row["attempt_no"]
            for row in conn.execute(
                "SELECT attempt_no FROM episode_generation_phase_logs WHERE episode_id = ?",
                (episode_id,),
            ).fetchall()
        }
        remaining_lines = conn.execute(
            "SELECT COUNT(*) AS c FROM episode_generation_line_logs WHERE episode_id = ?",
            (episode_id,),
        ).fetchone()["c"]

    # attempt_no=1(before_boundary)とattempt_no=2(exact_boundary)は保持、3(after_boundary)のみ削除
    assert remaining_phases == {1, 2}
    assert remaining_lines == 2
