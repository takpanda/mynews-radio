#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_FILE="${SCRIPT_DIR}/../tools/thumbnail-server/thumbnail_server.py"
WORKFLOW_DIR="${SCRIPT_DIR}/../tools/thumbnail-server/workflows"
PLIST_TEMPLATE="${SCRIPT_DIR}/../tools/thumbnail-server/com.mynews.qwen-thumb-server.plist"

HOST="${THUMBNAIL_SERVER_HOST:-192.168.1.102}"
USER="${THUMBNAIL_SERVER_USER:-tak}"
REMOTE_DIR="${THUMBNAIL_SERVER_DIR:-/Users/tak/apps/qwen-thumb-server}"
PORT="${THUMBNAIL_SERVER_PORT:-8501}"
HEALTH_URL="${THUMBNAIL_SERVER_URL:-http://${HOST}:${PORT}/busy}"
PYTHON_BIN="${THUMBNAIL_SERVER_PYTHON:-/Users/tak/.qwen-venv/bin/python}"
HEALTH_CONNECT_TIMEOUT="${THUMBNAIL_HEALTH_CONNECT_TIMEOUT:-2}"
HEALTH_MAX_TIME="${THUMBNAIL_HEALTH_MAX_TIME:-3}"
IDLE_WAIT_TIMEOUT="${THUMBNAIL_DEPLOY_IDLE_TIMEOUT:-600}"
SSH_TARGET="${USER}@${HOST}"
LABEL="com.mynews.qwen-thumb-server"

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
if [[ ! -f "$SOURCE_FILE" || ! -f "$PLIST_TEMPLATE" || ! -f "${WORKFLOW_DIR}/qwen_image_2_1_turbo_t2i.json" ]]; then
  echo "Thumbnail server source, workflow, or LaunchAgent template not found." >&2
  exit 1
fi
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "THUMBNAIL_SERVER_PORT must be a number." >&2
  exit 2
fi
if ! [[ "$IDLE_WAIT_TIMEOUT" =~ ^[0-9]+$ ]]; then
  echo "THUMBNAIL_DEPLOY_IDLE_TIMEOUT must be a number of seconds." >&2
  exit 2
fi

BACKUP_NAME="thumbnail_server.py.$(date +%Y%m%d%H%M%S).bak"
LOCAL_PLIST="$(mktemp)"
trap 'rm -f "$LOCAL_PLIST"' EXIT
printf -v REMOTE_DIR_Q '%q' "$REMOTE_DIR"
printf -v BACKUP_NAME_Q '%q' "$BACKUP_NAME"
printf -v PYTHON_BIN_Q '%q' "$PYTHON_BIN"
printf -v LABEL_Q '%q' "$LABEL"

python3 - "$PLIST_TEMPLATE" "$LOCAL_PLIST" "$PYTHON_BIN" "${REMOTE_DIR}/thumbnail_server.py" "$PORT" "${REMOTE_DIR}/server.log" <<'PY'
import pathlib
import plistlib
import sys

template_path, output_path, python_bin, server_script, port, log_file = sys.argv[1:]
data = pathlib.Path(template_path).read_text(encoding="utf-8")
for marker, value in {
    "__PYTHON_BIN__": python_bin,
    "__SERVER_SCRIPT__": server_script,
    "__PORT__": port,
    "__LOG_FILE__": log_file,
}.items():
    data = data.replace(marker, value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
plistlib.loads(data.encode("utf-8"))
pathlib.Path(output_path).write_text(data, encoding="utf-8")
PY

echo "Checking Python dependencies on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "${PYTHON_BIN_Q} -c 'import importlib.util, sys; modules = (\"PIL\", \"fastapi\", \"httpx\"); missing = [name for name in modules if importlib.util.find_spec(name) is None]; print(\"Missing required Python modules: \" + \", \".join(missing), file=sys.stderr) if missing else print(\"Python dependencies: OK\"); sys.exit(bool(missing))'"

echo "Backing up existing server source on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "mkdir -p ${REMOTE_DIR_Q}/backups && if [[ -f ${REMOTE_DIR_Q}/thumbnail_server.py ]]; then cp ${REMOTE_DIR_Q}/thumbnail_server.py ${REMOTE_DIR_Q}/backups/${BACKUP_NAME_Q}; fi"

echo "Synchronizing thumbnail server source..."
rsync -av "$SOURCE_FILE" "${SSH_TARGET}:${REMOTE_DIR}/thumbnail_server.py"
echo "Synchronizing ComfyUI workflow..."
ssh "$SSH_TARGET" "mkdir -p ${REMOTE_DIR_Q}/workflows"
rsync -av "${WORKFLOW_DIR}/" "${SSH_TARGET}:${REMOTE_DIR}/workflows/"
echo "Installing the launchd LaunchAgent definition..."
rsync -av "$LOCAL_PLIST" "${SSH_TARGET}:${REMOTE_DIR}/com.mynews.qwen-thumb-server.plist"

echo "Waiting for thumbnail and shared /busy work to become idle..."
idle=0
initial_busy_json="$(curl --connect-timeout "$HEALTH_CONNECT_TIMEOUT" --max-time "$HEALTH_MAX_TIME" --fail --silent "$HEALTH_URL" 2>/dev/null || true)"
if [[ -z "$initial_busy_json" ]]; then
  if ssh "$SSH_TARGET" "pgrep -f '[t]humbnail_server.py' >/dev/null"; then
    echo "The server process is running but ${HEALTH_URL} is unavailable; leaving it untouched." >&2
    exit 1
  fi
  idle=1
fi
for ((attempt = 0; idle == 0 && attempt <= IDLE_WAIT_TIMEOUT; attempt++)); do
  busy_json="$(curl --connect-timeout "$HEALTH_CONNECT_TIMEOUT" --max-time "$HEALTH_MAX_TIME" --fail --silent "$HEALTH_URL" 2>/dev/null || true)"
  if [[ "$busy_json" ]] && python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("busy") == 0 else 1)' "$busy_json" 2>/dev/null; then
    idle=1
    break
  fi
  sleep 1
done
if [[ "$idle" -ne 1 ]]; then
  echo "Thumbnail server did not become idle within ${IDLE_WAIT_TIMEOUT}s; leaving the running service untouched." >&2
  exit 1
fi

echo "Restarting thumbnail server through launchd on ${SSH_TARGET}..."
ssh "$SSH_TARGET" "set -e; uid=\$(id -u); agent_dir=\${HOME}/Library/LaunchAgents; mkdir -p \"\$agent_dir\"; cp ${REMOTE_DIR_Q}/com.mynews.qwen-thumb-server.plist \"\$agent_dir/com.mynews.qwen-thumb-server.plist\"; launchctl bootout gui/\$uid/${LABEL_Q} 2>/dev/null || true; launchctl bootstrap gui/\$uid \"\$agent_dir/com.mynews.qwen-thumb-server.plist\""

echo "Checking ${HEALTH_URL}..."
for attempt in {1..20}; do
  if curl --connect-timeout "$HEALTH_CONNECT_TIMEOUT" --max-time "$HEALTH_MAX_TIME" --fail --silent --show-error "$HEALTH_URL"; then
    echo
    echo "Thumbnail server is responding. Backup: ${REMOTE_DIR}/backups/${BACKUP_NAME}"
    exit 0
  fi
  sleep 1
done

echo "Thumbnail server did not respond at ${HEALTH_URL}. Check the remote log: ${REMOTE_DIR}/server.log" >&2
exit 1
