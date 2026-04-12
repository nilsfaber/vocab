import subprocess
import sqlite3
import os
import sys
import json
import re
import time
import zipfile
import urllib.request



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

ADB = "C:/git/platform-tools/adb.exe" if os.name == "nt" else "adb"
REMOTE_BASE = "/sdcard"
KOREADER_PATH = f"{REMOTE_BASE}/koreader/settings"
DB_NAME = "vocabulary_builder.sqlite3"
LOCAL_DB = "data/vocab.sqlite3"
BOOKS_DIR = "data/books"
APP_DIR   = "docs"

HARDCOVER_URL   = "https://api.hardcover.app/v1/graphql"
HARDCOVER_TOKEN = os.environ.get("HARDCOVER_TOKEN", "")

_READ_BOOKS_QUERY = """
query MyReadBooks {
  me {
    user_books(where: {status_id: {_eq: 3}}) {
      book {
        title
        contributions { author { name } }
      }
    }
  }
}
"""

def _normalize_title(title: str) -> str:
    t = title.lower().strip()
    for prefix in ("the ", "a ", "an "):
        if t.startswith(prefix):
            t = t[len(prefix):]
    return re.sub(r"[^\w\s]", "", t).strip()


def fetch_read_books() -> tuple:
    """Return (normalised_titles, api_ok).
    api_ok=True only when token is present and the request succeeded."""
    if not HARDCOVER_TOKEN:
        return set(), False
    try:
        payload = json.dumps({"query": _READ_BOOKS_QUERY}).encode()
        req = urllib.request.Request(
            HARDCOVER_URL, data=payload,
            headers={"Authorization": f"Bearer {HARDCOVER_TOKEN}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        me = data.get("data", {}).get("me", {})
        if isinstance(me, list):
            me = me[0] if me else {}
        user_books = me.get("user_books", [])
        titles = {_normalize_title(ub["book"]["title"])
                  for ub in user_books if ub.get("book", {}).get("title")}
        return titles, True
    except Exception as e:
        _log(f"⚠ Hardcover API error: {e}")
        return set(), False


def run_adb(args):
    try:
        result = subprocess.run([ADB] + args, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"❌ adb not found: '{ADB}'\n   Install it with: sudo apt install adb")
        sys.exit(1)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        print(f"❌ ADB error (exit {result.returncode}): {detail or '(no output)'}")
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


DEVICE_BOOKS_PATHS = ["/sdcard/books", "/sdcard/Books", "/sdcard/Download", "/sdcard"]

def pull_books(device):
    print("🔍 Finding epub files on device...")
    # Search known book locations first, fall back to full sdcard scan
    paths = []
    for search_path in DEVICE_BOOKS_PATHS:
        output = run_adb(["-s", device, "shell", "find", search_path,
                          "-maxdepth", "3", "-name", "*.epub", "-type", "f"])
        found = [p.strip() for p in output.splitlines() if p.strip()]
        if found:
            paths = found
            print(f"  Found {len(found)} epub(s) in {search_path}")
            break
    if not paths:
        print("⚠ No epub files found on device")

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


_P_RE  = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r'<[^>]+>')

def extract_paragraphs(epub_path):
    paragraphs = []
    try:
        with zipfile.ZipFile(epub_path) as zf:
            for name in zf.namelist():
                if name.endswith((".html", ".xhtml", ".htm")):
                    try:
                        content = zf.read(name).decode("utf-8", errors="ignore")
                        for m in _P_RE.finditer(content):
                            text = _TAG_RE.sub("", m.group(1))
                            text = " ".join(text.split())
                            if text:
                                paragraphs.append(text)
                    except Exception as e:
                        print(f"    ⚠ skipping {name}: {e}")
    except zipfile.BadZipFile:
        print(f"  ⚠ skipping corrupt file: {os.path.basename(epub_path)}")
    return paragraphs


def extract_sentence(paragraph: str, word: str) -> str:
    """Return the single sentence in paragraph that contains word."""
    sentences = _SENTENCE_BREAK.split(paragraph.strip())
    word_lower = word.lower()
    for s in sentences:
        if word_lower in s.lower():
            return s.strip()
    return sentences[0].strip() if sentences else paragraph


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

    # Hardcover status check
    read_titles, hardcover_ok = fetch_read_books()
    if not HARDCOVER_TOKEN:
        _log("⚠ HARDCOVER_TOKEN not set — scanning all local books (no occurrence limit removed)")
    elif hardcover_ok:
        _log(f"✅ Hardcover connected — {len(read_titles)} book(s) marked as read, unlimited occurrences")
    else:
        _log("⚠ Hardcover API unavailable — falling back to all local books")

    # Parse epubs for occurrences — filter to read books if Hardcover connected
    epubs = find_local_epubs()
    if hardcover_ok and read_titles and epubs:
        filtered = {p: d for p, d in epubs.items()
                    if any(_normalize_title(d) in rt or rt in _normalize_title(d)
                           for rt in read_titles)}
        if filtered:
            _log(f"📖 Filtered to {len(filtered)}/{len(epubs)} epub(s) you have read")
            epubs = filtered
        else:
            _log(f"⚠ No local epubs matched Hardcover read list — using all {len(epubs)}")

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
        results = []
        for display, paragraphs in paragraph_cache.values():
            for para in paragraphs:
                if pattern.search(para):
                    results.append({"book": display, "paragraph": extract_sentence(para, word)})
                    if not hardcover_ok and len(results) >= 10:
                        return results
        return results

    new_count = 0
    if paragraph_cache:
        _log(f"🔎 Computing occurrences for {len(rows)} word(s)...")
    for i, row in enumerate(rows, 1):
        if paragraph_cache:
            _progress(i, len(rows), row["word"][:40])
        key = row["word"].lower()
        if vocab.get(key, {}).get("deleted"):
            continue  # skip words the user has deleted
        if key in vocab:
            # Update KOReader-tracked fields only; preserve enriched/imagegen fields
            vocab[key]["review_count"] = row["review_count"]
            vocab[key]["streak_count"] = row["streak_count"]
            if paragraph_cache:  # only overwrite occurrences if we have epub data
                vocab[key]["occurrences"] = compute_occurrences(row["word"])
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
            if vocab.get(key, {}).get("deleted"):
                continue
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
                    entry["phonetic"]      = data[0].get("phonetic", "")
                    entry["part_of_speech"] = first.get("partOfSpeech", "")
                    entry["definition"]    = defs[0].get("definition", "")
                    entry["example"]       = defs[0].get("example") or ""
                    # All definitions across all parts of speech
                    entry["definitions"] = [
                        {
                            "part_of_speech": m.get("partOfSpeech", ""),
                            "definition":     d.get("definition", ""),
                            "example":        d.get("example") or "",
                        }
                        for m in meanings
                        for d in m.get("definitions", [])
                    ]
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
    devices = get_devices()
    device = pick_device(devices)

    check_koreader(device)
    pull_database(device)
    pull_books(device)
    vocab = export_json() 
    # read a json
    # vocab = _load_existing_vocab(f"{APP_DIR}/vocab.json")
    fetch_definitions(vocab)
    fetch_translations(vocab)
    _write_log()


if __name__ == "__main__":
    main()
