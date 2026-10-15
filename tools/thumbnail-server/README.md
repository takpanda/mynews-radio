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

The default SSH target is `tak@192.168.1.102`. Override the target and paths
with environment variables, or pass a host as the first argument:

```bash
THUMBNAIL_SERVER_USER=tak \
THUMBNAIL_SERVER_HOST=192.168.1.102 \
THUMBNAIL_SERVER_DIR=/Users/tak/apps/qwen-thumb-server \
THUMBNAIL_SERVER_PORT=8501 \
THUMBNAIL_SERVER_URL=http://192.168.1.102:8501/busy \
bash scripts/deploy_thumbnail_server.sh
```

The deploy script requires SSH key-based access, `rsync` and Python 3 on the
remote Mac, and `curl` on the machine running the script. The script only
deploys `thumbnail_server.py`; it does not install Python dependencies.

## Manual start

On the Mac mini, run from the server directory:

```bash
cd /Users/tak/apps/qwen-thumb-server
nohup python3 thumbnail_server.py > thumbnail_server.log 2>&1 < /dev/null &
```

To check the service manually:

```bash
curl --fail http://192.168.1.102:8501/busy
```
