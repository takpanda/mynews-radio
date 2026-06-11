import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from app.services.episode_service import EpisodeService

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))
from reset_stale_generating import main


class TestResetStaleGenerating:
    def test_resets_generating_to_pending(self):
        svc = EpisodeService()
        eid1 = svc.create_episode(episode_date="2099-03-01", status="generating")
        eid2 = svc.create_episode(episode_date="2099-03-02", status="generating")

        captured = StringIO()
        sys.stdout, original = captured, sys.stdout
        try:
            main()
        finally:
            sys.stdout = original

        assert "Updated 2 episode(s) from generating to pending." in captured.getvalue()
        assert svc.get_episode(eid1)["status"] == "pending"
        assert svc.get_episode(eid2)["status"] == "pending"

    def test_no_generating_records_is_idempotent(self):
        captured = StringIO()
        sys.stdout, original = captured, sys.stdout
        try:
            main()
        finally:
            sys.stdout = original

        assert "No generating episodes found. Nothing to update." in captured.getvalue()

    def test_other_statuses_not_affected(self):
        svc = EpisodeService()
        completed_id = svc.create_episode(episode_date="2099-04-01", status="completed")
        failed_id = svc.create_episode(episode_date="2099-04-02", status="failed")
        generating_id = svc.create_episode(episode_date="2099-04-03", status="generating")

        captured = StringIO()
        sys.stdout, original = captured, sys.stdout
        try:
            main()
        finally:
            sys.stdout = original

        assert svc.get_episode(completed_id)["status"] == "completed"
        assert svc.get_episode(failed_id)["status"] == "failed"
        assert svc.get_episode(generating_id)["status"] == "pending"
        assert "Updated 1 episode(s) from generating to pending." in captured.getvalue()

    def test_db_error_exits_with_message(self):
        captured = StringIO()
        sys.stdout, original = captured, sys.stdout
        try:
            with patch(
                "reset_stale_generating.get_db_connection",
                side_effect=RuntimeError("connection refused"),
            ):
                try:
                    main()
                except SystemExit as e:
                    assert e.code == 1

        finally:
            sys.stdout = original

        assert "Error connecting to database:" in captured.getvalue()
