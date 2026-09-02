#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'_-]{0,63}")
SPACE_RE = re.compile(r"\s+")
HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
DEVANAGARI_LETTER_RE = re.compile(r"[\u0904-\u0939\u0958-\u0961]")
SANSKRIT_IAST_RE = re.compile(
    r"[\u0101\u012b\u016b\u1e5b\u1e5d\u1e37\u1e39\u1e43\u1e41\u1e25\u015b\u1e63\u1e45\u00f1\u1e6d\u1e0d\u1e47"
    r"\u0100\u012a\u016a\u1e5a\u1e5c\u1e36\u1e38\u1e42\u1e40\u1e24\u015a\u1e62\u1e44\u00d1\u1e6c\u1e0c\u1e46]"
)
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_SERVICE_ORDER = ("deepseek", "openai", "google")
EMPTY_SELECTION_DELAY_MS = 300
STABLE_SELECTION_DELAY_MS = 650
DBUS_SERVICE = "org.local.SelectionTranslator"
DBUS_PATH = "/org/local/SelectionTranslator"
DBUS_INTERFACE = "org.local.SelectionTranslator"
ENGLISH_TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. Translate the user's English text into Simplified Chinese. "
    "Return only the translated Chinese text. Do not explain, add notes, quote the source, or use Markdown."
)
SANSKRIT_TRANSLATION_SYSTEM_PROMPT = (
    "You are a Sanskrit translation engine. Translate the user's Sanskrit text into Simplified Chinese. "
    "The source may use Devanagari or IAST transliteration, with optional hyphens or spaces. "
    "Analyze compounds and inflection internally, including case endings, and express their relation naturally in Chinese. "
    "Use established Chinese Buddhist terminology and preserve proper names when no established translation exists. "
    "Return only the translated Chinese text. Do not explain, add notes, quote the source, or use Markdown."
)
LATIN_TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. The user's Latin-script text may be English or Sanskrit transliteration "
    "written in IAST or plain ASCII. Identify the language internally and translate it into Simplified Chinese. "
    "For Sanskrit, analyze compounds and inflection internally, use established Chinese Buddhist terminology, "
    "and express case relations naturally. Return only the translated Chinese text. "
    "Do not explain, add notes, quote the source, or use Markdown."
)
CHINESE_TRANSLATION_SYSTEM_PROMPT = (
    "You are a Chinese translation and pronunciation engine. Translate the user's Chinese text into natural English "
    "and provide standard Hanyu Pinyin with tone marks. Return exactly two plain-text lines: the English translation "
    "on the first line, and '拼音：' followed by the pinyin on the second line. Do not add notes, quote the source, "
    "or use Markdown."
)


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def emit_state(payload, write=True):
    if write:
        write_shared_state(payload)
    emit(payload)


def run_text_command(command, timeout=0.35):
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip()


def read_selection(include_clipboard=True):
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    candidates = []

    if session_type == "wayland":
        candidates.append(["wl-paste", "--primary", "--no-newline"])
        if include_clipboard:
            candidates.append(["wl-paste", "--no-newline"])
    else:
        candidates.extend([
            ["xclip", "-selection", "primary", "-o"],
            ["xsel", "-p", "-o"],
            ["wl-paste", "--primary", "--no-newline"],
        ])
        if include_clipboard:
            candidates.append(["wl-paste", "--no-newline"])

    for command in candidates:
        text = run_text_command(command)
        if text:
            return text
    return ""


def read_selection_source(source):
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland":
        command = ["wl-paste", "--primary", "--no-newline"] if source == "primary" else ["wl-paste", "--no-newline"]
        return run_text_command(command)
    if source == "primary":
        for command in (["xclip", "-selection", "primary", "-o"], ["xsel", "-p", "-o"]):
            text = run_text_command(command)
            if text:
                return text
        return ""
    return run_text_command(["xclip", "-selection", "clipboard", "-o"])


def normalize_word(text):
    if not text:
        return ""
    match = WORD_RE.search(text.strip())
    if not match:
        return ""
    return match.group(0).strip("'_-").lower()


def normalize_text(text):
    normalized = unicodedata.normalize("NFC", text or "")
    return SPACE_RE.sub(" ", normalized.strip())


def english_words(text):
    return [match.group(0).strip("'_-") for match in WORD_RE.finditer(text or "")]


def source_language(text):
    normalized = unicodedata.normalize("NFC", text or "")
    if DEVANAGARI_LETTER_RE.search(normalized) or SANSKRIT_IAST_RE.search(normalized):
        return "sanskrit"
    return "english"


def resolve_source_language(text, language=None):
    if language in ("english", "sanskrit", "latin", "chinese"):
        return language
    return source_language(text)


def translation_system_prompt(text, language=None):
    language = resolve_source_language(text, language)
    if language == "sanskrit":
        return SANSKRIT_TRANSLATION_SYSTEM_PROMPT
    if language == "latin":
        return LATIN_TRANSLATION_SYSTEM_PROMPT
    if language == "chinese":
        return CHINESE_TRANSLATION_SYSTEM_PROMPT
    return ENGLISH_TRANSLATION_SYSTEM_PROMPT


def looks_like_sentence(text):
    return source_language(text) == "sanskrit" or len(english_words(text)) > 1


def lookup(db_path, word):
    if not word or not os.path.exists(db_path):
        return None

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT word, phonetic, translation, definition, exchange
            FROM entries
            WHERE word = ?
            LIMIT 1
            """,
            (word,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None
    return dict(row)


def load_config(args=None):
    plasma_payload = load_plasma_applet_config()
    path = os.path.expanduser("~/.config/selection-translator/config.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    args = args or argparse.Namespace()
    service_order = (
        getattr(args, "service_order", "")
        or os.environ.get("SELECTION_TRANSLATOR_SERVICE_ORDER")
        or payload.get("service_order")
        or plasma_payload.get("service_order")
        or DEFAULT_SERVICE_ORDER
    )
    clipboard_auto_translate = first_config_value(
        getattr(args, "clipboard_auto_translate", None),
        os.environ.get("SELECTION_TRANSLATOR_CLIPBOARD") if "SELECTION_TRANSLATOR_CLIPBOARD" in os.environ else None,
        payload.get("clipboard_auto_translate"),
        plasma_payload.get("clipboard_auto_translate"),
        True,
    )

    return {
        "clipboard_auto_translate": parse_bool(clipboard_auto_translate),
        "service_order": normalize_service_order(service_order),
        "deepseek_api_key": clean_config_value(getattr(args, "deepseek_api_key", "") or os.environ.get("DEEPSEEK_API_KEY") or payload.get("deepseek_api_key") or plasma_payload.get("deepseek_api_key") or ""),
        "deepseek_model": clean_config_value(getattr(args, "deepseek_model", "") or os.environ.get("DEEPSEEK_MODEL") or payload.get("deepseek_model") or plasma_payload.get("deepseek_model") or DEFAULT_DEEPSEEK_MODEL),
        "deepseek_base_url": clean_config_value(getattr(args, "deepseek_base_url", "") or os.environ.get("DEEPSEEK_BASE_URL") or payload.get("deepseek_base_url") or plasma_payload.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL),
        "openai_api_key": clean_config_value(getattr(args, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY") or payload.get("openai_api_key") or plasma_payload.get("openai_api_key") or ""),
        "openai_model": clean_config_value(getattr(args, "openai_model", "") or os.environ.get("OPENAI_MODEL") or payload.get("openai_model") or plasma_payload.get("openai_model") or DEFAULT_OPENAI_MODEL),
        "openai_base_url": clean_config_value(getattr(args, "openai_base_url", "") or os.environ.get("OPENAI_BASE_URL") or payload.get("openai_base_url") or plasma_payload.get("openai_base_url") or DEFAULT_OPENAI_BASE_URL),
    }


def clean_config_value(value):
    return str(value or "").replace("\\n", "").replace("\\r", "").strip()


def first_config_value(*values):
    return next((value for value in values if value is not None and value != ""), None)


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def normalize_service_order(value):
    if isinstance(value, str):
        requested = value.split(",")
    elif isinstance(value, (list, tuple)):
        requested = value
    else:
        requested = []

    order = []
    for service in requested:
        service_id = str(service).strip().lower()
        if service_id in DEFAULT_SERVICE_ORDER and service_id not in order:
            order.append(service_id)
    for service_id in DEFAULT_SERVICE_ORDER:
        if service_id not in order:
            order.append(service_id)
    return order


def load_plasma_applet_config():
    path = os.path.expanduser("~/.config/plasma-org.kde.plasma.desktop-appletsrc")
    try:
        lines = open(path, "r", encoding="utf-8", errors="ignore").read().splitlines()
    except OSError:
        return {}

    translator_applets = set()
    current_section = ""
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            current_section = line
        elif line == "plugin=org.local.selectiontranslator":
            translator_applets.add(current_section.rstrip("]") + "][Configuration][General]")

    if not translator_applets:
        return {}

    key_map = {
        "clipboardAutoTranslate": "clipboard_auto_translate",
        "deepseekApiKey": "deepseek_api_key",
        "deepseekModel": "deepseek_model",
        "deepseekBaseUrl": "deepseek_base_url",
        "openaiApiKey": "openai_api_key",
        "openaiModel": "openai_model",
        "openaiBaseUrl": "openai_base_url",
        "serviceOrder": "service_order",
    }
    result = {}
    in_translator_config = False
    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            in_translator_config = line in translator_applets
            continue
        if not in_translator_config or "=" not in line:
            continue
        key, value = line.split("=", 1)
        mapped = key_map.get(key)
        if mapped and clean_config_value(value) and not result.get(mapped):
            result[mapped] = value
    return result


class SelectionEventDebouncer:
    def __init__(self, process, schedule, cancel):
        self.process = process
        self.schedule = schedule
        self.cancel = cancel
        self.pending_clear = None
        self.pending_selection = None
        self.pending_text = ""

    def handle(self, text):
        if normalize_text(text):
            self.cancel_clear()
            self.cancel_selection()
            self.pending_text = text
            self.pending_selection = self.schedule(
                STABLE_SELECTION_DELAY_MS,
                self.flush_selection,
            )
            return
        self.cancel_selection()
        self.cancel_clear()
        self.pending_clear = self.schedule(EMPTY_SELECTION_DELAY_MS, self.flush_clear)

    def cancel_selection(self):
        if self.pending_selection is not None:
            self.cancel(self.pending_selection)
            self.pending_selection = None
        self.pending_text = ""

    def cancel_clear(self):
        if self.pending_clear is not None:
            self.cancel(self.pending_clear)
            self.pending_clear = None

    def flush_clear(self):
        self.pending_clear = None
        self.process("")
        return False

    def flush_selection(self):
        self.pending_selection = None
        text = self.pending_text
        self.pending_text = ""
        self.process(text)
        return False


def extract_openai_text(payload):
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def openai_translate(text, config, language=None):
    api_key = config["openai_api_key"]
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")

    base_url = config["openai_base_url"].rstrip("/")
    request_payload = {
        "model": config["openai_model"],
        "instructions": translation_system_prompt(text, language),
        "input": text,
        "max_output_tokens": 800,
    }
    request = urllib.request.Request(
        base_url + "/responses",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    translated = extract_openai_text(payload)
    if not translated:
        raise RuntimeError("OpenAI 没有返回译文")
    return translated, "OpenAI " + config["openai_model"]


def extract_chat_completion_text(payload):
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            text = item.get("text") if isinstance(item, dict) else None
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def deepseek_translate(text, config, language=None):
    api_key = config["deepseek_api_key"]
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")

    base_url = config["deepseek_base_url"].rstrip("/")
    request_payload = {
        "model": config["deepseek_model"],
        "messages": [
            {"role": "system", "content": translation_system_prompt(text, language)},
            {"role": "user", "content": text},
        ],
        "thinking": {"type": "disabled"},
        "stream": False,
        "max_tokens": 300,
    }
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))

    translated = extract_chat_completion_text(payload)
    if not translated:
        raise RuntimeError("DeepSeek 没有返回译文")
    return translated, "DeepSeek " + config["deepseek_model"]


def google_translate(text, language=None):
    language = resolve_source_language(text, language)
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "sa" if language == "sanskrit" else "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text,
    })
    request = urllib.request.Request(
        "https://translate.googleapis.com/translate_a/single?" + params,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    parts = []
    for item in payload[0]:
        if item and item[0]:
            parts.append(item[0])
    return "".join(parts).strip()


def translate_sentence(text, args=None, language=None):
    errors = []
    config = load_config(args)
    language = resolve_source_language(text, language)
    cached = read_translation_cache(text, language)
    if cached:
        return cached["translation"], cached["engine"] + " (缓存)"

    with translation_lock(text, language):
        cached = read_translation_cache(text, language)
        if cached:
            return cached["translation"], cached["engine"] + " (缓存)"

        backends = {
            "deepseek": ("DeepSeek", lambda: deepseek_translate(text, config, language)),
            "openai": ("OpenAI", lambda: openai_translate(text, config, language)),
            "google": ("Google Translate", lambda: (google_translate(text, language), "Google Translate")),
        }
        service_order = config["service_order"]
        if language in ("sanskrit", "latin", "chinese"):
            service_order = [
                service_id
                for service_id in service_order
                if service_id in ("deepseek", "openai")
                and config[service_id + "_api_key"]
            ]
            if not service_order:
                raise RuntimeError("在线 AI 翻译需要先配置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY")

        for service_id in service_order:
            label, translate = backends[service_id]
            try:
                translated = translate()
                write_translation_cache(text, translated[0], translated[1], language)
                return translated
            except Exception as error:
                errors.append(label + ": " + str(error))

    raise RuntimeError("；".join(errors))


class translation_lock:
    def __init__(self, text, language=None):
        self.path = os.path.join(cache_dir(), cache_key(text, language) + ".lock")
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "w")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "selection-translator")


def cache_key(text, language=None):
    normalized = normalize_text(text)
    language = resolve_source_language(normalized, language)
    cache_input = normalized if language == "english" else language + "\0" + normalized
    return hashlib.sha256(cache_input.encode("utf-8")).hexdigest()


def cache_path(text, language=None):
    return os.path.join(cache_dir(), cache_key(text, language) + ".json")


def read_translation_cache(text, language=None):
    language = resolve_source_language(text, language)
    try:
        with open(cache_path(text, language), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("text") != normalize_text(text):
        return None
    if payload.get("sourceLanguage", "english") != language:
        return None
    if not payload.get("translation") or not payload.get("engine"):
        return None
    return payload


def write_translation_cache(text, translation, engine, language=None):
    os.makedirs(cache_dir(), exist_ok=True)
    language = resolve_source_language(text, language)
    payload = {
        "text": normalize_text(text),
        "translation": translation,
        "engine": engine,
        "sourceLanguage": language,
    }
    tmp_path = cache_path(text, language) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp_path, cache_path(text, language))


def shared_state_path():
    return os.path.join(cache_dir(), "shared-state.json")


def write_shared_state(payload):
    with shared_state_lock():
        write_shared_state_unlocked(payload)


def write_shared_state_unlocked(payload):
    os.makedirs(cache_dir(), exist_ok=True)
    state = dict(payload)
    state["stateVersion"] = 1
    tmp_path = shared_state_path() + ".tmp." + str(os.getpid())
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp_path, shared_state_path())


class shared_state_lock:
    def __init__(self):
        self.path = os.path.join(cache_dir(), "shared-state.lock")
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "w")
        fcntl.flock(self.handle, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.handle:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


def begin_translation(text, language=None):
    normalized = normalize_text(text)
    language = resolve_source_language(normalized, language)
    with shared_state_lock():
        state = read_shared_state()
        started_at = state.get("startedAt", 0)
        still_running = (
            state.get("translating")
            and normalize_text(state.get("text", "")) == normalized
            and state.get("sourceLanguage", "english") == language
            and isinstance(started_at, (int, float))
            and time.time() - started_at < 45
        )
        if still_running:
            return "", state

        request_id = uuid.uuid4().hex
        state = {
            "found": False,
            "sentenceCandidate": False,
            "translating": True,
            "text": normalized,
            "sourceLanguage": language,
            "message": "翻译中...",
            "requestId": request_id,
            "startedAt": time.time(),
        }
        write_shared_state_unlocked(state)
        return request_id, state


def finish_translation(request_id, payload):
    with shared_state_lock():
        state = read_shared_state()
        if state.get("requestId") != request_id:
            return False
        write_shared_state_unlocked(payload)
        return True


def sentence_selection_state(text, language=None):
    normalized = normalize_text(text)
    language = resolve_source_language(normalized, language)
    with shared_state_lock():
        state = read_shared_state()
        started_at = state.get("startedAt", 0)
        if (
            state.get("translating")
            and normalize_text(state.get("text", "")) == normalized
            and state.get("sourceLanguage", "english") == language
            and isinstance(started_at, (int, float))
            and time.time() - started_at < 45
        ):
            return state

        cached = read_translation_cache(normalized, language)
        if cached:
            state = {
                "translated": True,
                "translating": False,
                "text": normalized[:500],
                "translation": cached["translation"],
                "engine": cached["engine"],
                "sourceLanguage": language,
            }
        else:
            state = {
                "found": False,
                "sentenceCandidate": True,
                "intentRequired": True,
                "translating": False,
                "text": normalized[:500],
                "wordCount": len(english_words(normalized)),
                "sourceLanguage": language,
                "message": "等待翻译操作",
            }
        write_shared_state_unlocked(state)
        return state


def sanskrit_selection_state(text):
    return sentence_selection_state(text, "sanskrit")


def selection_state(text, db_path):
    source_text = normalize_text(text)
    if HAN_RE.search(source_text):
        return sentence_selection_state(source_text, "chinese")
    if source_language(source_text) == "sanskrit":
        return sanskrit_selection_state(source_text)
    if looks_like_sentence(source_text):
        return sentence_selection_state(source_text, "latin")

    word = normalize_word(source_text)
    if not word:
        state = {"found": False, "message": "请选择英文单词"}
        write_shared_state(state)
        return state

    entry = lookup(db_path, word)
    if entry is None:
        return sentence_selection_state(source_text, "latin")

    state = {
        "found": True,
        "word": entry.get("word") or word,
        "phonetic": entry.get("phonetic") or "",
        "translation": entry.get("translation") or "",
        "definition": entry.get("definition") or "",
        "exchange": entry.get("exchange") or "",
    }
    write_shared_state(state)
    return state


def begin_word_translation():
    with shared_state_lock():
        state = read_shared_state()
        word = normalize_word(state.get("word", ""))
        if not state.get("found") or not word:
            return "", {"translated": False, "message": "请先选择一个英文单词"}

        started_at = state.get("wordOnlineStartedAt", 0)
        if (
            state.get("wordOnlineTranslating")
            and isinstance(started_at, (int, float))
            and time.time() - started_at < 45
        ):
            return "", state

        request_id = uuid.uuid4().hex
        state["wordOnlineTranslation"] = ""
        state["wordOnlineEngine"] = ""
        state["wordOnlineTranslating"] = True
        state["wordOnlineRequestId"] = request_id
        state["wordOnlineStartedAt"] = time.time()
        write_shared_state_unlocked(state)
        return request_id, state


def finish_word_translation(request_id, translation, engine, error=""):
    with shared_state_lock():
        state = read_shared_state()
        if state.get("wordOnlineRequestId") != request_id:
            return None
        state["wordOnlineTranslating"] = False
        state["wordOnlineTranslation"] = translation
        state["wordOnlineEngine"] = engine
        state["wordOnlineError"] = error
        state.pop("wordOnlineRequestId", None)
        state.pop("wordOnlineStartedAt", None)
        write_shared_state_unlocked(state)
        return state


def json_state(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dbus_service_running():
    try:
        import dbus

        return dbus.SessionBus().name_has_owner(DBUS_SERVICE)
    except Exception:
        return False


def start_daemon(db_path):
    if dbus_service_running():
        return
    command = [
        sys.executable,
        os.path.abspath(__file__),
        "--daemon",
        "--db",
        os.path.abspath(db_path),
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def send_selection_event(text, source):
    try:
        import dbus

        proxy = dbus.SessionBus().get_object(DBUS_SERVICE, DBUS_PATH)
        proxy.ProcessSelection(
            text,
            source,
            dbus_interface=DBUS_INTERFACE,
            timeout=2,
        )
    except Exception:
        pass


def run_daemon(db_path):
    import dbus
    import dbus.service
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    DBusGMainLoop(set_as_default=True)

    class SelectionTranslatorService(dbus.service.Object):
        def __init__(self):
            self.loop = GLib.MainLoop()
            self.db_path = db_path
            self.watcher_commands = []
            self.watchers = []
            self.poll_source = None
            self.last_seen = {"primary": None, "clipboard": None}
            self.stopping = False
            self.last_primary_at = 0.0
            self.selection_events = SelectionEventDebouncer(
                self.process_selection,
                GLib.timeout_add,
                GLib.source_remove,
            )
            bus = dbus.SessionBus()
            bus_name = dbus.service.BusName(
                DBUS_SERVICE,
                bus=bus,
                do_not_queue=True,
            )
            super().__init__(bus_name, DBUS_PATH)

        @dbus.service.signal(DBUS_INTERFACE, signature="s")
        def StateChanged(self, state):
            pass

        def publish(self, state):
            self.StateChanged(json_state(state))
            return False

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def GetState(self):
            return json_state(read_shared_state())

        @dbus.service.method(DBUS_INTERFACE, in_signature="ss", out_signature="")
        def ProcessSelection(self, text, source):
            now = time.monotonic()
            if source == "primary":
                self.last_primary_at = now
            elif not load_config()["clipboard_auto_translate"] or now - self.last_primary_at < 0.4:
                return
            self.selection_events.handle(str(text))

        def process_selection(self, text):
            state = selection_state(text, self.db_path)
            self.publish(state)
            return state

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def Refresh(self):
            state = self.process_selection(read_selection())
            return json_state(state)

        @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="s")
        def Translate(self, text):
            return self.start_translation(str(text))

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def TranslateCurrent(self):
            state = read_shared_state()
            return self.start_translation(state.get("text", ""), state.get("sourceLanguage"))

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def TranslateWordCurrent(self):
            request_id, state = begin_word_translation()
            self.publish(state)
            if request_id:
                threading.Thread(
                    target=self.translate_word_worker,
                    args=(request_id, state["word"]),
                    daemon=True,
                ).start()
            return json_state(state)

        def start_translation(self, text, language=None):
            source_text = normalize_text(text)
            language = resolve_source_language(source_text, language)
            if not source_text or (language == "english" and not looks_like_sentence(source_text)):
                state = {"translated": False, "message": "请选择英文句子或梵语转写"}
                write_shared_state(state)
                self.publish(state)
                return json_state(state)

            request_id, state = begin_translation(source_text, language)
            self.publish(state)
            if request_id:
                threading.Thread(
                    target=self.translate_worker,
                    args=(request_id, source_text, language),
                    daemon=True,
                ).start()
            return json_state(state)

        def translate_worker(self, request_id, source_text, language):
            try:
                translated, engine = translate_sentence(source_text, language=language)
                state = {
                    "translated": True,
                    "translating": False,
                    "text": source_text,
                    "translation": translated,
                    "engine": engine,
                    "sourceLanguage": language,
                }
            except Exception as error:
                state = {
                    "translated": False,
                    "translating": False,
                    "text": source_text,
                    "sourceLanguage": language,
                    "message": "翻译失败：" + str(error),
                }

            if finish_translation(request_id, state):
                GLib.idle_add(self.publish, state)

        def translate_word_worker(self, request_id, word):
            try:
                translated, engine = translate_sentence(word, language="english")
                state = finish_word_translation(request_id, translated, engine)
            except Exception as error:
                state = finish_word_translation(
                    request_id,
                    "",
                    "",
                    "在线翻译失败：" + str(error),
                )
            if state:
                GLib.idle_add(self.publish, state)

        def start_watchers(self):
            if os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
                self.last_seen = {
                    "primary": read_selection_source("primary"),
                    "clipboard": read_selection_source("clipboard"),
                }
                self.poll_source = GLib.timeout_add(250, self.poll_x11_selections)
                return
            base_command = [
                sys.executable,
                os.path.abspath(__file__),
                "--selection-event",
            ]
            self.watcher_commands = [
                ["wl-paste", "--primary", "--watch", *base_command, "--source", "primary"],
                ["wl-paste", "--watch", *base_command, "--source", "clipboard"],
            ]
            self.watchers = [self.start_watcher(command) for command in self.watcher_commands]
            GLib.timeout_add_seconds(2, self.ensure_watchers)

        def poll_x11_selections(self):
            if self.stopping:
                return False
            for source in ("primary", "clipboard"):
                text = read_selection_source(source)
                if text == self.last_seen[source]:
                    continue
                self.last_seen[source] = text
                self.ProcessSelection(text, source)
            return True

        def start_watcher(self, command):
            try:
                return subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                return None

        def ensure_watchers(self):
            if self.stopping:
                return False
            for index, command in enumerate(self.watcher_commands):
                watcher = self.watchers[index]
                if watcher is None or watcher.poll() is not None:
                    self.watchers[index] = self.start_watcher(command)
            return True

        def stop_watchers(self):
            self.stopping = True
            if self.poll_source is not None:
                GLib.source_remove(self.poll_source)
                self.poll_source = None
            for watcher in self.watchers:
                if watcher is not None and watcher.poll() is None:
                    watcher.terminate()
            for watcher in self.watchers:
                if watcher is None:
                    continue
                try:
                    watcher.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    watcher.kill()
                    watcher.wait()

        def run(self):
            signal.signal(signal.SIGTERM, lambda *_: self.loop.quit())
            self.start_watchers()
            current = read_selection(load_config()["clipboard_auto_translate"])
            if current:
                self.process_selection(current)
            try:
                self.loop.run()
            finally:
                self.selection_events.cancel_selection()
                self.selection_events.cancel_clear()
                self.stop_watchers()

    try:
        SelectionTranslatorService().run()
    except dbus.exceptions.NameExistsException:
        return


def translate_text_sync(source_text, args, language):
    request_id, translating_state = begin_translation(source_text, language)
    if not request_id:
        return translating_state
    try:
        translated, engine = translate_sentence(source_text, args, language)
    except Exception as error:
        failure = {
            "translated": False,
            "translating": False,
            "text": source_text,
            "sourceLanguage": language,
            "message": "翻译失败：" + str(error),
        }
        if finish_translation(request_id, failure):
            return failure
        return {
            **failure,
            "stale": True,
            "message": "旧文本的翻译已忽略",
        }

    result = {
        "translated": True,
        "translating": False,
        "text": source_text,
        "translation": translated,
        "engine": engine,
        "sourceLanguage": language,
    }
    if finish_translation(request_id, result):
        return result
    return {**result, "stale": True}


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", action="store_true")
    parser.add_argument("--selection-event", action="store_true")
    parser.add_argument("--source", default="primary")
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--start-daemon", action="store_true")
    parser.add_argument("--state", action="store_true")
    parser.add_argument("--text", default="")
    parser.add_argument("--db", default="")
    parser.add_argument("--limit", default="1")
    parser.add_argument("--stamp", default="")
    parser.add_argument("--translate", action="store_true")
    parser.add_argument("--translate-word-current", action="store_true")
    parser.add_argument(
        "--source-language",
        choices=("auto", "english", "sanskrit", "latin", "chinese"),
        default="auto",
    )
    parser.add_argument("--deepseek-api-key", default="")
    parser.add_argument("--deepseek-model", default="")
    parser.add_argument("--deepseek-base-url", default="")
    parser.add_argument("--openai-api-key", default="")
    parser.add_argument("--openai-model", default="")
    parser.add_argument("--openai-base-url", default="")
    parser.add_argument("--service-order", default="")
    args = parser.parse_args(argv)

    if args.selection_event:
        event_text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        send_selection_event(event_text, args.source)
        return 0
    if args.start_daemon:
        if not args.db:
            parser.error("--db is required with --start-daemon")
        start_daemon(args.db)
        return 0
    if args.daemon:
        if not args.db:
            parser.error("--db is required with --daemon")
        run_daemon(args.db)
        return 0
    if args.state:
        emit(read_shared_state())
        return 0
    if not args.db:
        parser.error("--db is required")

    if args.translate_word_current:
        request_id, state = begin_word_translation()
        if not request_id:
            emit(state)
            return 0
        try:
            translation, engine = translate_sentence(state["word"], args, "english")
            result = finish_word_translation(request_id, translation, engine)
        except Exception as error:
            result = finish_word_translation(request_id, "", "", "在线翻译失败：" + str(error))
        emit(result or read_shared_state())
        return 0

    source_text = normalize_text(read_selection() if args.selection else args.text)
    if args.translate:
        language = None if args.source_language == "auto" else args.source_language
        language = resolve_source_language(source_text, language)
        if not source_text or (language == "english" and not looks_like_sentence(source_text)):
            emit_state({"translated": False, "message": "请选择英文句子或梵语转写"})
            return 0
        emit(translate_text_sync(source_text, args, language))
        return 0

    state = selection_state(source_text, args.db)
    emit(state)
    return 0


def read_shared_state():
    try:
        with open(shared_state_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
