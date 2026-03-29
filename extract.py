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
APP_DIR   = "app"


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

    print(f"✅ {len(pulled)} epub(s) ready ({new_count} new)")
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


def export_json(output=None):
    if output is None:
        output = f"{APP_DIR}/vocab.json"

    # carry over previously fetched definitions so they survive a re-export
    existing_defs = {}
    if os.path.exists(output):
        try:
            with open(output, encoding="utf-8") as f:
                for e in json.load(f):
                    if e.get("enriched"):
                        existing_defs[e["word"]] = {
                            "definition":     e.get("definition", ""),
                            "part_of_speech": e.get("part_of_speech", ""),
                            "example":        e.get("example", ""),
                            "synonyms":       e.get("synonyms", []),
                            "antonyms":       e.get("antonyms", []),
                            "enriched":       True,
                        }
        except Exception:
            pass

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

    for row in rows:
        if row["word"] in existing_defs:
            row.update(existing_defs[row["word"]])

    epubs = find_local_epubs()
    if epubs:
        print(f"📖 Parsing {len(epubs)} epub(s)...")
        paragraph_cache = {}
        for i, (epub_path, display) in enumerate(epubs.items(), 1):
            _progress(i, len(epubs), display[:40])
            paragraph_cache[epub_path] = (display, extract_paragraphs(epub_path))

        for entry in rows:
            pattern = re.compile(r'\b' + re.escape(entry["word"]) + r'\w*', re.IGNORECASE)
            entry["occurrences"] = [
                {"book": display, "paragraph": trim_to_context(para, entry["word"])}
                for display, paragraphs in paragraph_cache.values()
                for para in paragraphs
                if pattern.search(para)
            ]
    else:
        print("⚠ No epub files found in data/books/")
        for entry in rows:
            entry["occurrences"] = []

    with open(output, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    total_occs = sum(len(e["occurrences"]) for e in rows)
    print(f"✅ Exported {len(rows)} words, {total_occs} occurrences → {output}")


def fetch_definitions(output=None):
    if output is None:
        output = f"{APP_DIR}/vocab.json"
    with open(output, encoding="utf-8") as f:
        entries = json.load(f)

    pending = [e for e in entries if not e.get("enriched")]
    if not pending:
        print("✅ Definitions already up to date")
        return

    print(f"📚 Fetching definitions for {len(pending)} word(s)...")
    updated = 0
    for i, entry in enumerate(pending, 1):
        word = entry["word"]
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

    with open(output, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"✅ Definitions fetched: {updated} found, {len(pending) - updated} not in dictionary")


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
    export_json()
    fetch_definitions()


if __name__ == "__main__":
    main()
