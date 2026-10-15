# Thumbnail server

`thumbnail_server.py` is the current source copied from `/Users/tak/apps/qwen-thumb-server/thumbnail_server.py` on `192.168.1.102`.
The source is kept unchanged. The server listens on port `8501` by default and reads `PORT` when overridden.

## Deployment

From the repository root, run:

```bash
bash scripts/deploy_thumbnail_server.sh
```

The script saves a timestamped copy of the existing remote source under
`/Users/tak/apps/qwen-thumb-server/backups/`, syncs this repository's source,
stops the existing `thumbnail_server.py` process, starts it with `nohup`, and
checks `GET /busy` up to 20 times.

The default SSH target is `tak@192.168.1.102` and the default interpreter is
`/Users/tak/.qwen-venv/bin/python`. Before taking a backup or stopping the
service, the script checks that this interpreter can find `PIL`, `fastapi`,
`httpx`, and `qwenimage2mlx`. If a dependency is missing, it exits before
stopping the existing process. Override the target, paths, Python interpreter,
and health-check timeouts with environment variables, or pass a host as the
first argument:

```bash
THUMBNAIL_SERVER_USER=tak \
THUMBNAIL_SERVER_HOST=192.168.1.102 \
THUMBNAIL_SERVER_DIR=/Users/tak/apps/qwen-thumb-server \
THUMBNAIL_SERVER_PORT=8501 \
THUMBNAIL_SERVER_URL=http://192.168.1.102:8501/busy \
THUMBNAIL_SERVER_PYTHON=/Users/tak/.qwen-venv/bin/python \
THUMBNAIL_HEALTH_CONNECT_TIMEOUT=2 \
THUMBNAIL_HEALTH_MAX_TIME=3 \
bash scripts/deploy_thumbnail_server.sh
```

The deploy script requires SSH key-based access, `rsync` on the local machine,
the configured Python interpreter and dependencies on the remote Mac, and
`curl` on the machine running the script. Each `/busy` request has a default
2-second connection timeout and 3-second total timeout; the timeout values can
be changed with `THUMBNAIL_HEALTH_CONNECT_TIMEOUT` and
`THUMBNAIL_HEALTH_MAX_TIME`. The script only deploys `thumbnail_server.py`; it
does not install Python dependencies.

## Manual start

On the Mac mini, run from the server directory:

```bash
cd /Users/tak/apps/qwen-thumb-server
nohup /Users/tak/.qwen-venv/bin/python thumbnail_server.py > thumbnail_server.log 2>&1 < /dev/null &
```

To check the service manually:

```bash
curl --fail http://192.168.1.102:8501/busy
```
