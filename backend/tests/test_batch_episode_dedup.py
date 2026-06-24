"""Tests for batch script episode dedup logic (_create_episode_record in orchestrate.py)."""

from unittest.mock import patch
from app.services.episode_service import EpisodeService


class TestOrchestrateCreateEpisodeRecord:
    """orchestrate._create_episode_record() の重複防止ロジックのテスト"""

    def test_existing_episode_reused(self):
        """同一日付の既存エピソードがある場合、再利用されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        original_id = svc.create_episode(episode_date="2099-06-01", status="completed")

        reused_id = _create_episode_record("2099-06-01")
        assert reused_id == original_id, "既存エピソードが再利用されること"

        ep = svc.get_episode(reused_id)
        assert ep["status"] == "generating", "再利用後は status=generating になること"

    def test_existing_generating_episode_reused(self):
        """同一日付でstatus=generatingの既存エピソードも再利用されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        original_id = svc.create_episode(episode_date="2099-06-02", status="generating")
        svc.update_episode_phase(original_id, "summarize")

        reused_id = _create_episode_record("2099-06-02")
        assert reused_id == original_id, "generating中の既存エピソードが再利用されること"

        ep = svc.get_episode(reused_id)
        assert ep["status"] == "generating"
        assert ep["phase"] == "", "phase がリセットされること"

    def test_existing_failed_episode_reused(self):
        """同一日付でstatus=failedの既存エピソードも再利用されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        original_id = svc.create_episode(episode_date="2099-06-03", status="failed")

        reused_id = _create_episode_record("2099-06-03")
        assert reused_id == original_id

    def test_no_existing_episode_creates_new(self):
        """同一日付の既存エピソードがない場合、新規作成されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        before = len(svc.get_episode_list())

        new_id = _create_episode_record("2099-07-01")
        assert new_id is not None

        after = len(svc.get_episode_list())
        assert after == before + 1

        ep = svc.get_episode(new_id)
        assert ep["status"] == "generating"

    def test_race_condition_raises_error(self):
        """claim_generating_slot が race condition で失敗した場合、RuntimeError になること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        svc.create_episode(episode_date="2099-08-01", status="completed")

        with patch.object(EpisodeService, "claim_generating_slot", return_value=False):
            import pytest
            with pytest.raises(RuntimeError, match="could not be acquired"):
                _create_episode_record("2099-08-01")


class TestRunDailyDedupPattern:
    """run_daily.py の重複防止パターン（find_by_date→reset→clear→claim）のテスト"""

    def test_reuse_existing_episode(self):
        """既存エピソードがある場合の再利用パス"""
        svc = EpisodeService()
        original_id = svc.create_episode(episode_date="2099-09-01", status="completed")

        existing_id = svc.find_by_date("2099-09-01")
        assert existing_id == original_id

        svc.reset_episode_for_reuse(existing_id)
        svc.clear_episode_items(existing_id)
        assert svc.claim_generating_slot(existing_id)

        ep = svc.get_episode(existing_id)
        assert ep["status"] == "generating"

    def test_create_new_when_no_existing(self):
        """既存エピソードがない場合の新規作成パス"""
        svc = EpisodeService()
        before = len(svc.get_episode_list())

        existing_id = svc.find_by_date("2099-09-02")
        assert existing_id is None

        new_id = svc.create_episode(episode_date="2099-09-02", status="generating")
        after = len(svc.get_episode_list())
        assert after == before + 1
        assert svc.get_episode(new_id)["status"] == "generating"

    def test_race_condition_on_claim(self):
        """claim_generating_slot が False を返す場合のフォールバック"""
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-09-03", status="completed")

        existing_id = svc.find_by_date("2099-09-03")
        svc.reset_episode_for_reuse(existing_id)
        svc.clear_episode_items(existing_id)

        assert not svc.claim_generating_slot(999999), "存在しないIDはclaimできない"
