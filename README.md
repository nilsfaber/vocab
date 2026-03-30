# Vocabulary Builder

Extract vocabulary words from a KOReader device, enrich them with dictionary definitions and in-book occurrences, and review them in a PWA.

## Folder structure

```
vocab/
├── docs/              # Web app — serve this folder
│   ├── index.html
│   ├── manifest.json
│   ├── sw.js
│   ├── vocab.json     # generated output (gitignored)
│   └── icons/
├── data/              # local cache — gitignored
│   ├── vocab.sqlite3  # pulled from device
│   └── books/         # pulled epub files
├── extract.py         # extraction & enrichment script
├── .gitignore
├── CLAUDE.md
└── README.md
```

## Requirements

- Python 3.9+
- Android Debug Bridge (adb) — set the path in `extract.py` under `ADB`
- KOReader installed on a connected Android device with USB debugging enabled
- Internet connection for fetching definitions

## Setup

1. Connect your Android device via USB and enable USB debugging.
2. Edit the `ADB` path at the top of `extract.py` if adb is not at `C:/git/platform-tools/adb.exe`.
3. Run the extraction script from the repo root:

```bash
python extract.py
```

This will:
- Pull `vocabulary_builder.sqlite3` from the device → `data/vocab.sqlite3`
- Find and pull all `.epub` files from `/sdcard` → `data/books/`
- Export enriched vocabulary data → `docs/vocab.json`
- Fetch definitions from the Free Dictionary API for any word not yet defined

4. Serve the app:

```bash
cd docs
python -m http.server 8000
```

5. Open `http://localhost:8000` in a browser.

## Re-running

Re-running `extract.py` is safe:
- Already-cached epub files are skipped (pull only new ones).
- Words that already have a definition are skipped.

## Web app

### Overview mode

A searchable grid of all vocabulary words. Click any card to open a detail panel showing:

- Definition and part of speech (from Free Dictionary API)
- Example sentence
- Context from the original KOReader lookup (sentence surrounding the word)
- All paragraph occurrences of the word across every book in your library, grouped by book
- Review stats (review count, streak)

### Game mode

A flashcard-style quiz:
- If a definition is available, it is shown as the clue with part of speech and an example sentence (with the word blanked out).
- Otherwise, the lookup context sentence is shown with the word blanked out.
- Choose the correct word from four options.
- After answering, the full definition and context are revealed.

### Manual words

Click **+ Add** in the header to add a word manually without a device. Fields:
- Word (required)
- Part of speech
- Definition
- Context sentence — use `___` as placeholder for the word
- Source / book title

Manual words are stored in `localStorage` and merged with the loaded `vocab.json`. They appear with an amber "manual" badge. They can be edited or deleted from their detail panel.

### PWA / offline

The app is installable as a PWA. On mobile, use "Add to Home Screen". Once installed:
- The app shell (HTML, SW, manifest, icons) is cached and works offline.
- `vocab.json` is served network-first and cached as a fallback.

## Dictionary data

Definitions are fetched from [dictionaryapi.dev](https://dictionaryapi.dev/) — free, no API key required. Only English words are supported. Words not found in the dictionary are silently skipped and can be filled in manually via the app.
