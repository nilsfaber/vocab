import subprocess
import sqlite3
import os
import sys
import json
import re
import time
import zipfile
import urllib.request
from html.parser import HTMLParser



_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+')

_LOG   = []
_LOG_PATH = "docs/parse_log.json"

def _log(msg):
    """Print and record for parse_log.json."""
    print(msg)
    _LOG.append({"time": time.strftime("%H:%M:%S"), "msg": str(msg)})

def _write_log():
    try:
        with open(_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump({"run_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "entries": _LOG}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"\u26a0 Could not write parse log: {e}")


def _progress(current, total, label="", width=40):
    filled = int(width * current / total) if total else 0
    bar = "█" * filled + "░" * (width - filled)
    pct = int(100 * current / total) if total else 0
    sys.stdout.write(f"\r  [{bar}] {pct:3d}%  {label:<40}")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")

ADB = "C:/git/platform-tools/adb.exe"
REMOTE_BASE = "/sdcard"
KOREADER_PATH = f"{REMOTE_BASE}/koreader/settings"
DB_NAME = "vocabulary_builder.sqlite3"
LOCAL_DB = "data/vocab.sqlite3"
BOOKS_DIR = "data/books"
APP_DIR   = "docs"


def run_adb(args):
    result = subprocess.run([ADB] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print("ADB error:", result.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_devices():
    output = run_adb(["devices"])
    lines = output.splitlines()[1:]  # skip header

    devices = []
    for line in lines:
        if line.strip() and "device" in line:
            devices.append(line.split()[0])

    return devices


def pick_device(devices):
    if len(devices) == 0:
        print("❌ No Android devices found")
        sys.exit(1)
    elif len(devices) == 1:
        print(f"✅ Using device: {devices[0]}")
        return devices[0]
    else:
        print("❌ Multiple devices found, please specify:")
        for d in devices:
            print(" -", d)
        sys.exit(1)


def check_koreader(device):
    output = run_adb(["-s", device, "shell", "ls", REMOTE_BASE])
    if "koreader" not in output:
        print("❌ KOReader folder not found in /sdcard/")
        sys.exit(1)


def pull_database(device):
    remote_file = f"{KOREADER_PATH}/{DB_NAME}"

    run_adb(["-s", device, "pull", remote_file, LOCAL_DB])
    if not os.path.exists(LOCAL_DB):
        print("❌ Failed to pull database")
        sys.exit(1)
    print("✅ Database pulled")


def pull_books(device):
    print("🔍 Finding epub files on device...")
    output = run_adb(["-s", device, "shell", "find", "/sdcard", "-name", "*.epub", "-type", "f"])
    paths = [p.strip() for p in output.splitlines() if p.strip()]

    os.makedirs(BOOKS_DIR, exist_ok=True)

    pulled = {}
    new_count = 0
    for i, remote_path in enumerate(paths, 1):
        filename = remote_path.split("/")[-1]
        local_path = f"{BOOKS_DIR}/{filename}"
        if not os.path.exists(local_path):
            run_adb(["-s", device, "pull", remote_path, local_path])
            new_count += 1
        pulled[filename] = local_path
        _progress(i, len(paths), filename[:40])

    _log(f"✅ {len(pulled)} epub(s) ready ({new_count} new)")
    return pulled


class _ParagraphExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self._in_p = False
        self._buf = []

    def handle_starttag(self, tag, *_):
        if tag == "p":
            self._in_p = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "p" and self._in_p:
            self._in_p = False
            text = " ".join(self._buf).split()
            text = " ".join(text)  # collapse whitespace
            if text:
                self.paragraphs.append(text)

    def handle_data(self, data):
        if self._in_p:
            self._buf.append(data)


def extract_paragraphs(epub_path):
    paragraphs = []
    try:
        with zipfile.ZipFile(epub_path) as zf:
            for name in zf.namelist():
                if name.endswith((".html", ".xhtml", ".htm")):
                    content = zf.read(name).decode("utf-8", errors="ignore")
                    parser = _ParagraphExtractor()
                    try:
                        parser.feed(content)
                    except Exception as e:
                        print(f"    ⚠ parse error in {name}: {e}")
                    paragraphs.extend(parser.paragraphs)
    except zipfile.BadZipFile:
        print(f"  ⚠ skipping corrupt file: {os.path.basename(epub_path)}")
    return paragraphs


def trim_to_context(paragraph, word, before=5, after=5):
    sentences = _SENTENCE_BREAK.split(paragraph.strip())
    word_lower = word.lower()
    target = next((i for i, s in enumerate(sentences) if word_lower in s.lower()), None)
    if target is None:
        return " ".join(sentences[:before + after + 1])
    start = max(0, target - before)
    end = min(len(sentences), target + after + 1)
    return " ".join(sentences[start:end])


def find_local_epubs():
    """Walk BOOKS_DIR recursively and return {path: display_name} for all epubs."""
    found = {}
    for root, _dirs, files in os.walk(BOOKS_DIR):
        for f in files:
            if f.lower().endswith(".epub"):
                full = os.path.join(root, f)
                found[full] = f.removesuffix(".epub").removesuffix(".epub".upper())
    return found


def _load_existing_vocab(output):
    """Load existing vocab.json. Handles both object (new) and array (legacy) format."""
    if not os.path.exists(output):
        return {}
    try:
        with open(output, encoding="utf-8") as f:
            existing = json.load(f)
        if isinstance(existing, dict):
            return existing
        elif isinstance(existing, list):
            _log("⚠ Migrating vocab.json from array to object format…")
            return {e["word"].lower(): e for e in existing if e.get("word")}
    except Exception:
        pass
    return {}


def _save_vocab(vocab, output):
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(vocab, f, ensure_ascii=False, indent=2)


def export_json(output=None):
    """Merge KOReader SQLite data into vocab.json. Only adds new words; preserves existing fields."""
    if output is None:
        output = f"{APP_DIR}/vocab.json"

    vocab = _load_existing_vocab(output)

    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.word, v.highlight, v.prev_context, v.next_context,
               v.create_time, v.review_count, v.streak_count, t.name AS title
        FROM vocabulary v
        LEFT JOIN title t ON v.title_id = t.id
        ORDER BY v.create_time DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Parse epubs for occurrences
    epubs = find_local_epubs()
    paragraph_cache = {}
    if epubs:
        _log(f"📖 Parsing {len(epubs)} epub(s)...")
        for i, (epub_path, display) in enumerate(epubs.items(), 1):
            _progress(i, len(epubs), display[:40])
            paragraph_cache[epub_path] = (display, extract_paragraphs(epub_path))
    else:
        _log("⚠ No epub files found in data/books/")

    def compute_occurrences(word):
        if not paragraph_cache:
            return []
        pattern = re.compile(r'\b' + re.escape(word) + r'\w*', re.IGNORECASE)
        return [
            {"book": display, "paragraph": trim_to_context(para, word)}
            for display, paragraphs in paragraph_cache.values()
            for para in paragraphs
            if pattern.search(para)
        ]

    new_count = 0
    for row in rows:
        key = row["word"].lower()
        if key in vocab:
            # Update KOReader-tracked fields only; preserve enriched/imagegen fields
            vocab[key]["review_count"] = row["review_count"]
            vocab[key]["streak_count"] = row["streak_count"]
            vocab[key]["occurrences"]  = compute_occurrences(row["word"])
        else:
            vocab[key] = {
                "word":             row["word"],
                "highlight":        row["highlight"],
                "prev_context":     row["prev_context"],
                "next_context":     row["next_context"],
                "create_time":      row["create_time"],
                "review_count":     row["review_count"],
                "streak_count":     row["streak_count"],
                "title":            row["title"],
                "source":           "koreader",
                "occurrences":      compute_occurrences(row["word"]),
                "images":           [],
                "default_image":    None,
                "flagged_for_regen": False,
                "translation":      {},
            }
            new_count += 1

    # Manual words
    try:
        with open("data/manual_words.json", encoding="utf-8") as f:
            manual = json.load(f)
        for word_str in manual:
            key = word_str.lower()
            if key not in vocab:
                vocab[key] = {
                    "word":             word_str,
                    "source":           "manual",
                    "occurrences":      [],
                    "images":           [],
                    "default_image":    None,
                    "flagged_for_regen": False,
                    "translation":      {},
                }
                new_count += 1
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    _save_vocab(vocab, output)
    total_occs = sum(len(e.get("occurrences", [])) for e in vocab.values())
    _log(f"✅ {len(vocab)} words ({new_count} new), {total_occs} occurrences → {output}")

    # Write public version: occurrences stripped of paragraph text (copyright-safe)
    public_output = output.replace("vocab.json", "vocab_public.json")
    public_vocab = {}
    for key, entry in vocab.items():
        public_entry = {k: v for k, v in entry.items() if k != "occurrences"}
        public_entry["occurrences"] = [
            {"book": occ["book"]} for occ in entry.get("occurrences", [])
        ]
        public_vocab[key] = public_entry
    _save_vocab(public_vocab, public_output)
    _log(f"📤 Public vocab (no paragraphs) → {public_output}")

    return vocab


def fetch_definitions(vocab, output=None):
    """Fetch dictionary definitions for words that don't have one yet."""
    if output is None:
        output = f"{APP_DIR}/vocab.json"

    pending = [(key, entry) for key, entry in vocab.items() if not entry.get("enriched")]
    if not pending:
        _log("✅ Definitions already up to date")
        return

    _log(f"📚 Fetching definitions for {len(pending)} word(s)...")
    updated = 0
    for i, (key, entry) in enumerate(pending, 1):
        word = entry.get("word", key)
        _progress(i, len(pending), word)
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.request.quote(word)}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vocab-builder/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            meanings = data[0].get("meanings", [])
            if meanings:
                first = meanings[0]
                defs = first.get("definitions", [])
                if defs:
                    entry["part_of_speech"] = first.get("partOfSpeech", "")
                    entry["definition"] = defs[0].get("definition", "")
                    entry["example"] = defs[0].get("example") or ""
                    synonyms = set()
                    antonyms = set()
                    for meaning in meanings:
                        synonyms.update(meaning.get("synonyms", []))
                        antonyms.update(meaning.get("antonyms", []))
                        for d in meaning.get("definitions", []):
                            synonyms.update(d.get("synonyms", []))
                            antonyms.update(d.get("antonyms", []))
                    entry["synonyms"] = sorted(synonyms)
                    entry["antonyms"] = sorted(antonyms)
                    entry["enriched"] = True
                    updated += 1
        except urllib.error.HTTPError as e:
            if e.code == 404:
                entry["enriched"] = True
            else:
                sys.stdout.write(f"\n  ⚠ {word}: HTTP {e.code}\n")
        except Exception as e:
            sys.stdout.write(f"\n  ⚠ {word}: {e}\n")

        time.sleep(0.3)

    _save_vocab(vocab, output)
    _log(f"✅ Definitions fetched: {updated} found, {len(pending) - updated} not in dictionary")


def fetch_translations(vocab, lang="nl", output=None):
    """Fetch translations (via MyMemory) for enriched words without one yet."""
    if output is None:
        output = f"{APP_DIR}/vocab.json"

    pending = [
        (key, entry) for key, entry in vocab.items()
        if entry.get("enriched") and not entry.get("translation", {}).get(lang)
    ]
    if not pending:
        _log(f"✅ Translations ({lang}) already up to date")
        return

    _log(f"🌐 Fetching {lang} translations for {len(pending)} word(s)...")
    updated = 0
    for i, (key, entry) in enumerate(pending, 1):
        word = entry.get("word", key)
        _progress(i, len(pending), word)
        url = (f"https://api.mymemory.translated.net/get?"
               f"q={urllib.request.quote(word)}&langpair=en|{lang}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "vocab-builder/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
            translated  = data.get("responseData", {}).get("translatedText", "").strip()
            match_score = float(data.get("responseData", {}).get("match", 0) or 0)
            if translated and match_score >= 0.5:
                if "translation" not in entry:
                    entry["translation"] = {}
                entry["translation"][lang] = translated
                updated += 1
        except Exception as e:
            sys.stdout.write(f"\n  ⚠ {word}: {e}\n")
        time.sleep(0.3)

    _save_vocab(vocab, output)
    _log(f"✅ Translations ({lang}): {updated}/{len(pending)} fetched")


def inspect_database():
    conn = sqlite3.connect(LOCAL_DB)
    cursor = conn.cursor()

    print("\n📂 Tables:")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()

    for t in tables:
        print(" -", t[0])

    print("\n📊 Schema:")
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table';")
    for row in cursor.fetchall():
        print(row[0], "\n")

    conn.close()


def main():
    # devices = get_devices()
    # device = pick_device(devices)

    # check_koreader(device)
    # pull_database(device)
    # pull_books(device)
    # vocab = export_json() 
    # read a json
    vocab = _load_existing_vocab(f"{APP_DIR}/vocab.json")
    fetch_definitions(vocab)
    fetch_translations(vocab)
    _write_log()


if __name__ == "__main__":
    main()
