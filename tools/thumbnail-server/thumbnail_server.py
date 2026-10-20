#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Qwen thumbnail service — builds an editorial thumbnail per episode.

Flow per job: Ollama art direction -> ComfyUI scene generation -> PIL composite.
Jobs are queued and processed ONE at a time (single worker + shared busy gate).

Endpoints:
  POST /thumbnail {title, topic, brand?} -> {job_id}
  GET  /thumbnail/{job_id}               -> {status, ...} (poll)
  GET  /files/{job_id}.png               -> the rendered PNG (when done)
"""
import os, re, json, time, uuid, queue, threading, logging, tempfile, asyncio, secrets, unicodedata
from io import BytesIO
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
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://192.168.1.102:8188").rstrip("/")
COMFYUI_WORKFLOW_PATH = Path(os.environ.get(
    "COMFYUI_WORKFLOW_PATH",
    str(Path(__file__).with_name("workflows") / "qwen_image_2_1_turbo_t2i.json"),
))
COMFYUI_REQUEST_TIMEOUT = float(os.environ.get("COMFYUI_REQUEST_TIMEOUT", "30"))
COMFYUI_JOB_TIMEOUT = float(os.environ.get("COMFYUI_JOB_TIMEOUT", "900"))
COMFYUI_POLL_INTERVAL = float(os.environ.get("COMFYUI_POLL_INTERVAL", "2"))
COMFYUI_CLEANUP_TIMEOUT = float(os.environ.get("COMFYUI_CLEANUP_TIMEOUT", "30"))
COMFYUI_RECOVERY_RETRY = float(os.environ.get("COMFYUI_RECOVERY_RETRY", "5"))
COMFYUI_UNKNOWN_QUIET_PERIOD = float(os.environ.get("COMFYUI_UNKNOWN_QUIET_PERIOD", "30"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "/tmp/qwen-thumb"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
COMFYUI_STATE_PATH = Path(os.environ.get(
    "COMFYUI_STATE_PATH", str(OUT_DIR / "comfyui-active-job.json")
))
DEFAULT_BRAND = os.environ.get("BRAND", "わかる解説")
WIDTH, HEIGHT = 960, 540
EPISODE_605_PANEL_WIDTH_RATIO = 0.5
EPISODE_605_SCENE_SHIFT_RATIO = 0.2
GOTH  = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
MINCHO = "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"
GREEN=(47,91,58); GOLD=(176,132,34); WHITE=(255,255,255)
HIGHLIGHT=(255,205,60); RED=(220,40,40)
DIN = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"

def _font_path(*candidates):
    return next((path for path in candidates if Path(path).is_file()), GOTH)

GOTH = _font_path(GOTH, "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")
DIN = _font_path(DIN, "/Library/Fonts/DIN Condensed Bold.ttf", GOTH)

app = FastAPI(title="qwen-thumbnail-service")
jobs = {}            # job_id -> dict(status, path, error)
job_q = queue.Queue()
gen_lock = threading.Lock()
# ---- shared "server busy" gate: ALL heavy .102 work (script LLM / audio TTS /
#      image gen) must NOT run simultaneously. Counter-based gate.
#      mynews-radio pipeline calls /busy/up before its .102 LLM/TTS phases and
#      /busy/down after. This service increments its own while rendering and
#      waits for the counter to hit 0 before starting a job. ----
_busy = 1 if COMFYUI_STATE_PATH.exists() else 0
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

def fit_text(text, path, max_width, max_size, min_size):
    """Shrink and, if needed, ellipsize one line so its measured width fits."""
    text = str(text).strip()
    for size in range(max_size, min_size - 1, -1):
        font = F(path, size)
        if font.getlength(text) <= max_width:
            return text, font
    font = F(path, min_size)
    suffix = "…"
    fitted = text
    while fitted and font.getlength(fitted + suffix) > max_width:
        fitted = fitted[:-1]
    return (fitted + suffix if fitted else suffix), font

def _contrast_text_color(rgb):
    """Pick black or white based on the stronger WCAG contrast ratio."""
    channels = [value / 255 for value in rgb]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return (20, 22, 24) if black_contrast >= white_contrast else (255, 255, 255)


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


def _subject_gender(subject):
    """Infer only explicit or well-known subject attributes; never guess from names."""
    text = unicodedata.normalize("NFKC", str(subject or "")).lower()
    if any(word in text for word in ("女性", "女優", "女性歌手", "女性アーティスト", "woman", "female")):
        return "woman"
    if any(word in text for word in ("男性", "男優", "男性歌手", "男性アーティスト", "man", "male")):
        return "man"
    # B'z is the subject of episode 587; the names are not used as likeness prompts.
    if any(word in text for word in ("b'z", "bz", "松本孝弘", "稲葉浩志")):
        return "man"
    return None


def _copy_for_subject(subject):
    text = unicodedata.normalize("NFKC", str(subject or "")).lower()
    if any(word in text for word in ("b'z", "bz", "音楽", "ミュージシャン", "アーティスト", "歌手", "バンド")):
        return "二人で紡ぐ音楽の物語", "特別対談"
    if any(word in text for word in ("security", "セキュリティ", "スマホ", "認証", "ai", "人工知能")):
        return "進化する技術と暮らし", "TECH WATCH"
    if any(word in text for word in ("街", "都市", "社会", "気候", "災害", "情勢")):
        return "備えから考える街の未来", "防災特集"
    if any(word in text for word in ("ランキング", "総集編", "まとめ")):
        return "今週の注目トピック", "WEEKLY"
    return "今知りたい話題の核心", "TODAY"


def _normalize_copy(value):
    return re.sub(r"[^\w]", "", str(value or "")).casefold()


def _copy_overlaps(left, right):
    left, right = _normalize_copy(left), _normalize_copy(right)
    return bool(left and right and (left in right or right in left))


def _fallback_direction(title, subtitle, key_points, source_articles, brand):
    """Create a useful deterministic direction when the LLM is unavailable or invalid."""
    subject = " ".join([title, subtitle, *key_points, *source_articles]).lower()
    if any(word in subject for word in ("security", "セキュリティ", "スマホ", "認証", "ai", "人工知能")):
        style, tone = "symbol", "bright-cool"
    elif any(word in subject for word in ("街", "都市", "社会", "気候", "災害", "情勢")):
        style, tone = "environment", "moody-dark"
    elif any(word in subject for word in ("まとめ", "ランキング", "総集編")):
        style, tone = "typography", "bright-warm"
    elif _subject_gender(subject):
        style, tone = "person", "bright-warm"
    elif any(word in subject for word in ("音楽", "ミュージシャン", "アーティスト", "歌手", "バンド")):
        style, tone = "object", "bright-warm"
    else:
        style, tone = "symbol", "bright-warm"
    headline, tag = _copy_for_subject(subject)
    return {
        "visual_style": style,
        "tone": tone,
        "accent": list(ACCENTS[tone]),
        "headline": headline,
        "tag": tag,
        "kicker": "TECH NEWS" if "ai" in subject or "tech" in subject else "SPECIAL REPORT",
        "brand": brand or DEFAULT_BRAND,
    }


def _validate_direction(data, fallback, title=""):
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
    llm_headline = fields["headline"]
    tag_repeats_llm_headline = _copy_overlaps(fields["tag"], llm_headline)
    if _copy_overlaps(llm_headline, title):
        fields["headline"] = fallback["headline"]
    if tag_repeats_llm_headline or _copy_overlaps(fields["tag"], fields["headline"]):
        fields["tag"] = fallback["tag"]
    if _copy_overlaps(fields["tag"], fields["headline"]):
        fields["tag"] = "TODAY"
    return {"visual_style": style, "tone": tone, "accent": accent, **fields}


def _scene_prompt(direction, subject, allow_unspecified_person=False):
    style = direction["visual_style"]
    style_prompt = {
        "person": "a Japanese adult, shown in profile or looking down, natural thoughtful expression",
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
    gender = _subject_gender(subject)
    person_safety = ""
    if style == "person":
        person_safety = (
            f"Depict a Japanese adult {gender}, matching the subject's stated gender. "
            "Create a generic editorial person and do not imitate or reproduce any real person's face. "
            "Keep the face unobstructed; do not overlay symbols, keys, or graphics on the face. "
            if gender else
            "Create only a generic Japanese adult; do not imitate or reproduce a real person's face. "
            if allow_unspecified_person else
            "Do not depict a person because the subject's gender is not established. "
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
        "記事タイトルを見出しに転記・短縮せず、話題を要約した独自の短文にしてください。"
        "タグは見出しと異なる短い語句にし、見出し中の語句を繰り返さないでください。"
        "人物を選べるのは主題の性別・属性が入力から明確な場合だけです。性別が判断できなければ object / symbol / environment を選んでください。"
        "人物を描く場合は入力に明記された性別・属性に合わせ、実在人物の顔や肖像を再現しないでください。顔に記号や鍵を重ねる指示は禁止。"
    )
    user_prompt = (
        f"episode_id: {episode_id}\ntitle: {title}\nsubtitle: {subtitle}\n"
        f"key_points: {json.dumps(key_points, ensure_ascii=False)}\n"
        f"source_articles: {json.dumps(source_articles, ensure_ascii=False)}\n"
        f"既定ブランド: {brand or DEFAULT_BRAND}\n"
    )
    try:
        direction = _validate_direction(_extract_json(_ollama_chat(sys_prompt + "\n" + user_prompt)), fallback, title)
        if direction["visual_style"] == "person" and not _subject_gender(subject):
            direction["visual_style"] = "object"
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
            preserve_scene_right=True,
        )
    direction["scene_prompt"] = _scene_prompt(
        direction, subject, allow_unspecified_person=str(episode_id) == "605"
    )
    if str(episode_id) == "605":
        direction["scene_prompt"] += (
            " Keep the entire head and face fully inside the rightmost third, with clear space from the vertical two-thirds boundary; "
            "no part of the face may touch or cross that boundary. Dress the person in casual office clothing, such as a collared shirt or knit top, "
            "in a relaxed contemporary office; avoid hospital gowns, scrubs, lab coats, and clinical settings."
        )
    return direction

# ---------- 2) generate scene via ComfyUI ----------
def _comfyui_workflow(scene_prompt):
    try:
        workflow = json.loads(COMFYUI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"ComfyUI workflow could not be loaded: {COMFYUI_WORKFLOW_PATH}") from exc
    if not isinstance(workflow, dict):
        raise RuntimeError("ComfyUI workflow must be an API-format object")
    try:
        encoder = workflow["452"]
        latent = workflow["456"]
        noise = workflow["488"]
        save = workflow["462"]
        if (encoder.get("class_type") != "TextEncodeQwenImage21"
                or latent.get("class_type") != "EmptyLatentImage"
                or noise.get("class_type") != "RandomNoise"
                or save.get("class_type") != "SaveImage"):
            raise KeyError("unexpected node types")
        encoder["inputs"]["prompt"] = scene_prompt
        # The ComfyUI node rejects missing resolution even though the template
        # JSON omits it. Keep the required text-encoder setting explicit.
        encoder["inputs"]["resolution"] = 1024
        noise["inputs"]["noise_seed"] = secrets.randbelow(2**64)
        save["inputs"]["filename_prefix"] = "thumb_mag"
    except (KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError("ComfyUI workflow is missing the expected Qwen node inputs") from exc
    return workflow


def _comfyui_error_message(history_entry):
    status = history_entry.get("status", {})
    messages = status.get("messages", []) if isinstance(status, dict) else []
    for message in messages:
        if isinstance(message, (list, tuple)) and len(message) > 1:
            detail = message[1]
            if isinstance(detail, dict) and detail.get("exception_message"):
                return str(detail["exception_message"])
    return "ComfyUI reported a generation error"


class ComfyUICleanupPending(RuntimeError):
    """The submitted job may still be active, so the shared busy gate stays held."""

    def __init__(self, state, cause):
        self.state = state
        prompt_id = state.get("prompt_id")
        label = prompt_id if prompt_id else "unknown submission"
        super().__init__(f"ComfyUI job cleanup is pending ({label}): {cause}")


def _write_comfyui_state(state):
    COMFYUI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=COMFYUI_STATE_PATH.parent,
        prefix=".comfyui-state-", suffix=".tmp", delete=False,
    ) as state_file:
        json.dump(state, state_file)
        temp_path = state_file.name
    os.replace(temp_path, COMFYUI_STATE_PATH)


def _clear_comfyui_state():
    try:
        COMFYUI_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        log.exception("could not clear ComfyUI recovery state")


def _queue_ids(queue_entries):
    if not isinstance(queue_entries, list):
        raise RuntimeError("ComfyUI /queue returned an invalid queue")
    ids = set()
    for item in queue_entries:
        if isinstance(item, (list, tuple)) and len(item) > 1 and isinstance(item[1], str):
            ids.add(item[1])
        elif isinstance(item, dict) and isinstance(item.get("prompt_id"), str):
            ids.add(item["prompt_id"])
        else:
            raise RuntimeError("ComfyUI /queue returned an unrecognized job entry")
    return ids


def _history_entry(client, prompt_id):
    response = client.get(f"{COMFYUI_URL}/history/{prompt_id}")
    response.raise_for_status()
    history = response.json()
    return history.get(prompt_id) if isinstance(history, dict) else None


def _cancel_and_confirm_comfyui_job(prompt_id):
    """Cancel this job and wait until history is terminal or it leaves the queue."""
    deadline = time.monotonic() + COMFYUI_CLEANUP_TIMEOUT
    interrupt_sent = False
    delete_sent = False
    with httpx.Client(timeout=COMFYUI_REQUEST_TIMEOUT) as client:
        while True:
            entry = _history_entry(client, prompt_id)
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            status_str = status.get("status_str") if isinstance(status, dict) else None
            if status_str in {"success", "error"}:
                return

            response = client.get(f"{COMFYUI_URL}/queue")
            response.raise_for_status()
            queue_data = response.json()
            if (not isinstance(queue_data, dict)
                    or "queue_running" not in queue_data
                    or "queue_pending" not in queue_data):
                raise RuntimeError("ComfyUI /queue returned an invalid response")
            running = _queue_ids(queue_data["queue_running"])
            pending = _queue_ids(queue_data["queue_pending"])

            if prompt_id in pending and not delete_sent:
                response = client.post(
                    f"{COMFYUI_URL}/queue", json={"delete": [prompt_id]}
                )
                response.raise_for_status()
                delete_sent = True
            elif prompt_id in running and not interrupt_sent:
                response = client.post(
                    f"{COMFYUI_URL}/interrupt", json={"prompt_id": prompt_id}
                )
                response.raise_for_status()
                interrupt_sent = True
            elif prompt_id not in running and prompt_id not in pending:
                return

            if time.monotonic() >= deadline:
                raise TimeoutError("ComfyUI job cancellation was not confirmed")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))


def _wait_until_comfyui_idle():
    """Resolve a submission with no known prompt ID by requiring a quiet queue."""
    deadline = None
    idle_since = None
    with httpx.Client(timeout=COMFYUI_REQUEST_TIMEOUT) as client:
        while True:
            response = client.get(f"{COMFYUI_URL}/queue")
            response.raise_for_status()
            queue_data = response.json()
            if (not isinstance(queue_data, dict)
                    or "queue_running" not in queue_data
                    or "queue_pending" not in queue_data):
                raise RuntimeError("ComfyUI /queue returned an invalid response")
            active = _queue_ids(queue_data["queue_running"])
            pending = _queue_ids(queue_data["queue_pending"])
            now = time.monotonic()
            if active or pending:
                idle_since = None
                if deadline is None:
                    deadline = now + COMFYUI_CLEANUP_TIMEOUT
            else:
                if idle_since is None:
                    idle_since = now
                    # Start the timeout with the quiet observation window. The
                    # HTTP request that produced this first empty snapshot is
                    # outside the interval being measured.
                    deadline = now + max(
                        COMFYUI_CLEANUP_TIMEOUT, COMFYUI_UNKNOWN_QUIET_PERIOD
                    )
                elif now - idle_since >= COMFYUI_UNKNOWN_QUIET_PERIOD:
                    return
            if deadline is not None and now >= deadline:
                raise TimeoutError("ComfyUI idle state could not be confirmed")
            sleep_for = 0.25 if deadline is None else min(0.25, max(0, deadline - now))
            time.sleep(sleep_for)


def _cleanup_comfyui_state(state):
    if state.get("submitted") and state.get("prompt_id"):
        _cancel_and_confirm_comfyui_job(state["prompt_id"])
    else:
        _wait_until_comfyui_idle()


def _recover_comfyui_state(state):
    while True:
        try:
            _cleanup_comfyui_state(state)
            _clear_comfyui_state()
            log.info("ComfyUI job is confirmed inactive; releasing shared busy gate")
            busy_down()
            return
        except Exception as exc:
            log.warning("ComfyUI recovery is waiting for service availability: %s", exc)
            time.sleep(COMFYUI_RECOVERY_RETRY)


def _start_comfyui_recovery(state):
    threading.Thread(
        target=_recover_comfyui_state,
        args=(state,),
        name="comfyui-job-recovery",
        daemon=True,
    ).start()


def gen_scene(scene_prompt):
    deadline = time.monotonic() + COMFYUI_JOB_TIMEOUT
    workflow = _comfyui_workflow(scene_prompt)
    prompt_id = str(uuid.uuid4())
    state = {"prompt_id": prompt_id, "submitted": False}
    _write_comfyui_state(state)
    job_finished = False
    try:
        with httpx.Client(timeout=COMFYUI_REQUEST_TIMEOUT) as client:
            response = client.post(
                f"{COMFYUI_URL}/prompt",
                json={
                    "prompt": workflow,
                    "extra_data": {},
                    "prompt_id": prompt_id,
                },
            )
            response.raise_for_status()
            data = response.json()
            returned_prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
            if not isinstance(returned_prompt_id, str) or not returned_prompt_id:
                raise RuntimeError("ComfyUI /prompt returned no prompt_id")
            prompt_id = returned_prompt_id
            state = {"prompt_id": prompt_id, "submitted": True}
            _write_comfyui_state(state)

            while True:
                if time.monotonic() >= deadline:
                    raise TimeoutError("ComfyUI scene generation timed out")
                entry = _history_entry(client, prompt_id)
                if entry:
                    status = entry.get("status", {})
                    status_str = status.get("status_str") if isinstance(status, dict) else None
                    if status_str == "error":
                        job_finished = True
                        _clear_comfyui_state()
                        raise RuntimeError(_comfyui_error_message(entry))
                    if status_str == "success":
                        job_finished = True
                        _clear_comfyui_state()
                        images = entry.get("outputs", {}).get("462", {}).get("images", [])
                        if not images or not isinstance(images[0], dict):
                            raise RuntimeError("ComfyUI completed without a SaveImage output")
                        image_info = images[0]
                        image_response = client.get(
                            f"{COMFYUI_URL}/view",
                            params={
                                "filename": image_info.get("filename", ""),
                                "subfolder": image_info.get("subfolder", ""),
                                "type": image_info.get("type", "output"),
                            },
                        )
                        image_response.raise_for_status()
                        if not image_response.content:
                            raise RuntimeError("ComfyUI returned an empty scene image")
                        return Image.open(BytesIO(image_response.content)).convert("RGB").resize(
                            (WIDTH, HEIGHT)
                        )
                time.sleep(min(COMFYUI_POLL_INTERVAL, max(0, deadline - time.monotonic())))
    except Exception as exc:
        definitely_rejected = (
            not state.get("submitted")
            and isinstance(exc, httpx.HTTPStatusError)
            and 400 <= exc.response.status_code < 500
        )
        if definitely_rejected:
            _clear_comfyui_state()
        elif not job_finished:
            try:
                _cleanup_comfyui_state(state)
                _clear_comfyui_state()
            except Exception as cleanup_exc:
                try:
                    _write_comfyui_state(state)
                except OSError:
                    log.exception("could not persist pending ComfyUI recovery state")
                raise ComfyUICleanupPending(state, cleanup_exc) from exc
        if isinstance(exc, httpx.TimeoutException):
            raise TimeoutError("ComfyUI request timed out") from exc
        if isinstance(exc, httpx.HTTPStatusError):
            detail = exc.response.text[:500]
            raise RuntimeError(
                f"ComfyUI returned HTTP {exc.response.status_code}: {detail}"
            ) from exc
        if isinstance(exc, httpx.RequestError):
            raise RuntimeError(f"ComfyUI is unavailable: {exc}") from exc
        raise

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
        if spec.get("preserve_scene_right"):
            # Fit the whole scene into the image area. This shifts it right without
            # discarding source pixels, while leaving a wider panel for the headline.
            shift = int(W * EPISODE_605_SCENE_SHIFT_RATIO)
            fitted = img.resize((W - shift, H), Image.Resampling.LANCZOS)
            img = Image.new("RGB", (W, H), img.getpixel((0, 0)))
            img.paste(fitted, (shift, 0))
    d = ImageDraw.Draw(img, "RGBA")
    # Episode 605 uses a narrower panel so its full generated scene remains visible.
    panel_right = int(W * (EPISODE_605_PANEL_WIDTH_RATIO if spec.get("preserve_scene_right") else 2 / 3))
    # Keep the layer order unambiguous when a generated face overlaps the panel.
    d.rectangle((0, 0, panel_right, H), fill=(*panel, 255))
    d.rectangle((0, 0, 12, H), fill=(*accent, 255))

    left, right = 48, panel_right - 40
    max_width = right - left
    brand_text, brand_font = fit_text(spec["brand"], GOTH, max_width, 27, 15)
    d.text((left, 28), brand_text, font=brand_font, fill=text_color)
    d.rectangle((left, 70, left + min(74, max_width), 74), fill=accent)
    kicker_text, kicker_font = fit_text(str(spec["kicker"]).upper(), DIN, max_width, 29, 14)
    d.text((left, 91), kicker_text, font=kicker_font, fill=muted_color)

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
    tag, tag_font = fit_text(spec["tag"], GOTH, max_width - 24, 23, 13)
    tag_width = int(tag_font.getlength(tag) + 24)
    d.rounded_rectangle((left, tag_y, left + tag_width, tag_y + 38), radius=4,
                        fill=(*accent, 255))
    d.text((left + 12, tag_y + 5), tag, font=tag_font, fill=_contrast_text_color(accent))
    footer_y = H - 39
    d.line((left, footer_y - 11, right, footer_y - 11), fill=(*accent, 200), width=2)
    footer, footer_font = fit_text("WAKARU  /  EXPLAINED", DIN, max_width, 18, 14)
    d.text((left, footer_y), footer, font=footer_font, fill=muted_color)
    return img

# ---------- worker ----------
def process_job(job_id):
    j = jobs[job_id]
    release_busy = True
    # Keep Ollama derive inside the same busy window as image generation.
    wait_for_idle_and_claim(job_id)
    try:
        j["status"] = "derive"
        direction = derive(
            episode_id=j.get("episode_id"), title=j["title"],
            subtitle=j.get("subtitle", j.get("topic", "")),
            key_points=j.get("key_points"), source_articles=j.get("source_articles"), brand=j.get("brand"),
        )
        scene_prompt = direction["scene_prompt"]
        j["scene_prompt"] = scene_prompt
        j["art_direction"] = direction
        j["headline"] = direction["headline"]
        j["highlight"] = direction["tag"]
        if direction.get("visual_style") == "typography":
            scene = None
        else:
            with gen_lock:
                j["status"] = "scene"
                scene = gen_scene(scene_prompt)
        j["status"] = "compose"
        img = compose(scene, direction, j.get("brand"))
        path = OUT_DIR / f"{job_id}.png"
        img.save(path)
        j["path"] = str(path)
        j["status"] = "done"
    except Exception as e:
        log.exception("job %s failed", job_id)
        j["status"] = "failed"; j["error"] = str(e)
        if isinstance(e, ComfyUICleanupPending):
            release_busy = False
            _start_comfyui_recovery(e.state)
    finally:
        if release_busy:
            busy_down()
        j["done_at"] = time.time()

def worker_loop():
    while True:
        process_job(job_q.get())


def _resume_comfyui_recovery():
    if not COMFYUI_STATE_PATH.exists():
        return
    try:
        state = json.loads(COMFYUI_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("state file is not an object")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.error("ComfyUI recovery state is unreadable; waiting for an idle queue: %s", exc)
        state = {"prompt_id": None, "submitted": False}
    _start_comfyui_recovery(state)


_resume_comfyui_recovery()
threading.Thread(target=worker_loop, daemon=True).start()

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
