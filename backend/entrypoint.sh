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

echo "$SCHEDULE cron /app/app/batch/run_daily.py >> /app/data/logs/crontab.log 2>&1" >> /etc/cron.d/mynews-batch
chmod 0644 /etc/cron.d/mynews-batch

# Install the crontab
crontab /etc/cron.d/mynews-batch
echo "[entrypoint] crontab installed:"
crontab -l

# Start cron daemon (skip if already running to avoid PID lock conflict)
if pgrep cron > /dev/null 2>&1; then
    echo "[entrypoint] cron already running, skipping start"
else
    cron
    echo "[entrypoint] cron started"
fi

# Ensure the cron log file exists and stream it to Docker logs.
mkdir -p /app/data/logs
touch /app/data/logs/crontab.log
tail -F /app/data/logs/crontab.log &

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
