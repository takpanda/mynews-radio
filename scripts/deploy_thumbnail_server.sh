#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="${SCRIPT_DIR}/../tools/thumbnail-server/thumbnail_server.py"

HOST="${THUMBNAIL_SERVER_HOST:-192.168.1.102}"
USER="${THUMBNAIL_SERVER_USER:-tak}"
REMOTE_DIR="${THUMBNAIL_SERVER_DIR:-/Users/tak/apps/qwen-thumb-server}"
PORT="${THUMBNAIL_SERVER_PORT:-8501}"
HEALTH_URL="${THUMBNAIL_SERVER_URL:-http://${HOST}:${PORT}/busy}"
PYTHON_BIN="${THUMBNAIL_SERVER_PYTHON:-/Users/tak/.qwen-venv/bin/python}"
HEALTH_CONNECT_TIMEOUT="${THUMBNAIL_HEALTH_CONNECT_TIMEOUT:-2}"
HEALTH_MAX_TIME="${THUMBNAIL_HEALTH_MAX_TIME:-3}"
SSH_TARGET="${USER}@${HOST}"

if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [host]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  HOST="$1"
  SSH_TARGET="${USER}@${HOST}"
  if [[ -z "${THUMBNAIL_SERVER_URL:-}" ]]; then
    HEALTH_URL="http://${HOST}:${PORT}/busy"
  fi
fi
if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "Thumbnail server source not found: $SOURCE_FILE" >&2
  exit 1
fi

BACKUP_NAME="thumbnail_server.py.$(date +%Y%m%d%H%M%S).bak"
printf -v REMOTE_DIR_Q '%q' "$REMOTE_DIR"
printf -v BACKUP_NAME_Q '%q' "$BACKUP_NAME"
printf -v PYTHON_BIN_Q '%q' "$PYTHON_BIN"

echo "Checking Python dependencies on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "${PYTHON_BIN_Q} -c 'import importlib.util, sys; modules = (\"PIL\", \"fastapi\", \"httpx\", \"qwenimage2mlx\"); missing = [name for name in modules if importlib.util.find_spec(name) is None]; print(\"Missing required Python modules: \" + \", \".join(missing), file=sys.stderr) if missing else print(\"Python dependencies: OK\"); sys.exit(bool(missing))'"

echo "Backing up existing server source on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "mkdir -p ${REMOTE_DIR_Q}/backups && if [[ -f ${REMOTE_DIR_Q}/thumbnail_server.py ]]; then cp ${REMOTE_DIR_Q}/thumbnail_server.py ${REMOTE_DIR_Q}/backups/${BACKUP_NAME_Q}; fi"

echo "Synchronizing thumbnail server source..."
rsync -av "$SOURCE_FILE" "${SSH_TARGET}:${REMOTE_DIR}/thumbnail_server.py"

printf -v PORT_Q '%q' "$PORT"
echo "Restarting thumbnail server on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "cd ${REMOTE_DIR_Q} && (pkill -f '[t]humbnail_server.py' || true) && sleep 1 && nohup env PORT=${PORT_Q} ${PYTHON_BIN_Q} thumbnail_server.py > thumbnail_server.log 2>&1 < /dev/null &"

echo "Checking ${HEALTH_URL}..."
for attempt in {1..20}; do
  if curl --connect-timeout "$HEALTH_CONNECT_TIMEOUT" --max-time "$HEALTH_MAX_TIME" --fail --silent --show-error "$HEALTH_URL"; then
    echo
    echo "Thumbnail server is responding. Backup: ${REMOTE_DIR}/backups/${BACKUP_NAME}"
    exit 0
  fi
  sleep 1
done

echo "Thumbnail server did not respond at ${HEALTH_URL}. Check the remote log: ${REMOTE_DIR}/thumbnail_server.log" >&2
exit 1
