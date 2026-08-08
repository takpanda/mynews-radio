"""BEE-630 QA是正: 記事境界のtransitionが複数行（両MCの短い掛け合い）になっても、
ジングル／無音挿入が境界につき1回だけに保たれることを確認するテスト。
"""
import json

from app.batch.synthesize_voicevox import synthesize_episode


def _mock_synthesize_line(self, text, speaker, output_path, delivery="neutral", kana_text=None):
    with open(output_path, "w") as f:
        f.write("dummy")
    return True


class TestTransitionBlockSingleJingleInsertion:
    def test_two_line_transition_inserts_jingle_once(self, tmp_path, monkeypatch):
        lines = [
            {"text": "ニュース1本文", "section": "news", "speaker": "male", "article_id": 1},
            {"text": "橋渡し発言", "section": "transition", "speaker": "female", "article_id": 2},
            {"text": "短い受け", "section": "transition", "speaker": "male", "article_id": 2},
            {"text": "ニュース2本文", "section": "news", "speaker": "male", "article_id": 2},
        ]
        script = {"title": "テスト", "lines": lines}
        ep_dir = tmp_path / "ep_test"
        ep_dir.mkdir()
        script_path = ep_dir / "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f)

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            _mock_synthesize_line,
        )

        result = synthesize_episode(str(ep_dir), tts_engine="voicevox")
        assert result == 4, "台本の4行すべてが合成成功すること"

        wav_dir = ep_dir / "lines"
        wav_files = sorted(p.name for p in wav_dir.glob("*.wav"))
        # 4行分のWAV + ジングル/無音1個 = 5個（transitionブロックの2行目ではジングルを追加しない）
        assert len(wav_files) == 5, f"ジングルが境界につき1回だけ挿入されること: {wav_files}"

        with open(script_path, "r", encoding="utf-8") as f:
            updated = json.load(f)
        updated_lines = updated["lines"]
        # 001=news1, 002=jingle(行に紐付かない), 003=transition1, 004=transition2, 005=news2
        assert updated_lines[0]["wav_file"] == "001.wav"
        assert updated_lines[1]["wav_file"] == "003.wav"
        assert updated_lines[2]["wav_file"] == "004.wav"
        assert updated_lines[3]["wav_file"] == "005.wav"

    def test_single_line_transition_still_inserts_jingle(self, tmp_path, monkeypatch):
        """discussion直前など1行のみのtransitionでは従来どおり1回挿入される（回帰確認）。"""
        lines = [
            {"text": "ニュース1本文", "section": "news", "speaker": "male", "article_id": 1},
            {"text": "掘り下げます", "section": "transition", "speaker": "female", "article_id": 1},
            {"text": "討論本文", "section": "discussion", "speaker": "male", "article_id": 1},
        ]
        script = {"title": "テスト", "lines": lines}
        ep_dir = tmp_path / "ep_test"
        ep_dir.mkdir()
        script_path = ep_dir / "script.json"
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f)

        monkeypatch.setattr(
            "app.batch.synthesize_voicevox.VoicevoxClient.synthesize_line",
            _mock_synthesize_line,
        )

        result = synthesize_episode(str(ep_dir), tts_engine="voicevox")
        assert result == 3

        wav_dir = ep_dir / "lines"
        wav_files = sorted(p.name for p in wav_dir.glob("*.wav"))
        # 3行分のWAV + ジングル/無音1個 = 4個
        assert len(wav_files) == 4

        with open(script_path, "r", encoding="utf-8") as f:
            updated = json.load(f)
        updated_lines = updated["lines"]
        assert updated_lines[0]["wav_file"] == "001.wav"
        assert updated_lines[1]["wav_file"] == "003.wav"
        assert updated_lines[2]["wav_file"] == "004.wav"
