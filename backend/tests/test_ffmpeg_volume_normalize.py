"""ffmpeg_service.normalize_mean_volume の単体試験。

実ffmpegには依存せず、subprocess.run をモックして
音量計測(volumedetect)→ゲイン適用(volume+alimiter)の2段階を検証する。
"""

import subprocess
from unittest.mock import patch

from app.services.ffmpeg_service import normalize_mean_volume


def _completed(stderr="", returncode=0):
    return subprocess.CompletedProcess(args=["ffmpeg"], returncode=returncode, stdout="", stderr=stderr)


def test_normalize_mean_volume_applies_gain_toward_target(tmp_path):
    measure_result = _completed(stderr="[Parsed_volumedetect_0 @ 0x0] mean_volume: -24.0 dB\n")
    apply_result = _completed(returncode=0)

    with patch("app.services.ffmpeg_service.find_ffmpeg", return_value="ffmpeg"), \
         patch("app.services.ffmpeg_service.subprocess.run", side_effect=[measure_result, apply_result]) as mock_run:
        ok = normalize_mean_volume(
            str(tmp_path / "in.wav"), str(tmp_path / "out.wav"),
            target_mean_dbfs=-16.0, peak_limit_dbfs=-1.0,
        )

    assert ok is True
    apply_cmd = mock_run.call_args_list[1].args[0]
    af_index = apply_cmd.index("-af") + 1
    assert "volume=8.0dB" in apply_cmd[af_index] or "volume=8dB" in apply_cmd[af_index]
    assert "alimiter=limit=" in apply_cmd[af_index]


def test_normalize_mean_volume_returns_false_when_measurement_unavailable(tmp_path):
    measure_result = _completed(stderr="no volumedetect output here\n")

    with patch("app.services.ffmpeg_service.find_ffmpeg", return_value="ffmpeg"), \
         patch("app.services.ffmpeg_service.subprocess.run", return_value=measure_result):
        ok = normalize_mean_volume(str(tmp_path / "in.wav"), str(tmp_path / "out.wav"))

    assert ok is False


def test_normalize_mean_volume_returns_false_when_apply_step_fails(tmp_path):
    measure_result = _completed(stderr="mean_volume: -10.0 dB\n")
    apply_result = _completed(returncode=1, stderr="ffmpeg error")

    with patch("app.services.ffmpeg_service.find_ffmpeg", return_value="ffmpeg"), \
         patch("app.services.ffmpeg_service.subprocess.run", side_effect=[measure_result, apply_result]):
        ok = normalize_mean_volume(str(tmp_path / "in.wav"), str(tmp_path / "out.wav"))

    assert ok is False


def test_normalize_mean_volume_returns_false_on_timeout(tmp_path):
    with patch("app.services.ffmpeg_service.find_ffmpeg", return_value="ffmpeg"), \
         patch("app.services.ffmpeg_service.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)):
        ok = normalize_mean_volume(str(tmp_path / "in.wav"), str(tmp_path / "out.wav"))

    assert ok is False
