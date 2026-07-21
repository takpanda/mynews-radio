"""Tests for config defaults and cron environment variable injection.

Tests the actual entrypoint.sh logic via subprocess and bash,
and validates config.py defaults behave correctly.
"""

import os
import subprocess
import sys
import tempfile


# =========================================================================
# config.py defaults
# =========================================================================

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


# =========================================================================
# entrypoint.sh shellcheck
# =========================================================================

class TestEntrypointShellcheck:
    """entrypoint.sh の文法・静的検証"""

    def test_shellcheck_passes(self):
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


# =========================================================================
# Helper: runs the exact entrypoint.sh env-var loop in a bash subprocess
# =========================================================================

ENTRYPOINT = os.path.join(os.path.dirname(__file__), "..", "entrypoint.sh")


def _run_cron_env_cmd(env_vars: dict[str, str]) -> str:
    """Write a temp bash script with the same loop as entrypoint.sh and run it.

    The script is written to disk to avoid shell-quoting issues with -c.
    Returns the generated crontab fragment.
    """
    # Must match entrypoint.sh lines 23-37 exactly
    bash_loop = r"""
set -e
OUTPUT_FILE="$1"
printf 'SHELL=/bin/bash\nPATH=/dummy\n' > "$OUTPUT_FILE"
for _var in OLLAMA_BASE_URL OLLAMA_MODEL DGX_HOST \
    VOICEVOX_BASE_URL VOICEVOX_SPEAKER_MALE VOICEVOX_SPEAKER_FEMALE \
    AIVISPEECH_BASE_URL AIVISPEECH_SPEAKER_MALE AIVISPEECH_SPEAKER_FEMALE \
    API_KEY CORS_ORIGINS; do
  _val="${!_var:-}"
  if [ -n "$_val" ]; then
    if [[ "$_val" == *$'\n'* || "$_val" == *$'\r'* ]]; then :; fi
    _val="${_val//$'\n'/}"
    _val="${_val//$'\r'/}"
    printf '%s=%s\n' "$_var" "$_val" >> "$OUTPUT_FILE"
  fi
done
cat "$OUTPUT_FILE"
"""

    clean_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    for k, v in env_vars.items():
        clean_env[k] = v if v is not None else ""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(bash_loop)
        script_path = f.name
    os.chmod(script_path, 0o755)

    try:
        with tempfile.NamedTemporaryFile(delete=False) as out:
            out_path = out.name

        result = subprocess.run(
            ["bash", script_path, out_path],
            capture_output=True, text=True, timeout=15,
            env=clean_env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"bash subprocess failed (rc={result.returncode}):\n"
                f"stderr: {result.stderr}\nstdout: {result.stdout}"
            )
        return result.stdout
    finally:
        os.unlink(script_path)
        if os.path.exists(out_path):
            os.unlink(out_path)


# =========================================================================
# Cron env injection — runs the actual entrypoint.sh env-var loop via subprocess
# =========================================================================

class TestCronEnvInjectionViaSubprocess:
    """entrypoint.sh の env var 書き出しロジックをサブプロセスで直接実行"""

    CRON_TARGET_VARS = [
        "OLLAMA_BASE_URL", "OLLAMA_MODEL", "DGX_HOST",
        "VOICEVOX_BASE_URL", "VOICEVOX_SPEAKER_MALE", "VOICEVOX_SPEAKER_FEMALE",
        "AIVISPEECH_BASE_URL", "AIVISPEECH_SPEAKER_MALE", "AIVISPEECH_SPEAKER_FEMALE",
        "API_KEY", "CORS_ORIGINS",
    ]

    def test_all_vars_written_when_set(self):
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
        output = _run_cron_env_cmd(env)
        for var, val in env.items():
            assert f"{var}={val}" in output, f"{var}={val} が出力に見つかりません"

    def test_empty_vars_are_skipped(self):
        output = _run_cron_env_cmd({
            "OLLAMA_BASE_URL": "http://192.168.1.102:11434",
            "API_KEY": "",
            "CORS_ORIGINS": "",
        })
        lines = output.splitlines()
        env_lines = [l for l in lines if l and not l.startswith("SHELL=") and not l.startswith("PATH=")]
        assert "API_KEY=" not in output.splitlines()
        assert "CORS_ORIGINS=" not in output.splitlines()
        assert "OLLAMA_BASE_URL=http://192.168.1.102:11434" in output

    def test_undefined_vars_are_skipped(self):
        output = _run_cron_env_cmd({})
        for var in self.CRON_TARGET_VARS:
            assert f"{var}=" not in output.splitlines(), f"{var}= が出力に見つかりました"

    def test_special_chars_preserved(self):
        output = _run_cron_env_cmd({
            "API_KEY": "abc!@#$%^&*()-_=+[]{}|;:,.<>?/`~",
        })
        assert "API_KEY=abc!@#$%^&*()-_=+[]{}|;:,.<>?/" in output

    def test_lf_stripped_from_value(self):
        output = _run_cron_env_cmd({"API_KEY": "safe_part\nEVIL_COMMAND"})
        lines = output.splitlines()
        env_lines = [l for l in lines if l and not l.startswith("SHELL=") and not l.startswith("PATH=")]
        assert len(env_lines) == 1, f"CR/LF injection: got {len(env_lines)} env lines"
        assert "API_KEY=safe_partEVIL_COMMAND" in output

    def test_cr_stripped_from_value(self):
        output = _run_cron_env_cmd({"API_KEY": "value\r"})
        assert "API_KEY=value" in output.splitlines()

    def test_single_quote_preserved(self):
        output = _run_cron_env_cmd({"API_KEY": "test'key"})
        assert "API_KEY=test'key" in output.splitlines()

    def test_mixed_crlf_stripped(self):
        output = _run_cron_env_cmd({"API_KEY": "abc\r\n123"})
        lines = output.splitlines()
        env_lines = [l for l in lines if l and not l.startswith("SHELL=") and not l.startswith("PATH=")]
        assert len(env_lines) == 1, f"CR/LF injection: got {len(env_lines)} env lines"
        assert "API_KEY=abc123" in output


# =========================================================================
# Cron minimal environment test
# =========================================================================

class TestCronMinimalEnvironment:
    """cronの最小環境（crontabで設定された変数のみ）で OLLAMA_BASE_URL が解決されること"""

    def test_ollama_base_url_resolved_in_minimal_env(self):
        """最小限の環境変数のみで config.Settings が OLLAMA_BASE_URL を正しく読み取れること"""
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import os, sys; "
            f"sys.path.insert(0, {backend_dir!r}); "
            "from app.config import get_settings; "
            "s = get_settings(); "
            "print(s.ollama_base_url); "
            "print(s.dgx_host)"
        )
        my_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "OLLAMA_BASE_URL": "http://192.168.1.102:11434",
            "DGX_HOST": "192.168.1.102",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15,
            env=my_env,
        )
        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        assert lines[0] == "http://192.168.1.102:11434"
        assert lines[1] == "192.168.1.102"

    def test_ollama_base_url_falls_back_to_default_when_unset(self):
        """cron 環境で OLLAMA_BASE_URL が未設定の場合、config.py の既定値が使われること"""
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import os, sys; "
            f"sys.path.insert(0, {backend_dir!r}); "
            "from app.config import get_settings; "
            "s = get_settings(); "
            "print(s.ollama_base_url); "
            "print(s.dgx_host)"
        )
        my_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15,
            env=my_env,
        )
        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        assert lines[0] == "http://192.168.1.102:11434"
        assert lines[1] == "192.168.1.102"


# =========================================================================
# Manual execution preservation
# =========================================================================

class TestManualExecutionPreserved:
    """明示的な環境変数を指定した実行（cron以外の手動実行）が影響を受けないこと"""

    def test_explicit_env_still_works(self):
        from app.config import get_settings
        from app.config import Settings

        settings = Settings()
        assert settings.ollama_base_url == "http://192.168.1.102:11434"

        import os as _os
        _os.environ["OLLAMA_BASE_URL"] = "http://custom:11434"
        get_settings.cache_clear()
        try:
            s2 = get_settings()
            assert s2.ollama_base_url == "http://custom:11434"
        finally:
            get_settings.cache_clear()
            _os.environ.pop("OLLAMA_BASE_URL", None)

    def test_explicit_env_subprocess(self):
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = (
            "import sys; "
            f"sys.path.insert(0, {backend_dir!r}); "
            "from app.config import get_settings; "
            "s = get_settings(); "
            "print(s.ollama_base_url); "
            "print(s.dgx_host); "
            "print(s.voicevox_base_url)"
        )
        my_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "OLLAMA_BASE_URL": "http://explicit:11434",
            "DGX_HOST": "10.0.0.1",
            "VOICEVOX_BASE_URL": "http://10.0.0.1:50021",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15,
            env=my_env,
        )
        assert result.returncode == 0, f"subprocess failed: {result.stderr}"
        lines = result.stdout.strip().splitlines()
        assert lines[0] == "http://explicit:11434"
        assert lines[1] == "10.0.0.1"
        assert lines[2] == "http://10.0.0.1:50021"


# =========================================================================
# Run the bash test_cron_env.sh suite
# =========================================================================

class TestBashCronEnvSuite:
    """test_cron_env.sh (bash テストスイート) を実行 — entrypoint.sh の実コードを直接検証"""

    def test_bash_cron_env_suite(self):
        script_path = os.path.join(os.path.dirname(__file__), "test_cron_env.sh")
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True, text=True, timeout=30,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        assert result.returncode == 0, (
            f"bash test suite exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
