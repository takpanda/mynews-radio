#!/usr/bin/env bash
set -e

# Load CRON_SCHEDULE from env (default: 6:00 AM JST = 0 6 * * * in UTC+9)
# Format: minute hour day-of-month month day-of-week
SCHEDULE="${CRON_SCHEDULE:-'0 21 * * *'}"

echo "[entrypoint] CRON_SCHEDULE=$SCHEDULE (crontab timezone offset applied for JST)"

# Set up /app/data/logs/batch directory
mkdir -p /app/data/logs/batch

# Write crontab (cron uses container TZ)
(cat <<'CRONTAB_HEADER'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CRONTAB_HEADER
) > /etc/cron.d/mynews-batch

# Write environment variables for cron jobs
# Note: only non-empty values are written; empty/undefined vars are skipped.
for _var in OLLAMA_BASE_URL OLLAMA_MODEL DGX_HOST \
    VOICEVOX_BASE_URL VOICEVOX_SPEAKER_MALE VOICEVOX_SPEAKER_FEMALE \
    AIVISPEECH_BASE_URL AIVISPEECH_SPEAKER_MALE AIVISPEECH_SPEAKER_FEMALE \
    API_KEY CORS_ORIGINS; do
  _val="${!_var:-}"
  if [ -n "$_val" ]; then
    printf '%s=%s\n' "$_var" "$_val" >> /etc/cron.d/mynews-batch
  fi
done

echo "$SCHEDULE cd /app && python3 /app/app/batch/run_daily.py >> /app/data/logs/crontab.log 2>&1" >> /etc/cron.d/mynews-batch
chmod 0644 /etc/cron.d/mynews-batch

# Install the crontab
crontab /etc/cron.d/mynews-batch
echo "[entrypoint] crontab installed (API_KEY masked):"
crontab -l | grep -v '^API_KEY='

# Start cron daemon (avoid duplicate startup)
if ! pgrep -x "cron" >/dev/null 2>&1; then
    cron
    echo "[entrypoint] cron started (pid=$(pgrep cron))"
else
    echo "[entrypoint] cron already running, skipping start"
fi

# Ensure the cron log file exists and stream it to Docker logs.
mkdir -p /app/data/logs
touch /app/data/logs/crontab.log
tail -F /app/data/logs/crontab.log &

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
