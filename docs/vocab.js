/**
 * vocab.js — shared JS for imagegen/index.html and docs/index.html
 *
 * Overridable by the page's inline script:
 *   VOCAB_SERVER   — set to server URL to enable server API (imagegen only)
 *   imgPath(word, filename) — override for imagegen's hi-res words/ path
 *   loadVocab()    — override if page needs custom loading logic
 */

// ── Config — overridable by host page ────────────────────────────────────────
let VOCAB_SERVER = null;   // imagegen sets: `http://${location.hostname}:8765`
let ICON_BASE    = '';     // imagegen sets: '/docs/' (absolute path via server.py)

// ── Data model ────────────────────────────────────────────────────────────────
let vocab = {};           // object keyed by lowercase word
let selectedWord   = null;
let lastOpenedWord = null;

function getDefault(word) { return vocab[word]?.default_image || vocab[word]?.images?.[0]?.filename || null; }
function hasDefault(word)  { return !!vocab[word]?.default_image; }
function isInRegen(word)   { return vocab[word]?.flagged_for_regen || false; }

// ── Filename helpers ──────────────────────────────────────────────────────────
function safeFilename(word) {
  return word.replace(/[^\w\-_. ]/g, '').trim().replace(/ /g, '_').slice(0, 80);
}

// Default: docs PWA path (compressed default image).
// imagegen overrides: imgPath = (word, f) => `words/${safeFilename(word)}/${f}`;
function imgPath(word, _filename) {
  return `images/${safeFilename(word)}.png`;
}

// ── Unseen image tracking ─────────────────────────────────────────────────────
const SEEN_KEY = 'imagen_seen';
function getSeenImages(word) {
  const seen = JSON.parse(localStorage.getItem(SEEN_KEY) || '{}');
  return new Set(seen[word] || []);
}
function markImagesSeen(word) {
  const seen = JSON.parse(localStorage.getItem(SEEN_KEY) || '{}');
  seen[word] = (vocab[word]?.images || []).map(i => i.filename);
  localStorage.setItem(SEEN_KEY, JSON.stringify(seen));
}
function hasUnseenImages(word) {
  const images = vocab[word]?.images || [];
  if (!images.length) return false;
  const seen = getSeenImages(word);
  return images.some(i => !seen.has(i.filename));
}

// ── Persistence ───────────────────────────────────────────────────────────────
// vocab_data localStorage write is intentionally skipped in the PWA — the service
// worker caches vocab.json (network-first) which is the authoritative offline copy.
// We keep the read path as a last-resort fallback for very old cached sessions.
function saveVocabToStorage() { /* no-op: rely on SW cache */ }

async function updateWordField(word, fields) {
  if (vocab[word]) Object.assign(vocab[word], fields);
  if (VOCAB_SERVER) {
    try {
      const res = await fetch(`${VOCAB_SERVER}/api/update-word`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word, ...fields }),
      });
      const data = await res.json();
      return !data.error;
    } catch { return false; }
  } else {
    saveVocabToStorage();
    return true;
  }
}

async function createWord(entry) {
  const key = (entry.word || '').toLowerCase();
  if (VOCAB_SERVER) {
    try {
      const res = await fetch(`${VOCAB_SERVER}/api/add-word`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(entry),
      });
      const data = await res.json();
      if (data.error) return { error: data.error };
      vocab[key] = data.entry;
      return { entry: data.entry };
    } catch { return { error: 'Cannot reach server' }; }
  } else {
    vocab[key] = entry;
    saveVocabToStorage();
    return { entry };
  }
}

async function deleteWord(word) {
  delete vocab[word];
  if (VOCAB_SERVER) {
    try {
      await fetch(`${VOCAB_SERVER}/api/word`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ word }),
      });
    } catch {}
  } else {
    saveVocabToStorage();
  }
}

// ── DOM refs ─────────────────────────────────────────────────────────────────
const sidebar        = document.getElementById('sidebar');
const searchInput    = document.getElementById('search');
const wordList       = document.getElementById('word-list');
const colsBtn        = document.getElementById('cols-btn');
const colsLabel      = document.getElementById('cols-label');
const gallery        = document.getElementById('gallery');
const wordView       = document.getElementById('word-view');
const wordTitle      = document.getElementById('word-title');
const mainImageWrap  = document.getElementById('main-image-wrap');
const mainImage      = document.getElementById('main-image');
const altsSection    = document.getElementById('alts-section');
const altsGrid       = document.getElementById('alts-grid');
const flagBtn        = document.getElementById('flag-btn');
const learntBtn      = document.getElementById('learnt-btn');
const wordPhonetic   = document.getElementById('word-phonetic');
const definitionsList = document.getElementById('definitions-list');
const defMoreBtn     = document.getElementById('def-more-btn');
const statsRows      = document.getElementById('stats-rows');
const defEdit        = document.getElementById('def-edit');
const transEdit      = document.getElementById('trans-edit');
const synsEdit       = document.getElementById('syns-edit');
const antsEdit       = document.getElementById('ants-edit');
const addWordBtn     = document.getElementById('add-word-btn');
const uiToggle       = document.getElementById('ui-toggle');
const lightbox       = document.getElementById('lightbox');
const lightboxImg    = document.getElementById('lightbox-img');
const occurrencesSection = document.getElementById('occurrences-section');
const occurrencesList    = document.getElementById('occurrences-list');

// Panel controls
const pillGame    = document.getElementById('pill-game');
const pillGallery = document.getElementById('pill-gallery');
const pillWord    = document.getElementById('pill-word');
const ctxGame     = document.getElementById('ctx-game');
const ctxGallery  = document.getElementById('ctx-gallery');
const ctxWord     = document.getElementById('ctx-word');

// Optional elements (imagegen-only)
const queueIndicator = document.getElementById('queue-indicator');
const queueCount     = document.getElementById('queue-count');

// ── Sort ──────────────────────────────────────────────────────────────────────
const sortSelect = document.getElementById('sort-by');
sortSelect.addEventListener('change', () => { renderWordList(); renderGallery(); });

function wordScore(data) {
  const s = data.stats || {};
  const total = (s.correct || 0) + (s.wrong || 0);
  return total ? (s.correct || 0) / total : -1;
}

function sortedWords() {
  const mode = sortSelect.value;
  const keys = Object.keys(vocab).filter(k => !vocab[k]?.deleted);
  switch (mode) {
    case 'date':
      return keys.sort((a, b) => {
        const da = vocab[a]?.images?.[0]?.date || '';
        const db = vocab[b]?.images?.[0]?.date || '';
        return db.localeCompare(da) || a.localeCompare(b);
      });
    case 'occurrences':
      return keys.sort((a, b) => {
        const oa = vocab[a]?.occurrences?.length || 0;
        const ob = vocab[b]?.occurrences?.length || 0;
        return ob - oa || a.localeCompare(b);
      });
    case 'score':
      return keys.sort((a, b) =>
        wordScore(vocab[b]) - wordScore(vocab[a]) || a.localeCompare(b)
      );
    default: // alpha
      return keys.sort((a, b) => a.localeCompare(b));
  }
}

function wordMetaLabel(word) {
  const mode = sortSelect.value;
  const data = vocab[word] || {};
  if (mode === 'date') {
    const d = data.images?.[0]?.date;
    return d ? d.slice(5) : '';
  }
  if (mode === 'occurrences') {
    const n = data.occurrences?.length || 0;
    return n > 0 ? String(n) : '';
  }
  if (mode === 'score') {
    const s = wordScore(data);
    return s >= 0 ? Math.round(s * 100) + '%' : '';
  }
  return '';
}

// ── Word list render ──────────────────────────────────────────────────────────
function renderWordList() {
  wordList.innerHTML = '';
  sortedWords().forEach(word => {
    const data = vocab[word] || {};
    const item = document.createElement('div');
    item.className = 'word-item' + (word === selectedWord ? ' active' : '');
    item.dataset.word = word;

    const label = document.createElement('span');
    label.style.flex = '1';
    label.textContent = data.word || word;
    item.appendChild(label);

    const meta = wordMetaLabel(word);
    if (meta) {
      const m = document.createElement('span');
      m.className = 'word-meta';
      m.textContent = meta;
      item.appendChild(m);
    }

    // Fixed-width dot slot so word-meta stays aligned regardless of dot presence
    const dotSlot = document.createElement('div');
    dotSlot.className = 'dot-slot';
    if (hasUnseenImages(word)) {
      dotSlot.innerHTML = '<div class="word-dot dot-new"></div>';
    } else if (data.flagged_for_regen) {
      dotSlot.innerHTML = '<div class="word-dot dot-regen"></div>';
    } else if (!data.default_image) {
      dotSlot.innerHTML = '<div class="word-dot dot-missing"></div>';
    }
    item.appendChild(dotSlot);
    item.addEventListener('click', () => openWord(word));
    wordList.appendChild(item);
  });
  const q = searchInput.value.trim().toLowerCase();
  if (q) filterWords(q);
}

// ── Gallery render ────────────────────────────────────────────────────────────
function renderGallery() {
  gallery.innerHTML = '';
  sortedWords().forEach(word => {
    const data = vocab[word] || {};
    const def  = data.default_image || data.images?.[0]?.filename;
    const card = document.createElement('div');
    card.className = 'gallery-card';
    card.dataset.word = word;

    if (def) {
      const img = document.createElement('img');
      img.src = imgPath(word, def);
      img.alt = word;
      img.loading = 'lazy';
      card.appendChild(img);
    }
    const lbl = document.createElement('div');
    lbl.className = 'card-label';
    lbl.textContent = data.word || word;
    card.appendChild(lbl);

    card.addEventListener('click', () => openWord(word));
    gallery.appendChild(card);
  });
  const q = searchInput.value.trim().toLowerCase();
  if (q) filterWords(q);
}

function updateGalleryCard(word) {
  const card = gallery.querySelector(`.gallery-card[data-word="${CSS.escape(word)}"]`);
  if (!card) return;
  const def = vocab[word]?.default_image || vocab[word]?.images?.[0]?.filename;
  let img = card.querySelector('img');
  if (def) {
    if (!img) { img = document.createElement('img'); img.loading = 'lazy'; card.prepend(img); }
    img.src = imgPath(word, def);
  }
}

// ── Occurrences ───────────────────────────────────────────────────────────────
function parseBookTitle(raw) {
  if (!raw) return 'Unknown book';
  const stripped = raw.replace(/^-\s*/, '');
  return stripped.split(/\s+--\s+/)[0].trim() || stripped.trim();
}

function highlightWord(para, word) {
  const re = new RegExp(`(${word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
  return para.replace(re, '<mark>$1</mark>');
}

function renderOccurrences(word) {
  const occs = vocab[word]?.occurrences || [];
  if (occurrencesSection) occurrencesSection.style.display = occs.length ? '' : 'none';
  if (!occurrencesList) return;
  occurrencesList.innerHTML = '';

  // Group by book title
  const byBook = {};
  occs.forEach(occ => {
    const title = parseBookTitle(occ.book);
    (byBook[title] = byBook[title] || []).push(occ);
  });

  Object.entries(byBook).forEach(([title, bookOccs]) => {
    const det = document.createElement('details');
    det.className = 'occurrence-item';

    const sum = document.createElement('summary');
    sum.className = 'occurrence-summary';

    const bookSpan = document.createElement('span');
    bookSpan.className = 'occurrence-book';
    bookSpan.textContent = title;
    sum.appendChild(bookSpan);

    const badge = document.createElement('span');
    badge.className = 'occurrence-count';
    badge.textContent = bookOccs.length;
    sum.appendChild(badge);

    det.appendChild(sum);

    bookOccs.forEach(occ => {
      const para = document.createElement('div');
      para.className = 'occurrence-para';
      para.innerHTML = highlightWord(occ.paragraph || '', word);
      det.appendChild(para);
    });

    occurrencesList.appendChild(det);
  });
}

// ── Prompt height helpers (imagegen only — safe no-op in PWA) ─────────────────
const promptEdit   = document.getElementById('prompt-edit');
const refinerEdit  = document.getElementById('refiner-edit');
const negativeEdit = document.getElementById('negative-edit');

function autoHeight(ta) {
  if (!ta) return;
  ta.style.height = 'auto';
  ta.style.height = ta.scrollHeight + 'px';
}
[promptEdit, refinerEdit, negativeEdit].forEach(ta => {
  if (ta) ta.addEventListener('input', () => autoHeight(ta));
});
function resetPromptHeight() {
  [promptEdit, refinerEdit, negativeEdit].forEach(ta => autoHeight(ta));
}

// ── Open word view ────────────────────────────────────────────────────────────
function openWord(word) {
  if (typeof isNewWordMode !== 'undefined' && isNewWordMode) exitNewWordMode();
  selectedWord = word;
  lastOpenedWord = word;
  const data   = vocab[word] || {};
  const images = data.images || [];
  const defImg = data.default_image || images[0]?.filename;

  localStorage.setItem('imagen_open_word', word);
  sidebar.classList.remove('searching');
  setViewMode('word');
  wordView.scrollTop = 0;

  document.querySelectorAll('.word-item').forEach(el => {
    el.classList.toggle('active', el.dataset.word === word);
  });

  if (wordTitle) wordTitle.textContent = data.word || word;
  if (wordPhonetic) wordPhonetic.textContent = data.phonetic || '';
  if (flagBtn) flagBtn.classList.toggle('flagged', data.flagged_for_regen || false);
  if (learntBtn) learntBtn.classList.toggle('learnt', data.learnt || false);

  if (defImg) {
    mainImage.src = imgPath(word, defImg);
    mainImage.alt = word;
    mainImageWrap?.classList.remove('no-image');
  } else {
    mainImage.src = '';
    mainImage.alt = '';
    mainImageWrap?.classList.add('no-image');
  }

  // Fill definition + translation
  if (defEdit)   defEdit.value   = data.definition || '';
  if (transEdit) transEdit.value = data.translation?.nl || '';
  if (synsEdit)  synsEdit.value  = (data.synonyms || []).join(', ');
  if (antsEdit)  antsEdit.value  = (data.antonyms || []).join(', ');
  // Reset word info edit state
  resetWordInfoEdit();

  // Render definitions list
  if (definitionsList) {
    definitionsList.classList.remove('expanded');
    definitionsList.innerHTML = '';
    const defs = data.definitions || [];
    defs.forEach(d => {
      const entry = document.createElement('div');
      entry.className = 'def-entry';
      const pos  = document.createElement('span');
      pos.className = 'def-pos';
      pos.textContent = d.part_of_speech;
      const text = document.createElement('span');
      text.className = 'def-text';
      text.textContent = d.definition;
      entry.appendChild(pos);
      entry.appendChild(text);
      if (d.example) {
        const ex = document.createElement('div');
        ex.className = 'def-example';
        ex.textContent = `"${d.example}"`;
        entry.appendChild(ex);
      }
      definitionsList.appendChild(entry);
    });
    // Show def-edit fallback only when no structured definitions
    if (defEdit) defEdit.style.display = defs.length ? 'none' : 'block';
    // Show view-more only when >1 definitions exist
    if (defMoreBtn) {
      defMoreBtn.style.display = defs.length > 1 ? '' : 'none';
      defMoreBtn.textContent = 'View more';
    }
  }

  // Render per-mode stats
  if (statsRows) {
    statsRows.innerHTML = '';
    const s = data.stats || {};
    const modes = [
      { key: 'context',  label: 'Context' },
      { key: 'reverse',  label: 'Definitions' },
      { key: 'image',    label: 'Image' },
      { key: 'dutch',    label: 'Dutch' },
    ];
    const active = modes.filter(m => s[m.key]?.correct || s[m.key]?.wrong);
    active.forEach(({ key, label }) => {
      const ms = s[key];
      const total = (ms.correct || 0) + (ms.wrong || 0);
      const pct = total ? Math.round(100 * ms.correct / total) : 0;
      const row = document.createElement('div');
      row.className = 'stats-row';
      row.innerHTML = `<span class="stats-row-label">${label}</span>
        <span class="stats-bar-wrap"><span class="stats-bar" style="width:${pct}%"></span></span>
        <span class="stats-pct">${pct}%</span>
        <span class="stats-counts">${ms.correct}/${total}</span>`;
      statsRows.appendChild(row);
    });
  }

  // Fill prompt textareas (imagegen only)
  if (promptEdit || refinerEdit || negativeEdit) {
    const defImgData = images.find(i => i.filename === defImg) || images[0] || {};
    if (promptEdit)   promptEdit.value   = defImgData.prompt_base    || '';
    if (refinerEdit)  refinerEdit.value  = defImgData.prompt_refiner || '';
    if (negativeEdit) negativeEdit.value = defImgData.negative       || vocab[word]?.negative || '';
    setTimeout(resetPromptHeight, 0);
  }

  // Alternatives grid (imagegen only)
  if (altsSection && altsGrid) {
    altsSection.style.display = images.length > 0 ? '' : 'none';
    altsGrid.innerHTML = '';
    images.forEach(img => {
      const thumb = document.createElement('div');
      thumb.className = 'alt-thumb' + (img.filename === defImg ? ' selected' : '');

      const image = document.createElement('img');
      image.src     = imgPath(word, img.filename);
      image.alt     = img.filename;
      image.loading = 'lazy';
      thumb.appendChild(image);

      const overlay = document.createElement('div');
      overlay.className = 'alt-overlay';
      overlay.textContent = img.filename.replace(`_${img.script}.png`, '');
      thumb.appendChild(overlay);

      // Delete button — imagegen only (requires server)
      if (VOCAB_SERVER) {
        const delBtn = document.createElement('button');
        delBtn.className = 'alt-delete-btn';
        delBtn.title = 'Delete this image';
        delBtn.innerHTML = `<svg class="icon"><use href="${ICON_BASE}icons.svg#icon-trash"/></svg>`;
        delBtn.addEventListener('click', async e => {
          e.stopPropagation();
          if (!confirm(`Delete ${img.filename}?`)) return;
          try {
            const res = await fetch(`${VOCAB_SERVER}/api/image`, {
              method: 'DELETE',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ word, filename: img.filename }),
            });
            if (!res.ok) {
              const err = await res.json().catch(() => ({}));
              alert(`Delete failed: ${err.error || res.status}`);
              return;
            }
            if (vocab[word]) {
              vocab[word].images = (vocab[word].images || []).filter(i => i.filename !== img.filename);
              if (vocab[word].default_image === img.filename)
                vocab[word].default_image = vocab[word].images.at(-1)?.filename || null;
            }
            openWord(word);
            renderWordList();
            updateGalleryCard(word);
          } catch { alert('Delete failed — server unreachable'); }
        });
        thumb.appendChild(delBtn);
      }

      thumb.addEventListener('click', async () => {
        if (vocab[word]) vocab[word].default_image = img.filename;
        openWord(word);
        renderWordList();
        updateGalleryCard(word);
        await updateWordField(word, { default_image: img.filename });
        if (typeof applyToDoc === 'function') applyToDoc(word, img.filename);
      });
      altsGrid.appendChild(thumb);
    });
  }

  renderOccurrences(word);
  markImagesSeen(word);
  // After marking seen, re-render this item's dot slot
  document.querySelectorAll(`.word-item[data-word="${CSS.escape(word)}"] .dot-slot`).forEach(slot => {
    const data2 = vocab[word] || {};
    slot.innerHTML = '';
    if (data2.flagged_for_regen) slot.innerHTML = '<div class="word-dot dot-regen"></div>';
    else if (!data2.default_image) slot.innerHTML = '<div class="word-dot dot-missing"></div>';
  });
}

// ── View mode: gallery | word | game ─────────────────────────────────────────
const gameView = document.getElementById('game-view');

function setViewMode(mode) {
  gallery.style.display = mode === 'gallery' ? '' : 'none';
  wordView.classList.toggle('active', mode === 'word');
  if (gameView) gameView.classList.toggle('active', mode === 'game');
  if (addWordBtn) addWordBtn.style.display = mode === 'gallery' ? '' : 'none';

  // Context row
  [ctxGame, ctxGallery, ctxWord].forEach(p => p?.classList.remove('active'));
  if (mode === 'game'    && ctxGame)    ctxGame.classList.add('active');
  if (mode === 'gallery' && ctxGallery) ctxGallery.classList.add('active');
  if (mode === 'word'    && ctxWord)    ctxWord.classList.add('active');

  // Pill active state
  if (pillGame)    pillGame.classList.toggle('active', mode === 'game');
  if (pillGallery) pillGallery.classList.toggle('active', mode === 'gallery');
  if (pillWord) {
    pillWord.classList.toggle('active', mode === 'word');
  }
}
function setWordView(active) { setViewMode(active ? 'word' : 'gallery'); }
setViewMode('gallery');

// ── Word info auto-save (debounced) ──────────────────────────────────────────
// ── Prev/next navigation (swipe + arrow keys) ─────────────────────────────────
function animatedOpenWord(word, dir) {
  openWord(word);
  wordView.classList.remove('nav-next', 'nav-prev');
  void wordView.offsetWidth; // force reflow to restart animation
  wordView.classList.add(dir === 'next' ? 'nav-next' : 'nav-prev');
}

function navigatePrev() {
  if (!selectedWord) return;
  const words = sortedWords();
  const idx = words.indexOf(selectedWord);
  if (idx > 0) animatedOpenWord(words[idx - 1], 'prev');
}
function navigateNext() {
  if (!selectedWord) return;
  const words = sortedWords();
  const idx = words.indexOf(selectedWord);
  if (idx < words.length - 1) animatedOpenWord(words[idx + 1], 'next');
}

// Swipe detection with real-time drag tracking
const mainEl = document.getElementById('main');
if (mainEl) {
  let touchStartX = 0, touchStartY = 0, touchDragging = false, touchAxisLocked = false;

  mainEl.addEventListener('touchstart', e => {
    touchStartX = e.touches[0].clientX;
    touchStartY = e.touches[0].clientY;
    touchDragging = false;
    touchAxisLocked = false;
    wordView.classList.remove('nav-next', 'nav-prev');
  }, { passive: true });

  mainEl.addEventListener('touchmove', e => {
    if (!selectedWord || !wordView.classList.contains('active')) return;
    const dx = e.touches[0].clientX - touchStartX;
    const dy = e.touches[0].clientY - touchStartY;

    if (!touchAxisLocked) {
      if (Math.abs(dx) > 8 && Math.abs(dx) > Math.abs(dy) * 1.2) {
        touchAxisLocked = true;
        touchDragging = true;
      } else if (Math.abs(dy) > 8) {
        touchAxisLocked = true; // vertical scroll wins
      }
    }

    if (touchDragging) {
      e.preventDefault();
      wordView.style.transform = `translateX(${dx}px)`;
      wordView.style.opacity   = String(Math.max(0.4, 1 - Math.abs(dx) / 350));
    }
  }, { passive: false });

  mainEl.addEventListener('touchend', e => {
    if (!touchDragging) return;
    const dx = e.changedTouches[0].clientX - touchStartX;
    touchDragging = false;

    if (Math.abs(dx) > 50) {
      // Commit: clear inline style, let animatedOpenWord take over
      wordView.style.transform = '';
      wordView.style.opacity   = '';
      if (dx < 0) navigateNext(); else navigatePrev();
    } else {
      // Snap back with a spring transition
      wordView.style.transition = 'transform 0.25s cubic-bezier(0.25,0.46,0.45,0.94), opacity 0.25s ease';
      wordView.style.transform  = '';
      wordView.style.opacity    = '';
      setTimeout(() => { wordView.style.transition = ''; }, 260);
    }
  }, { passive: true });
}

// Pill button listeners
if (pillGame) pillGame.addEventListener('click', () => {
  if (gameView && gameView.classList.contains('active')) {
    selectedWord = null;
    localStorage.removeItem('imagen_open_word');
    document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
    setViewMode('gallery');
    return;
  }
  if (typeof isNewWordMode !== 'undefined' && isNewWordMode) exitNewWordMode();
  selectedWord = null;
  localStorage.removeItem('imagen_open_word');
  document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
  setViewMode('game');
  // Only start a fresh round if there is no active challenge
  if (!gameCurrent) {
    initGameResults();
    gameScore = gameAttempts = 0;
    if (gameScoreEl)    gameScoreEl.textContent = '0';
    if (gameAttemptsEl) gameAttemptsEl.textContent = '0';
    gameRecentWords = [];
    nextGameRound();
  }
});
if (pillGallery) pillGallery.addEventListener('click', () => {
  if (typeof isNewWordMode !== 'undefined' && isNewWordMode) exitNewWordMode();
  selectedWord = null;
  localStorage.removeItem('imagen_open_word');
  document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
  setViewMode('gallery');
});
if (pillWord) pillWord.addEventListener('click', () => {
  if (selectedWord) { setViewMode('word'); return; }
  const target = lastOpenedWord && vocab[lastOpenedWord]
    ? lastOpenedWord
    : sortedWords()[0];
  if (target) openWord(target);
});

function parseList(val) {
  return val.split(',').map(s => s.trim()).filter(Boolean);
}

const wordInfoFields = () => [defEdit, transEdit, synsEdit, antsEdit].filter(Boolean);

let _saveTimer = null;
async function saveWordInfo() {
  if (!selectedWord) return;
  const fields = { definition: defEdit?.value.trim() || '' };
  if (transEdit) fields.translation = { ...(vocab[selectedWord]?.translation || {}), nl: transEdit.value.trim() };
  if (synsEdit)  fields.synonyms    = parseList(synsEdit.value);
  if (antsEdit)  fields.antonyms    = parseList(antsEdit.value);
  await updateWordField(selectedWord, fields);
}
function debouncedSave() {
  clearTimeout(_saveTimer);
  _saveTimer = setTimeout(saveWordInfo, 600);
}
wordInfoFields().forEach(f => f?.addEventListener('input', debouncedSave));

function resetWordInfoEdit() {
  clearTimeout(_saveTimer);
  _saveTimer = null;
}

// ── Definition view-more toggle ───────────────────────────────────────────────
if (defMoreBtn) {
  defMoreBtn.addEventListener('click', () => {
    const expanded = definitionsList?.classList.toggle('expanded');
    defMoreBtn.textContent = expanded ? 'View less' : 'View more';
  });
}

// ── Learnt toggle ─────────────────────────────────────────────────────────────
if (learntBtn) {
  learntBtn.addEventListener('click', async () => {
    if (!selectedWord) return;
    const newVal = !vocab[selectedWord]?.learnt;
    if (vocab[selectedWord]) vocab[selectedWord].learnt = newVal;
    learntBtn.classList.toggle('learnt', newVal);
    renderWordList();
    await updateWordField(selectedWord, { learnt: newVal });
  });
}

// ── Flag button (imagegen only) ───────────────────────────────────────────────
if (flagBtn) {
  flagBtn.addEventListener('click', async () => {
    if (!selectedWord) return;
    const newVal = !isInRegen(selectedWord);
    if (vocab[selectedWord]) vocab[selectedWord].flagged_for_regen = newVal;
    flagBtn.classList.toggle('flagged', newVal);
    renderWordList();
    await updateWordField(selectedWord, { flagged_for_regen: newVal });
  });
}

// ── Theme ─────────────────────────────────────────────────────────────────────
const THEME_KEY = 'vocab_theme';
function applyTheme(t) {
  document.documentElement.dataset.theme = t || 'dark';
  localStorage.setItem(THEME_KEY, t || 'dark');
  document.querySelectorAll('.theme-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.theme === (t || 'dark'))
  );
}
applyTheme(localStorage.getItem(THEME_KEY) || 'dark');
document.addEventListener('click', e => {
  const btn = e.target.closest('.theme-btn');
  if (btn?.dataset.theme) applyTheme(btn.dataset.theme);
});

// ── Columns slider ────────────────────────────────────────────────────────────
const COLS_CYCLE = [1, 2, 3, 4];
let currentCols = parseInt(localStorage.getItem('imagen_cols') || '4', 10);
if (!COLS_CYCLE.includes(currentCols)) currentCols = 4;
if (colsLabel) colsLabel.textContent = currentCols;
document.documentElement.style.setProperty('--cols', currentCols);

if (colsBtn) {
  colsBtn.addEventListener('click', () => {
    currentCols = COLS_CYCLE[(COLS_CYCLE.indexOf(currentCols) + 1) % COLS_CYCLE.length];
    if (colsLabel) colsLabel.textContent = currentCols;
    document.documentElement.style.setProperty('--cols', currentCols);
    localStorage.setItem('imagen_cols', currentCols);
  });
}

// ── Search ────────────────────────────────────────────────────────────────────
searchInput.addEventListener('focus', () => sidebar.classList.add('searching'));
searchInput.addEventListener('blur', () => {
  setTimeout(() => {
    if (!searchInput.value.trim()) sidebar.classList.remove('searching');
  }, 150);
});
searchInput.addEventListener('input', () => filterWords(searchInput.value.trim().toLowerCase()));

function filterWords(q) {
  document.querySelectorAll('.word-item').forEach(el => {
    el.style.display = !q || el.dataset.word.toLowerCase().includes(q) ? '' : 'none';
  });
  document.querySelectorAll('.gallery-card').forEach(el => {
    el.classList.toggle('hidden', !!(q && !el.dataset.word.toLowerCase().includes(q)));
  });
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
if (mainImageWrap) {
  mainImageWrap.addEventListener('click', () => {
    if (!mainImage.src) return;
    if (lightboxImg) lightboxImg.src = mainImage.src;
    if (lightbox) lightbox.classList.add('open');
  });
}
if (lightbox) {
  lightbox.addEventListener('click', () => lightbox.classList.remove('open'));
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && lightbox) lightbox.classList.remove('open');
});

// ── UI toggle ─────────────────────────────────────────────────────────────────
let uiVisible = true;
if (uiToggle) {
  uiToggle.addEventListener('click', () => {
    uiVisible = !uiVisible;
    document.body.classList.toggle('ui-hidden', !uiVisible);
    const eyeIcon = uiVisible ? 'icon-circle-outline' : 'icon-circle';
    uiToggle.innerHTML = `<svg class="icon icon-lg"><use href="${ICON_BASE}icons.svg#${eyeIcon}"/></svg>`;
    sidebar.classList.toggle('collapsed', !uiVisible);
  });
}

// ── Delete word ───────────────────────────────────────────────────────────────
const deleteWordBtn    = document.getElementById('delete-word-btn');
const confirmModal     = document.getElementById('confirm-modal');
const confirmModalBody = document.getElementById('confirm-modal-body');
const confirmCancelBtn = document.getElementById('confirm-cancel-btn');
const confirmDeleteBtn = document.getElementById('confirm-delete-btn');

if (deleteWordBtn) {
  deleteWordBtn.addEventListener('click', () => {
    if (!selectedWord || (typeof isNewWordMode !== 'undefined' && isNewWordMode)) return;
    const display = vocab[selectedWord]?.word || selectedWord;
    if (confirmModalBody) confirmModalBody.textContent =
      `"${display}" will be permanently removed. Images on disk are not deleted.`;
    if (confirmModal) confirmModal.classList.add('open');
  });
}
if (confirmCancelBtn) {
  confirmCancelBtn.addEventListener('click', () => {
    if (confirmModal) confirmModal.classList.remove('open');
  });
}
if (confirmModal) {
  confirmModal.addEventListener('click', e => {
    if (e.target === confirmModal) confirmModal.classList.remove('open');
  });
}
if (confirmDeleteBtn) {
  confirmDeleteBtn.addEventListener('click', async () => {
    if (!selectedWord) return;
    const word = selectedWord;
    if (confirmModal) confirmModal.classList.remove('open');
    await deleteWord(word);
    selectedWord = null;
    localStorage.removeItem('imagen_open_word');
    setViewMode('gallery');
    renderWordList();
    renderGallery();
  });
}

// ── Add word ──────────────────────────────────────────────────────────────────
let isNewWordMode = false;
const newWordBar    = document.getElementById('new-word-bar');
const newWordInput  = document.getElementById('new-word-input');
const createWordBtn = document.getElementById('create-word-btn');

function openNewWordMode() {
  isNewWordMode = true;
  selectedWord  = null;
  localStorage.removeItem('imagen_open_word');
  // Show word view manually (selectedWord is null so setViewMode('word') would disable pillWord)
  gallery.style.display = 'none';
  wordView.classList.add('active');
  if (ctxWord)    ctxWord.classList.add('active');
  if (ctxGame)    ctxGame.classList.remove('active');
  if (ctxGallery) ctxGallery.classList.remove('active');
  if (newWordBar) newWordBar.classList.add('visible');
  if (wordTitle)    wordTitle.textContent    = '';
  if (wordPhonetic) wordPhonetic.textContent = '';
  if (definitionsList) { definitionsList.innerHTML = ''; definitionsList.classList.remove('expanded'); }
  if (defEdit)   { defEdit.value = ''; defEdit.style.display = 'block'; }
  if (defMoreBtn) defMoreBtn.style.display = 'none';
  mainImage.src  = '';
  mainImage.alt  = '';
  if (transEdit) transEdit.value = '';
  if (synsEdit)  synsEdit.value  = '';
  if (antsEdit)  antsEdit.value  = '';
  if (promptEdit)   promptEdit.value   = '';
  if (refinerEdit)  refinerEdit.value  = '';
  if (negativeEdit) negativeEdit.value = '';
  resetPromptHeight();
  if (altsSection)        altsSection.style.display  = 'none';
  if (occurrencesSection) occurrencesSection.style.display = 'none';
  if (flagBtn)            flagBtn.classList.remove('flagged');
  document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
  if (newWordInput) { newWordInput.value = ''; newWordInput.focus(); }
}

function exitNewWordMode() {
  isNewWordMode = false;
  if (newWordBar) newWordBar.classList.remove('visible');
}

// ── Quick-add panel (used when game is active, avoids leaving game view) ───────
const quickAddPanel = document.getElementById('quick-add-panel');
const quickAddInput = document.getElementById('quick-add-input');
const quickAddBtn   = document.getElementById('quick-add-submit');

if (quickAddBtn) {
  quickAddBtn.addEventListener('click', async () => {
    const raw = quickAddInput?.value.trim();
    if (!raw) { quickAddInput?.focus(); return; }
    const entry = {
      word: raw, definition: '', translation: { nl: '' },
      images: [], default_image: null, flagged_for_regen: false, enriched: false,
    };
    const result = await createWord(entry);
    if (result.error) { alert(`Error: ${result.error}`); return; }
    renderWordList();
    renderGallery();
    if (quickAddInput) quickAddInput.value = '';
    if (quickAddPanel) quickAddPanel.classList.remove('visible');
  });
}
if (quickAddInput) {
  quickAddInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') quickAddBtn?.click();
    if (e.key === 'Escape') {
      quickAddPanel?.classList.remove('visible');
    }
  });
}

if (addWordBtn) addWordBtn.addEventListener('click', () => {
  if (gameView && gameView.classList.contains('active')) {
    // In game mode: show quick-add panel below game, don't switch view
    if (quickAddPanel) {
      quickAddPanel.classList.toggle('visible');
      if (quickAddPanel.classList.contains('visible')) quickAddInput?.focus();
    }
  } else {
    openNewWordMode();
  }
});

if (createWordBtn) {
  createWordBtn.addEventListener('click', async () => {
    const raw  = newWordInput?.value.trim();
    if (!raw) { if (newWordInput) newWordInput.focus(); return; }

    const entry = {
      word:              raw,
      definition:        defEdit?.value.trim() || '',
      translation:       { nl: transEdit?.value.trim() || '' },
      images:            [],
      default_image:     null,
      flagged_for_regen: false,
      enriched:          false,
    };
    const result = await createWord(entry);
    if (result.error) { alert(`Error: ${result.error}`); return; }
    exitNewWordMode();
    renderWordList();
    renderGallery();
    openWord(result.entry.word.toLowerCase());
  });
}

// ── Game mode ─────────────────────────────────────────────────────────────────
let gameScore        = 0;
let gameAttempts     = 0;
let gameResults      = {};
let gameCurrent      = '';
let gameAnswered     = false;
let gameRecentWords  = [];
let gameMode         = 'random';  // 'random' | 'context' | 'reverse' | 'image' | 'dutch'
let gameCurrentMode  = 'context'; // resolved mode frozen at round-start for gameGuess
let gameCorrectValue = '';        // correct answer for current round
const GAME_RECENT_CAP = 8;

const gameNextBtn    = document.getElementById('game-next-btn');
const gameScoreEl    = document.getElementById('game-score');
const gameAttemptsEl = document.getElementById('game-attempts');
const gameModeSelect = document.getElementById('game-mode-select');

if (gameModeSelect) {
  gameModeSelect.addEventListener('change', () => {
    gameMode = gameModeSelect.value;
    nextGameRound();
  });
}

function initGameResults() {
  gameResults = {};
}

function gamePool(mode) {
  mode = mode ?? gameMode;
  return Object.entries(vocab).filter(([, v]) => {
    switch (mode) {
      case 'reverse': return !!v.definition;
      case 'image':   return !!v.default_image;
      case 'dutch':   return !!(v.translation?.nl);
      case 'random':  return v.definition || (v.occurrences || []).some(o => o.paragraph);
      default:        return v.definition || (v.occurrences || []).some(o => o.paragraph);
    }
  });
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function weightedPick(pool) {
  const weights = pool.map(([k]) => {
    const r = gameResults[k];
    if (!r) return 0.5;
    const total = r.correct + r.wrong;
    return total ? Math.max(0.05, r.wrong / total) : 0.5;
  });
  let rand = Math.random() * weights.reduce((a, b) => a + b, 0);
  for (let i = 0; i < pool.length; i++) {
    rand -= weights[i];
    if (rand <= 0) return pool[i];
  }
  return pool[pool.length - 1];
}

function pickDistractors(targetKey, mode) {
  const targetPos = vocab[targetKey]?.part_of_speech || '';
  if (mode === 'reverse') {
    // Return 3 definition strings from other words
    const candidates = shuffle(Object.entries(vocab).filter(([k, v]) =>
      k !== targetKey && !!v.definition
    ));
    const samePOS = candidates.filter(([, v]) => v.part_of_speech === targetPos);
    const other   = candidates.filter(([, v]) => v.part_of_speech !== targetPos);
    return [...samePOS, ...other].slice(0, 3).map(([, v]) => v.definition);
  }
  // Default: return 3 word strings
  const samePOS = shuffle(Object.entries(vocab).filter(([k, v]) =>
    k !== targetKey && v.part_of_speech === targetPos
  ));
  const other = shuffle(Object.entries(vocab).filter(([k, v]) =>
    k !== targetKey && v.part_of_speech !== targetPos
  ));
  return [...samePOS, ...other].slice(0, 3).map(([k, v]) => v.word || k);
}

function gameEsc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function gameEscRe(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function buildGameContext(key, reveal) {
  const v    = vocab[key] || {};
  const word = v.word || key;
  const occs = (v.occurrences || []).filter(o => o.paragraph);
  if (!occs.length) return '';
  const occ  = occs[Math.floor(Math.random() * occs.length)];
  const re   = new RegExp(`(\\b${gameEscRe(word)}\\b)`, 'gi');
  const para = gameEsc(occ.paragraph);
  if (reveal) return para.replace(re, '<mark>$1</mark>');
  return para.replace(re, `<span class="game-blank">${gameEsc(word)}</span>`);
}

function buildChoiceButtons(choices, choicesEl) {
  choicesEl.innerHTML = '';
  shuffle(choices).forEach(value => {
    const btn = document.createElement('button');
    btn.className = 'choice-btn';
    btn.dataset.choice = value;
    btn.textContent = value;
    btn.addEventListener('click', () => gameGuess(value));
    choicesEl.appendChild(btn);
  });
}

function nextGameRound() {
  if (!gameView) return;
  const pool = gamePool();
  const clueTextEl = document.getElementById('clue-text');
  const choicesEl  = document.getElementById('game-choices');
  if (!clueTextEl || !choicesEl) return;

  if (pool.length < 4) {
    clueTextEl.textContent = 'Not enough words for this mode.';
    choicesEl.innerHTML = '';
    return;
  }

  gameAnswered     = false;
  gameCurrent      = '';
  gameCorrectValue = '';

  // Resolve random mode: pick from modes that have enough words
  if (gameMode === 'random') {
    const modes = ['context', 'reverse', 'image', 'dutch'].filter(m => gamePool(m).length >= 4);
    gameCurrentMode = modes[Math.floor(Math.random() * modes.length)] || 'context';
  } else {
    gameCurrentMode = gameMode;
  }

  const solvedEl = document.getElementById('clue-solved-actions');
  const sourceEl = document.getElementById('clue-source');
  const poolEl   = document.getElementById('pool-label');
  if (solvedEl) solvedEl.innerHTML = '';
  if (sourceEl) sourceEl.textContent = '';
  if (gameNextBtn) { gameNextBtn.textContent = 'Skip →'; gameNextBtn.classList.remove('answered'); }
  if (poolEl) poolEl.textContent = `${pool.length} words`;

  const fresh = pool.filter(([k]) => !gameRecentWords.includes(k));
  const [key, data] = weightedPick(fresh.length >= 4 ? fresh : pool);
  gameCurrent = key;
  gameRecentWords.push(key);
  if (gameRecentWords.length > GAME_RECENT_CAP) gameRecentWords.shift();

  const word    = data.word || key;
  const labelEl = document.getElementById('clue-label');

  switch (gameCurrentMode) {
    case 'reverse': {
      if (labelEl) labelEl.textContent = 'Which definition matches this word?';
      const pos = data.part_of_speech ? ` — <em>${gameEsc(data.part_of_speech)}</em>` : '';
      clueTextEl.innerHTML = `<strong class="game-word-clue">${gameEsc(word)}</strong>${pos}`;
      gameCorrectValue = data.definition;
      buildChoiceButtons([data.definition, ...pickDistractors(key, 'reverse')], choicesEl);
      break;
    }
    case 'image': {
      if (labelEl) labelEl.textContent = 'Which word matches this image?';
      clueTextEl.innerHTML = '';
      const img = document.createElement('img');
      img.src = imgPath(key, data.default_image);
      img.alt = '';
      img.className = 'clue-image';
      clueTextEl.appendChild(img);
      gameCorrectValue = word;
      buildChoiceButtons([word, ...pickDistractors(key, 'image')], choicesEl);
      break;
    }
    case 'dutch': {
      if (labelEl) labelEl.textContent = 'Which word matches this Dutch translation?';
      clueTextEl.textContent = data.translation.nl;
      gameCorrectValue = word;
      buildChoiceButtons([word, ...pickDistractors(key, 'dutch')], choicesEl);
      break;
    }
    default: { // context
      if (data.definition) {
        const pos = data.part_of_speech ? `<em>${gameEsc(data.part_of_speech)}</em> ` : '';
        if (labelEl) labelEl.textContent = 'Which word matches this definition?';
        clueTextEl.innerHTML = pos + gameEsc(data.definition);
        if (sourceEl && data.example) {
          sourceEl.textContent = `"${data.example.replace(new RegExp('\\b' + gameEscRe(word) + '\\b', 'gi'), '___')}"`;
        }
      } else {
        if (labelEl) labelEl.textContent = 'What word fits here?';
        clueTextEl.innerHTML = buildGameContext(key, false);
        const occs = (data.occurrences || []).filter(o => o.paragraph);
        if (sourceEl) sourceEl.textContent = occs.length ? `— ${parseBookTitle(occs[0].book)}` : '';
      }
      gameCorrectValue = word;
      buildChoiceButtons([word, ...pickDistractors(key, 'context')], choicesEl);
    }
  }
}

function gameGuess(value) {
  if (gameAnswered) return;
  gameAnswered = true;
  gameAttempts++;
  if (gameAttemptsEl) gameAttemptsEl.textContent = gameAttempts;
  if (gameNextBtn) { gameNextBtn.textContent = 'Next →'; gameNextBtn.classList.add('answered'); }

  const currentData = vocab[gameCurrent] || {};
  const currentWord = currentData.word || gameCurrent;
  const correct = value === gameCorrectValue;

  if (correct) gameScore++;
  if (gameScoreEl) gameScoreEl.textContent = gameScore;

  // Per-mode stats
  const existing = vocab[gameCurrent]?.stats || {};
  const mode = gameCurrentMode;
  const modeStats = existing[mode] || { correct: 0, wrong: 0 };
  modeStats[correct ? 'correct' : 'wrong']++;
  const total = existing.total || { correct: 0, wrong: 0 };
  total[correct ? 'correct' : 'wrong']++;
  const stats = { ...existing, [mode]: modeStats, total };
  if (vocab[gameCurrent]) vocab[gameCurrent].stats = stats;
  updateWordField(gameCurrent, { stats });

  document.querySelectorAll('.choice-btn').forEach(btn => {
    btn.disabled = true;
    if (btn.dataset.choice === gameCorrectValue) btn.classList.add('correct');
    else if (btn.dataset.choice === value && !correct) btn.classList.add('wrong');
  });

  // Reveal answer
  const clueTextEl = document.getElementById('clue-text');
  const sourceEl   = document.getElementById('clue-source');
  if (clueTextEl) {
    const pos   = currentData.part_of_speech ? `<em>${gameEsc(currentData.part_of_speech)}</em> ` : '';
    const parts = [`<strong>${gameEsc(currentWord)}</strong> — ${pos}${gameEsc(currentData.definition || '')}`];
    const ctx   = buildGameContext(gameCurrent, true);
    if (ctx) parts.push(`<span style="font-style:italic;color:var(--text-dim)">${ctx}</span>`);
    clueTextEl.innerHTML = parts.join('<br><br>');
    if (sourceEl && currentData.example) sourceEl.textContent = `"${currentData.example}"`;
  }

  const solvedEl = document.getElementById('clue-solved-actions');
  if (solvedEl) {
    solvedEl.innerHTML = '';
    const viewBtn = document.createElement('button');
    viewBtn.textContent = 'View card';
    viewBtn.addEventListener('click', () => openWord(gameCurrent));
    solvedEl.appendChild(viewBtn);
    if (!vocab[gameCurrent]?.learnt) {
      const learnBtn = document.createElement('button');
      learnBtn.textContent = '★ Mark as learnt';
      learnBtn.addEventListener('click', async () => {
        if (vocab[gameCurrent]) vocab[gameCurrent].learnt = true;
        await updateWordField(gameCurrent, { learnt: true });
        learnBtn.textContent = '✓ Learnt';
        learnBtn.disabled = true;
        if (learntBtn) learntBtn.classList.add('learnt');
      });
      solvedEl.appendChild(learnBtn);
    }
  }
}

if (gameNextBtn) gameNextBtn.addEventListener('click', () => {
  if (gameCurrent && !gameAnswered) {
    // Reveal correct answer on skip without counting it as an attempt
    document.querySelectorAll('.choice-btn').forEach(btn => {
      btn.disabled = true;
      if (btn.dataset.choice === gameCorrectValue) btn.classList.add('correct');
    });
    const clueTextEl = document.getElementById('clue-text');
    const sourceEl   = document.getElementById('clue-source');
    const currentData = vocab[gameCurrent] || {};
    const currentWord = currentData.word || gameCurrent;
    if (clueTextEl) {
      const pos   = currentData.part_of_speech ? `<em>${gameEsc(currentData.part_of_speech)}</em> ` : '';
      const parts = [`<strong>${gameEsc(currentWord)}</strong> — ${pos}${gameEsc(currentData.definition || '')}`];
      const ctx   = buildGameContext(gameCurrent, true);
      if (ctx) parts.push(`<span style="font-style:italic;color:var(--text-dim)">${ctx}</span>`);
      clueTextEl.innerHTML = parts.join('<br><br>');
      if (sourceEl && currentData.example) sourceEl.textContent = `"${currentData.example}"`;
    }
    gameAnswered = true;
    gameNextBtn.textContent = 'Next →';
    gameNextBtn.classList.add('answered');
    return;
  }
  nextGameRound();
});

document.addEventListener('keydown', e => {
  if (gameView && gameView.classList.contains('active')) {
    if (['1','2','3','4'].includes(e.key) && !gameAnswered) {
      const btns = document.querySelectorAll('.choice-btn:not(:disabled)');
      btns[+e.key - 1]?.click();
    }
    if ((e.key === 'Enter' || e.key === ' ') && gameAnswered) {
      e.preventDefault();
      nextGameRound();
    }
    return;
  }
  if (wordView && wordView.classList.contains('active') && selectedWord) {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA') return;
    if (e.key === 'ArrowLeft')  { e.preventDefault(); navigatePrev(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); navigateNext(); }
  }
});

// ── Ctx-word prev/next buttons ────────────────────────────────────────────────
const ctxPrevBtn = document.getElementById('ctx-prev-btn');
const ctxNextBtn = document.getElementById('ctx-next-btn');
if (ctxPrevBtn) ctxPrevBtn.addEventListener('click', navigatePrev);
if (ctxNextBtn) ctxNextBtn.addEventListener('click', navigateNext);

// ── Vocab loading ─────────────────────────────────────────────────────────────
function wotdKeyForDate(dateStr) {
  const keys = Object.keys(vocab).sort();
  if (!keys.length) return null;
  const hash = [...dateStr].reduce((acc, c) => acc + c.charCodeAt(0), 0);
  return keys[hash % keys.length];
}

function initAfterVocabLoad() {
  const errorMsg = document.getElementById('error-msg');
  if (errorMsg) errorMsg.style.display = 'none';
  renderWordList();
  renderGallery();
  const saved = localStorage.getItem('imagen_open_word');
  if (saved && vocab[saved]) openWord(saved);
  if (typeof onVocabReady === 'function') onVocabReady();
}

// Default loadVocab: fetch vocab.json, fall back to vocab_public.json, then localStorage.
// Imagegen overrides this function in its inline script to always use VOCAB_SERVER.
async function loadVocab() {
  for (const url of ['vocab.json', 'vocab_public.json']) {
    try {
      const resp = await fetch(url);
      if (resp.ok) {
        vocab = await resp.json();
        saveVocabToStorage();
        initAfterVocabLoad();
        return;
      }
    } catch {}
  }
  // Both failed — try localStorage cache
  try {
    const stored = localStorage.getItem('vocab_data');
    if (stored) {
      vocab = JSON.parse(stored);
      initAfterVocabLoad();
      return;
    }
  } catch {}
  const errorMsg = document.getElementById('error-msg');
  if (errorMsg) errorMsg.style.display = 'block';
}
