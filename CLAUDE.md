# Claude instructions

## PWA version
The app in `docs/` is a PWA. After any change to `docs/index.html`, `docs/sw.js`, or `docs/manifest.json`:
- Bump the cache name in `docs/sw.js` (e.g. `vocab-v1` → `vocab-v2`) so returning users get the updated shell.
- If new static files were added to `docs/`, add them to the `SHELL` array in `docs/sw.js`.

## README
Update `README.md` whenever functionality changes — new features, changed commands, or changed folder structure.
Keep the setup section accurate; users follow it verbatim.

## General
- `data/` and `docs/vocab.json` are gitignored. Never commit them.
- Python paths in `extract.py` are relative to the repo root; run the script from there.
- The app is served from `docs/` with `python -m http.server 8000` run inside that folder.

## Backlog

Ordered by priority (complexity vs. gain). Tackle top-down.

---
### Easy fixes
#### Overview
Change hidden concept, add a second grid below the
current overview where all the words that are marked as learned reside. make that grid collapsible
#### Detail card
The h2 and close button should stay on top and visible,
so you see which word you are on and can close it at any time

#### Game UI
Increase the game feedback size, figure out a max size for the clue card and to get a sensible height. now the distance between challenge and multiple choice answer is too big. make sure to have the answers always be in the same position between challenges
Move the next button to the bottom .

#### Top Bar 
 Move the overview toolbar to the header, switch it to a game toolbar when going to the game.
in game mode for now just show the score.

#### Settings view
For both add a settings button to the top right and for now create a shared settings view.
add a reset stats button
add a to toggle to switch between themes:
dark/light/e-paper 
use the following settings as inspiration:
/* --- CSS Custom Properties --- */
:root {
  --bg-primary: #1a1a2e;
  --bg-secondary: #16213e;
  --bg-card: #0f3460;
  --bg-surface: #1a1a3e;
  --accent: #e94560;
  --accent-hover: #ff6b81;
  --accent-dim: #c23152;
  --text-primary: #eaeaea;
  --text-secondary: #a0a0b8;
  --text-muted: #6c6c8a;
  --success: #2ed573;
  --warning: #ffa502;
  --danger: #ff4757;
}

/* ── Light theme ────────────────────────────────────── */
:root[data-theme="light"] {
  --bg-primary:    #d8dae2;  /* page background — mid gray */
  --bg-secondary:  #cdd0da;  /* slightly darker */
  --bg-card:       #bfc3cf;  /* card surfaces */
  --bg-surface:    #e2e4ec;  /* inputs, feed items — lighter than page */
  --accent:        #c0273f;
  --accent-hover:  #e03050;
  --accent-dim:    #a01f35;
  --text-primary:  #1a1a2e;
  --text-secondary:#3a3a5a;
  --text-muted:    #6a6a8a;
  --success:       #1a8a3a;
  --warning:       #b86000;
  --danger:        #cc2233;
}
/* ── E-paper theme ──────────────────────────────────── */
:root[data-theme="epaper"] { /* primarly use borders to deleniate buttons regions*/
  --bg-primary:    #ffffff; 
  --bg-secondary:  #f8f8f8;
  --bg-card:       #efefef;
  --bg-surface:    #f4f4f4;
  --accent:        #111111;
  --accent-hover:  #333333;
  --accent-dim:    #555555;
  --text-primary:  #111111;
  --text-secondary:#444444;
  --text-muted:    #888888;
  --success:       #1a6b1a;
  --warning:       #7a5200;
  --danger:        #9a1515;
}


---

### Higher effort (split as needed)

#### 12 - Improve definition card
- Add location of word occurrence in book (chapter / % progress)
- Move book title to context section, not directly under the word
- Show scored / failed counts per word

#### 10 - File Import/Export of data
**10a** — Export: download vocab + manual words as JSON from localStorage.
**10b** — Import: upload JSON, merge with existing data (handle conflicts/duplicates).
Sharing game stats is optional.

#### 16 - More game modes
**16a** — Reverse mode: word is shown, player picks the correct definition/sentence.
**16b** — Image mode: word card backed by a locally-generated image (see item 14).

#### 2 - Local vocab.sqlite3 fallback
**2a** — Detect when no device is connected, show a clear message/fallback UI.
**2b** — Read local `vocab.sqlite3` directly in the browser using sql.js.

#### 13 - Fetch translations
Add option to fetch translations for configured languages (Dutch initially).

#### 13 - Check if wiki article exists for word
link it when it exists

---

### Low priority / defer

#### 5 - Show not-found dictionary words
Words with no dictionary API result shown in a separate grid in overview.

#### 14 - Local image generation per word
Generate an image per word using a local model (e.g. Flux) based on context sentence.
Use as low-opacity background on word card and in detail modal.
Prompt style: vintage sci-fi paperback illustration, 1970s print, halftone shading, bold outlines.

#### 17 - Predict unknown words to add
Analyze library text to suggest words the user likely doesn't know yet.

#### 18 - Show log for epub parsing step
Surface parsing logs in the UI after extract.py processes epubs.


### Done

#### 3 - Fix detailed word view click conflict
Clicking the card closes the detail view AND triggers expand. Separate these two interactions cleanly.

#### 6 - Fix skip button highlight after puzzle is solved
Skip button should not appear highlighted/active once a puzzle is solved.

#### 7 - Never use noun as game challenge
Nouns are too easy. Filter them out in `nextRound()` when selecting a word to quiz on.

#### 4 - Show word card on solved puzzle
After a correct guess, show a button or auto-open the full word detail card.

#### 1 - Fix word occurrence matching (word boundaries)
For "fen", "defence" should not match. Use `\b` word boundary regex globally.
Conjugations (e.g. "fens") should still be detected — only exclude mid-word matches.

#### 8 - Fix game mode layout and overflow
Game mode should not scroll if content fits. Layout should be stable:
- Challenge text anchored to the top
- Answer choices anchored to the bottom
- No layout shift based on challenge length

#### 0 - Fix PWA manifest link
Update any remaining `app/` references to `docs/` in manifest or service worker.

#### 11 - Move Add button into overview toolbar
Remove from top bar; place it inside the overview section (e.g. as an empty card or toolbar button).

#### 15 - Add sort modes for overview
Add sort options: alphabetical, score/fail rate (from game challenges).
Alongside existing: date added, occurrence count.

#### 9 - Preserve challenge when switching between game and overview
Switching to overview and back should not reset the current challenge.
Visiting overview mid-challenge should not count as a score.


---