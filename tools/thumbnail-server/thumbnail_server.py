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
import os, re, json, time, uuid, queue, threading, logging, tempfile, sys
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
GREEN=(47,91,58); GOLD=(176,132,34); WHITE=(255,255,255)
HIGHLIGHT=(255,205,60); RED=(220,40,40)

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
_busy_lock = threading.Lock()
def busy_up():
    global _busy
    with _busy_lock:
        _busy += 1
def busy_down():
    global _busy
    with _busy_lock:
        _busy = max(0, _busy - 1)
def busy_count():
    with _busy_lock:
        return _busy

def F(path, size, idx=0):
    return ImageFont.truetype(path, size, index=idx)
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
    """Return (scene_prompt, headline, highlight_kw, theme_kw)."""
    title = (title or "").strip()
    topic = (topic or "").strip()
    sys_prompt = (
        "あなたは日本の情報番組『わかる解説』のサムネイル制作担当です。"
        "エピソードのタイトルとトピックから、YouTube・広告向けの**インパクトあるサムネイル**を設計してください。"
        "必ずJSONで返してください。{\"scene_prompt\":\"qwenimage2mlxで生成する画像の英語プロンプト。"
        "そのエピソードの話題を象徴するメインの被写体を具体的に。高コントラストでYouTube風。"
        "最後に『warm editorial, cinematic lighting, ultra detailed, no text, no watermark』を必ず付け加えて。\","
        "\"headline\":\"日本語の短い見出し（15文字以内、1行で読めるインパクトのある表現）\","
        "\"highlight\":\"見出しの中で黄色ハイライトで強調するキーワード（見出しに必ず含まれる単語）\"}" )
    user_prompt = f"タイトル: {title}\nトピック: {topic}\n"
    try:
        out = _ollama_chat(sys_prompt + "\n" + user_prompt)
        d = _extract_json(out) or {}
        scene_prompt = (d.get("scene_prompt") or "").strip()
        headline = (d.get("headline") or "").strip()
        highlight = (d.get("highlight") or "").strip()
        if scene_prompt and headline:
            return scene_prompt, headline, (highlight or ""), ""
    except Exception as e:
        log.warning("derive LLM failed: %s", e)
    # fallback: keyword/template
    kw = (title or "ニュース")[:6]
    scene_prompt = (f"a bold editorial illustration about {kw}, warm palette, "
                    f"cinematic lighting, ultra detailed, no text, no watermark")
    headline = (title or "今日の話題")
    return scene_prompt, headline, "", kw

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

# ---------- 3) composite YT-style thumbnail ----------
def compose(scene, headline, highlight_kw, brand=None):
    img = scene.copy()
    W, H = img.size
    # dark gradient band (top) for headline readability
    grad = Image.new("L", (1, H), 0)
    for y in range(H):
        v = int(205 * (1 - y/500)) if y <= 500 else 0
        grad.putpixel((0, y), v)
    grad = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (8, 8, 12))
    img = Image.composite(black, img, grad)
    d = ImageDraw.Draw(img, "RGBA")

    # logo top-left (brand), white + gold, black outline
    f_logo = F(GOTH, 60)
    parts = brand or DEFAULT_BRAND
    # split brand into first color-part and rest if possible; simple: all gold
    lx, ly = 40, 26
    d.text((lx, ly), parts, font=f_logo, fill=(255, 255, 255, 255),
           stroke_width=4, stroke_fill=(0, 0, 0, 255))
    # small gold "解説バッジ" accent
    # (kept minimal; brand already shown)

    # headline: split into two lines around highlight keyword
    f_head = F(GOTH, 104)
    hl = headline or "今日の話題"
    # build line arrangement: if highlight present and in hl, emphasize it
    hi = highlight_kw.strip()
    top_line, bottom_line = hl, None
    if hi and hi in hl:
        idx = hl.find(hi)
        left, right = hl[:idx], hl[idx:]
        # put non-highlight part on line1, highlight (plus remainder) on line2
        # simple: line1 = left, line2 = right
        if left.strip():
            top_line, bottom_line = left.strip(), right.strip()
        else:
            top_line, bottom_line = "", right.strip()
    else:
        top_line, bottom_line = hl, ""

    # 見出しが画像幅を超えないよう、文字幅に応じてフォントを動的縮小する。
    MAX_W = W - 80                      # 左右マージン(40pxずつ)
    MIN_FONT = 32
    def _fit_font(txt):
        """txt が MAX_W に収まるフォントを 104px から段階的に縮小して返す。"""
        size = 104
        while size > MIN_FONT:
            f = F(GOTH, size)
            if f.getlength(txt) <= MAX_W:
                return f
            size -= 4
        return F(GOTH, MIN_FONT)

    def _fit_font(txt):
        """txt が MAX_W に収まるフォントを 104px から段階的に縮小して返す。"""
        size = 104
        while size > MIN_FONT:
            f = F(GOTH, size)
            if f.getlength(txt) <= MAX_W:
                return f
            size -= 4
        return F(GOTH, MIN_FONT)

    def draw_line(txt, y, highlight=False, font=None):
        if not txt: return
        f = font or _fit_font(txt)       # 指定が無ければ自動縮小
        w = int(f.getlength(txt))
        x = max(40, (W - w) // 2)        # 中央揃えだが左マージン40pxは確保
        d.text((x+5, y+5), txt, font=f, fill=(0, 0, 0, 150))
        d.text((x, y), txt, font=f, fill=(255, 255, 255, 255),
               stroke_width=8, stroke_fill=(0, 0, 0, 255))
        if highlight:
            bh = textbox(f, txt)[1]
            d.rounded_rectangle([x-10, y-8, x+w+10, y+bh+10], radius=10,
                                fill=(HIGHLIGHT[0], HIGHLIGHT[1], HIGHLIGHT[2], 245))
            d.text((x, y), txt, font=f, fill=(15, 15, 15, 255),
                   stroke_width=2, stroke_fill=(90, 60, 0, 120))


    if bottom_line:
        # two lines: top (if any) + highlighted bottom; draw bottom even if top empty
        # 両行のフォントサイズを統一するため、長い方の行に合わせて縮小する。
        candidates = [t for t in (top_line, bottom_line) if t.strip()]
        size = 104
        while size > MIN_FONT:
            f = F(GOTH, size)
            if all(f.getlength(t) <= MAX_W for t in candidates):
                break
            size -= 4
        common_font = F(GOTH, max(MIN_FONT, size))
        y1 = 190
        if top_line:
            draw_line(top_line, y1, highlight=bool(hi and hi in top_line), font=common_font)
        draw_line(bottom_line, y1 + 120, highlight=bool(hi and hi in bottom_line), font=common_font)
    else:
        draw_line(top_line, (H - textbox(_fit_font(top_line), top_line)[1]) // 2,
                  highlight=bool(hi and hi in top_line))
    return img

# ---------- worker ----------
def worker_loop():
    while True:
        job_id = job_q.get()
        j = jobs[job_id]
        # gate: wait until no other heavy .102 work is running
        while busy_count() > 0:
            log.info("job %s waiting for server to be idle (busy=%d)", job_id, busy_count())
            time.sleep(5)
        try:
            busy_up()   # mark server busy (don't let LLM/TTS start during render)
            with gen_lock:
                j["status"] = "scene"
                scene = gen_scene(j["scene_prompt"])
                j["status"] = "compose"
                img = compose(scene, j["headline"], j["highlight"], j.get("brand"))
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
def busy_up_ep():
    busy_up(); return {"busy": busy_count()}
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
    scene_prompt, headline, highlight, kw = derive(req.title, req.topic)
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "scene_prompt": scene_prompt,
                    "headline": headline, "highlight": highlight, "path": None, "error": None, "brand": req.brand}
    job_q.put(job_id)
    touch_activity()   # incoming job refreshes idle-watchdog timer
    log.info("enqueued %s title=%r headline=%r", job_id, req.title, headline)
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
