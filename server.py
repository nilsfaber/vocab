#!/usr/bin/env python3
"""
Vocab local server.
Serves the imagegen/ UI, the docs/ PWA, and exposes an API to run generation scripts.

Usage (from repo root):
    python server.py [--port 8765]

Then open:
    http://localhost:8765/          → imagegen UI
    http://localhost:8765/docs/     → docs PWA
    http://localhost:8188/          → ComfyUI (separate process)
"""

import argparse
import json
import mimetypes
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT      = Path(__file__).parent.resolve()
IMAGEN_DIR     = REPO_ROOT / "imagegen"
GENERATORS_DIR = IMAGEN_DIR / "generators"
VOCAB_PATH     = REPO_ROOT / "docs" / "vocab.json"
PUBLIC_PATH    = REPO_ROOT / "docs" / "vocab_public.json"

_jobs: dict[str, dict] = {}
_job_queue: queue.Queue = queue.Queue()   # (job_id, script_path, words)
_running_job_id: str | None = None


def _queue_worker() -> None:
    global _running_job_id
    while True:
        job_id, script, words = _job_queue.get()
        _running_job_id = job_id
        try:
            cmd = [sys.executable, str(script), "--words"] + words + ["--force"]
            job = _jobs[job_id]
            job["cmd"] = " ".join(cmd)
            proc = subprocess.Popen(
                cmd, cwd=str(REPO_ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                job["lines"].append(line.rstrip())
            proc.wait()
            job["rc"] = proc.returncode
            job["done"] = True
        finally:
            _running_job_id = None
            _job_queue.task_done()


threading.Thread(target=_queue_worker, daemon=True).start()


def _enqueue_job(job_id: str, script: Path, words: list[str]) -> None:
    _jobs[job_id] = {"lines": [], "done": False, "rc": None, "cmd": ""}
    _job_queue.put((job_id, script, words))


def _read_vocab() -> dict:
    try:
        return json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def _write_vocab(vocab: dict) -> None:
    VOCAB_PATH.write_text(json.dumps(vocab, ensure_ascii=False, indent=2), encoding="utf-8")
    # Keep public version in sync: occurrences stripped of paragraph text
    if PUBLIC_PATH.exists():
        public = {}
        for key, entry in vocab.items():
            e = {k: v for k, v in entry.items() if k != "occurrences"}
            e["occurrences"] = [{"book": occ["book"]} for occ in entry.get("occurrences", [])]
            public[key] = e
        PUBLIC_PATH.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")


def list_scripts() -> list[str]:
    return sorted(f.name for f in GENERATORS_DIR.glob("*.py"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass  # suppress access log
    def log_error(self, fmt, *args): print(f"[server error] {fmt % args}", flush=True)

    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path

        # ── API ──────────────────────────────────────────────────────────────
        if path == "/api/scripts":
            self._json(list_scripts())
            return

        if path.startswith("/api/status/"):
            job_id = path.rsplit("/", 1)[-1]
            job = _jobs.get(job_id)
            if not job:
                self._json({"error": "not found"}, 404)
            else:
                self._json({"lines": job["lines"], "done": job["done"], "rc": job["rc"]})
            return

        if path == "/api/vocab":
            self._json(_read_vocab())
            return

        if path == "/api/queue":
            pending = list(_job_queue.queue)  # snapshot of waiting items
            self._json({
                "running": _running_job_id,
                "pending": [item[0] for item in pending],
            })
            return

        # ── Static files ─────────────────────────────────────────────────────
        if path in ("/", "/index.html"):
            fpath = IMAGEN_DIR / "index.html"
        elif path.startswith("/docs"):
            rel = path[len("/docs"):].lstrip("/") or "index.html"
            fpath = REPO_ROOT / "docs" / rel
        else:
            fpath = IMAGEN_DIR / path.lstrip("/")

        if fpath.is_file():
            data = fpath.read_bytes()
            mime = mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", len(data))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._json({"error": "not found"}, 404)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/word":
            length = int(self.headers.get("Content-Length", 0))
            body   = json.loads(self.rfile.read(length) or b"{}")
            word   = (body.get("word") or "").strip().lower()
            if not word:
                self._json({"error": "word required"}, 400)
                return
            vocab = _read_vocab()
            if word not in vocab:
                self._json({"error": f"word not found: {word}"}, 404)
                return
            vocab[word]["deleted"] = True
            _write_vocab(vocab)
            self._json({"ok": True})
        elif path == "/api/image":
            length   = int(self.headers.get("Content-Length", 0))
            body     = json.loads(self.rfile.read(length) or b"{}")
            word     = (body.get("word") or "").strip().lower()
            filename = (body.get("filename") or "").strip()
            if not word or not filename:
                self._json({"error": "word and filename required"}, 400)
                return
            vocab = _read_vocab()
            if word not in vocab:
                self._json({"error": f"word not found: {word}"}, 404)
                return
            entry = vocab[word]
            # Remove from images list
            entry["images"] = [i for i in entry.get("images", []) if i["filename"] != filename]
            # Clear default_image if it was this file
            if entry.get("default_image") == filename:
                entry["default_image"] = entry["images"][-1]["filename"] if entry["images"] else None
            _write_vocab(vocab)
            # Delete physical file
            img_path = REPO_ROOT / "imagegen" / "words" / word / filename
            if img_path.exists():
                img_path.unlink()
            self._json({"ok": True, "default_image": entry.get("default_image")})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/apply":
            self._handle_apply()
            return
        if path == "/api/update-word":
            self._handle_update_word()
            return
        if path == "/api/add-word":
            self._handle_add_word()
            return
        if path == "/api/reenrich":
            self._handle_reenrich()
            return
        if path != "/api/run":
            self._json({"error": "not found"}, 404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")
        script          = body.get("script", "")
        words           = body.get("words", [])
        prompt_base     = body.get("prompt_base", "").strip()
        prompt_refiner  = body.get("prompt_refiner", "").strip()
        negative        = body.get("negative", "").strip()

        if not script or not words:
            self._json({"error": "script and words are required"}, 400)
            return

        script_path = GENERATORS_DIR / script
        if not script_path.is_file():
            self._json({"error": f"script not found: {script}"}, 404)
            return

        # If the user edited the prompt, patch scenes.json before running so
        # phase 2 picks up the new text (phase 1 is skipped because scene exists).
        if (prompt_base or prompt_refiner or negative) and words:
            scenes_path = IMAGEN_DIR / "scenes.json"
            try:
                scenes = json.loads(scenes_path.read_text()) if scenes_path.exists() else {}
                for word in words:
                    if word not in scenes:
                        scenes[word] = {}
                    if prompt_base:
                        scenes[word]["prompt_base"] = prompt_base
                    if prompt_refiner:
                        scenes[word]["prompt_refiner"] = prompt_refiner
                    if negative:
                        scenes[word]["negative"] = negative
                    # Ensure phase 1 (Ollama) is skipped — scene must be non-empty
                    if not scenes[word].get("scene"):
                        scenes[word]["scene"] = "(user-provided prompt)"
                scenes_path.parent.mkdir(parents=True, exist_ok=True)
                scenes_path.write_text(json.dumps(scenes, indent=2, ensure_ascii=False))
            except Exception as e:
                self._json({"error": f"failed to patch scenes.json: {e}"}, 500)
                return

        job_id = uuid.uuid4().hex[:8]
        _enqueue_job(job_id, script_path, words)
        pending = max(0, _job_queue.qsize() - 1)  # jobs behind this one
        self._json({"job_id": job_id, "queue_position": pending})

    def _handle_add_word(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")
        raw    = (body.get("word") or "").strip()
        if not raw:
            self._json({"error": "word required"}, 400)
            return
        key   = raw.lower()
        vocab = _read_vocab()
        if key in vocab:
            self._json({"error": f"word already exists: {raw}"}, 409)
            return
        entry = {
            "word":              raw,
            "definition":        body.get("definition", ""),
            "phonetic":          "",
            "definitions":       [],
            "translation":       body.get("translation", {}),
            "images":            [],
            "default_image":     None,
            "flagged_for_regen": True,
            "learnt":            False,
            "deleted":           False,
            "enriched":          False,
        }
        vocab[key] = entry
        _write_vocab(vocab)
        self._json({"ok": True, "entry": entry})

    def _handle_reenrich(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")
        key    = (body.get("word") or "").strip().lower()
        if not key:
            self._json({"error": "word required"}, 400)
            return
        vocab = _read_vocab()
        if key not in vocab:
            self._json({"error": f"word not found: {key}"}, 404)
            return
        entry = vocab[key]
        word  = entry.get("word", key)

        # Fetch from dictionaryapi.dev
        try:
            url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.request.quote(word)}"
            req = urllib.request.Request(url, headers={"User-Agent": "vocab-builder/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            meanings = data[0].get("meanings", [])
            if meanings:
                first = meanings[0]
                defs  = first.get("definitions", [])
                if defs:
                    entry["phonetic"]       = data[0].get("phonetic", "") or entry.get("phonetic", "")
                    entry["part_of_speech"] = first.get("partOfSpeech", "")
                    entry["definition"]     = defs[0].get("definition", "")
                    entry["example"]        = defs[0].get("example") or ""
                    entry["definitions"]    = [
                        {"part_of_speech": m.get("partOfSpeech",""), "definition": d.get("definition",""), "example": d.get("example") or ""}
                        for m in meanings for d in m.get("definitions", [])
                    ]
                    synonyms, antonyms = set(), set()
                    for m in meanings:
                        synonyms.update(m.get("synonyms", []))
                        antonyms.update(m.get("antonyms", []))
                        for d in m.get("definitions", []):
                            synonyms.update(d.get("synonyms", []))
                            antonyms.update(d.get("antonyms", []))
                    entry["synonyms"] = sorted(synonyms)
                    entry["antonyms"] = sorted(antonyms)
                    entry["enriched"] = True
        except Exception:
            pass

        # Supplement with Datamuse
        def _datamuse(rel, w):
            url = f"https://api.datamuse.com/words?rel_{rel}={urllib.request.quote(w)}&max=30"
            req = urllib.request.Request(url, headers={"User-Agent": "vocab-builder/1.0"})
            with urllib.request.urlopen(req, timeout=5) as r:
                return [x["word"] for x in json.loads(r.read())]
        word_lower = word.lower()
        word_stem  = re.sub(r'(ing|ed|s|er|est|ly)$', '', word_lower)
        try:
            dm_syns = [w for w in _datamuse("syn", word) if w.lower() != word_lower and word_stem not in w.lower()]
            entry["synonyms"] = sorted(set(entry.get("synonyms", [])) | set(dm_syns))
        except Exception:
            pass
        try:
            dm_ants = [w for w in _datamuse("ant", word) if w.lower() != word_lower]
            entry["antonyms"] = sorted(set(entry.get("antonyms", [])) | set(dm_ants))
        except Exception:
            pass

        # Fetch translation if missing
        lang = "nl"
        if not entry.get("translation", {}).get(lang):
            try:
                url = f"https://api.mymemory.translated.net/get?q={urllib.request.quote(word)}&langpair=en|{lang}"
                req = urllib.request.Request(url, headers={"User-Agent": "vocab-builder/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    tdata = json.loads(resp.read())
                translated  = tdata.get("responseData", {}).get("translatedText", "").strip()
                match_score = float(tdata.get("responseData", {}).get("match", 0) or 0)
                if translated and match_score >= 0.5:
                    if "translation" not in entry:
                        entry["translation"] = {}
                    entry["translation"][lang] = translated
            except Exception:
                pass

        vocab[key] = entry
        _write_vocab(vocab)
        self._json({"ok": True, "entry": entry})

    def _handle_update_word(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length) or b"{}")
        word   = body.pop("word", "").strip().lower()
        if not word:
            self._json({"error": "word required"}, 400)
            return
        vocab = _read_vocab()
        if word not in vocab:
            self._json({"error": f"word not found: {word}"}, 404)
            return
        vocab[word].update(body)
        _write_vocab(vocab)
        self._json({"ok": True})

    def _handle_apply(self) -> None:
        length   = int(self.headers.get("Content-Length", 0))
        body     = json.loads(self.rfile.read(length) or b"{}")
        word     = body.get("word", "").strip()
        filename = body.get("filename", "").strip()

        if not word or not filename:
            self._json({"error": "word and filename required"}, 400)
            return

        import re
        def safe(w): return re.sub(r'[^\w\-_. ]', '', w).strip().replace(' ', '_')[:80]

        src = IMAGEN_DIR / "words" / safe(word) / filename
        if not src.is_file():
            self._json({"error": f"source not found: {src}"}, 404)
            return

        out_dir = REPO_ROOT / "docs" / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / f"{safe(word)}.png"

        import shutil
        import subprocess as sp
        try:
            result = sp.run(
                ["pngquant", "--quality=45-75", "--speed", "1", "--force",
                 "--output", str(dest), str(src)],
                capture_output=True
            )
            if result.returncode not in (0, 98):  # 98 = already optimal
                raise RuntimeError(result.stderr.decode())
            method = "pngquant"
        except (FileNotFoundError, RuntimeError):
            shutil.copy2(src, dest)
            method = "copy"

        size_kb = dest.stat().st_size // 1024

        vocab = _read_vocab()
        wkey = word.lower()
        if wkey in vocab:
            vocab[wkey]["default_image"] = filename
            _write_vocab(vocab)

        self._json({"message": f"Saved to {dest.relative_to(REPO_ROOT)} ({size_kb} KB, via {method})"})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vocab local server")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("", args.port), Handler)
    p = args.port
    print(f"Vocab server running on port {p}")
    print(f"  Imagegen UI  →  http://localhost:{p}/")
    print(f"  Docs PWA     →  http://localhost:{p}/docs/")
    print(f"  ComfyUI      →  http://localhost:8188/  (separate process)")
    print("Stop with Ctrl-C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
