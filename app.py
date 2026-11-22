"""JARVIS NEXUS Global: Fast Voice, Polished Punjabi, Detailed Docs, Cloud & Google Workspace Ready."""
import ast
import asyncio
import hmac
import io
import json
import operator
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
DB = Path(os.environ.get("JARVIS_DB", str(ROOT / "jarvis.db")))
WORKSPACE_DIR = Path(os.environ.get("JARVIS_WORKSPACE", str(ROOT / "workspace")))
TOKEN = os.environ.get("JARVIS_TOKEN", "")
app = FastAPI(title="JARVIS NEXUS GLOBAL", docs_url=None, redoc_url=None, openapi_url=None)
_hits = defaultdict(deque)
_hit_lock = threading.Lock()
_oauth_states = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,created TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,title TEXT NOT NULL,done INTEGER DEFAULT 0,created TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY,title TEXT NOT NULL,due TEXT NOT NULL,fired INTEGER DEFAULT 0,created TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,detail TEXT,created TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY,v TEXT NOT NULL,updated TEXT)")
    c.commit()
    return c


def kv_get(k, default=""):
    with connect() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return row["v"] if row else default


def kv_set(k, v):
    with connect() as c:
        c.execute(
            "INSERT INTO kv(k,v,updated) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated=excluded.updated",
            (k, v, now()),
        )


def throttle(key, limit=60, window=60):
    t = time.monotonic()
    with _hit_lock:
        if len(_hits) > 10000:
            for k in list(_hits)[:5000]:
                if not _hits[k] or _hits[k][-1] < t - window:
                    _hits.pop(k, None)
        q = _hits[key]
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, "Rate limit exceeded. Try again later.")
        q.append(t)


def auth(request: Request):
    if len(TOKEN) < 32:
        raise HTTPException(503, "JARVIS_TOKEN must be configured (at least 32 characters)")
    supplied = request.headers.get("X-Jarvis-Token", "")
    if not hmac.compare_digest(supplied, TOKEN):
        raise HTTPException(401, "Invalid JARVIS token")
    origin = request.headers.get("origin")
    if origin:
        p = urllib.parse.urlsplit(origin)
        host = request.headers.get("host", "")
        if p.netloc != host or p.scheme not in ("https", "http"):
            raise HTTPException(403, "Cross-origin request blocked")
    throttle("auth:" + supplied[:12], 120)
    return True


@app.middleware("http")
async def secure(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        try:
            throttle("ip:" + request.client.host if request.client else "ip:unknown", 240)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), payment=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; media-src 'self' blob: data:; connect-src 'self'; font-src 'self' data:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.url.path == "/" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class Chat(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    voice_mode: bool = False
    language: str = "auto"


class Task(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class Reminder(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due: str


class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=160)
    content: str = Field(max_length=50000)


OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calc(s):
    if len(s) > 100:
        raise ValueError("Expression too long")

    def walk(n, d=0):
        if d > 15:
            raise ValueError("Expression too deep")
        if isinstance(n, ast.Expression):
            return walk(n.body, d + 1)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float) and abs(n.value) < 1e12:
            return n.value
        if isinstance(n, ast.UnaryOp) and type(n.op) in (ast.UAdd, ast.USub):
            return walk(n.operand, d + 1) * (1 if isinstance(n.op, ast.UAdd) else -1)
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            a, b = walk(n.left, d + 1), walk(n.right, d + 1)
            if isinstance(n.op, ast.Pow) and (abs(b) > 10 or abs(a) > 1e6):
                raise ValueError("Exponent too large")
            if isinstance(n.op, (ast.Div, ast.FloorDiv, ast.Mod)) and b == 0:
                raise ValueError("Division by zero")
            v = OPS[type(n.op)](a, b)
            if abs(v) > 1e15:
                raise ValueError("Result too large")
            return v
        raise ValueError("Only arithmetic allowed")

    return walk(ast.parse(s, mode="eval"))


def audit(action, detail=""):
    with connect() as c:
        c.execute("INSERT INTO audit(action,detail,created) VALUES(?,?,?)", (action, detail[:200], now()))


def resolve_workspace_file(rel_path: str) -> Path:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = rel_path.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith("/") or ".." in Path(cleaned).parts:
        raise HTTPException(400, "Invalid relative workspace path")
    target = (WORKSPACE_DIR / cleaned).resolve()
    base = WORKSPACE_DIR.resolve()
    if base not in target.parents:
        raise HTTPException(400, "Path must stay inside workspace")
    return target


GURMUKHI_PHRASE_FIXES = {
    "ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ": "सत श्री अकाल",
    "ਵਾਹਿਗੁਰੂ ਜੀ ਕਾ ਖਾਲਸਾ ਵਾਹਿਗੁਰੂ ਜੀ ਕੀ ਫਤਿਹ": "वाहेगुरु जी का खालसा वाहेगुरु जी की फतेह",
    "ਤੁਹਾਡੀ": "तुहाडी",
    "ਮਦਦ": "मदद",
    "ਕਰ ਸਕਦੀ ਹਾਂ": "कर सकदी हां",
    "ਕਰਾਂਗੀ": "करांगी",
    "ਸਮਝ ਗਈ": "समझ गई",
    "ਕੋਈ ਗੱਲ ਨਹੀਂ": "कोई गल नहीं",
    "ਬਿਲਕੁਲ": "बिलकुल",
    "ਦੱਸੋ": "दस्सो",
    "ਕਿੱਦਾਂ": "किद्दां",
    "ਤੁਸੀਂ": "तुसीं",
    "ਮੈਂ": "मैं",
    "ਹਾਂਜੀ": "हांजी",
    "ਧੰਨਵਾਦ": "धन्यवाद",
    "ਜਦੋਂ": "जदों",
    "ਲੋੜ": "लोड़",
    "ਬੇਝਿਜਕ": "बेझिझक",
    "ਹਮੇਸ਼ਾ": "हमेशा",
    "ਹਾਜ਼ਰ": "हाज़िर",
    "ਮੌਸਮ": "मौसम",
    "ਚੰਗਾ": "चंगा",
    "ਸੋਹਣਾ": "सोहणा",
    "ਵਧੀਆ": "वधीया",
    "ਅੱਜ": "अज्ज",
    "ਕੱਲ੍ਹ": "कल्ल",
    "ਸਵੇਰ": "सवेर",
    "ਸ਼ਾਮ": "शाम",
    "ਰਾਤ": "रात",
    "ਪੰਜਾਬੀ": "पंजाबी",
    "ਗੱਲਬਾਤ": "गलबात",
}

GURMUKHI_CONSONANTS = {
    "ੳ": "उ", "ਅ": "अ", "ੲ": "इ", "ਸ": "स", "ਹ": "ह",
    "ਕ": "क", "ਖ": "ख", "ਗ": "ग", "ਘ": "घ", "ਙ": "ङ",
    "ਚ": "च", "ਛ": "छ", "ਜ": "ज", "ਝ": "झ", "ਞ": "ञ",
    "ਟ": "ट", "ਠ": "ठ", "ਡ": "ड", "ਢ": "ढ", "ਣ": "ण",
    "ਤ": "त", "ਥ": "थ", "ਦ": "द", "ਧ": "ध", "ਨ": "न",
    "ਪ": "प", "ਫ": "फ", "ਬ": "ब", "ਭ": "भ", "ਮ": "म",
    "ਯ": "य", "ਰ": "र", "ਲ": "ल", "ਵ": "व", "ੜ": "ड़",
    "ਸ਼": "श", "ਖ਼": "ख़", "ਗ਼": "ग़", "ਜ਼": "ज़", "ਫ਼": "फ़", "ਲ਼": "ल",
}

GURMUKHI_MATRAS = {
    "ਾ": "ा", "ਿ": "ि", "ੀ": "ी", "ੁ": "ु", "ੂ": "ू",
    "ੇ": "े", "ੈ": "ै", "ੋ": "ो", "ੌ": "ौ",
}


def normalize_punjabi_speech(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    for pa_phrase, hi_phrase in GURMUKHI_PHRASE_FIXES.items():
        s = s.replace(pa_phrase, hi_phrase)
    if not re.search(r"[\u0A00-\u0A7F]", s):
        return re.sub(r"\s+", " ", s).strip()

    out = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        pair = s[i:i + 2]
        if pair in GURMUKHI_CONSONANTS:
            base = GURMUKHI_CONSONANTS[pair]
            i += 2
        elif ch in GURMUKHI_CONSONANTS:
            base = GURMUKHI_CONSONANTS[ch]
            i += 1
        elif ch in GURMUKHI_MATRAS:
            out.append(GURMUKHI_MATRAS[ch])
            i += 1
            continue
        elif ch in ("ਂ", "ੰ"):
            out.append("ं")
            i += 1
            continue
        elif ch in ("ੱ", "਼", "੍"):
            i += 1
            continue
        elif "\u0A66" <= ch <= "\u0A6F":
            out.append(chr(ord("०") + (ord(ch) - ord("\u0A66"))))
            i += 1
            continue
        elif ch in ("।", "॥"):
            out.append("।")
            i += 1
            continue
        else:
            out.append(ch)
            i += 1
            continue

        while i < n and s[i] in ("਼", "ੱ"):
            i += 1

        if i < n and s[i] == "੍":
            out.append(base + "्")
            i += 1
            continue

        if i < n and s[i] in GURMUKHI_MATRAS:
            matra = GURMUKHI_MATRAS[s[i]]
            i += 1
            nasal = ""
            if i < n and s[i] in ("ਂ", "ੰ"):
                nasal = "ं"
                i += 1
            out.append(base + matra + nasal)
        else:
            nasal = ""
            if i < n and s[i] in ("ਂ", "ੰ"):
                nasal = "ं"
                i += 1
            out.append(base + nasal)

    joined = "".join(out)
    joined = re.sub(r"\s+([।?!,.:;])", r"\1", joined)
    return re.sub(r"\s+", " ", joined).strip()


SYSTEM = (
    "You are JARVIS NEXUS, a natural, warm, fast and concise conversational assistant. "
    "Speak like a helpful human assistant in everyday bolchal (conversational speech), avoiding stiff or overly literary words. "
    "Strictly obey the requested [CONVERSATION LANGUAGE] and script. Never switch languages or scripts unexpectedly. "
    "Avoid introductions such as Hello I am JARVIS unless asked. Do not use markdown headings, "
    "asterisks, bullets, or tables in voice-style answers. Never output tags or brackets like [[SPEAK:...]]. "
    "Always finish your sentence cleanly without cutting off mid-thought. "
    "Never claim you are placing, connecting, or dialing a real phone call unless an actual calling action succeeded; "
    "if asked to call someone, clearly say direct calling is not supported here and offer to look up their contact instead. "
    "Use a consistent warm feminine JARVIS persona: in Hindi say kar sakti hoon, karungi, samajh gayi; "
    "in Punjabi say ਕਰ ਸਕਦੀ ਹਾਂ, ਕਰਾਂਗੀ, ਸਮਝ ਗਈ. "
    "Keep replies clear, complete, natural, and fast."
)


def ai_provider():
    if os.environ.get("GEMINI_API_KEY", "").strip():
        return "gemini"
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return "openai"
    return "none"


def clean_reply_text(raw_reply: str, language: str = "auto") -> str:
    cleaned = re.sub(r"\[\[SPEAK:[\s\S]*?(?:\]\]|$)", "", str(raw_reply or ""), flags=re.IGNORECASE).strip()
    if language == "pa-IN":
        cleaned = re.sub(r"[\u0900-\u097F\u0C00-\u0C7F]+", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned and cleaned[-1] not in ".!?।":
        cleaned += "।" if language == "pa-IN" else "."
    return cleaned


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int = 250, temperature: float = 0.25, timeout: int = 10) -> str:
    provider = ai_provider()
    if provider == "none":
        raise HTTPException(503, "AI is not configured. Set GEMINI_API_KEY or OPENAI_API_KEY on the server.")
    if provider == "gemini":
        key = os.environ["GEMINI_API_KEY"].strip()
        model = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest").strip()
        if not model or not all(c.isalnum() or c in "-_." for c in model):
            raise HTTPException(503, "Invalid GEMINI_MODEL configuration")
        url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    else:
        key = os.environ["OPENAI_API_KEY"].strip()
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "max_completion_tokens": max_tokens,
        }
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.load(response)
        if provider == "gemini":
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            answer = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
        else:
            answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty model reply")
        return answer.strip()
    except urllib.error.HTTPError as e:
        status = e.code
        if status in (401, 403):
            raise HTTPException(502, provider.upper() + " rejected the API key or permissions (upstream " + str(status) + ").") from e
        if status in (500, 502, 503, 504):
            raise HTTPException(503, provider.upper() + " temporarily unavailable (upstream " + str(status) + "). Please retry shortly.") from e
        if status == 429:
            raise HTTPException(503, provider.upper() + " rate limit or quota reached (upstream 429). Check free-tier availability.") from e
        if status == 404:
            raise HTTPException(502, provider.upper() + " model unavailable (upstream 404). Check model configuration.") from e
        raise HTTPException(502, provider.upper() + " provider error (upstream " + str(status) + ").") from e
    except (TimeoutError, urllib.error.URLError) as e:
        raise HTTPException(504, "AI provider connection timed out or failed.") from e
    except Exception as e:
        raise HTTPException(502, "AI provider returned an invalid or empty response.") from e


def ai_reply(message, voice_mode=False, language="auto"):
    language_names = {
        "auto": "the exact language and writing script of the user's question",
        "en-IN": "English",
        "en-US": "English",
        "en-GB": "English",
        "hi-IN": "natural everyday Hindi in Devanagari script",
        "es-ES": "Spanish",
        "fr-FR": "French",
        "de-DE": "German",
        "pt-BR": "Brazilian Portuguese",
        "ar-SA": "Arabic",
        "ja-JP": "Japanese",
        "ko-KR": "Korean",
        "zh-CN": "Mandarin Chinese",
        "it-IT": "Italian",
        "ru-RU": "Russian",
        "bn-IN": "Bengali",
        "ta-IN": "Tamil",
        "te-IN": "Telugu",
        "pa-IN": (
            "polished, natural everyday bolchal Punjabi written STRICTLY in Gurmukhi script "
            "(use clear, simple Punjabi words like ਕਿੱਦਾਂ, ਦੱਸੋ, ਮੈਂ ਕਰ ਸਕਦੀ ਹਾਂ, ਬਿਲਕੁਲ, ਠੀਕ ਹੈ; "
            "avoid stiff bookish/Sanskritized words and never mix Hindi or English in the main reply; "
            "always complete the sentence naturally)"
        ),
        "pa-Latn-IN": "natural everyday bolchal Punjabi written ONLY in Roman (Latin) script, with authentic Punjabi words",
        "ur-PK": "Urdu",
    }
    selected = language_names.get(language, "the language of the question")
    prompt_text = (
        message
        + "\n\n[CONVERSATION LANGUAGE: Respond ONLY in "
        + selected
        + ". Never switch to Hindi or English if Punjabi is selected.]"
    )
    if voice_mode:
        prompt_text += (
            "\n[VOICE RESPONSE: Reply in plain text with no Markdown or tags. "
            "Keep it to 1 complete, warm, natural spoken sentence that never cuts off.]"
        )
    max_tokens = 120 if voice_mode else 360
    answer = call_llm(SYSTEM, prompt_text, max_tokens=max_tokens, temperature=0.2, timeout=10)
    cleaned = clean_reply_text(answer, language)
    speak_str = normalize_punjabi_speech(cleaned) if language == "pa-IN" else cleaned
    return cleaned, speak_str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1800)
    language: str = Field(default="hi-IN", pattern="^(pa-IN|hi-IN|en-IN|en-GB|en-US)$")


TTS_VOICES = {
    "hi-IN": "hi-IN-SwaraNeural",
    "en-IN": "en-IN-NeerjaNeural",
    "en-US": "en-US-JennyNeural",
    "en-GB": "en-GB-SoniaNeural",
}


@app.post("/api/tts", dependencies=[Depends(auth)])
async def tts(req: SpeechRequest):
    throttle("tts:" + TOKEN[:12], 50, 60)
    try:
        import edge_tts
    except ImportError as exc:
        raise HTTPException(503, "Install edge-tts in the active Python environment") from exc
    try:
        fallback = False
        spoken_input = req.text.strip()
        if req.language == "pa-IN":
            selected = TTS_VOICES["hi-IN"]
            fallback = True
            rate = "-4%"
            if re.search(r"[\u0A00-\u0A7F]", spoken_input):
                spoken_input = normalize_punjabi_speech(spoken_input)
        else:
            selected = TTS_VOICES[req.language]
            rate = "+8%" if req.language.startswith("en") else "+4%"

        async def synthesize():
            data = bytearray()
            async for chunk in edge_tts.Communicate(spoken_input, voice=selected, rate=rate).stream():
                if chunk.get("type") == "audio":
                    data.extend(chunk["data"])
                    if len(data) > 8_000_000:
                        raise ValueError("Audio exceeds size limit")
            return bytes(data)

        data = await asyncio.wait_for(synthesize(), timeout=6)
        if len(data) < 600:
            raise ValueError("Incomplete or empty audio received")
        if not (data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and (data[1] & 224) == 224)):
            raise ValueError("TTS returned data that does not look like MP3")
        return Response(
            data,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'inline; filename="jarvis-speech.mp3"',
                "X-Jarvis-TTS-Voice": selected,
                "X-Jarvis-TTS-Fallback": "hi-IN" if fallback else "none",
            },
        )
    except HTTPException:
        raise
    except asyncio.TimeoutError as exc:
        raise HTTPException(504, "Neural speech timed out") from exc
    except Exception as exc:
        raise HTTPException(502, "Neural speech generation failed (" + type(exc).__name__ + ")") from exc


class DocumentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=30000)
    format: str


def expand_detailed_content(title: str, content: str) -> str:
    raw = content.strip()
    if len(raw) >= 450 and "\n" in raw:
        return raw
    if ai_provider() == "none":
        return raw
    doc_prompt = (
        f"Create a clear, thorough, well-structured document for the title: '{title}'.\n"
        f"User input/notes: {raw}\n\n"
        "Include these exact sections using Markdown headings:\n"
        "## Overview\n"
        "Write 2 clear paragraphs explaining the topic and context.\n"
        "## Key Details & Breakdown\n"
        "Write 4 to 6 bullet points covering core concepts, features, or steps with practical detail.\n"
        "## Practical Use Cases & Best Practices\n"
        "Write 3 bullet points or 1 short paragraph showing real-world application and tips.\n"
        "## Summary\n"
        "Write 1 concise concluding paragraph.\n"
        "Use clear, accurate, easy-to-read English unless the input is clearly in another language."
    )
    try:
        return call_llm(
            "You are a structured technical and business document writer. Produce thorough, well-organized, accurate content.",
            doc_prompt,
            max_tokens=900,
            temperature=0.3,
            timeout=15,
        )
    except Exception:
        return raw


def document_sections(text):
    sections = []
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if not block:
            continue
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            if re.match(r"^#{1,4}\s+", line):
                sections.append(("heading", re.sub(r"^#{1,4}\s+", "", line)))
            elif re.match(r"^\*\*[^*]+\*\*\s*:?$", line):
                sections.append(("heading", line.strip("* :")))
            elif re.match(r"^[-*]\s+", line):
                sections.append(("bullet", re.sub(r"^[-*]\s+", "", line)))
            else:
                sections.append(("paragraph", line.replace("**", "")))
    return sections[:250]


@app.post("/api/document", dependencies=[Depends(auth)])
def generate_document(req: DocumentRequest):
    throttle("document:" + TOKEN[:12], 15, 60)
    if req.format not in ("pdf", "docx"):
        raise HTTPException(400, "Choose pdf or docx")
    detailed_text = expand_detailed_content(req.title, req.content)
    sections = document_sections(detailed_text)
    try:
        if req.format == "docx":
            from docx import Document

            d = Document()
            sec = d.sections[0]
            sec.header.paragraphs[0].text = "JARVIS NEXUS  |  AI DOCUMENT"
            d.add_heading(req.title, 0)
            for typ, txt in sections:
                if typ == "heading":
                    d.add_heading(txt, level=1)
                elif typ == "bullet":
                    d.add_paragraph(txt, style="List Bullet")
                else:
                    d.add_paragraph(txt)
            d.add_paragraph("Prepared using JARVIS AI. Verify factual claims before sharing.")
            bio = io.BytesIO()
            d.save(bio)
            data = bio.getvalue()
            media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ext = "docx"
        else:
            from reportlab.lib import colors
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
            from xml.sax.saxutils import escape

            font = "Helvetica"
            has_gurmukhi_font = False
            candidates = [
                str(ROOT / "fonts" / "NotoSansGurmukhi-Regular.ttf"),
                str(ROOT / "fonts" / "NotoSans-Regular.ttf"),
                "C:/Windows/Fonts/raavi.ttf",
                "/usr/share/fonts/truetype/noto/NotoSansGurmukhi-Regular.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            for candidate in candidates:
                if Path(candidate).is_file():
                    try:
                        pdfmetrics.registerFont(TTFont("JarvisUnicode", candidate))
                        font = "JarvisUnicode"
                        if "gurmukhi" in candidate.lower() or "raavi" in candidate.lower():
                            has_gurmukhi_font = True
                        break
                    except Exception:
                        pass

            def fmt_pdf(s: str) -> str:
                val = normalize_punjabi_speech(s) if not has_gurmukhi_font else s
                return escape(val)

            styles = getSampleStyleSheet()
            styles.add(ParagraphStyle(name="JTitle", fontName=font, fontSize=19, leading=26, textColor=colors.HexColor("#15304f"), spaceAfter=18))
            styles.add(ParagraphStyle(name="JHead", fontName=font, fontSize=13, leading=19, textColor=colors.HexColor("#087c9d"), spaceBefore=13, spaceAfter=7))
            styles.add(ParagraphStyle(name="JBody", fontName=font, fontSize=10.5, leading=17, spaceAfter=9))
            bio = io.BytesIO()
            doc = SimpleDocTemplate(bio, pagesize=(595.28, 841.89), leftMargin=52, rightMargin=52, topMargin=55, bottomMargin=55, title=fmt_pdf(req.title))
            story = [Paragraph(fmt_pdf(req.title), styles["JTitle"])]
            for typ, txt in sections:
                style = styles["JHead"] if typ == "heading" else styles["JBody"]
                story.append(Paragraph(("• " if typ == "bullet" else "") + fmt_pdf(txt), style))
            story.append(Spacer(1, 20))
            story.append(Paragraph("Prepared using JARVIS AI. Verify factual claims before sharing.", styles["JBody"]))

            def footer(c, d):
                c.setFont(font, 8)
                c.setFillColor(colors.grey)
                c.drawString(52, 30, "JARVIS NEXUS  |  AI-generated draft")
                c.drawRightString(542, 30, str(d.page))

            doc.build(story, onFirstPage=footer, onLaterPages=footer)
            data = bio.getvalue()
            media = "application/pdf"
            ext = "pdf"
        filename = "JARVIS-" + re.sub(r"[^A-Za-z0-9_-]+", "-", req.title).strip("-")[:55] + "." + ext
        return Response(
            content=data,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
        )
    except Exception as e:
        raise HTTPException(500, "Document generation failed. Check server logs and installed document dependencies.") from e


def google_oauth_config(request: Request):
    cid = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    csec = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
    if not redirect_uri:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("host", "127.0.0.1:8000")
        redirect_uri = f"{proto}://{host}/api/google/callback"
    return cid, csec, redirect_uri


def google_access_token(request: Request):
    tok = kv_get("google_access_token")
    exp = float(kv_get("google_token_expires", "0") or "0")
    if tok and time.time() < exp - 60:
        return tok
    refresh_tok = kv_get("google_refresh_token")
    cid, csec, _ = google_oauth_config(request)
    if not (refresh_tok and cid and csec):
        raise HTTPException(401, "Google account not connected. Click Connect Google first.")
    body = urllib.parse.urlencode(
        {"client_id": cid, "client_secret": csec, "refresh_token": refresh_tok, "grant_type": "refresh_token"}
    ).encode("utf-8")
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.load(resp)
        tok = data["access_token"]
        kv_set("google_access_token", tok)
        kv_set("google_token_expires", str(time.time() + int(data.get("expires_in", 3600))))
        return tok
    except Exception as exc:
        raise HTTPException(401, "Google session expired. Reconnect Google account.") from exc


@app.get("/api/google/status", dependencies=[Depends(auth)])
def google_status(request: Request):
    cid, csec, _ = google_oauth_config(request)
    connected = bool(kv_get("google_refresh_token") or kv_get("google_access_token"))
    return {"configured": bool(cid and csec), "connected": connected}


@app.get("/api/google/auth-url", dependencies=[Depends(auth)])
def google_auth_url(request: Request):
    cid, csec, redirect_uri = google_oauth_config(request)
    if not (cid and csec):
        raise HTTPException(503, "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in server environment variables.")
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time() + 600
    scopes = " ".join([
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/contacts.readonly",
    ])
    params = urllib.parse.urlencode({
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?" + params}


@app.get("/api/google/callback")
def google_callback(request: Request, code: str = "", state: str = ""):
    exp = _oauth_states.pop(state, 0)
    if not code or exp < time.time():
        raise HTTPException(400, "Invalid or expired OAuth state")
    cid, csec, redirect_uri = google_oauth_config(request)
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": cid,
        "client_secret": csec,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request("https://oauth2.googleapis.com/token", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        kv_set("google_access_token", data["access_token"])
        kv_set("google_token_expires", str(time.time() + int(data.get("expires_in", 3600))))
        if data.get("refresh_token"):
            kv_set("google_refresh_token", data["refresh_token"])
        audit("google.connect", "OAuth connected")
        return RedirectResponse(url="/?google=connected")
    except Exception as exc:
        raise HTTPException(502, "Failed to exchange Google OAuth code") from exc


@app.get("/api/google/contacts", dependencies=[Depends(auth)])
def google_contacts(request: Request, q: str = ""):
    tok = google_access_token(request)
    url = "https://people.googleapis.com/v1/people/me/connections?personFields=names,emailAddresses,phoneNumbers&pageSize=100"
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.load(resp)
        out = []
        ql = q.strip().lower()
        for person in data.get("connections", []):
            name = (person.get("names") or [{}])[0].get("displayName", "")
            email = (person.get("emailAddresses") or [{}])[0].get("value", "")
            phone = (person.get("phoneNumbers") or [{}])[0].get("value", "")
            if ql and ql not in (name + " " + email + " " + phone).lower():
                continue
            if name or email or phone:
                out.append({"name": name or email or phone, "email": email, "phone": phone})
        return {"contacts": out[:30]}
    except Exception as exc:
        raise HTTPException(502, "Could not fetch Google Contacts") from exc


@app.get("/api/google/emails", dependencies=[Depends(auth)])
def google_emails(request: Request):
    tok = google_access_token(request)
    list_req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=6",
        headers={"Authorization": "Bearer " + tok},
    )
    try:
        with urllib.request.urlopen(list_req, timeout=12) as resp:
            msgs = json.load(resp).get("messages", [])
        items = []
        for m in msgs[:5]:
            m_req = urllib.request.Request(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{m['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=From",
                headers={"Authorization": "Bearer " + tok},
            )
            with urllib.request.urlopen(m_req, timeout=10) as mr:
                md = json.load(mr)
            hdrs = {h["name"].lower(): h["value"] for h in md.get("payload", {}).get("headers", [])}
            items.append({"id": m["id"], "from": hdrs.get("from", ""), "subject": hdrs.get("subject", "(No subject)"), "snippet": md.get("snippet", "")[:140]})
        return {"emails": items}
    except Exception as exc:
        raise HTTPException(502, "Could not fetch Gmail inbox") from exc


@app.get("/api/files", dependencies=[Depends(auth)])
def list_workspace_files():
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for p in sorted(WORKSPACE_DIR.rglob("*")):
        if p.is_file():
            items.append({"path": p.relative_to(WORKSPACE_DIR).as_posix(), "bytes": p.stat().st_size})
    return items[:100]


@app.post("/api/files/write", dependencies=[Depends(auth)])
def write_workspace_file(req: FileWriteRequest):
    target = resolve_workspace_file(req.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    rel = target.relative_to(WORKSPACE_DIR).as_posix()
    audit("file.write", rel)
    return {"path": rel, "bytes": target.stat().st_size}


@app.get("/api/files/read", dependencies=[Depends(auth)])
def read_workspace_file(path: str):
    target = resolve_workspace_file(path)
    if not target.is_file():
        raise HTTPException(404, "File not found")
    return {"path": target.relative_to(WORKSPACE_DIR).as_posix(), "content": target.read_text(encoding="utf-8")}


@app.get("/api/health")
def health():
    provider = ai_provider()
    return {
        "ok": True,
        "service": "jarvis-nexus-global",
        "version": "1.13.0",
        "ai_configured": provider != "none",
        "ai_provider": provider,
        "token_configured": len(TOKEN) >= 32,
    }


@app.get("/api/tasks", dependencies=[Depends(auth)])
def tasks():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 200")]


@app.post("/api/tasks", dependencies=[Depends(auth)])
def add_task(t: Task):
    if not t.title.strip():
        raise HTTPException(400, "Empty title")
    with connect() as c:
        cur = c.execute("INSERT INTO tasks(title,created) VALUES (?,?)", (t.title.strip(), now()))
        newid = cur.lastrowid
    audit("task.create", str(newid))
    return {"id": newid, "title": t.title.strip(), "done": 0}


@app.post("/api/tasks/{task_id}/toggle", dependencies=[Depends(auth)])
def toggle(task_id: int):
    with connect() as c:
        cur = c.execute("UPDATE tasks SET done=1-done WHERE id=?", (task_id,))
        if not cur.rowcount:
            raise HTTPException(404, "Task not found")
    audit("task.toggle", str(task_id))
    return {"ok": True}


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(auth)])
def delete(task_id: int):
    with connect() as c:
        cur = c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        if not cur.rowcount:
            raise HTTPException(404, "Task not found")
    audit("task.delete", str(task_id))
    return {"ok": True}


@app.get("/api/history", dependencies=[Depends(auth)])
def history():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 60) ORDER BY id")]


@app.post("/api/chat", dependencies=[Depends(auth)])
def chat(q: Chat):
    throttle("chat:" + TOKEN[:12], 30, 60)
    msg = q.message.strip()
    if not msg:
        raise HTTPException(400, "Empty message")
    low = msg.lower()
    speak_text = None
    try:
        if low.startswith(("calculate ", "calc ")):
            expr = msg.split(" ", 1)[1]
            reply = f"{expr} = {calc(expr)}"
            mode = "calculator"
        elif low in ("time", "date", "today", "what time is it"):
            reply = "Current UTC time: " + now()
            mode = "clock"
        elif low.startswith("add task "):
            task = add_task(Task(title=msg[9:]))
            reply = "Task created: " + task["title"]
            mode = "tasks"
        elif low in ("help", "commands"):
            reply = "Try: calculate 23*7, add task Review proposal, time. AI chat uses your configured Gemini/OpenAI provider."
            mode = "help"
        else:
            reply, speak_text = ai_reply(msg, q.voice_mode, q.language)
            mode = "ai"
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError) as e:
        raise HTTPException(400, str(e))
    with connect() as c:
        c.execute("INSERT INTO messages(role,content,created) VALUES(?,?,?)", ("user", msg, now()))
        c.execute("INSERT INTO messages(role,content,created) VALUES(?,?,?)", ("assistant", reply, now()))
    return {"reply": reply, "speak_text": speak_text or reply, "mode": mode}


@app.post("/api/reminders", dependencies=[Depends(auth)])
def add_reminder(r: Reminder):
    try:
        due = datetime.fromisoformat(r.due.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid due date")
    if due.tzinfo is None or due <= datetime.now(timezone.utc):
        raise HTTPException(400, "Future timezone-aware date required")
    if not r.title.strip():
        raise HTTPException(400, "Empty title")
    with connect() as c:
        cur = c.execute("INSERT INTO reminders(title,due,created) VALUES(?,?,?)", (r.title.strip(), due.astimezone(timezone.utc).isoformat(), now()))
        newid = cur.lastrowid
    audit("reminder.create", str(newid))
    return {"id": newid, "due": due.isoformat()}


@app.get("/api/reminders", dependencies=[Depends(auth)])
def reminders():
    with connect() as c:
        c.execute("UPDATE reminders SET fired=1 WHERE fired=0 AND due<=?", (now(),))
        return [dict(r) for r in c.execute("SELECT * FROM reminders ORDER BY due DESC LIMIT 100")]


@app.get("/api/audit", dependencies=[Depends(auth)])
def audit_log():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 40")]


@app.get("/api/research", dependencies=[Depends(auth)])
def research(q: str):
    if not q.strip() or len(q) > 120:
        raise HTTPException(400, "Query must be 1–120 characters")
    headers = {"User-Agent": "JARVIS-NEXUS-Global/1.0 (research prototype)"}
    gen_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": 5, "prop": "extracts", "exintro": 1, "explaintext": 1, "exsentences": 2, "format": "json"}
    )
    try:
        with urllib.request.urlopen(urllib.request.Request(gen_url, headers=headers), timeout=10) as r:
            data = json.load(r)
        results = [
            {
                "title": p.get("title", ""),
                "summary": p.get("extract", "")[:600],
                "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p.get("title", "").replace(" ", "_")),
            }
            for p in data.get("query", {}).get("pages", {}).values()
            if p.get("title")
        ]
        if not results:
            sr_url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
                {"action": "query", "list": "search", "srsearch": q, "srlimit": 5, "format": "json"}
            )
            with urllib.request.urlopen(urllib.request.Request(sr_url, headers=headers), timeout=10) as sr:
                sdata = json.load(sr)
            results = [
                {
                    "title": item.get("title", ""),
                    "summary": re.sub(r"<[^>]+>", "", item.get("snippet", ""))[:600] or "Wikipedia search match.",
                    "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(item.get("title", "").replace(" ", "_")),
                }
                for item in sdata.get("query", {}).get("search", [])
                if item.get("title")
            ]
    except Exception as e:
        raise HTTPException(502, "Wikipedia lookup unavailable") from e
    return {"provider": "Wikipedia", "results": results}


class DesktopLaunch(BaseModel):
    name: str
    confirm: bool = False


@app.post("/api/desktop/open", dependencies=[Depends(auth)])
def desktop_open(req: DesktopLaunch, request: Request):
    if not req.confirm:
        raise HTTPException(400, "Explicit confirmation required")
    if sys.platform != "win32" or os.environ.get("JARVIS_LOCAL_DESKTOP", "") != "1":
        raise HTTPException(501, "Local desktop launch is disabled. Set JARVIS_LOCAL_DESKTOP=1 only on your own Windows PC.")
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403, "Localhost only")
    if request.headers.get("host", "").split(":")[0] not in ("127.0.0.1", "localhost", "[::1]"):
        raise HTTPException(403, "Localhost host required")
    commands = {"notepad": ["notepad.exe"], "calculator": ["calc.exe"], "paint": ["mspaint.exe"], "explorer": ["explorer.exe"]}
    if req.name not in commands:
        raise HTTPException(400, "Unsupported desktop application")
    try:
        subprocess.Popen(commands[req.name], shell=False, close_fds=True)
    except OSError as exc:
        raise HTTPException(502, "Windows could not launch " + req.name) from exc
    audit("desktop.open", req.name)
    return {"launched": req.name}


class VideoLookup(BaseModel):
    query: str = Field(min_length=2, max_length=140)


@app.post("/api/video/lookup", dependencies=[Depends(auth)])
def video_lookup(req: VideoLookup):
    """Return a public YouTube video ID; do not download or proxy media."""
    throttle("video:" + TOKEN[:12], 20, 60)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise HTTPException(503, "Video lookup requires yt-dlp (pip install yt-dlp)") from exc
    try:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "socket_timeout": 3,
            "retries": 0,
            "extractor_retries": 0,
            "noplaylist": True,
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info("ytsearch2:" + req.query, download=False)
        entries = (info or {}).get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            vid = entry.get("id", "")
            if isinstance(vid, str) and re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                return {
                    "id": vid,
                    "title": str(entry.get("title") or req.query)[:180],
                    "watch_url": "https://www.youtube.com/watch?v=" + vid,
                }
        raise HTTPException(404, "No playable video identifier found; open YouTube search instead")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, "YouTube lookup failed; open YouTube search instead") from exc


@app.get("/.well-known/assetlinks.json", include_in_schema=False)
def assetlinks():
    pkg = os.environ.get("TWA_PACKAGE_NAME", "com.jarvis.nexus.app").strip()
    fp = os.environ.get("TWA_SHA256_FINGERPRINT", "").strip()
    if not fp:
        return JSONResponse([])
    return JSONResponse([
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {"namespace": "android_app", "package_name": pkg, "sha256_cert_fingerprints": [fp]},
        }
    ])


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "index.html").read_text(encoding="utf-8")


@app.get("/{filename}", include_in_schema=False)
def static(filename: str):
    if filename not in ("hologram.webp", "reference-hero.webp", "jarvis-nexus-logo.png", "icon-192.png", "icon-512.png", "manifest.webmanifest"):
        raise HTTPException(404, "Not found")
    return FileResponse(ROOT / filename, media_type="application/manifest+json" if filename.endswith("webmanifest") else None)
