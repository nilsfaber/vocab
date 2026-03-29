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
    print("🔍 Looking for KOReader folder...")
    output = run_adb(["-s", device, "shell", "ls", REMOTE_BASE])

    if "koreader" not in output:
        print("❌ KOReader folder not found in /sdcard/")
        sys.exit(1)

    print("✅ Found koreader folder")


def pull_database(device):
    remote_file = f"{KOREADER_PATH}/{DB_NAME}"

    print("📥 Pulling database...")
    run_adb(["-s", device, "pull", remote_file, LOCAL_DB])

    if not os.path.exists(LOCAL_DB):
        print("❌ Failed to pull database")
        sys.exit(1)

    print(f"✅ Database saved as {LOCAL_DB}")


def pull_books(device):
    print("🔍 Finding epub files on device...")
    output = run_adb(["-s", device, "shell", "find", "/sdcard", "-name", "*.epub", "-type", "f"])
    paths = [p.strip() for p in output.splitlines() if p.strip()]

    os.makedirs(BOOKS_DIR, exist_ok=True)

    pulled = {}  # filename -> local path
    for remote_path in paths:
        filename = remote_path.split("/")[-1]
        local_path = f"{BOOKS_DIR}/{filename}"
        if not os.path.exists(local_path):
            print(f"  📥 {filename}")
            run_adb(["-s", device, "pull", remote_path, local_path])
        else:
            print(f"  ✔ {filename} (already cached)")
        pulled[filename] = local_path

    print(f"✅ {len(pulled)} epub(s) ready")
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
                    if e.get("definition"):
                        existing_defs[e["word"]] = {
                            "definition":     e["definition"],
                            "part_of_speech": e.get("part_of_speech", ""),
                            "example":        e.get("example", ""),
                            "synonyms":       e.get("synonyms", []),
                            "antonyms":       e.get("antonyms", []),
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
        paragraph_cache = {}  # epub_path -> (display_name, [paragraphs])
        for epub_path, display in epubs.items():
            print(f"  {display}")
            paragraph_cache[epub_path] = (display, extract_paragraphs(epub_path))

        for entry in rows:
            word_lower = entry["word"].lower()
            entry["occurrences"] = [
                {"book": display, "paragraph": trim_to_context(para, entry["word"])}
                for display, paragraphs in paragraph_cache.values()
                for para in paragraphs
                if word_lower in para.lower()
            ]
    else:
        print("⚠ No epub files found in data/books/ — skipping occurrences")
        for entry in rows:
            entry["occurrences"] = []

    with open(output, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    print(f"✅ Exported {len(rows)} words to {output}")


def fetch_definitions(output=None):
    if output is None:
        output = f"{APP_DIR}/vocab.json"
    with open(output, encoding="utf-8") as f:
        entries = json.load(f)

    updated = 0
    for entry in entries:
        # skip if already fully enriched (definition + synonyms key present)
        if entry.get("definition") and "synonyms" in entry:
            continue

        word = entry["word"]
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
                    updated += 1
                    print(f"  ✅ {word}: {entry['definition'][:70]}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  — {word}: not found")
            else:
                print(f"  ⚠ {word}: HTTP {e.code}")
        except Exception as e:
            print(f"  ⚠ {word}: {e}")

        time.sleep(0.3)

    with open(output, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)

    print(f"✅ Added definitions for {updated} words in {output}")


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
