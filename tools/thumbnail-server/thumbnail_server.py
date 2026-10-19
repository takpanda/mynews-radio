#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen thumbnail service — builds a per-episode "わかる解説" YouTube-style
thumbnail from episode title/topic.

Runs on .102 (Mac-mini-M4Pro) where qwenimage2mlx (MLX) + Ollama live.
Flow per job: Ollama derive (scene prompt + headline + highlight keyword)
              -> qwenimage2mlx scene gen (turbo) -> PIL composite (YT style).
Jobs are queued and processed ONE at a time (single worker + lock).

Endpoints:
  POST /thumbnail {title, topic, brand?} -> {job_id}
  GET  /thumbnail/{job_id}               -> {status, ...} (poll)
  GET  /files/{job_id}.png               -> the rendered PNG (when done)
"""
import os, re, json, time, uuid, queue, threading, logging, tempfile, sys, asyncio
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import httpx
import uvicorn

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s")
log = logging.getLogger("qwen-thumb")

# ---------- config ----------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e2b-mlx")
OUT_DIR = Path(os.environ.get("OUT_DIR", "/tmp/qwen-thumb"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_BRAND = os.environ.get("BRAND", "わかる解説")
WIDTH, HEIGHT = 960, 540
GOTH  = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
MINCHO = "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"
DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
GREEN=(47,91,58); GOLD=(176,132,34); WHITE=(255,255,255)
HIGHLIGHT=(255,205,60); RED=(220,40,40)

def _font_path(*candidates):
    return next((path for path in candidates if Path(path).is_file()), GOTH)

GOTH = _font_path(GOTH, "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
DIN = _font_path(DIN, "/Library/Fonts/DIN Condensed Bold.ttf", GOTH)

app = FastAPI(title="qwen-thumbnail-service")
jobs = {}            # job_id -> dict(status, path, error)
job_q = queue.Queue()
gen_lock = threading.Lock()
_pipe = None
_pipe_lock = threading.Lock()

# ---- idle watchdog: Qwen-Image-2.1 holds ~50GB resident and _pipe=None does NOT
#      return it to the OS (MLX/Metal buffers). Only a process restart frees it.
#      So after the model has been loaded and then been idle for IDLE_RESTART_MINUTES,
#      we execv a fresh copy of this script (replaces the process → model freed). ----
IDLE_RESTART_MINUTES = float(os.environ.get("IDLE_RESTART_MINUTES", "15"))
_last_activity = time.time()
_last_ts_lock = threading.Lock()
def touch_activity():
    global _last_activity
    with _last_ts_lock:
        _last_activity = time.time()
def idle_for_seconds():
    with _last_ts_lock:
        return time.time() - _last_activity

# ---- shared "server busy" gate: ALL heavy .102 work (script LLM / audio TTS /
#      image gen) must NOT run simultaneously. Counter-based gate.
#      mynews-radio pipeline calls /busy/up before its .102 LLM/TTS phases and
#      /busy/down after. This service increments its own while rendering and
#      waits for the counter to hit 0 before starting a job. ----
_busy = 0
_busy_lock = threading.Condition()
def busy_down():
    global _busy
    with _busy_lock:
        if _busy > 0:
            _busy -= 1
            _busy_lock.notify_all()
def busy_count():
    with _busy_lock:
        return _busy

def try_claim_busy():
    """Claim the shared gate without waiting for a blocking worker thread."""
    global _busy
    with _busy_lock:
        if _busy != 0:
            return False
        _busy = 1
        return True

def wait_for_idle_and_claim(job_id):
    """Wait for an idle gate and claim it atomically for one heavy operation."""
    global _busy
    with _busy_lock:
        while _busy != 0:
            log.info("%s waiting for server to be idle (busy=%d)", job_id, _busy)
            _busy_lock.wait()
        _busy = 1

def F(path, size, idx=0):
    try:
        return ImageFont.truetype(path, size, index=idx)
    except OSError:
        return ImageFont.load_default(size=size)
def textbox(font, s):
    b = font.getbbox(s); return b[2]-b[0], b[3]-b[1]

# ---------- 1) derive scene prompt / headline / highlight from episode ----------
def _ollama_chat(prompt, max_tokens=900):
    r = httpx.post(f"{OLLAMA_URL}/api/chat", json={
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False, "options": {"temperature": 0.7, "num_predict": max_tokens},
    }, timeout=90.0)
    r.raise_for_status()
    return r.json().get("message", {}).get("content", "")

def _extract_json(text):
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try: return json.loads(m.group(0))
        except Exception: pass
    return None

def derive(title, topic):
    """Return a scene prompt and validated editorial art direction."""
    title = (title or "").strip()
    topic = (topic or "").strip()
    sys_prompt = (
        "あなたは日本の情報番組『わかる解説』のサムネイル制作担当です。"
        "エピソードのタイトルとトピックから、YouTube・広告向けの**インパクトあるサムネイル**を設計してください。"
        "必ず次のJSONで返してください。"
        "{\"scene_prompt\":\"画像生成向け英語プロンプト。テーマを象徴する被写体を右側に配置し、"
        "左側は文字用に余白を空ける。文字・ロゴ・透かしは描かない\","
        "\"visual_style\":\"person|object|symbol|environment|typography のいずれか\","
        "\"tone\":\"bright-warm|bright-cool|moody-dark のいずれか\","
        "\"accent\":[R,G,B],\"headline\":\"日本語の短い見出し、2行程度\","
        "\"tag\":\"短い分類タグ\",\"kicker\":\"英数字を含む短い前置き\","
        "\"brand\":\"わかる解説\"}。画像の末尾に editorial, cinematic lighting, no text を含める。" )
    user_prompt = f"タイトル: {title}\nトピック: {topic}\n"
    out = _ollama_chat(sys_prompt + "\n" + user_prompt)
    d = _extract_json(out) or {}
    scene_prompt = (d.get("scene_prompt") or "").strip()
    headline = (d.get("headline") or "").strip()
    if scene_prompt and headline:
        style = d.get("visual_style", "object")
        tone = d.get("tone", "bright-warm")
        if style not in {"person", "object", "symbol", "environment", "typography"}:
            style = "object"
        if tone not in {"bright-warm", "bright-cool", "moody-dark"}:
            tone = "bright-warm"
        raw_accent = d.get("accent", [176, 132, 34])
        if not isinstance(raw_accent, list) or len(raw_accent) != 3:
            raw_accent = [176, 132, 34]
        try:
            accent = tuple(max(0, min(255, int(channel))) for channel in raw_accent)
        except (TypeError, ValueError):
            accent = (176, 132, 34)
        return scene_prompt, {
            "visual_style": style, "tone": tone, "accent": accent,
            "headline": headline, "tag": str(d.get("tag") or "ニュース"),
            "kicker": str(d.get("kicker") or "SPECIAL REPORT"),
            "brand": str(d.get("brand") or DEFAULT_BRAND),
        }
    # fallback: keyword/template
    kw = (title or "ニュース")[:6]
    scene_prompt = (f"a bold editorial illustration about {kw}, warm palette, "
                    f"cinematic lighting, ultra detailed, no text, no watermark")
    headline = (title or "今日の話題")
    return scene_prompt, {
        "visual_style": "object", "tone": "bright-warm", "accent": GOLD,
        "headline": headline, "tag": kw, "kicker": "TODAY'S STORY",
        "brand": DEFAULT_BRAND,
    }

# ---------- 2) generate scene via qwenimage2mlx ----------
def get_pipe():
    global _pipe
    with _pipe_lock:
        if _pipe is None:
            from qwenimage2mlx import QwenImage21
            log.info("loading QwenImage21(turbo=True) ...")
            _pipe = QwenImage21(turbo=True)
            log.info("model ready")
        return _pipe

def gen_scene(scene_prompt):
    pipe = get_pipe()
    img = pipe.generate(scene_prompt, width=WIDTH, height=HEIGHT,
                        steps=6, seed=42, save=False)
    if isinstance(img, Image.Image):
        return img.convert("RGB").resize((WIDTH, HEIGHT))
    # generate() may return a path or None; fallback
    p = img if isinstance(img, str) else None
    if p and Path(p).exists():
        return Image.open(p).convert("RGB").resize((WIDTH, HEIGHT))
    raise RuntimeError("scene generation returned no image")

# ---------- 3) composite editorial thumbnail ----------
def compose(scene, art_direction, brand=None):
    """Burn a left-aligned editorial cover into a scene image."""
    spec = dict(art_direction or {})
    W, H = scene.size if scene is not None else (WIDTH, HEIGHT)
    spec.setdefault("headline", "今日の話題")
    spec.setdefault("tone", "bright-warm")
    spec.setdefault("accent", GOLD)
    spec.setdefault("tag", "ニュース")
    spec.setdefault("kicker", "SPECIAL REPORT")
    spec.setdefault("brand", brand or DEFAULT_BRAND)
    if brand:
        spec["brand"] = brand
    tone = spec["tone"] if spec["tone"] in {"bright-warm", "bright-cool", "moody-dark"} else "bright-warm"
    accent = spec["accent"]
    if not isinstance(accent, (tuple, list)) or len(accent) != 3:
        accent = GOLD
    accent = tuple(max(0, min(255, int(c))) for c in accent)
    dark = tone == "moody-dark"
    text_color = (250, 248, 242) if dark else (32, 35, 38)
    muted_color = (205, 207, 203) if dark else (87, 89, 89)
    panel = (17, 20, 24) if dark else ((246, 239, 222) if tone == "bright-warm" else (230, 241, 245))

    if scene is None:
        img = Image.new("RGB", (W, H), panel)
        # A restrained geometric field gives typography-only covers a designed background.
        bg = ImageDraw.Draw(img)
        bg.polygon([(W * .58, 0), (W, 0), (W, H), (W * .75, H)], fill=accent)
        bg.ellipse((W * .69, -H * .14, W * 1.1, H * .52), fill=tuple((c + 28) // 2 for c in panel))
    else:
        img = scene.convert("RGB").resize((W, H)).copy()
    d = ImageDraw.Draw(img, "RGBA")
    # The editorial panel reserves the right third for the generated subject.
    panel_right = int(W * 2 / 3)
    d.rectangle((0, 0, panel_right, H), fill=(*panel, 242 if scene is not None else 255))
    d.rectangle((0, 0, 12, H), fill=(*accent, 255))

    left, right = 48, panel_right - 40
    max_width = right - left
    d.text((left, 28), spec["brand"], font=F(GOTH, 27), fill=text_color)
    d.rectangle((left, 70, left + min(74, max_width), 74), fill=accent)
    d.text((left, 91), str(spec["kicker"]).upper(), font=F(DIN, 29), fill=muted_color)

    headline = str(spec["headline"]).strip() or "今日の話題"
    # Prefer a balanced two-line Japanese split; reduce type size until both lines fit.
    chars = list(headline)
    split = max(1, min(len(chars) - 1, round(len(chars) / 2))) if len(chars) > 1 else len(chars)
    lines = ["".join(chars[:split]), "".join(chars[split:])] if len(chars) > 1 else [headline]
    size = 88
    while size > 30 and any(F(GOTH, size).getlength(line) > max_width for line in lines):
        size -= 2
    font = F(GOTH, size)
    # If even the minimum is too wide, fit by character count without allowing bleed.
    wrapped = []
    for line in lines:
        current = ""
        for char in line:
            if current and font.getlength(current + char) > max_width:
                wrapped.append(current)
                current = char
            else:
                current += char
        if current:
            wrapped.append(current)
    lines = wrapped[:3]
    y = int(H * .34)
    line_height = max(36, int(size * 1.12))
    for line in lines:
        d.text((left, y), line, font=font, fill=text_color)
        y += line_height

    tag_y = min(H - 83, y + 8)
    tag = str(spec["tag"])
    tag_font = F(GOTH, 23)
    tag_width = min(max_width, int(tag_font.getlength(tag) + 28))
    d.rounded_rectangle((left, tag_y, left + tag_width, tag_y + 38), radius=4,
                        fill=(*accent, 255))
    d.text((left + 12, tag_y + 5), tag, font=tag_font, fill=(255, 255, 255))
    footer_y = H - 39
    d.line((left, footer_y - 11, right, footer_y - 11), fill=(*accent, 200), width=2)
    d.text((left, footer_y), "WAKARU  /  EXPLAINED", font=F(DIN, 18), fill=muted_color)
    return img

# ---------- worker ----------
def process_job(job_id):
    j = jobs[job_id]
    # Keep Ollama derive inside the same busy window as image generation.
    wait_for_idle_and_claim(job_id)
    try:
        j["status"] = "derive"
        scene_prompt, art_direction = derive(j["title"], j["topic"])
        j["scene_prompt"] = scene_prompt
        j["art_direction"] = art_direction
        j["headline"] = art_direction["headline"]
        if j.get("brand"):
            art_direction["brand"] = j["brand"]
        if art_direction.get("visual_style") == "typography":
            scene = None
        else:
            with gen_lock:
                j["status"] = "scene"
                scene = gen_scene(scene_prompt)
        j["status"] = "compose"
        img = compose(scene, art_direction, j.get("brand"))
        path = OUT_DIR / f"{job_id}.png"
        img.save(path)
        j["path"] = str(path)
        j["status"] = "done"
    except Exception as e:
        log.exception("job %s failed", job_id)
        j["status"] = "failed"; j["error"] = str(e)
    finally:
        busy_down()
        touch_activity()   # last activity = job completion (watchdog refresh)
        j["done_at"] = time.time()

def worker_loop():
    while True:
        process_job(job_q.get())

threading.Thread(target=worker_loop, daemon=True).start()

# idle watchdog: if the model is loaded (50GB) and the server has been idle
# (busy=0, no recent job) for IDLE_RESTART_MINUTES, execv a fresh copy to free RAM.
def idle_watchdog():
    while True:
        if _pipe is not None and busy_count() == 0 and idle_for_seconds() > IDLE_RESTART_MINUTES * 60:
            log.info("model loaded but idle %.0f min -> restarting to free 50GB RAM",
                     idle_for_seconds() / 60.0)
            try:
                os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)])
            except Exception as e:
                log.exception("execv failed: %s", e)
                time.sleep(60)
        time.sleep(20)

threading.Thread(target=idle_watchdog, daemon=True).start()

@app.post("/busy/up")
async def busy_up_ep():
    # Keep waiting requests on the event loop so they cannot consume Starlette's
    # finite sync-endpoint thread pool needed by /busy/down.
    while not try_claim_busy():
        await asyncio.sleep(0.05)
    return {"busy": busy_count()}
@app.post("/busy/down")
def busy_down_ep():
    busy_down(); return {"busy": busy_count()}
@app.get("/busy")
def busy_get():
    return {"busy": busy_count()}

class Req(BaseModel):
    title: str = ""
    topic: str = ""
    brand: str | None = None

@app.post("/thumbnail")
def enqueue(req: Req):
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "title": req.title, "topic": req.topic,
                    "scene_prompt": None, "headline": None, "highlight": None,
                    "path": None, "error": None, "brand": req.brand}
    job_q.put(job_id)
    touch_activity()   # incoming job refreshes idle-watchdog timer
    log.info("enqueued %s title=%r", job_id, req.title)
    return {"job_id": job_id, "status": "queued"}

@app.get("/thumbnail/{job_id}")
def status(job_id: str):
    j = jobs.get(job_id)
    if not j: raise HTTPException(404, "unknown job")
    return {k: j[k] for k in ("status", "error")} | {"job_id": job_id}

@app.get("/files/{job_id}.png")
def image(job_id: str):
    j = jobs.get(job_id)
    if not j or j["status"] != "done" or not j["path"]: raise HTTPException(404, "not ready")
    return FileResponse(j["path"], media_type="image/png")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8501)), log_level="info")
