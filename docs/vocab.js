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
let selectedWord = null;

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
function saveVocabToStorage() {
  try { localStorage.setItem('vocab_data', JSON.stringify(vocab)); } catch {}
}

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
const openBtn        = document.getElementById('open-sidebar');
const searchInput    = document.getElementById('search');
const wordList       = document.getElementById('word-list');
const colsSlider     = document.getElementById('cols-slider');
const colsLabel      = document.getElementById('cols-label');
const gallery        = document.getElementById('gallery');
const wordView       = document.getElementById('word-view');
const wordTitle      = document.getElementById('word-title');
const mainImageWrap  = document.getElementById('main-image-wrap');
const mainImage      = document.getElementById('main-image');
const altsSection    = document.getElementById('alts-section');
const altsGrid       = document.getElementById('alts-grid');
const flagBtn        = document.getElementById('flag-btn');
const defEdit        = document.getElementById('def-edit');
const defSaveBtn     = document.getElementById('def-save-btn');
const transEdit      = document.getElementById('trans-edit');
const transSaveBtn   = document.getElementById('trans-save-btn');
const synsEdit       = document.getElementById('syns-edit');
const synsSaveBtn    = document.getElementById('syns-save-btn');
const antsEdit       = document.getElementById('ants-edit');
const antsSaveBtn    = document.getElementById('ants-save-btn');
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
  const keys = Object.keys(vocab);
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

    if (data.flagged_for_regen) {
      const dot = document.createElement('div');
      dot.className = 'regen-dot';
      item.appendChild(dot);
    } else if (hasUnseenImages(word)) {
      const dot = document.createElement('div');
      dot.className = 'new-dot';
      item.appendChild(dot);
    } else if (!data.default_image) {
      const dot = document.createElement('div');
      dot.className = 'no-default-dot';
      item.appendChild(dot);
    }
    item.addEventListener('click', () => guardNav(() => openWord(word)));
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

    card.addEventListener('click', () => guardNav(() => openWord(word)));
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
  const data   = vocab[word] || {};
  const images = data.images || [];
  const defImg = data.default_image || images[0]?.filename;

  localStorage.setItem('imagen_open_word', word);
  sidebar.classList.remove('searching');
  setViewMode('word');

  document.querySelectorAll('.word-item').forEach(el => {
    el.classList.toggle('active', el.dataset.word === word);
  });

  if (wordTitle) wordTitle.textContent = data.word || word;
  if (flagBtn) flagBtn.classList.toggle('flagged', data.flagged_for_regen || false);

  if (defImg) {
    mainImage.src = imgPath(word, defImg);
    mainImage.alt = word;
  } else {
    mainImage.src = '';
    mainImage.alt = 'No image';
  }

  // Fill definition + translation
  if (defEdit)   defEdit.value   = data.definition || '';
  if (transEdit) transEdit.value = data.translation?.nl || '';
  if (synsEdit)  synsEdit.value  = (data.synonyms || []).join(', ');
  if (antsEdit)  antsEdit.value  = (data.antonyms || []).join(', ');
  // Reset word info edit state
  resetWordInfoEdit();

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

      // Approved toggle (imagegen only)
      const approveBtn = document.createElement('button');
      approveBtn.className = 'approve-btn' + (img.approved ? ' approved' : '');
      approveBtn.title = img.approved ? 'Approved' : 'Mark as approved';
      approveBtn.textContent = '✓';
      approveBtn.addEventListener('click', async e => {
        e.stopPropagation();
        img.approved = !img.approved;
        approveBtn.classList.toggle('approved', img.approved);
        approveBtn.title = img.approved ? 'Approved' : 'Mark as approved';
        const updatedImages = (vocab[word]?.images || []).map(i =>
          i.filename === img.filename ? { ...i, approved: img.approved } : i
        );
        if (vocab[word]) vocab[word].images = updatedImages;
        await updateWordField(word, { images: updatedImages });
      });
      thumb.appendChild(approveBtn);

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
  document.querySelectorAll(`.word-item[data-word="${CSS.escape(word)}"] .new-dot`).forEach(d => d.remove());
}

// ── View mode: gallery | word | game ─────────────────────────────────────────
const gameView = document.getElementById('game-view');

function setViewMode(mode) {
  gallery.style.display = mode === 'gallery' ? '' : 'none';
  wordView.classList.toggle('active', mode === 'word');
  if (gameView) gameView.classList.toggle('active', mode === 'game');

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
    pillWord.disabled = !selectedWord;
  }
}
function setWordView(active) { setViewMode(active ? 'word' : 'gallery'); }
setViewMode('gallery');

// ── Unsaved-changes guard ─────────────────────────────────────────────────────
const unsavedModal     = document.getElementById('unsaved-modal');
const unsavedSaveBtn   = document.getElementById('unsaved-save-btn');
const unsavedDiscardBtn= document.getElementById('unsaved-discard-btn');
const unsavedCancelBtn = document.getElementById('unsaved-cancel-btn');
let pendingNavAction   = null;

function guardNav(action) {
  if (!wordInfoEditing) { action(); return; }
  pendingNavAction = action;
  if (unsavedModal) unsavedModal.classList.add('open');
}

if (unsavedSaveBtn) {
  unsavedSaveBtn.addEventListener('click', async () => {
    if (unsavedModal) unsavedModal.classList.remove('open');
    await saveWordInfo();
    pendingNavAction?.();
    pendingNavAction = null;
  });
}
if (unsavedDiscardBtn) {
  unsavedDiscardBtn.addEventListener('click', () => {
    if (unsavedModal) unsavedModal.classList.remove('open');
    resetWordInfoEdit();
    pendingNavAction?.();
    pendingNavAction = null;
  });
}
if (unsavedCancelBtn) {
  unsavedCancelBtn.addEventListener('click', () => {
    if (unsavedModal) unsavedModal.classList.remove('open');
    pendingNavAction = null;
  });
}
if (unsavedModal) {
  unsavedModal.addEventListener('click', e => {
    if (e.target === unsavedModal) {
      unsavedModal.classList.remove('open');
      pendingNavAction = null;
    }
  });
}

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
  if (idx > 0) guardNav(() => animatedOpenWord(words[idx - 1], 'prev'));
}
function navigateNext() {
  if (!selectedWord) return;
  const words = sortedWords();
  const idx = words.indexOf(selectedWord);
  if (idx < words.length - 1) guardNav(() => animatedOpenWord(words[idx + 1], 'next'));
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
    guardNav(() => {
      selectedWord = null;
      localStorage.removeItem('imagen_open_word');
      document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
      setViewMode('gallery');
    });
    return;
  }
  guardNav(() => {
    if (typeof isNewWordMode !== 'undefined' && isNewWordMode) exitNewWordMode();
    selectedWord = null;
    localStorage.removeItem('imagen_open_word');
    document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
    initGameResults();
    gameScore = gameAttempts = 0;
    if (gameScoreEl)    gameScoreEl.textContent = '0';
    if (gameAttemptsEl) gameAttemptsEl.textContent = '0';
    gameRecentWords = [];
    setViewMode('game');
    nextGameRound();
  });
});
if (pillGallery) pillGallery.addEventListener('click', () => {
  guardNav(() => {
    if (typeof isNewWordMode !== 'undefined' && isNewWordMode) exitNewWordMode();
    selectedWord = null;
    localStorage.removeItem('imagen_open_word');
    document.querySelectorAll('.word-item').forEach(el => el.classList.remove('active'));
    setViewMode('gallery');
  });
});
if (pillWord) pillWord.addEventListener('click', () => {
  if (selectedWord) setViewMode('word');
});

// ── Word info panel — single pencil/save toggle ───────────────────────────────
function setBtnIcon(btn, name) {
  const use = btn?.querySelector('use');
  if (use) use.setAttribute('href', `${ICON_BASE}icons.svg#icon-${name}`);
}

function parseList(val) {
  return val.split(',').map(s => s.trim()).filter(Boolean);
}

let wordInfoEditing = false;
const wordInfoFields = () => [defEdit, transEdit, synsEdit, antsEdit].filter(Boolean);

function enterWordInfoEdit() {
  wordInfoEditing = true;
  wordInfoFields().forEach(f => { f.readOnly = false; });
  if (defSaveBtn) { defSaveBtn.classList.add('editing'); setBtnIcon(defSaveBtn, 'check'); }
  defEdit?.focus();
}

async function saveWordInfo() {
  wordInfoEditing = false;
  wordInfoFields().forEach(f => { f.readOnly = true; });
  if (defSaveBtn) { defSaveBtn.classList.remove('editing'); setBtnIcon(defSaveBtn, 'pencil'); }
  if (!selectedWord) return;
  const fields = { definition: defEdit?.value.trim() || '' };
  if (transEdit) fields.translation = { ...(vocab[selectedWord]?.translation || {}), nl: transEdit.value.trim() };
  if (synsEdit)  fields.synonyms    = parseList(synsEdit.value);
  if (antsEdit)  fields.antonyms    = parseList(antsEdit.value);
  await updateWordField(selectedWord, fields);
}

function resetWordInfoEdit() {
  wordInfoEditing = false;
  wordInfoFields().forEach(f => { f.readOnly = true; });
  if (defSaveBtn) { defSaveBtn.classList.remove('editing'); setBtnIcon(defSaveBtn, 'pencil'); }
}

if (defSaveBtn) {
  defSaveBtn.addEventListener('click', () => {
    if (!wordInfoEditing) enterWordInfoEdit();
    else saveWordInfo();
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

// ── Sidebar collapse ──────────────────────────────────────────────────────────
if (openBtn) {
  openBtn.addEventListener('click', () => {
    sidebar.classList.remove('collapsed');
    openBtn.classList.remove('visible');
  });
}

// ── Columns slider ────────────────────────────────────────────────────────────
if (colsSlider) {
  const savedCols = parseInt(localStorage.getItem('imagen_cols') || '4', 10);
  colsSlider.value = savedCols;
  if (colsLabel) colsLabel.textContent = savedCols;
  document.documentElement.style.setProperty('--cols', savedCols);

  colsSlider.addEventListener('input', () => {
    const v = colsSlider.value;
    if (colsLabel) colsLabel.textContent = v;
    document.documentElement.style.setProperty('--cols', v);
    localStorage.setItem('imagen_cols', v);
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
    const eyeIcon = uiVisible ? 'icon-eye' : 'icon-circle';
    uiToggle.innerHTML = `<svg class="icon icon-lg"><use href="${ICON_BASE}icons.svg#${eyeIcon}"/></svg>`;
    sidebar.classList.toggle('collapsed', !uiVisible);
    if (openBtn) openBtn.classList.toggle('visible', !uiVisible);
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
const addWordBtn    = document.getElementById('add-word-btn');
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
  if (wordTitle)  wordTitle.textContent = '';
  mainImage.src  = '';
  mainImage.alt  = '';
  if (defEdit)   defEdit.value   = '';
  if (transEdit) transEdit.value = '';
  if (synsEdit)  synsEdit.value  = '';
  if (antsEdit)  antsEdit.value  = '';
  [defEdit, transEdit, synsEdit, antsEdit].forEach(f => { if (f) f.readOnly = true; });
  [defSaveBtn, transSaveBtn, synsSaveBtn, antsSaveBtn].forEach(b => {
    if (!b) return;
    b.classList.remove('editing', 'saved');
    setBtnIcon(b, 'pencil');
  });
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
    guardNav(() => openNewWordMode());
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
let gameScore    = 0;
let gameAttempts = 0;
let gameResults  = {};
let gameCurrent  = '';
let gameAnswered = false;
let gameRecentWords = [];
const GAME_RECENT_CAP = 8;

const gameNextBtn    = document.getElementById('game-next-btn');
const gameScoreEl    = document.getElementById('game-score');
const gameAttemptsEl = document.getElementById('game-attempts');

function initGameResults() {
  gameResults = {};
  Object.entries(vocab).forEach(([k, v]) => {
    if (v.stats) gameResults[k] = { ...v.stats };
  });
}

function gamePool() {
  return Object.entries(vocab).filter(([, v]) => {
    const hasContext = (v.occurrences || []).some(o => o.paragraph);
    return v.definition || hasContext;
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

function pickDistractors(targetKey) {
  const targetPos = vocab[targetKey]?.part_of_speech || '';
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
function gameEscAttr(s) { return String(s || '').replace(/'/g, '&#39;'); }
function gameEscRe(s)   { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

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

function nextGameRound() {
  if (!gameView) return;
  const pool = gamePool();
  const clueTextEl = document.getElementById('clue-text');
  const choicesEl  = document.getElementById('game-choices');
  if (!clueTextEl || !choicesEl) return;

  if (pool.length < 4) {
    clueTextEl.textContent = 'Not enough words with definitions or occurrences for the game.';
    choicesEl.innerHTML = '';
    return;
  }

  gameAnswered = false;
  gameCurrent  = '';
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

  const word = data.word || key;
  const labelEl = document.getElementById('clue-label');

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

  const distractors = pickDistractors(key);
  choicesEl.innerHTML = shuffle([word, ...distractors]).map(w =>
    `<button class="choice-btn" onclick="gameGuess('${gameEscAttr(w)}')">${gameEsc(w)}</button>`
  ).join('');
}

function gameGuess(word) {
  if (gameAnswered) return;
  gameAnswered = true;
  gameAttempts++;
  if (gameAttemptsEl) gameAttemptsEl.textContent = gameAttempts;
  if (gameNextBtn) { gameNextBtn.textContent = 'Next →'; gameNextBtn.classList.add('answered'); }

  const currentData = vocab[gameCurrent] || {};
  const currentWord = currentData.word || gameCurrent;
  const correct = word === currentWord;

  if (correct) gameScore++;
  if (gameScoreEl) gameScoreEl.textContent = gameScore;

  const r = gameResults[gameCurrent] = gameResults[gameCurrent] || { correct: 0, wrong: 0 };
  r[correct ? 'correct' : 'wrong']++;
  const stats = { correct: r.correct, wrong: r.wrong };
  if (vocab[gameCurrent]) vocab[gameCurrent].stats = stats;
  updateWordField(gameCurrent, { stats });

  document.querySelectorAll('.choice-btn').forEach(btn => {
    btn.disabled = true;
    const t = btn.textContent.trim();
    if (t === currentWord) btn.classList.add('correct');
    else if (t === word && !correct) btn.classList.add('wrong');
  });

  // Reveal answer
  const clueTextEl = document.getElementById('clue-text');
  const sourceEl   = document.getElementById('clue-source');
  if (clueTextEl) {
    if (currentData.definition) {
      const pos = currentData.part_of_speech ? `<em>${gameEsc(currentData.part_of_speech)}</em> ` : '';
      const parts = [`<strong>${gameEsc(currentWord)}</strong> — ${pos}${gameEsc(currentData.definition)}`];
      const ctx = buildGameContext(gameCurrent, true);
      if (ctx) parts.push(`<span style="font-style:italic;color:var(--text-dim)">${ctx}</span>`);
      clueTextEl.innerHTML = parts.join('<br><br>');
      if (sourceEl && currentData.example) sourceEl.textContent = `"${currentData.example}"`;
    } else {
      clueTextEl.innerHTML = buildGameContext(gameCurrent, true);
    }
  }

  const solvedEl = document.getElementById('clue-solved-actions');
  if (solvedEl) {
    solvedEl.innerHTML = `<button onclick="openWord('${gameEscAttr(gameCurrent)}')">View card</button>`;
  }
}

if (gameNextBtn) gameNextBtn.addEventListener('click', nextGameRound);

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

// ── Vocab loading ─────────────────────────────────────────────────────────────
function initAfterVocabLoad() {
  const errorMsg = document.getElementById('error-msg');
  if (errorMsg) errorMsg.style.display = 'none';
  renderWordList();
  renderGallery();
  const saved = localStorage.getItem('imagen_open_word');
  if (saved && vocab[saved]) openWord(saved);
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
