"""Tests for batch script episode creation with seq numbering."""

from app.services.episode_service import EpisodeService


class TestOrchestrateCreateEpisodeRecord:
    """orchestrate._create_episode_record() の新規作成 + seq採番のテスト"""

    def test_existing_episode_does_not_prevent_new_creation(self):
        """同一日付の既存エピソードがあっても新規作成されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        original_id = svc.create_episode(episode_date="2099-06-01", status="completed")

        new_id, seq = _create_episode_record("2099-06-01")
        assert new_id != original_id, "既存エピソードとは別のIDで新規作成されること"
        assert seq == 1, "2本目はseq=1になること"

        ep = svc.get_episode(new_id)
        assert ep["status"] == "generating", "新規作成後は status=generating になること"
        assert ep["seq"] == 1

    def test_first_episode_of_day_gets_seq_0(self):
        """同一日付の既存エピソードがない場合、seq=0で新規作成されること"""
        from app.batch.orchestrate import _create_episode_record

        svc = EpisodeService()
        before = len(svc.get_episode_list())

        new_id, seq = _create_episode_record("2099-07-01")
        assert new_id is not None
        assert seq == 0, "1本目はseq=0になること"

        after = len(svc.get_episode_list())
        assert after == before + 1

        ep = svc.get_episode(new_id)
        assert ep["status"] == "generating"
        assert ep["seq"] == 0

    def test_third_episode_gets_seq_2(self):
        """3本目はseq=2になること（MAX(seq)+1が正しく動作する）"""
        svc = EpisodeService()
        # Use create_radio_episode so seq is correct for each
        svc.create_radio_episode(episode_date="2099-08-01")
        svc.create_radio_episode(episode_date="2099-08-01")

        from app.batch.orchestrate import _create_episode_record
        new_id, seq = _create_episode_record("2099-08-01")
        assert seq == 2, "3本目はseq=2になること"
        ep = svc.get_episode(new_id)
        assert ep["seq"] == 2


class TestCreateRadioEpisode:
    """create_radio_episode の原子性・stale処理テスト"""

    def test_creates_first_episode_with_seq_0(self):
        svc = EpisodeService()
        episode_id, seq = svc.create_radio_episode("2099-09-01")
        ep = svc.get_episode(episode_id)
        assert seq == 0
        assert ep["seq"] == 0
        assert ep["status"] == "generating"
        assert ep["type"] == "radio"

    def test_second_episode_gets_seq_1(self):
        svc = EpisodeService()
        svc.create_radio_episode("2099-09-01")
        _, seq = svc.create_radio_episode("2099-09-01")
        assert seq == 1

    def test_commentary_does_not_affect_seq(self):
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-09-01", type="commentary")
        _, seq = svc.create_radio_episode("2099-09-01")
        assert seq == 0

    def test_resets_stale_generating_episodes(self):
        svc = EpisodeService()
        stale_id, _ = svc.create_radio_episode("2099-09-05")
        _, seq = svc.create_radio_episode("2099-09-05")
        assert seq == 1
        stale = svc.get_episode(stale_id)
        assert stale["status"] == "failed"

class TestSeqNumbering:
    """episode_service の seq 関連メソッドのテスト"""

    def test_count_radio_by_date_returns_correct_count(self):
        svc = EpisodeService()
        assert svc.count_radio_by_date("2099-09-01") == 0

        svc.create_episode(episode_date="2099-09-01", type="radio")
        assert svc.count_radio_by_date("2099-09-01") == 1

        svc.create_episode(episode_date="2099-09-01", type="radio")
        assert svc.count_radio_by_date("2099-09-01") == 2

    def test_commentary_not_counted_in_radio_count(self):
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-09-01", type="radio")
        svc.create_episode(episode_date="2099-09-01", type="commentary")
        assert svc.count_radio_by_date("2099-09-01") == 1

    def test_other_date_not_counted(self):
        svc = EpisodeService()
        svc.create_episode(episode_date="2099-09-01", type="radio")
        svc.create_episode(episode_date="2099-09-02", type="radio")
        assert svc.count_radio_by_date("2099-09-01") == 1
        assert svc.count_radio_by_date("2099-09-02") == 1


class TestBuildRadioTitle:
    """build_radio_title のテスト"""

    def test_seq_0_format(self):
        from app.services.episode_service import build_radio_title
        result = build_radio_title("テックニュース", "2026-06-27", 0)
        assert result == "テックニュース 2026.06.27"

    def test_seq_1_format(self):
        from app.services.episode_service import build_radio_title
        result = build_radio_title("テックニュース", "2026-06-27", 1)
        assert result == "テックニュース 2026.06.27-01"

    def test_seq_2_format(self):
        from app.services.episode_service import build_radio_title
        result = build_radio_title("テックニュース", "2026-06-27", 2)
        assert result == "テックニュース 2026.06.27-02"

    def test_news_no_tonari_seq_0(self):
        from app.services.episode_service import build_radio_title
        result = build_radio_title("ニュースのとなり", "2026-06-27", 0)
        assert result == "ニュースのとなり 2026.06.27"

    def test_news_no_tonari_seq_1(self):
        from app.services.episode_service import build_radio_title
        result = build_radio_title("ニュースのとなり", "2026-06-27", 1)
        assert result == "ニュースのとなり 2026.06.27-01"


class TestOverrideScriptTitle:
    """override_script_title のテスト"""

    def test_override_updates_title_in_script_json(self, tmp_path):
        import json
        from app.services.episode_service import override_script_title

        script_path = tmp_path / "script.json"
        script_data = {"title": "オリジナルタイトル", "lines": []}
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f)

        override_script_title(str(script_path), "テックニュース", "2026-06-27", 0)

        with open(script_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result["title"] == "テックニュース 2026.06.27"

    def test_override_with_seq_1(self, tmp_path):
        import json
        from app.services.episode_service import override_script_title

        script_path = tmp_path / "script.json"
        script_data = {"title": "オリジナル", "lines": [{"text": "hello"}]}
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script_data, f)

        override_script_title(str(script_path), "ニュースのとなり", "2026-06-27", 1)

        with open(script_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        assert result["title"] == "ニュースのとなり 2026.06.27-01"
        # Other fields unchanged
        assert len(result["lines"]) == 1


class TestJingleDetection:
    """build_episode のジングル判定テスト（統合後の jingle_paths_for_title）"""

    class FakeSettings:
        jingle_news_no_tonari_opening_path = "/path/news_no_tonari_opening.wav"
        jingle_news_no_tonari_ending_path = "/path/news_no_tonari_ending.wav"
        jingle_opening_path = "/path/default_opening.wav"
        jingle_ending_path = "/path/default_ending.wav"

    def test_exact_title_still_matches(self):
        from app.batch.build_episode import _get_opening_path, jingle_paths_for_title
        script = {"title": "ニュースのとなり"}
        assert _get_opening_path(script, self.FakeSettings()) == "/path/news_no_tonari_opening.wav"
        opening, ending = jingle_paths_for_title(script, self.FakeSettings())
        assert opening == "/path/news_no_tonari_opening.wav"
        assert ending == "/path/news_no_tonari_ending.wav"

    def test_new_format_title_starts_with_matches(self):
        from app.batch.build_episode import _get_opening_path, jingle_paths_for_title
        script = {"title": "ニュースのとなり 2026.06.27"}
        assert _get_opening_path(script, self.FakeSettings()) == "/path/news_no_tonari_opening.wav"
        opening, ending = jingle_paths_for_title(script, self.FakeSettings())
        assert opening == "/path/news_no_tonari_opening.wav"
        assert ending == "/path/news_no_tonari_ending.wav"

    def test_new_format_with_seq_matches(self):
        from app.batch.build_episode import _get_opening_path, jingle_paths_for_title
        script = {"title": "ニュースのとなり 2026.06.27-01"}
        assert _get_opening_path(script, self.FakeSettings()) == "/path/news_no_tonari_opening.wav"
        opening, ending = jingle_paths_for_title(script, self.FakeSettings())
        assert opening == "/path/news_no_tonari_opening.wav"
        assert ending == "/path/news_no_tonari_ending.wav"

    def test_tech_news_uses_default_jingle(self):
        from app.batch.build_episode import _get_opening_path, jingle_paths_for_title
        script = {"title": "テックニュース 2026.06.27"}
        assert _get_opening_path(script, self.FakeSettings()) == "/path/default_opening.wav"
        opening, ending = jingle_paths_for_title(script, self.FakeSettings())
        assert opening == "/path/default_opening.wav"
        assert ending == "/path/default_ending.wav"

    def test_tech_news_with_seq_uses_default_jingle(self):
        from app.batch.build_episode import _get_opening_path, jingle_paths_for_title
        script = {"title": "テックニュース 2026.06.27-02"}
        assert _get_opening_path(script, self.FakeSettings()) == "/path/default_opening.wav"
        opening, ending = jingle_paths_for_title(script, self.FakeSettings())
        assert opening == "/path/default_opening.wav"
        assert ending == "/path/default_ending.wav"
