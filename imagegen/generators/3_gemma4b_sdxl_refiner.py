"""
Two-phase vocabulary image generator.

Phase 1  — Ollama (CPU): generate a sci-fi scene per word, save to scenes.json.
Phase 2  — ComfyUI (GPU): render each scene to test/images/ via the ComfyUI API.
           Uses SDXL base + refiner for higher quality output.

Requirements:
  - Ollama running  (ollama serve)
  - ComfyUI running (python ComfyUI/main.py)
  - sd_xl_base_1.0.safetensors and sd_xl_refiner_1.0.safetensors in ComfyUI models
"""

import argparse
import json
import os
import random
import re
import time
from datetime import date
from pathlib import Path
import requests

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "gemma4:e2b"

COMFY_URL          = "http://127.0.0.1:8188"
CHECKPOINT         = "sd_xl_base_1.0.safetensors"
REFINER_CHECKPOINT = "sd_xl_refiner_1.0.safetensors"

WIDTH, HEIGHT = 1536, 640

# Base sampler — handles composition and broad structure (steps 0→28 of 35)
BASE_STEPS    = 50
BASE_END_STEP = 35
BASE_CFG      = 7.5
BASE_SAMPLER  = "dpmpp_2m"
BASE_SCHED    = "karras"

# Style CLIP — encoded in a separate pass and concatenated, so it never
# competes with scene keywords for token budget (inspired by wordimage.py)
BASE_STYLE = (
    "bright colours, high details, vintage sci-fi illustration, "
    "retro-futuristic design, painted, airbrushed, gouache, "
    "soft diffuse lighting, balanced composition, slight grain texture, no text"
)

ARTISTS_BASE = []  # no fixed anchor — artists picked per image by Ollama

# Brief style tags used by Ollama to match the best artist to the scene
ARTISTS = {
    "Simon Stalenhag":  "solitary figures in rural landscapes with melancholy machines, wide vistas",
    "Syd Mead":         "sleek futurism, chrome vehicles, urban environments, people with technology",
    "John Harris":      "epic deep space vistas, large spacecraft, gas giants, sweeping grandeur",
    "Klaus Burgle":     "optimistic mid-century space age, warm interiors, human daily life in space",
    "Angus McKie":      "highly detailed spacecraft and mechanical interiors, dynamic comic-style angles",
    "John Berkey":      "loose impressionistic spacecraft and space scenes, dramatic painterly strokes",
    "Davis Meltzer":    "technical machinery, detailed mechanisms, dramatic high-contrast lighting",
}

NEGATIVE = (
    "text, watermark, signature, blurry, low resolution, low quality, "
    "amateur, messy, poorly drawn, grayscale, monochrome, poor composition, "
    "grainy, artifacts, noise, distorted, cartoon, photorealistic, 3d render, "
    "anime, chaotic, fantasy, car, line art, ink lines, comic book, hard outlines, sketch, steampunk"
)

VARIANT    = "3_gemma4b_sdxl_refiner"
BASE_DIR   = Path(__file__).resolve().parent              # imagegen/generators/
IMAGEN_DIR = BASE_DIR.parent / "words"                    # imagegen/words/
VOCAB_PATH = BASE_DIR.parent.parent / "docs" / "vocab.json"  # docs/vocab.json
# SCENES_PATH set at runtime (ephemeral phase-1 cache in imagegen/)

# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_filename(word):
    word = re.sub(r'[^\w\-_. ]', '', word)
    return word.strip().replace(" ", "_")[:80]


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def has_imagen_image(word, force=False):
    """Return True if word already has an image from this variant (skip logic)."""
    if force:
        return False
    word_dir = os.path.join(IMAGEN_DIR, safe_filename(word))
    if not os.path.isdir(word_dir):
        return False
    return any(f.endswith(f"_{VARIANT}.png") for f in os.listdir(word_dir))


def next_imagen_filename(word):
    """Return DDMMYY_X_VARIANT.png with X auto-incremented to avoid collision."""
    d = date.today().strftime("%d%m%y")
    word_dir = os.path.join(IMAGEN_DIR, safe_filename(word))
    x = 1
    while os.path.exists(os.path.join(word_dir, f"{d}_{x}_{VARIANT}.png")):
        x += 1
    return f"{d}_{x}_{VARIANT}.png"


def update_vocab(vocab, word_key, word_display, filename, scene_data):
    """Add a generated image entry into the unified vocab dict in-place."""
    if word_key not in vocab:
        vocab[word_key] = {"word": word_display, "images": [], "default_image": None}
    entry = vocab[word_key]
    if "images" not in entry:
        entry["images"] = []

    if any(img["filename"] == filename for img in entry["images"]):
        print(f"  [already in vocab: {filename}]")
        return

    from datetime import date as _date
    entry["images"].append({
        "filename":       filename,
        "script":         VARIANT,
        "prompt_base":    scene_data.get("prompt_base", ""),
        "prompt_refiner": scene_data.get("prompt_refiner", ""),
        "negative":       scene_data.get("negative", ""),
        "scene":          scene_data.get("scene", ""),
        "date":           _date.today().isoformat(),
        "approved":       False,
    })
    entry["default_image"] = filename
    print(f"  [vocab updated: {filename}]")


# ── Phase 1: Ollama scene generation ─────────────────────────────────────────

def generate_scene(word, definition, prev_context, next_context):
    hint = (definition or "(no definition)")[:200]
    passage = ""
    if prev_context or next_context:
        passage = f"…{prev_context.strip()} {word} {next_context.strip()}…"

    system = (
        "You are a retro sci-fi concept artist painting grounded, tangible futures. "
        "Match the word's domain to the right subject type: "
        "words about people, relationships, emotions, or social dynamics → use named human characters as the central subject; "
        "words about actions, forces, or processes → show a person or machine actively doing something; "
        "words about things or qualities → use a specific named object or machine; "
        "words about places or states → use an environment. "
        "The scene's central subject and action must make the word's meaning self-evident — "
        "someone watching for five seconds must sense it without reading anything. "
        "All scenes are set in a specific sci-fi location: planetary surface, orbital station, deep space, colony, etc. "
        "BANNED: cars, energy filaments, glowing tendrils, pulsating matter, crystalline structures, floating orbs, bio-luminescent caves. "
        "Every scene must be visually distinct — different subject, composition, and colour palette."
    )
    prompt = (
        f'Design a retro sci-fi visual metaphor for the word "{word}".\n'
        f'Definition: {hint}\n'
    )
    if passage:
        prompt += f'Book context: {passage}\n'
    prompt += (
        f'\nFirst, decide how "{word}" is best visualised as a still image:\n'
        "- GROUP: a social scene, ritual, or relationship between named people (best for words about people, kinship, emotion, social roles)\n"
        "- ACTION: a named character doing something that embodies the word\n"
        "- OBJECT: a specific named machine, vessel, or device\n"
        "- ENVIRONMENT: a place or setting that embodies the concept\n"
        "Pick the type that makes the word most immediately readable.\n\n"
        "Reply with exactly 6 lines, nothing else:\n"
        "Approach: [group / action / object / environment — and one sentence why]\n"
        "Metaphor: [the tension or dynamic that embodies the word]\n"
        "Location: [specific sci-fi environment — vary freely across deep space, asteroid field, gas giant orbit, spacecraft interior, orbital station, planetary surface, colony dome, etc.]\n"
        "Focus: [name the central subject and describe their action — what are they doing and why does it show the word]\n"
        "Mood: [lighting and 1-2 dominant colours]\n"
        "Anchor: [one concrete striking detail — the thing a viewer remembers]"
    )
    OLLAMA_OPTS = {"temperature": 1.0, "top_p": 0.95, "top_k": 64,
                   "num_predict": 400, "seed": random.randint(1, 2**31)}

    def chat(messages):
        resp = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL, "messages": messages,
            "stream": False, "think": False, "options": OLLAMA_OPTS,
        }, timeout=60)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()

    critique = (
        f'Review your scene for the word "{word}" against these criteria:\n'
        "1. Approach: does the scene commit to the approach you chose (action / object / environment)? "
        "Is that approach the clearest way to show the word as a still image?\n"
        "2. Focus: does it name a specific character or machine and show an action that makes "
        f'"{word}" visually obvious to someone who doesn\'t know the word?\n'
        "3. Anchor: is it a concrete, physical, nameable detail — not abstract phenomena?\n"
        "4. Are there any banned elements (energy filaments, glowing tendrils, pulsating matter, "
        "crystalline structures, floating orbs)?\n\n"
        "Rewrite any lines that fail. Reply with the full corrected 6-line scene, nothing else."
    )

    try:
        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ]
        draft = chat(messages)
        if not draft:
            return "", ""
        # Second pass: critique and revise
        messages += [
            {"role": "assistant", "content": draft},
            {"role": "user",      "content": critique},
        ]
        scene = chat(messages)
        if not scene:
            return "", ""
        # Third pass: distil prose into SDXL visual keywords
        kw_prompt = (
            "Convert the scene above into 15-20 comma-separated visual keywords for an image generation model.\n"
            "Rules:\n"
            "- Replace all proper names (character names, ship names, device names) with descriptive roles: "
            "'Engineer Solis' → 'engineer', 'Kepler-9' → 'cargo freighter', 'Synchronization Array' → 'mechanical array'\n"
            "- Add framing based on the Approach:\n"
            "  OBJECT → 'object dominant in foreground, environmental context visible behind it, no figures, no people'\n"
            "  ACTION → include the character's role and their action\n"
            "  GROUP  → include 'group of figures' and describe their roles and arrangement\n"
            "  ENVIRONMENT → 'wide establishing shot, no figures'\n"
            "- Concrete nouns first: objects, machines, character roles, environment\n"
            "- Strong adjectives: colours, materials, textures, emotional register\n"
            "- Action-descriptors as nouns: collision, confrontation, struggle, impact — not verb phrases\n"
            "- No sentences, no verbs in verb form, no articles, no proper names\n"
            "- Order by visual dominance — most prominent element first\n"
            f"- Add 2-3 emotional atmosphere words near the end that match the word '{word}' "
            "(e.g. tense, ominous, triumphant, melancholic, serene, frantic, reverent, oppressive)\n"
            f"- Finally, pick the single best matching artist for this scene from this list and append 'art by <name>':\n"
            + "\n".join(f"  {name}: {desc}" for name, desc in ARTISTS.items()) + "\n"
            "Output only the comma-separated keyword string (ending with 'art by <name>'), nothing else."
        )
        messages += [
            {"role": "assistant", "content": scene},
            {"role": "user",      "content": kw_prompt},
        ]
        keywords = chat(messages)
        return scene, keywords
    except Exception as e:
        print(f"  [Ollama error] {e}")
        return "", ""


def build_prompts(entry, scene, keywords=None):
    """Return (base_positive, refiner_positive) for ComfyUI."""
    word = (entry.get("word") or "").strip()

    if keywords:
        scene_desc = keywords.strip().rstrip(",")
    else:
        # Fallback for old scenes.json entries without sdxl_keywords
        parts = {"metaphor": "", "location": "", "focus": "", "mood": "", "anchor": ""}
        if scene:
            for line in scene.splitlines():
                for key in parts:
                    if line.lower().startswith(f"{key}:"):
                        parts[key] = line.split(":", 1)[1].strip()

        def first_sentence(text):
            for sep in (".", "—", ";"):
                idx = text.find(sep)
                if 0 < idx < 120:
                    return text[:idx + 1].strip()
            return text[:120].strip()

        if any(parts.values()):
            scene_desc = ", ".join(filter(None, [
                first_sentence(parts["anchor"]),
                first_sentence(parts["focus"]),
                parts["location"][:80].strip(),
                parts["mood"][:60].strip(),
            ]))
        else:
            scene_desc = first_sentence(scene or entry.get("definition", "") or word)

    # Artist is chosen by Ollama and appended to keywords as "art by <name>".
    # Fall back to a random pick for the refiner if no artist found in keywords.
    artist_names = list(ARTISTS.keys())
    fallback_artist = random.choice(artist_names) if artist_names else ""

    # Base positive: scene-specific content first, then style prefix.
    # SDXL weights earlier tokens higher so the scene should lead.
    # BASE_STYLE goes into a separate ConditioningConcat pass.
    base_positive = f"{scene_desc}, retro-futuristic sci-fi art"

    # Extract artist from keywords for the refiner, or use fallback
    refiner_artist = fallback_artist
    if keywords:
        for name in artist_names:
            if name.lower() in keywords.lower():
                refiner_artist = name
                break
    refiner_positive = (
        f"masterpiece, best quality, sharp focus, fine detail, hyperdetailed, "
        f"retro-futuristic sci-fi, painted illustration, airbrushed, cinematic lighting, {refiner_artist}"
    )
    return base_positive, refiner_positive


def phase1_generate_scenes(data, scenes, scenes_path, force=False, limit=None):
    """Call Ollama for every word that needs an image and has no scene yet."""
    pending = [
        e for e in data
        if not has_imagen_image(e.get("word"), force=force)
        and not scenes.get(e.get("word"), {}).get("scene")
    ]
    if limit:
        pending = pending[:limit]

    if not pending:
        print("Phase 1: nothing to do (all scenes already generated).")
        return

    print(f"Phase 1: generating scenes for {len(pending)} words via Ollama…\n")

    for i, entry in enumerate(pending, 1):
        word = entry.get("word", "")
        definition   = entry.get("definition", "")
        prev_context = entry.get("prev_context", "")
        next_context = entry.get("next_context", "")

        print(f"  [{i}/{len(pending)}] {word}")
        scene, keywords = generate_scene(word, definition, prev_context, next_context)
        if not scene:
            print(f"    [skipped — Ollama returned empty]")
            continue
        base_prompt, refiner_prompt = build_prompts(entry, scene, keywords)
        scenes[word] = {
            "scene":          scene,
            "sdxl_keywords":  keywords,
            "prompt_base":    base_prompt,
            "prompt_refiner": refiner_prompt,
        }
        for line in scene.splitlines():
            print(f"    {line}")
        if keywords:
            print(f"    → keywords: {keywords}")

    save_json(scenes_path, scenes)
    print(f"\nPhase 1 done. Scenes saved to {scenes_path}\n")


# ── Phase 2: ComfyUI image generation ────────────────────────────────────────

def comfy_workflow(positive_base, positive_refiner, negative, seed):
    return {
        # Base model
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        # Latent canvas
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1},
        },
        # Base conditioning — scene keywords in one CLIP pass, style in another,
        # then concatenated so neither competes for the 77-token budget
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_base, "clip": ["4", 1]},
        },
        "20": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": BASE_STYLE, "clip": ["4", 1]},
        },
        "21": {
            "class_type": "ConditioningConcat",
            "inputs": {"conditioning_to": ["6", 0], "conditioning_from": ["20", 0]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        # Base KSampler — steps 0→BASE_END_STEP (80% of BASE_STEPS)
        "10": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise":                 "enable",
                "noise_seed":                seed,
                "steps":                     BASE_STEPS,
                "cfg":                       BASE_CFG,
                "sampler_name":              BASE_SAMPLER,
                "scheduler":                 BASE_SCHED,
                "start_at_step":             0,
                "end_at_step":               BASE_END_STEP,
                "return_with_leftover_noise": "enable",
                "model":                     ["4", 0],
                "positive":                  ["21", 0],
                "negative":                  ["7", 0],
                "latent_image":              ["5", 0],
            },
        },
        # Refiner model
        "12": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": REFINER_CHECKPOINT},
        },
        # Refiner conditioning — encoded by refiner's own CLIP
        "15": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_refiner, "clip": ["12", 1]},
        },
        "16": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["12", 1]},
        },
        # Refiner KSampler — steps BASE_END_STEP→end (final 20%)
        "11": {
            "class_type": "KSamplerAdvanced",
            "inputs": {
                "add_noise":                 "disable",
                "noise_seed":                0,
                "steps":                     BASE_STEPS,
                "cfg":                       BASE_CFG,
                "sampler_name":              BASE_SAMPLER,
                "scheduler":                 BASE_SCHED,
                "start_at_step":             BASE_END_STEP,
                "end_at_step":               10000,
                "return_with_leftover_noise": "disable",
                "model":                     ["12", 0],
                "positive":                  ["15", 0],
                "negative":                  ["16", 0],
                "latent_image":              ["10", 0],
            },
        },
        # Decode with refiner VAE, save
        "17": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["11", 0], "vae": ["12", 2]},
        },
        "19": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "vocab_tmp", "images": ["17", 0]},
        },
    }


def comfy_generate(positive_base, positive_refiner, negative):
    seed = random.randint(0, 2**32 - 1)
    workflow = comfy_workflow(positive_base, positive_refiner, negative, seed)

    resp = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=10)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    print(f"    queued ({prompt_id[:8]}…) ", end="", flush=True)
    for _ in range(600):
        time.sleep(1)
        hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=5).json()
        if prompt_id in hist:
            print(" done")
            outputs = hist[prompt_id].get("outputs", {})
            for node_out in outputs.values():
                if "images" in node_out:
                    img_meta = node_out["images"][0]
                    img_resp = requests.get(f"{COMFY_URL}/view", params={
                        "filename": img_meta["filename"],
                        "subfolder": img_meta.get("subfolder", ""),
                        "type":     img_meta.get("type", "output"),
                    }, timeout=10)
                    img_resp.raise_for_status()
                    return img_resp.content
        print(".", end="", flush=True)

    print(" TIMEOUT")
    return None


def phase2_generate_images(data, scenes, vocab, vocab_path, force=False, limit=None):
    pending = [
        e for e in data
        if e.get("word") in scenes
        and not has_imagen_image(e.get("word"), force=force)
    ]
    if limit:
        pending = pending[:limit]

    if not pending:
        print("Phase 2: nothing to do.")
        return

    try:
        requests.get(f"{COMFY_URL}/system_stats", timeout=3).raise_for_status()
    except Exception:
        print(f"ERROR: ComfyUI not reachable at {COMFY_URL}. Start it with:\n"
              "  python ComfyUI/main.py")
        return

    print(f"Phase 2: generating {len(pending)} images via ComfyUI…\n")

    generated = errors = 0
    for i, entry in enumerate(pending, 1):
        word = entry.get("word", "")
        print(f"  [{i}/{len(pending)}] {word}")

        scene_data     = scenes[word]
        keywords       = scene_data.get("sdxl_keywords")
        base_prompt    = scene_data.get("prompt_base") or build_prompts(entry, scene_data.get("scene", ""), keywords)[0]
        refiner_prompt = scene_data.get("prompt_refiner") or build_prompts(entry, scene_data.get("scene", ""), keywords)[1]
        negative       = scene_data.get("negative") or NEGATIVE
        scene_data["prompt_base"]    = base_prompt
        scene_data["prompt_refiner"] = refiner_prompt
        scene_data["negative"]       = negative

        print(f"    base: {base_prompt}")
        image_bytes = comfy_generate(base_prompt, refiner_prompt, negative)
        if not image_bytes:
            errors += 1
            continue

        word_dir = IMAGEN_DIR / safe_filename(word)
        word_dir.mkdir(parents=True, exist_ok=True)
        fname    = next_imagen_filename(word)
        img_path = word_dir / fname

        with open(img_path, "wb") as f:
            f.write(image_bytes)
        print(f"    saved → {img_path} ({img_path.stat().st_size // 1024}KB)")

        update_vocab(vocab, word.lower(), word, fname, scene_data)
        save_json(vocab_path, vocab)
        generated += 1

    print(f"\nPhase 2 done. Generated: {generated}  Errors: {errors}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit=None, force=False, words=None):
    vocab_path  = VOCAB_PATH
    scenes_path = BASE_DIR.parent / "scenes.json"  # imagegen/scenes.json
    print(f"Loading vocab from {vocab_path}…")

    vocab = load_json(vocab_path, {})
    if not vocab:
        print(f"ERROR: No vocab found at {vocab_path}. Run extract.py first.")
        return

    # Build entry list (object-keyed vocab → list of values)
    if words:
        word_set = {w.lower() for w in words}
        data  = [v for k, v in vocab.items() if k in word_set]
        force = True
    else:
        data = list(vocab.values())

    IMAGEN_DIR.mkdir(parents=True, exist_ok=True)

    scenes = load_json(scenes_path, {})

    phase1_generate_scenes(data, scenes, scenes_path, force=force, limit=limit)
    phase2_generate_images(data, scenes, vocab, vocab_path, force=force, limit=limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int,  default=None, help="Process at most N words")
    parser.add_argument("--force", action="store_true",    help="Regenerate even if image exists")
    parser.add_argument("--words", nargs="+", default=None, help="Only process these words (implies --force)")
    parser.add_argument("--test",  type=str,  default=None, metavar="WORD",
                        help="Generate and print scene+prompts for WORD, no image")
    args = parser.parse_args()

    if args.test:
        word = args.test
        data = load_json(VOCAB_PATH, {})
        entry = data.get(word.lower()) or next(
            (v for v in data.values() if v.get("word", "").lower() == word.lower()),
            {"word": word}
        )
        definition   = entry.get("definition", "")
        prev_context = entry.get("prev_context", "")
        next_context = entry.get("next_context", "")
        print(f"\nWord:       {word}")
        if definition:
            print(f"Definition: {definition}")
        if prev_context or next_context:
            print(f"Context:    …{prev_context.strip()} [{word}] {next_context.strip()}…")
        print("\n── Generating scene via Ollama… ──\n")
        scene, keywords = generate_scene(word, definition, prev_context, next_context)
        print(scene)
        if keywords:
            print(f"\n── SDXL keywords ──\n{keywords}")
        base_prompt, refiner_prompt = build_prompts(entry, scene, keywords)
        print(f"\n── Base positive (encoded by base CLIP) ──\n{base_prompt}\n")
        print(f"── Refiner positive (encoded by refiner CLIP) ──\n{refiner_prompt}\n")
        print(f"── Negative (both) ──\n{NEGATIVE}\n")
    else:
        run(limit=args.limit, force=args.force, words=args.words)
