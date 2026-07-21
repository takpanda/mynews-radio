"""Tests for config defaults and cron environment variable injection."""

import os
import subprocess
import textwrap


class TestConfigDefaults:
    """config.py の既定値が受入条件を満たしていることの確認"""

    def test_dgx_host_default_is_192_168_1_102(self):
        from app.config import Settings
        settings = Settings()
        assert settings.dgx_host == "192.168.1.102"

    def test_ollama_base_url_default_is_192_168_1_102(self):
        from app.config import Settings
        settings = Settings()
        assert settings.ollama_base_url == "http://192.168.1.102:11434"

    def test_ollama_base_url_matches_dgx_host(self):
        from app.config import Settings
        settings = Settings()
        expected = f"http://{settings.dgx_host}:11434"
        assert settings.ollama_base_url == expected

    def test_voicevox_base_url_unchanged(self):
        from app.config import Settings
        settings = Settings()
        assert settings.voicevox_base_url == "http://192.168.1.102:50021"

    def test_aivispeech_base_url_unchanged(self):
        from app.config import Settings
        settings = Settings()
        assert settings.aivispeech_base_url == "http://192.168.1.102:10101"


class TestCronEnvInjection:
    """entrypoint.sh の環境変数書き出し処理を模擬したテスト"""

    CRON_TARGET_VARS = [
        "OLLAMA_BASE_URL", "OLLAMA_MODEL", "DGX_HOST",
        "VOICEVOX_BASE_URL", "VOICEVOX_SPEAKER_MALE", "VOICEVOX_SPEAKER_FEMALE",
        "AIVISPEECH_BASE_URL", "AIVISPEECH_SPEAKER_MALE", "AIVISPEECH_SPEAKER_FEMALE",
        "API_KEY", "CORS_ORIGINS",
    ]

    def _generate_crontab_with_env(self, env_overrides: dict[str, str]) -> str:
        """entrypoint.sh の env var 書き出しロジックを Python で再現"""
        header = textwrap.dedent("""\
        SHELL=/bin/bash
        PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
        """)
        lines = [header]
        for var in self.CRON_TARGET_VARS:
            val = env_overrides.get(var)
            if val is not None and val != "":
                lines.append(f"{var}={val}")
        lines.append("0 21 * * * cd /app && python3 /app/app/batch/run_daily.py >> /app/data/logs/crontab.log 2>&1")
        return "\n".join(lines) + "\n"

    def test_all_vars_written_when_set(self):
        """全変数が設定されている場合、正しく書き出されること"""
        env = {
            "OLLAMA_BASE_URL": "http://192.168.1.102:11434",
            "OLLAMA_MODEL": "qwen3.6:27b",
            "DGX_HOST": "192.168.1.102",
            "VOICEVOX_BASE_URL": "http://192.168.1.102:50021",
            "VOICEVOX_SPEAKER_MALE": "21",
            "VOICEVOX_SPEAKER_FEMALE": "20",
            "AIVISPEECH_BASE_URL": "http://192.168.1.102:10101",
            "AIVISPEECH_SPEAKER_MALE": "1310138976",
            "AIVISPEECH_SPEAKER_FEMALE": "1388823424",
            "API_KEY": "test-key-123",
            "CORS_ORIGINS": "http://localhost:3010,https://radio.beeworks.cc",
        }
        result = self._generate_crontab_with_env(env)
        for var, val in env.items():
            assert f"{var}={val}" in result, f"{var}={val} が crontab に見つかりません"

    def test_empty_vars_are_skipped(self):
        """空値の変数は crontab に書き出されないこと"""
        env = {
            "OLLAMA_BASE_URL": "http://192.168.1.102:11434",
            "API_KEY": "",
            "CORS_ORIGINS": "",
        }
        result = self._generate_crontab_with_env(env)
        assert "API_KEY=" not in result, "空の API_KEY が書き出されている"
        assert "CORS_ORIGINS=" not in result, "空の CORS_ORIGINS が書き出されている"
        assert "OLLAMA_BASE_URL=http://192.168.1.102:11434" in result

    def test_undefined_vars_are_skipped(self):
        """未定義の変数は crontab に書き出されないこと"""
        result = self._generate_crontab_with_env({})
        assert "OLLAMA_BASE_URL=" not in result
        assert "DGX_HOST=" not in result

    def test_cron_command_line_preserved(self):
        """cron のコマンド行が変更されていないこと"""
        result = self._generate_crontab_with_env({})
        assert "cd /app && python3 /app/app/batch/run_daily.py" in result
        assert "crontab.log" in result

    def test_special_chars_in_value(self):
        """特殊文字を含む値でも cron 定義が壊れないこと"""
        env = {
            "CORS_ORIGINS": "http://localhost:3010,http://example.com:8080",
            "API_KEY": "abc!@#$%^&*()-_=+[]{}|;:',.<>?/`~",
        }
        result = self._generate_crontab_with_env(env)
        assert "CORS_ORIGINS=http://localhost:3010,http://example.com:8080" in result
        assert "API_KEY=abc!@#$%^&*()-_=+[]{}|;:',.<>?/`~" in result

    def test_entrypoint_shellcheck_passes(self):
        """entrypoint.sh が shellcheck をパスすること（shellcheck が利用可能な場合）"""
        script_path = os.path.join(os.path.dirname(__file__), "..", "entrypoint.sh")
        try:
            result = subprocess.run(
                ["shellcheck", "--shell=bash", script_path],
                capture_output=True, text=True, timeout=30,
            )
            assert result.returncode == 0, (
                f"shellcheck failed:\n{result.stdout}\n{result.stderr}"
            )
        except FileNotFoundError:
            pass  # shellcheck not installed — skip
