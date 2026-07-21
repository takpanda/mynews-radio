#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2086,SC2120
#
# Test entrypoint.sh environment variable injection logic.
# Runs the EXACT same shell code as entrypoint.sh against a temp file.
set -euo pipefail

PASS=0
FAIL=0
TEST_NUM=0

ALL_VARS=(OLLAMA_BASE_URL OLLAMA_MODEL DGX_HOST \
          VOICEVOX_BASE_URL VOICEVOX_SPEAKER_MALE VOICEVOX_SPEAKER_FEMALE \
          AIVISPEECH_BASE_URL AIVISPEECH_SPEAKER_MALE AIVISPEECH_SPEAKER_FEMALE \
          API_KEY CORS_ORIGINS)

_cleanup_env() {
  for _v in "${ALL_VARS[@]}"; do unset "$_v" 2>/dev/null || true; done
}

_header() {
  printf 'SHELL=/bin/bash\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n'
}

# The exact env-var-writing loop from entrypoint.sh (writes to $OUTPUT_FILE).
_write_env() {
  local _var _val
  for _var in "${ALL_VARS[@]}"; do
    _val="${!_var:-}"
    if [ -n "$_val" ]; then
      if [[ "$_val" == *$'\n'* || "$_val" == *$'\r'* ]]; then
        :  # warning skipped in test
      fi
      _val="${_val//$'\n'/}"
      _val="${_val//$'\r'/}"
      printf '%s=%s\n' "$_var" "$_val" >> "$OUTPUT_FILE"
    fi
  done
}

_set_env() {
  _cleanup_env
  while [ $# -ge 2 ]; do
    export "$1=$2"
    shift 2
  done
}

begin_test() {
  _cleanup_env
  OUTPUT_FILE=$(mktemp)
  _header > "$OUTPUT_FILE"
}

end_test() {
  rm -f "$OUTPUT_FILE"
}

check() {
  local desc="$1"
  TEST_NUM=$((TEST_NUM + 1))
  shift
  if eval "$@"; then
    PASS=$((PASS + 1))
    echo "ok $TEST_NUM - $desc"
  else
    FAIL=$((FAIL + 1))
    echo "not ok $TEST_NUM - $desc"
    echo "# --- $OUTPUT_FILE ---"
    cat -A "$OUTPUT_FILE" | sed 's/^/# /'
  fi
}


# =========================================================================
# Test 1: all vars written when set
# =========================================================================
begin_test
_set_env \
  OLLAMA_BASE_URL http://192.168.1.102:11434 \
  OLLAMA_MODEL qwen3.6:27b \
  DGX_HOST 192.168.1.102 \
  VOICEVOX_BASE_URL http://192.168.1.102:50021 \
  VOICEVOX_SPEAKER_MALE 21 \
  VOICEVOX_SPEAKER_FEMALE 20 \
  AIVISPEECH_BASE_URL http://192.168.1.102:10101 \
  AIVISPEECH_SPEAKER_MALE 1310138976 \
  AIVISPEECH_SPEAKER_FEMALE 1388823424 \
  API_KEY test-key-123 \
  CORS_ORIGINS "http://localhost:3010,https://radio.beeworks.cc"
_write_env
check "all vars written when set" \
  "grep -q '^OLLAMA_BASE_URL=http://192.168.1.102:11434' \"\$OUTPUT_FILE\" && \
   grep -q '^OLLAMA_MODEL=qwen3.6:27b' \"\$OUTPUT_FILE\" && \
   grep -q '^DGX_HOST=192.168.1.102' \"\$OUTPUT_FILE\" && \
   grep -q '^API_KEY=test-key-123' \"\$OUTPUT_FILE\" && \
   grep -q '^CORS_ORIGINS=http://localhost:3010,https://radio.beeworks.cc' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 2: empty vars are skipped
# =========================================================================
begin_test
_set_env \
  OLLAMA_BASE_URL http://192.168.1.102:11434 \
  API_KEY "" \
  CORS_ORIGINS ""
_write_env
check "empty vars skipped" \
  "! grep -q '^API_KEY=' \"\$OUTPUT_FILE\" && \
   ! grep -q '^CORS_ORIGINS=' \"\$OUTPUT_FILE\" && \
   grep -q '^OLLAMA_BASE_URL=' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 3: undefined vars skipped
# =========================================================================
begin_test
_set_env
_write_env
check "undefined vars skipped" \
  "! grep -q '^OLLAMA_BASE_URL=' \"\$OUTPUT_FILE\" && \
   ! grep -q '^DGX_HOST=' \"\$OUTPUT_FILE\" && \
   ! grep -q '^API_KEY=' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 4: whitespace in values preserved
# =========================================================================
begin_test
_set_env CORS_ORIGINS "http://localhost:3010, http://example.com:8080"
_write_env
check "whitespace in values preserved" \
  "grep -q 'CORS_ORIGINS=http://localhost:3010, http://example.com:8080' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 5: special characters in values preserved (grep -F)
# =========================================================================
begin_test
_set_env API_KEY 'abc!@#$%^&*()-_=+[]{}|;:,.<>?/`~'
_write_env
check "special characters preserved" \
  "grep -qF 'API_KEY=abc!@#\$%^&*()-_=+[]{}|;:,.<>?/\`~' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 6: LF (\\n) stripped from values (injection prevention)
# =========================================================================
begin_test
_val_with_lf=$(printf 'safe_part\nEVIL_COMMAND')
_set_env API_KEY "$_val_with_lf"
_write_env
check "LF stripped, no injection" \
  "grep -q '^API_KEY=safe_partEVIL_COMMAND' \"\$OUTPUT_FILE\" && \
   [ \"\$(grep -c '' \"\$OUTPUT_FILE\")\" -eq 3 ]"
end_test


# =========================================================================
# Test 7: CR (\\r) stripped from values
# =========================================================================
begin_test
_val_with_cr=$(printf 'value\r')
_set_env API_KEY "$_val_with_cr"
_write_env
check "CR stripped from value" \
  "grep -q '^API_KEY=value$' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 8: hash (#) in value preserved
# =========================================================================
begin_test
_set_env API_KEY 'abc#def'
_write_env
check "hash in value preserved" \
  "grep -q '^API_KEY=abc#def' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 9: percent (%) in value preserved
# =========================================================================
begin_test
_set_env OLLAMA_MODEL 'qwen3.6:27b%test'
_write_env
check "percent in value preserved" \
  "grep -q '^OLLAMA_MODEL=qwen3.6:27b%test' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 10: single quote in value handled safely
# =========================================================================
begin_test
_set_env API_KEY "test'key"
_write_env
check "single quote in value preserved" \
  "grep -qF \"API_KEY=test'key\" \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 11: mixed CR+LF stripped
# =========================================================================
begin_test
_val_mixed=$(printf 'abc\r\n123')
_set_env API_KEY "$_val_mixed"
_write_env
check "mixed CR+LF stripped" \
  "grep -q '^API_KEY=abc123' \"\$OUTPUT_FILE\" && \
   [ \"\$(grep -c '' \"\$OUTPUT_FILE\")\" -eq 3 ]"
end_test


# =========================================================================
# Test 12: CRON_SCHEDULE default has no stray quotes (entrypoint.sh line 6 exact code)
# =========================================================================
begin_test
SCHEDULE="${CRON_SCHEDULE:-0 21 * * *}"
echo "$SCHEDULE" > "$OUTPUT_FILE"
check "CRON_SCHEDULE default has no stray quotes" \
  "grep -q '^0 21 \\* \\* \\*$' \"\$OUTPUT_FILE\" && \
   ! grep -q \"'\" \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 13: CRON_SCHEDULE custom value respected (entrypoint.sh line 6 exact code)
# =========================================================================
begin_test
CRON_SCHEDULE='*/15 * * * *' SCHEDULE="${CRON_SCHEDULE:-0 21 * * *}"
echo "$SCHEDULE" > "$OUTPUT_FILE"
check "CRON_SCHEDULE custom value respected" \
  "grep -q '^*/15 \\* \\* \\* \\*$' \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 14: crontab schedule line format (entrypoint.sh lines 6+39 exact code)
# Generates the full cron schedule line as entrypoint.sh does, verifying
# the first field is a valid cron minute expression (no stray quotes).
# =========================================================================
begin_test
# Simulate entrypoint.sh lines 6 and 39 exactly
_CRON_SCHEDULE="${CRON_SCHEDULE:-0 21 * * *}"
_cron_line="${_CRON_SCHEDULE} cd /app && python3 /app/app/batch/run_daily.py >> /app/data/logs/crontab.log 2>&1"
echo "$_cron_line" > "$OUTPUT_FILE"
check "crontab schedule line format (default) is valid cron" \
  "grep -Eq '^[0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ [0-9*/,-]+ cd /app &&' \"\$OUTPUT_FILE\" && \
   ! grep -q \"'\" \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Test 15: crontab schedule line with custom schedule (entrypoint.sh lines 6+39 exact code)
# =========================================================================
begin_test
CRON_SCHEDULE='30 6 * * 1-5' _CRON_SCHEDULE="${CRON_SCHEDULE:-0 21 * * *}"
_cron_line="${_CRON_SCHEDULE} cd /app && python3 /app/app/batch/run_daily.py >> /app/data/logs/crontab.log 2>&1"
echo "$_cron_line" > "$OUTPUT_FILE"
check "crontab schedule line format (custom weekdays) is valid" \
  "grep -Eq '^30 6 \\* \\* 1-5 cd /app &&' \"\$OUTPUT_FILE\" && \
   ! grep -q \"'\" \"\$OUTPUT_FILE\""
end_test


# =========================================================================
# Summary
# =========================================================================
echo ""
echo "# $TEST_NUM tests, $PASS pass, $FAIL fail"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
