# Vocabulary Builder

Extract vocabulary from a KOReader device, enrich with definitions and images, and review in a PWA.

## Three pillars

| | Folder | Runs on |
|---|---|---|
| **Vocab extraction** | `extract.py` (repo root) | Dev machine |
| **Image generation** | `imagegen/` | Dev machine (GPU) |
| **Web app** | `docs/` | Browser / GitHub Pages |

---

## Folder structure

```
vocab/
├── extract.py              # Vocab extraction + enrichment
├── setup.sh                # Dependency checker
│
├── docs/                   # Deployable PWA (GitHub Pages)
│   ├── index.html
│   ├── sw.js
│   ├── manifest.json
│   ├── icons/
│   ├── vocab.json          # gitignored — generated
│   └── images/             # gitignored — generated compressed images
│
├── imagegen/               # Dev-only image generation
│   ├── index.html          # Management UI
│   ├── server.py           # Local API server
│   ├── gemma4b_sdxl_refiner.py
│   ├── mistralnemo_sdxl.py
│   ├── manifest.json       # gitignored — image registry
│   └── <word>/             # gitignored — per-word image dirs
│
└── data/                   # gitignored — local cache
    ├── vocab.sqlite3
    └── books/
```

---

## Requirements

- Python 3.9+
- Android Debug Bridge (adb) — for device sync
- `pngquant` — for image compression
- Ollama with `gemma4:e2b` pulled — for image generation
- ComfyUI with SDXL base + refiner checkpoints — for image generation

Run the setup checker:
```bash
bash setup.sh
```

---

## Pillar 1 — Vocab extraction

### From a KOReader device

1. Connect Android device via USB with USB debugging enabled.
2. Edit the `ADB` path at the top of `extract.py` if needed.
3. Run from the repo root:

```bash
python extract.py
```

This:
- Pulls `vocabulary_builder.sqlite3` → `data/vocab.sqlite3`
- Pulls all `.epub` files from `/sdcard` → `data/books/`
- Exports enriched vocab → `docs/vocab.json`
- Fetches definitions from [dictionaryapi.dev](https://dictionaryapi.dev/) for new words

Re-running is safe — existing definitions and cached epubs are skipped.

### Adding a word manually

Add the word string to `data/manual_words.json` (create it if it doesn't exist):
```json
["ephemeral", "sanguine"]
```
Then re-run `python extract.py`. Definitions are fetched automatically.

---

## Pillar 2 — Image generation

### Prerequisites

```bash
source venv/bin/activate
ollama serve               # keep running
python ComfyUI/main.py     # keep running
```

### Start the imagegen server

Always run the server instead of a plain HTTP server — it serves the UI and exposes the run API.

```bash
# From repo root:
python imagegen/server.py          # uses test/vocab.json
python imagegen/server.py --prod   # uses docs/vocab.json
```

Open `http://localhost:8765`.

### Run a script from the command line

```bash
python imagegen/gemma4b_sdxl_refiner.py --prod           # all words
python imagegen/gemma4b_sdxl_refiner.py --words brethren alacrity  # specific words
python imagegen/gemma4b_sdxl_refiner.py --prod --force   # regenerate all
```

### imagegen UI

- **Word list** — sorted alphabetically. Dots: 🔴 no default set, 🟠 flagged for regen, 🔵 new unseen images.
- **Word view** — click any word to see its images. The word title overlays the current image.
- **Alternatives** — thumbnail grid below the image. Click a thumbnail to set it as the default **and** write it to `docs/images/<word>.png`.
- **Run panel** — select a script, optionally edit the base prompt, click **▶ Run**. Output streams live. New images appear without page reload.
- **Definition editor** — edit the definition inline and save. Used when re-running generation for that word.
- **Flag button** (🔁) next to word title — adds/removes the word from the regen queue. Download the queue as JSON from the sidebar.
- **Columns slider** — adjust gallery column count (persisted).
- **Fullscreen** — expands the current image or gallery.

### Image file layout

```
imagegen/
└── <word>/
    └── DDMMYY_N_<scriptname>.png    # e.g. 050426_1_gemma4b_sdxl_refiner.png
```

The `imagegen/manifest.json` tracks all variants, prompts, scenes, and the selected default per word.

### Write to docs

Selecting an image in the UI automatically compresses it with pngquant and writes it to `docs/images/<word>.png`.

---

## Pillar 3 — Web app (`docs/`)

Serve locally:
```bash
cd docs
python -m http.server 8000
```
Or use the imagegen server which also serves any static path.

Open `http://localhost:8000`.

### Overview

Searchable, sortable grid of all vocabulary words. Sort by date added, occurrence count, alphabetical, or game score.

Click a card to open the detail panel showing:
- Definition, part of speech, example sentence
- Original KOReader lookup context
- All paragraph occurrences across your library
- Game stats
- Hero image (if generated)
- Wikipedia link (live lookup, cached per session)

### Game mode

Flashcard-style quiz. Nouns excluded.
- Clue: definition with word blanked, or context sentence with word blanked.
- Pick the correct word from four options.
- After answering, full definition and context are revealed.
- Mark correct answers as **Learned** to remove from future rounds.

### Manual words

Click **+ Add** in the toolbar to add a word without a device. Fields: word, part of speech, definition, context sentence (`___` as placeholder), source. Stored in `localStorage`, merged at runtime with `vocab.json`. Editable and deletable from the detail panel.

### Settings

- **Theme** — Dark (default), Light, E-Paper. Persisted in `localStorage`.
- **Reset game stats** — clears all correct/wrong counts.
- **Parse log** — view timestamped output from the last `extract.py` run.

### PWA / offline

Installable via "Add to Home Screen". App shell cached by service worker. `vocab.json` is network-first with offline fallback.

---

## Dictionary data

Definitions from [dictionaryapi.dev](https://dictionaryapi.dev/) — free, no API key. English only. Unfound words are skipped and can be filled manually in the app or via `data/manual_words.json`.
