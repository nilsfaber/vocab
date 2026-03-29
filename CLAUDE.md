# Claude instructions

## PWA version
The app in `app/` is a PWA. After any change to `app/index.html`, `app/sw.js`, or `app/manifest.json`:
- Bump the cache name in `app/sw.js` (e.g. `vocab-v1` → `vocab-v2`) so returning users get the updated shell.
- If new static files were added to `app/`, add them to the `SHELL` array in `app/sw.js`.

## README
Update `README.md` whenever functionality changes — new features, changed commands, or changed folder structure.
Keep the setup section accurate; users follow it verbatim.

## General
- `data/` and `app/vocab.json` are gitignored. Never commit them.
- Python paths in `extract.py` are relative to the repo root; run the script from there.
- The app is served from `app/` with `python -m http.server 8000` run inside that folder.

## Backlog

## 1 - fix finding wrong word occurences
For the word onus, bonus was found,
conjugations should still be detected

## 2 - add more game modes
add a game mode where the word is given and a sentence or explanation needs to be selected, the opposite as the current game.
think of a concept where for each word i can generate an image of the sentence where it was added is used to generate an image locally

## 3 - predict other words to add the vocabulary list
analyse the words that are not known to generate additional words that the user
probably doesnt know.

## 4 - add a method to use the local vocab.sqlite3 if no device is connected

## 5 - fix detailed word view
clicking closes the view but is also assigned to expanding the word.

## 6 - show log for the step after parsing the epubs

## 7 - do something with not found words in dictionary api