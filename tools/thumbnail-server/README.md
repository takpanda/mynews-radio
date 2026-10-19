# Thumbnail server

`thumbnail_server.py` in this repository is the deployment source for `/Users/tak/apps/qwen-thumb-server/thumbnail_server.py` on `192.168.1.102`.
Keep service changes and the API workflow in this repository so the deploy script preserves them. Thumbnail requests enqueue immediately; the worker derives the art direction, generates a scene with ComfyUI, then composites and saves the image. The server listens on port `8501` by default and reads `PORT` when overridden.

## ComfyUI scene generation

The service submits the API-format workflow at
`workflows/qwen_image_2_1_turbo_t2i.json` to `POST /prompt`, waits for
`GET /history/{prompt_id}`, and downloads the `SaveImage` result through
`GET /view`. The workflow uses the Qwen-Image 2.1 Turbo models installed on
`192.168.1.102`; node `452` receives the generated scene prompt and the
service sets its required `resolution` to `1024`. The output latent is
1280×720 and the Turbo sampler uses the workflow's fixed eight-step sigmas.
Each job gets a fresh noise seed.

Configuration environment variables:

- `COMFYUI_URL` (default `http://192.168.1.102:8188`)
- `COMFYUI_WORKFLOW_PATH` (default: the workflow file above)
- `COMFYUI_REQUEST_TIMEOUT` (default `30` seconds per HTTP request)
- `COMFYUI_JOB_TIMEOUT` (default `900` seconds for submission, generation, and download)
- `COMFYUI_POLL_INTERVAL` (default `2` seconds)
- `COMFYUI_CLEANUP_TIMEOUT` (default `30` seconds to confirm cancellation)
- `COMFYUI_RECOVERY_RETRY` (default `5` seconds between recovery attempts)
- `COMFYUI_UNKNOWN_QUIET_PERIOD` (default `30` seconds of an empty queue when the submitted prompt ID is unknown)
- `COMFYUI_STATE_PATH` (default: `OUT_DIR/comfyui-active-job.json`)

The thumbnail worker holds the shared `/busy` gate from art-direction generation
through ComfyUI rendering and composition. If a submitted job times out or its
history connection fails, the server removes it from the pending queue or sends
a prompt-targeted interrupt, then confirms that it is terminal or absent from
the ComfyUI queue. If ComfyUI is unreachable during cleanup, the job is marked
`failed` but the busy gate stays held. A recovery worker retries; the active-job
marker also restores the gate after a thumbnail-server restart. For an uncertain
submission with no known prompt ID, recovery waits for the ComfyUI queue to stay
empty for the configured quiet period. The backend auto-generation path treats
thumbnail generation as best-effort and persists `thumbnail.png` and the episode
path only after it receives the completed image.

## Deployment

From the repository root, run:

```bash
bash scripts/deploy_thumbnail_server.sh
```

The script saves a timestamped copy of the existing remote source under
`/Users/tak/apps/qwen-thumb-server/backups/`, syncs this repository's source,
workflow, and LaunchAgent definition, waits for `GET /busy` to report idle, then restarts
the service through `launchctl`. The LaunchAgent uses `RunAtLoad` and `KeepAlive`
so launchd starts it at login and restarts it after an unexpected exit. Its
stdout and stderr are written to `server.log` in the service directory.

The default SSH target is `tak@192.168.1.102` and the default interpreter is
`/Users/tak/.qwen-venv/bin/python`. Before taking a backup or stopping the
service, the script checks that this interpreter can find `PIL`, `fastapi`,
and `httpx`. ComfyUI runs separately on the configured host. If a dependency is missing, it exits before
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
