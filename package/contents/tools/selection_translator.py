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
import urllib.parse
import urllib.request
import uuid


WORD_RE = re.compile(r"[A-Za-z][A-Za-z'_-]{0,63}")
SPACE_RE = re.compile(r"\s+")
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DBUS_SERVICE = "org.local.SelectionTranslator"
DBUS_PATH = "/org/local/SelectionTranslator"
DBUS_INTERFACE = "org.local.SelectionTranslator"
TRANSLATION_SYSTEM_PROMPT = (
    "You are a translation engine. Translate the user's English text into Simplified Chinese. "
    "Return only the translated Chinese text. Do not explain, add notes, quote the source, or use Markdown."
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


def read_selection():
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    candidates = []

    if session_type == "wayland":
        candidates.extend([
            ["wl-paste", "--primary", "--no-newline"],
            ["wl-paste", "--no-newline"],
        ])
    else:
        candidates.extend([
            ["xclip", "-selection", "primary", "-o"],
            ["xsel", "-p", "-o"],
            ["wl-paste", "--primary", "--no-newline"],
            ["wl-paste", "--no-newline"],
        ])

    for command in candidates:
        text = run_text_command(command)
        if text:
            return text
    return ""


def normalize_word(text):
    if not text:
        return ""
    match = WORD_RE.search(text.strip())
    if not match:
        return ""
    return match.group(0).strip("'_-").lower()


def normalize_text(text):
    return SPACE_RE.sub(" ", (text or "").strip())


def english_words(text):
    return [match.group(0).strip("'_-") for match in WORD_RE.finditer(text or "")]


def looks_like_sentence(text):
    words = english_words(text)
    return len(words) > 1


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

    return {
        "deepseek_api_key": clean_config_value(getattr(args, "deepseek_api_key", "") or os.environ.get("DEEPSEEK_API_KEY") or payload.get("deepseek_api_key") or plasma_payload.get("deepseek_api_key") or ""),
        "deepseek_model": clean_config_value(getattr(args, "deepseek_model", "") or os.environ.get("DEEPSEEK_MODEL") or payload.get("deepseek_model") or plasma_payload.get("deepseek_model") or DEFAULT_DEEPSEEK_MODEL),
        "deepseek_base_url": clean_config_value(getattr(args, "deepseek_base_url", "") or os.environ.get("DEEPSEEK_BASE_URL") or payload.get("deepseek_base_url") or plasma_payload.get("deepseek_base_url") or DEFAULT_DEEPSEEK_BASE_URL),
        "openai_api_key": clean_config_value(getattr(args, "openai_api_key", "") or os.environ.get("OPENAI_API_KEY") or payload.get("openai_api_key") or plasma_payload.get("openai_api_key") or ""),
        "openai_model": clean_config_value(getattr(args, "openai_model", "") or os.environ.get("OPENAI_MODEL") or payload.get("openai_model") or plasma_payload.get("openai_model") or DEFAULT_OPENAI_MODEL),
        "openai_base_url": clean_config_value(getattr(args, "openai_base_url", "") or os.environ.get("OPENAI_BASE_URL") or payload.get("openai_base_url") or plasma_payload.get("openai_base_url") or DEFAULT_OPENAI_BASE_URL),
    }


def clean_config_value(value):
    return str(value or "").replace("\\n", "").replace("\\r", "").strip()


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
        "deepseekApiKey": "deepseek_api_key",
        "deepseekModel": "deepseek_model",
        "deepseekBaseUrl": "deepseek_base_url",
        "openaiApiKey": "openai_api_key",
        "openaiModel": "openai_model",
        "openaiBaseUrl": "openai_base_url",
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


def openai_translate(text, config):
    api_key = config["openai_api_key"]
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY")

    base_url = config["openai_base_url"].rstrip("/")
    request_payload = {
        "model": config["openai_model"],
        "instructions": TRANSLATION_SYSTEM_PROMPT,
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


def deepseek_translate(text, config):
    api_key = config["deepseek_api_key"]
    if not api_key:
        raise RuntimeError("未配置 DEEPSEEK_API_KEY")

    base_url = config["deepseek_base_url"].rstrip("/")
    request_payload = {
        "model": config["deepseek_model"],
        "messages": [
            {"role": "system", "content": TRANSLATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "max_tokens": 800,
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


def google_translate(text):
    params = urllib.parse.urlencode({
        "client": "gtx",
        "sl": "en",
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


def translate_sentence(text, args=None):
    errors = []
    config = load_config(args)
    cached = read_translation_cache(text)
    if cached:
        return cached["translation"], cached["engine"] + " (缓存)"

    with translation_lock(text):
        cached = read_translation_cache(text)
        if cached:
            return cached["translation"], cached["engine"] + " (缓存)"

        try:
            translated = deepseek_translate(text, config)
            write_translation_cache(text, translated[0], translated[1])
            return translated
        except Exception as error:
            errors.append("DeepSeek: " + str(error))

        try:
            translated = openai_translate(text, config)
            write_translation_cache(text, translated[0], translated[1])
            return translated
        except Exception as error:
            errors.append("OpenAI: " + str(error))

        try:
            translated = google_translate(text), "Google Translate"
            write_translation_cache(text, translated[0], translated[1])
            return translated
        except Exception as error:
            errors.append("Google Translate: " + str(error))

    raise RuntimeError("；".join(errors))


class translation_lock:
    def __init__(self, text):
        self.path = os.path.join(cache_dir(), cache_key(text) + ".lock")
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


def cache_key(text):
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def cache_path(text):
    return os.path.join(cache_dir(), cache_key(text) + ".json")


def read_translation_cache(text):
    try:
        with open(cache_path(text), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if payload.get("text") != normalize_text(text):
        return None
    if not payload.get("translation") or not payload.get("engine"):
        return None
    return payload


def write_translation_cache(text, translation, engine):
    os.makedirs(cache_dir(), exist_ok=True)
    payload = {
        "text": normalize_text(text),
        "translation": translation,
        "engine": engine,
    }
    tmp_path = cache_path(text) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    os.replace(tmp_path, cache_path(text))


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


def begin_translation(text):
    normalized = normalize_text(text)
    with shared_state_lock():
        state = read_shared_state()
        started_at = state.get("startedAt", 0)
        still_running = (
            state.get("translating")
            and normalize_text(state.get("text", "")) == normalized
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


def sentence_selection_state(text):
    normalized = normalize_text(text)
    with shared_state_lock():
        state = read_shared_state()
        started_at = state.get("startedAt", 0)
        if (
            state.get("translating")
            and normalize_text(state.get("text", "")) == normalized
            and isinstance(started_at, (int, float))
            and time.time() - started_at < 45
        ):
            return state

        cached = read_translation_cache(normalized)
        if cached:
            state = {
                "translated": True,
                "translating": False,
                "text": normalized[:500],
                "translation": cached["translation"],
                "engine": cached["engine"],
            }
        else:
            state = {
                "found": False,
                "sentenceCandidate": True,
                "translating": False,
                "text": normalized[:500],
                "wordCount": len(english_words(normalized)),
                "message": "是否翻译整句？",
            }
        write_shared_state_unlocked(state)
        return state


def selection_state(text, db_path):
    source_text = normalize_text(text)
    if looks_like_sentence(source_text):
        return sentence_selection_state(source_text)

    word = normalize_word(source_text)
    if not word:
        state = {"found": False, "message": "请选择英文单词"}
        write_shared_state(state)
        return state

    entry = lookup(db_path, word)
    if entry is None:
        state = {"found": False, "word": word, "message": "本地词库没有这个词"}
        write_shared_state(state)
        return state

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
            self.watchers = []
            self.last_primary_at = 0.0
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
            elif now - self.last_primary_at < 0.4:
                return
            self.publish(selection_state(str(text), self.db_path))

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def Refresh(self):
            state = selection_state(read_selection(), self.db_path)
            self.publish(state)
            return json_state(state)

        @dbus.service.method(DBUS_INTERFACE, in_signature="s", out_signature="s")
        def Translate(self, text):
            return self.start_translation(str(text))

        @dbus.service.method(DBUS_INTERFACE, in_signature="", out_signature="s")
        def TranslateCurrent(self):
            return self.start_translation(read_shared_state().get("text", ""))

        def start_translation(self, text):
            source_text = normalize_text(text)
            if not looks_like_sentence(source_text):
                state = {"translated": False, "message": "请选择一个英文句子"}
                write_shared_state(state)
                self.publish(state)
                return json_state(state)

            request_id, state = begin_translation(source_text)
            self.publish(state)
            if request_id:
                threading.Thread(
                    target=self.translate_worker,
                    args=(request_id, source_text),
                    daemon=True,
                ).start()
            return json_state(state)

        def translate_worker(self, request_id, source_text):
            try:
                translated, engine = translate_sentence(source_text)
                state = {
                    "translated": True,
                    "translating": False,
                    "text": source_text,
                    "translation": translated,
                    "engine": engine,
                }
            except Exception as error:
                state = {
                    "translated": False,
                    "translating": False,
                    "text": source_text,
                    "message": "整句翻译失败：" + str(error),
                }

            if finish_translation(request_id, state):
                GLib.idle_add(self.publish, state)

        def start_watchers(self):
            base_command = [
                sys.executable,
                os.path.abspath(__file__),
                "--selection-event",
            ]
            commands = [
                ["wl-paste", "--primary", "--watch", *base_command, "--source", "primary"],
                ["wl-paste", "--watch", *base_command, "--source", "clipboard"],
            ]
            for command in commands:
                try:
                    self.watchers.append(subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    ))
                except OSError:
                    continue

        def stop_watchers(self):
            for watcher in self.watchers:
                if watcher.poll() is None:
                    watcher.terminate()
            for watcher in self.watchers:
                try:
                    watcher.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    watcher.kill()
                    watcher.wait()

        def run(self):
            signal.signal(signal.SIGTERM, lambda *_: self.loop.quit())
            self.start_watchers()
            current = read_selection()
            if current:
                self.publish(selection_state(current, self.db_path))
            try:
                self.loop.run()
            finally:
                self.stop_watchers()

    try:
        SelectionTranslatorService().run()
    except dbus.exceptions.NameExistsException:
        return


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
    parser.add_argument("--deepseek-api-key", default="")
    parser.add_argument("--deepseek-model", default="")
    parser.add_argument("--deepseek-base-url", default="")
    parser.add_argument("--openai-api-key", default="")
    parser.add_argument("--openai-model", default="")
    parser.add_argument("--openai-base-url", default="")
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

    source_text = normalize_text(read_selection() if args.selection else args.text)
    if args.translate:
        if not looks_like_sentence(source_text):
            emit_state({"translated": False, "message": "请选择一个英文句子"})
            return 0
        request_id, translating_state = begin_translation(source_text)
        if not request_id:
            emit(translating_state)
            return 0
        try:
            translated, engine = translate_sentence(source_text, args)
        except Exception as error:
            failure = {
                "translated": False,
                "translating": False,
                "text": source_text,
                "message": "整句翻译失败：" + str(error),
            }
            if not finish_translation(request_id, failure):
                emit({
                    "translated": False,
                    "translating": False,
                    "text": source_text,
                    "stale": True,
                    "message": "旧句子的翻译已忽略",
                })
                return 0
            emit(failure)
            return 0

        result = {
            "translated": True,
            "translating": False,
            "text": source_text,
            "translation": translated,
            "engine": engine,
        }
        if not finish_translation(request_id, result):
            emit({
                "translated": True,
                "translating": False,
                "text": source_text,
                "translation": translated,
                "engine": engine,
                "stale": True,
            })
            return 0

        emit(result)
        return 0

    emit(selection_state(source_text, args.db))
    return 0


def read_shared_state():
    try:
        with open(shared_state_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
