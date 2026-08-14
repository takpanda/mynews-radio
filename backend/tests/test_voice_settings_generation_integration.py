"""BEE-725: 保存済みボイス設定が各生成経路（手動/定期/記事解説/再合成）へ伝播することのテスト。"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services import settings_service


def _save_voice_settings():
    settings_service.save_voice_settings(
        settings_service.validate_voice_settings(
            aivispeech_speaker_male=9001, aivispeech_speaker_female=9002,
            voicevox_speaker_male=9011, voicevox_speaker_female=9012,
            fishs2pro_voice_male="custom-male", fishs2pro_voice_female="custom-female",
        )
    )


def _make_fake_open(script_json: str):
    def _open(*args, **kwargs):
        m = MagicMock()
        m.__enter__.return_value.read.return_value = script_json
        return m
    return _open


class TestRadioPipelineUsesSavedVoiceSettings:
    """手動生成・定期生成が共有する _determine_tts_config の解決対象."""

    def test_determine_tts_config_uses_saved_values_per_engine(self):
        from app.batch.radio_pipeline import _determine_tts_config

        _save_voice_settings()

        aivis = _determine_tts_config("aivispeech")
        assert (aivis["speaker_male"], aivis["speaker_female"]) == (9001, 9002)

        voicevox = _determine_tts_config("voicevox")
        assert (voicevox["speaker_male"], voicevox["speaker_female"]) == (9011, 9012)

        fishs2pro = _determine_tts_config("fishs2pro")
        assert (fishs2pro["speaker_male"], fishs2pro["speaker_female"]) == ("custom-male", "custom-female")

    def test_determine_tts_config_falls_back_to_config_when_unsaved(self):
        from app.batch.radio_pipeline import _determine_tts_config
        from app.config import Settings

        settings = Settings()
        config = _determine_tts_config("voicevox")
        assert (config["speaker_male"], config["speaker_female"]) == (
            settings.voicevox_speaker_male, settings.voicevox_speaker_female,
        )

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_run_radio_pipeline_passes_saved_speakers_to_synthesize(
        self, mock_build, mock_review, mock_gen, mock_sum, mock_import,
    ):
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        _save_voice_settings()
        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-08-01")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):
            run_radio_pipeline(ep_id, episode_date="2099-08-01", tts_engine="voicevox")

        kwargs = mock_synth.call_args.kwargs
        assert kwargs["speaker_male"] == 9011
        assert kwargs["speaker_female"] == 9012

    @patch("app.batch.radio_pipeline.import_articles_by_source", return_value=(3, 0))
    @patch("app.batch.radio_pipeline.summarize_articles", return_value=5)
    @patch("app.batch.radio_pipeline.generate_script", return_value=5)
    @patch("app.batch.radio_pipeline.review_script", return_value={"revised": False, "review_count": 0})
    @patch("app.batch.radio_pipeline.build_episode", return_value={"audio_path": "ep.mp3"})
    def test_explicit_speakers_still_win_over_saved_values(
        self, mock_build, mock_review, mock_gen, mock_sum, mock_import,
    ):
        """既存契約: 下位処理への明示的な話者値は保存値より優先される."""
        from app.batch.radio_pipeline import run_radio_pipeline
        from app.services.episode_service import EpisodeService

        _save_voice_settings()
        svc = EpisodeService()
        ep_id, _ = svc.create_radio_episode("2099-08-02")

        with patch("app.batch.radio_pipeline.synthesize_episode", return_value=3) as mock_synth, \
             patch("builtins.open", _make_fake_open('{"lines": [{"text": "hello"}]}')):
            run_radio_pipeline(
                ep_id, episode_date="2099-08-02",
                tts_base_url="http://custom:8080",
                tts_speaker_male=111, tts_speaker_female=222,
            )

        kwargs = mock_synth.call_args.kwargs
        assert kwargs["speaker_male"] == 111
        assert kwargs["speaker_female"] == 222


class TestCommentaryGenerationUsesSavedVoiceSettings:
    def test_commentary_generation_passes_saved_speakers_to_synthesize(self):
        from app.api.generate import _run_commentary_generation, GenerateRequest
        from app.services.episode_service import EpisodeService

        _save_voice_settings()
        svc = EpisodeService()
        ep_id = svc.create_episode(episode_date="2099-08-03", status="generating")
        body = GenerateRequest(
            date="2099-08-03", url="https://example.com/article",
            style="solo", mc_gender="male", tts_engine="fishs2pro",
        )
        fake_script = '{"lines": [{"article_id": 1, "text": "commentary"}]}'

        with patch("app.api.generate.fetch_article_by_url",
                   return_value={"title": "T", "url": body.url, "text": "body", "source": "url_input"}), \
             patch("app.api.generate.ArticleService.upsert_article", return_value=True), \
             patch("app.api.generate.ArticleService.fetch_new_articles", return_value=[]), \
             patch("app.api.generate.get_db_connection") as mock_conn, \
             patch("app.api.generate.generate_commentary_script", return_value=1), \
             patch("app.api.generate.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}), \
             patch("builtins.open", _make_fake_open(fake_script)):

            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: 123 if key == "id" else None
            mock_conn_instance = MagicMock()
            mock_conn_instance.__enter__.return_value.execute.return_value.fetchone.return_value = mock_row
            mock_conn.return_value = mock_conn_instance

            _run_commentary_generation(ep_id, body)

        kwargs = mock_synth.call_args.kwargs
        assert kwargs["speaker_male"] == "custom-male"
        assert kwargs["speaker_female"] == "custom-female"

        ep = svc.get_episode(ep_id)
        assert ep["status"] == "completed"


class TestResynthesisUsesSavedVoiceSettings:
    def test_stream_synthesize_passes_saved_speakers(self):
        from app.api.generate import SynthesizeRequest, _stream_synthesize
        from app.services.episode_service import EpisodeService

        _save_voice_settings()
        service = EpisodeService()
        episode_id = service.create_episode("2099-08-04", status="completed", type="radio")
        base_dir = Path(os.environ["EPISODES_DIR"]) / str(episode_id)
        base_dir.mkdir(parents=True)
        (base_dir / "script.json").write_text('{"lines": [{"text": "hello"}]}', encoding="utf-8")

        with patch("app.api.generate.DEFAULT_EPISODES_DIR", os.environ["EPISODES_DIR"]), \
             patch("app.api.generate.synthesize_episode", return_value=1) as mock_synth, \
             patch("app.api.generate.build_episode", return_value={"audio_path": "episode.mp3"}):
            list(_stream_synthesize(episode_id, SynthesizeRequest(tts_engine="aivispeech")))

        kwargs = mock_synth.call_args.kwargs
        assert kwargs["speaker_male"] == 9001
        assert kwargs["speaker_female"] == 9002
