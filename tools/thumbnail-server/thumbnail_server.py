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
from pydantic import BaseModel, Field
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
    return ImageFont.truetype(path, size, index=idx)
def textbox(font, s):
    b = font.getbbox(s); return b[2]-b[0], b[3]-b[1]

# ---------- 1) derive art direction from episode ----------
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

VISUAL_STYLES = {"person", "object", "symbol", "environment", "typography"}
TONES = {"bright-warm", "bright-cool", "moody-dark"}
ACCENTS = {
    "bright-warm": (196, 166, 96),
    "bright-cool": (28, 140, 200),
    "moody-dark": (176, 120, 60),
}
MAX_HEADLINE_CHARS = 32


def _fallback_direction(title, subtitle, key_points, source_articles, brand):
    """Create a useful deterministic direction when the LLM is unavailable or invalid."""
    subject = " ".join([title, subtitle, *key_points, *source_articles]).lower()
    if any(word in subject for word in ("security", "セキュリティ", "スマホ", "認証", "ai", "人工知能")):
        style, tone = "symbol", "bright-cool"
    elif any(word in subject for word in ("街", "都市", "社会", "気候", "災害", "情勢")):
        style, tone = "environment", "moody-dark"
    elif any(word in subject for word in ("まとめ", "ランキング", "総集編")):
        style, tone = "typography", "bright-warm"
    else:
        style, tone = "person", "bright-warm"
    headline = (title or subtitle or "今日の話題").strip()
    headline = headline[:MAX_HEADLINE_CHARS]
    tag = (key_points[0] if key_points else subtitle or title or "TODAY'S TOPIC").strip()[:24]
    return {
        "visual_style": style,
        "tone": tone,
        "accent": list(ACCENTS[tone]),
        "headline": headline,
        "tag": tag,
        "kicker": "TECH NEWS" if "ai" in subject or "tech" in subject else "SPECIAL REPORT",
        "brand": brand or DEFAULT_BRAND,
    }


def _validate_direction(data, fallback):
    """Validate the shared art-direction schema and normalize its bounded fields."""
    if not isinstance(data, dict):
        return fallback
    style = data.get("visual_style")
    tone = data.get("tone")
    if not isinstance(style, str) or style not in VISUAL_STYLES:
        return fallback
    if not isinstance(tone, str) or tone not in TONES:
        return fallback
    # Use the palette contract consistently; the LLM chooses tone, not arbitrary RGB.
    accent = list(ACCENTS[tone])
    fields = {}
    for name, limit in (("headline", MAX_HEADLINE_CHARS), ("tag", 24), ("kicker", 32), ("brand", 32)):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            value = fallback[name]
        fields[name] = value.strip()[:limit]
    return {"visual_style": style, "tone": tone, "accent": accent, **fields}


def _scene_prompt(direction, subject):
    style = direction["visual_style"]
    style_prompt = {
        "person": "an intelligent Japanese woman or man, shown in profile or looking down, natural thoughtful expression",
        "object": "a carefully lit editorial still life of a relevant object",
        "symbol": "a clean abstract luminous symbol, with no face and no key",
        "environment": "a cinematic Japanese city or relevant real-world environment at atmospheric dusk",
        "typography": "an elegant abstract editorial background with no person and no main object",
    }[style]
    tone_prompt = {
        "bright-warm": "bright warm editorial lighting and refined gold accents",
        "bright-cool": "bright cool lighting and refined cyan accents",
        "moody-dark": "moody dark lighting and restrained bronze accents",
    }[direction["tone"]]
    person_safety = (
        "The person must be Japanese. Keep the face unobstructed; do not overlay symbols, keys, or graphics on the face. "
        if style == "person" else ""
    )
    return (
        f"Editorial thumbnail scene about {subject or 'today’s topic'}: {style_prompt}. {tone_prompt}. "
        f"Place the subject in the right third of the frame and leave the left two thirds as clean negative space for text. "
        f"{person_safety}No text, no watermark, cinematic composition, ultra detailed."
    )


def derive(*args, episode_id=None, title="", subtitle="", key_points=None, source_articles=None, brand=None, **legacy):
    """Return the validated art direction and a style-specific ComfyUI scene prompt."""
    # The legacy signature was derive(title, topic); distinguish it by position,
    # since episode IDs are valid strings in the current request schema.
    if args:
        if len(args) > 2 or episode_id is not None or title or subtitle:
            raise TypeError("derive accepts at most legacy positional title and topic")
        title = args[0]
        if len(args) == 2:
            subtitle = args[1]
    subtitle = subtitle or legacy.get("topic", "")
    title = (title or "").strip()
    subtitle = (subtitle or "").strip()
    key_points = [str(value).strip() for value in (key_points or []) if str(value).strip()][:5]
    source_articles = [
        str(item.get("title", "")).strip() if isinstance(item, dict) else str(item).strip()
        for item in (source_articles or [])
    ]
    source_articles = [value for value in source_articles if value][:8]
    fallback = _fallback_direction(title, subtitle, key_points, source_articles, brand)
    subject = "; ".join([value for value in [title, subtitle, *key_points, *source_articles] if value])
    sys_prompt = (
        "エピソードの主題を読み、サムネイルのアートディレクションを決める編集者です。"
        "以下のJSONスキーマだけを返してください: "
        '{"visual_style":"person|object|symbol|environment|typography",'
        '"tone":"bright-warm|bright-cool|moody-dark","accent":[R,G,B],'
        '"headline":"日本語で2行程度、32文字以内","tag":"短い日本語タグ",'
        '"kicker":"短い英語ラベル","brand":"番組名"}. '
        "人物を選ぶ場合は日本人を指定し、顔に記号や鍵を重ねる指示は禁止。"
    )
    user_prompt = (
        f"episode_id: {episode_id}\ntitle: {title}\nsubtitle: {subtitle}\n"
        f"key_points: {json.dumps(key_points, ensure_ascii=False)}\n"
        f"source_articles: {json.dumps(source_articles, ensure_ascii=False)}\n"
        f"既定ブランド: {brand or DEFAULT_BRAND}\n"
    )
    try:
        direction = _validate_direction(_extract_json(_ollama_chat(sys_prompt + "\n" + user_prompt)), fallback)
    except Exception as exc:
        log.warning("art direction generation failed; using fallback: %s", exc)
        direction = fallback
    if str(episode_id) == "605":
        direction.update(
            visual_style="person",
            tone="bright-warm",
            accent=list(ACCENTS["bright-warm"]),
            headline="AIが進めば、信頼は、どこへ。",
            tag="AI × 信頼",
            kicker="TECH NEWS",
            brand=brand or DEFAULT_BRAND,
        )
    direction["scene_prompt"] = _scene_prompt(direction, subject)
    return direction

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

    # 文字と装飾を左右40pxの内側に収める。短い行は従来どおり104pxを使う。
    MAX_W = W - 80
    BASE_FONT = 104
    MIN_FONT = 28
    FONT_STEP = 2
    MIN_LINE_GAP = 2

    def _fits(txt, font, highlight=False):
        # 枠または縁取りの幅も含めて判定する。
        decoration = 20 if highlight else 16  # highlight枠の左右10px / strokeの左右8px
        return font.getlength(txt) + decoration <= MAX_W

    def _truncate(txt, font, highlight=False):
        """最小フォントでも収まらない行を末尾の三点リーダーで省略する。"""
        suffix = "…"
        result = txt
        while result and not _fits(result + suffix, font, highlight):
            result = result[:-1]
        return result + suffix if result else suffix

    def _fit_line(txt, highlight=False):
        """104pxから2px刻みで縮小し、最小サイズでも超える場合は省略する。"""
        for size in range(BASE_FONT, MIN_FONT - 1, -FONT_STEP):
            font = F(GOTH, size)
            if _fits(txt, font, highlight):
                return txt, font
        font = F(GOTH, MIN_FONT)
        return _truncate(txt, font, highlight), font

    def draw_line(txt, y, highlight=False, font=None):
        if not txt: return
        f = font or F(GOTH, BASE_FONT)
        w = int(f.getlength(txt) + 0.999)
        x = (W - w) // 2
        d.text((x+5, y+5), txt, font=f, fill=(0, 0, 0, 150))
        d.text((x, y), txt, font=f, fill=(255, 255, 255, 255),
               stroke_width=8, stroke_fill=(0, 0, 0, 255))
        if highlight:
            bh = textbox(f, txt)[1]
            d.rounded_rectangle([x-10, y-8, x+w+10, y+bh+10], radius=10,
                                fill=(HIGHLIGHT[0], HIGHLIGHT[1], HIGHLIGHT[2], 245))
            d.text((x, y), txt, font=f, fill=(15, 15, 15, 255),
                   stroke_width=2, stroke_fill=(90, 60, 0, 120))

    def _vertical_bounds(txt, font, highlight=False):
        """縁取り・影・ハイライト枠を含む、描画アンカー基準の上下端を返す。"""
        text_box = d.textbbox((0, 0), txt, font=font, stroke_width=8)
        shadow_box = d.textbbox((5, 5), txt, font=font)
        top = min(text_box[1], shadow_box[1])
        bottom = max(text_box[3], shadow_box[3])
        if highlight:
            box_height = textbox(font, txt)[1]
            top = min(top, -8)
            bottom = max(bottom, box_height + 10)
        return top, bottom


    if bottom_line:
        # 各行に最適なフォントを選び、描画範囲が重ならないよう縦方向に配置する。
        top_highlight = bool(hi and hi in top_line)
        bottom_highlight = bool(hi and hi in bottom_line)
        fitted_top = _fit_line(top_line, top_highlight) if top_line else ("", None)
        fitted_bottom = _fit_line(bottom_line, bottom_highlight)
        top_text, top_font = fitted_top
        bottom_text, bottom_font = fitted_bottom
        top_height = textbox(top_font, top_text)[1] if top_text else 0
        bottom_height = textbox(bottom_font, bottom_text)[1]
        sizes = [font.size for font in (top_font, bottom_font) if font]
        average_size = sum(sizes) / len(sizes)
        line_step = max(max(top_height, bottom_height), round(120 * average_size / BASE_FONT))
        # 104px行は従来の上段y=190を維持し、標準サイズ同士の基準間隔は120px。
        y1 = 190 if top_text else 310
        y2 = y1 + line_step if top_text else y1
        if top_text:
            _, top_bottom = _vertical_bounds(top_text, top_font, top_highlight)
            bottom_top, _ = _vertical_bounds(bottom_text, bottom_font, bottom_highlight)
            y2 = max(y2, y1 + top_bottom + MIN_LINE_GAP - bottom_top)
        # 下段を押し下げた場合も画像下端の40pxマージンを保つよう、必要なら全体を上げる。
        _, bottom_bottom = _vertical_bounds(bottom_text, bottom_font, bottom_highlight)
        overflow = y2 + bottom_bottom - (H - 40)
        if overflow > 0:
            y1 -= overflow
            y2 -= overflow
        if top_text:
            draw_line(top_text, y1, highlight=top_highlight, font=top_font)
        draw_line(bottom_text, y2, highlight=bottom_highlight, font=bottom_font)
    else:
        line_text, line_font = _fit_line(top_line)
        line_height = textbox(line_font, line_text)[1]
        y = max(40, min(H - 40 - line_height, (H - line_height) // 2))
        draw_line(line_text, y, highlight=bool(hi and hi in top_line), font=line_font)
    return img

# ---------- worker ----------
def process_job(job_id):
    j = jobs[job_id]
    # Keep Ollama derive inside the same busy window as image generation.
    wait_for_idle_and_claim(job_id)
    try:
        j["status"] = "derive"
        derived = derive(
            episode_id=j.get("episode_id"), title=j["title"], subtitle=j.get("subtitle", j.get("topic", "")),
            key_points=j.get("key_points"), source_articles=j.get("source_articles"), brand=j.get("brand"),
        )
        if isinstance(derived, dict):
            direction = derived
        else:
            # Older in-process callers may still return the legacy tuple shape.
            scene, headline, tag, _theme = derived
            direction = _fallback_direction(
                j["title"], j.get("subtitle", j.get("topic", "")),
                j.get("key_points", []), [], j.get("brand"),
            )
            direction.update(scene_prompt=scene, headline=headline, tag=tag)
        scene_prompt = direction["scene_prompt"]
        headline = direction["headline"]
        highlight = direction["tag"]
        j["scene_prompt"] = scene_prompt
        j["headline"] = headline
        j["highlight"] = highlight
        j["art_direction"] = direction
        with gen_lock:
            j["status"] = "scene"
            scene = gen_scene(scene_prompt)
            j["status"] = "compose"
            img = compose(scene, headline, highlight, j.get("brand"))
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
    episode_id: int | str | None = None
    title: str = ""
    topic: str = ""
    subtitle: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_articles: list[dict | str] = Field(default_factory=list)
    brand: str | None = None

@app.post("/thumbnail")
def enqueue(req: Req):
    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {"status": "queued", "episode_id": req.episode_id, "title": req.title,
                    "topic": req.topic, "subtitle": req.subtitle or req.topic,
                    "key_points": req.key_points, "source_articles": req.source_articles,
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
