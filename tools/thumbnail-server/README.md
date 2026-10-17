# Thumbnail server

`thumbnail_server.py` in this repository is the deployment source for `/Users/tak/apps/qwen-thumb-server/thumbnail_server.py` on `192.168.1.102`.
Keep service changes in this file so the deploy script preserves them. Thumbnail requests enqueue immediately; the worker derives the prompt and renders the image. The server listens on port `8501` by default and reads `PORT` when overridden.

## Deployment

From the repository root, run:

```bash
bash scripts/deploy_thumbnail_server.sh
```

The script saves a timestamped copy of the existing remote source under
`/Users/tak/apps/qwen-thumb-server/backups/`, syncs this repository's source
and LaunchAgent definition, waits for `GET /busy` to report idle, then restarts
the service through `launchctl`. The LaunchAgent uses `RunAtLoad` and `KeepAlive`
so launchd starts it at login and restarts it after an unexpected exit. Its
stdout and stderr are written to `server.log` in the service directory.

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
`THUMBNAIL_HEALTH_MAX_TIME`. The script waits up to 600 seconds by default for
`/busy` to report `{"busy":0}` before restarting; set
`THUMBNAIL_DEPLOY_IDLE_TIMEOUT` to change that limit. If the service remains
busy or `/busy` cannot be reached, the script exits without stopping the
running process. The script only deploys `thumbnail_server.py`; it does not
install Python dependencies. Because this is a LaunchAgent, it starts when the
`tak` user logs in; a LaunchAgent does not start before a GUI login. Confirm
the host's login policy before relying on it after a reboot.

## Service inspection

On the Mac mini, inspect the loaded service and process with:

```bash
launchctl list | grep com.mynews.qwen-thumb-server
pgrep -fl thumbnail_server.py
```

The user LaunchAgent plist is installed at
`~/Library/LaunchAgents/com.mynews.qwen-thumb-server.plist`. To check the API:

```bash
curl --fail http://192.168.1.102:8501/busy
```
