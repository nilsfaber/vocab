"""
Two-phase vocabulary image generator.

Phase 1  — Ollama (CPU): generate a sci-fi scene per word, save to scenes.json.
Phase 2  — ComfyUI (GPU): render each scene via the ComfyUI API.

Requirements:
  - Ollama running  (ollama serve)
  - ComfyUI running (python ComfyUI/main.py)
"""

import argparse
import json
import os
import random
import re
import time

import requests

# ── Config ────────────────────────────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral-nemo:latest"

COMFY_URL    = "http://127.0.0.1:8188"
CHECKPOINT   = "sd_xl_base_1.0.safetensors"

WIDTH, HEIGHT = 1536, 640
STEPS         = 30
CFG           = 7.5
SAMPLER       = "dpmpp_2m"
SCHEDULER     = "karras"

STYLE = (
    "Syd Mead, John Harris style, bright colours, high details, science fiction, "
    "vintage sci-fi illustration, inked line art, bold black outlines, "
    "visible halftone dots, screen tone shading, cross-hatching shadows, "
    "retro-futuristic design, printed on paper, slight ink bleed, grainy texture, "
    "flat shading, minimal gradients, soft diffuse lighting, balanced composition"
)

NEGATIVE = (
    "text, watermark, crowd, chaotic, random people, messy composition, "
    "red and green color contrast, photorealistic, 3d render, anime, blurry, "
    "fantasy, car, signature"
)

from pathlib import Path

VARIANT    = "mistralnemo_sdxl"
BASE_DIR   = Path(__file__).resolve().parent              # imagegen/generators/
IMAGEN_DIR = BASE_DIR.parent / "words"                    # imagegen/words/
VOCAB_PATH = BASE_DIR.parent.parent / "docs" / "vocab.json"

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
    if force:
        return False
    word_dir = IMAGEN_DIR / safe_filename(word)
    if not word_dir.is_dir():
        return False
    return any(f.endswith(f"_{VARIANT}.png") for f in os.listdir(word_dir))


def next_imagen_filename(word):
    from datetime import date as _date
    d = _date.today().strftime("%d%m%y")
    word_dir = IMAGEN_DIR / safe_filename(word)
    x = 1
    while (word_dir / f"{d}_{x}_{VARIANT}.png").exists():
        x += 1
    return f"{d}_{x}_{VARIANT}.png"


def update_vocab(vocab, word_key, word_display, filename, scene_data):
    if word_key not in vocab:
        vocab[word_key] = {"word": word_display, "images": [], "default_image": None}
    entry = vocab[word_key]
    if "images" not in entry:
        entry["images"] = []
    if any(img["filename"] == filename for img in entry["images"]):
        return
    from datetime import date as _date
    entry["images"].append({
        "filename":    filename,
        "script":      VARIANT,
        "prompt_base":    scene_data.get("prompt_base") or scene_data.get("prompt", ""),
        "prompt_refiner": scene_data.get("prompt_refiner", ""),
        "negative":       scene_data.get("negative", ""),
        "scene":       scene_data.get("scene", ""),
        "date":        _date.today().isoformat(),
        "approved":    False,
    })
    entry["default_image"] = filename


# ── Phase 1: Ollama scene generation ─────────────────────────────────────────

def generate_scene(word, definition, context):
    hint = (definition or context or "(no context)")[:300]
    system = (
        "You are a sci-fi concept artist designing visual metaphors for vocabulary words. "
        "Each scene must embody the word's meaning through concrete visible action — "
        "the viewer should sense the word's concept without it being written anywhere. "
        "Be specific, vivid, and inventive. Never repeat similar scenes. "
        "Never start any line with 'A lone', 'A colossal', 'A solitary', 'A massive', or 'A single'. "
        "Vary your sentence structure — describe relationships, processes, contrasts, or transformations, not just objects."
    )
    prompt = (
        f'Design a sci-fi visual metaphor for the word "{word}".\n'
        f'Meaning: {hint}\n\n'
        f'The scene must make "{word}" feel visually obvious through what is happening — '
        f"not through text or symbols.\n\n"
        "Reply with exactly 4 lines, nothing else:\n"
        "Metaphor: [one sentence — the dynamic or tension in the scene that embodies the word]\n"
        "Location: [specific sci-fi setting]\n"
        "Focus: [the central action or interaction — not a single object, but something happening]\n"
        "Atmosphere: [lighting, mood, environmental details]"
    )
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model":   OLLAMA_MODEL,
            "prompt":  prompt,
            "system":  system,
            "stream":  False,
            "options": {"temperature": 0.9, "num_predict": 160, "seed": random.randint(1, 2**31)},
        }, timeout=40)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"  [Ollama error] {e}")
        return ""


def build_prompt(entry, scene):
    word       = (entry.get("word")         or "").strip()
    definition = (entry.get("definition")   or "").strip()

    # Parse all scene fields — order matters for SDXL prompt weighting
    parts = {"metaphor": "", "location": "", "focus": "", "atmosphere": ""}
    if scene:
        for line in scene.splitlines():
            for key in parts:
                if line.lower().startswith(f"{key}:"):
                    parts[key] = line.split(":", 1)[1].strip()

    def clip_phrase(text, max_words=10):
        """Trim to max_words without trailing ellipsis."""
        words = text.split()
        return " ".join(words[:max_words])

    if any(parts.values()):
        scene_desc = ", ".join(filter(None, [
            clip_phrase(parts["focus"],      10),
            clip_phrase(parts["location"],    7),
            clip_phrase(parts["atmosphere"],  7),
        ]))
    else:
        scene_desc = clip_phrase(scene or definition or word, 18)

    # Scene content — core style anchors prepended so they lead the token sequence
    return f"Syd Mead, John Harris, bright colours, high details, sci-fi illustration, no text, {scene_desc}"


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
        definition = entry.get("definition", "")
        context = f"{entry.get('prev_context','')} {entry.get('next_context','')}".strip()

        print(f"  [{i}/{len(pending)}] {word}")
        scene = generate_scene(word, definition, context)
        scenes[word] = {"scene": scene, "prompt": build_prompt(entry, scene)}
        if scene:
            print(f"    {scene[:90]}")

    save_json(scenes_path, scenes)
    print(f"\nPhase 1 done. Scenes saved to {scenes_path}\n")


# ── Phase 2: ComfyUI image generation ────────────────────────────────────────

def comfy_workflow(positive, negative, seed):
    return {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": CHECKPOINT},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1},
        },
        # Node 6: scene content (fits within 77 tokens on its own)
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["4", 1]},
        },
        # Node 10: style tokens (separate CLIP pass)
        "10": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": STYLE, "clip": ["4", 1]},
        },
        # Node 11: concat scene + style conditioning
        "11": {
            "class_type": "ConditioningConcat",
            "inputs": {"conditioning_to": ["6", 0], "conditioning_from": ["10", 0]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["4", 1]},
        },
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": STEPS,
                "cfg": CFG,
                "sampler_name": SAMPLER,
                "scheduler": SCHEDULER,
                "denoise": 1.0,
                "model":         ["4", 0],
                "positive":      ["11", 0],
                "negative":      ["7", 0],
                "latent_image":  ["5", 0],
            },
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "vocab_tmp", "images": ["8", 0]},
        },
    }


def comfy_generate(positive, negative):
    seed = random.randint(0, 2**32 - 1)
    workflow = comfy_workflow(positive, negative, seed)

    # Submit prompt
    resp = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=10)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    # Poll history until done
    print(f"    queued ({prompt_id[:8]}…) ", end="", flush=True)
    for _ in range(600):          # up to ~10 min
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


def phase2_generate_images(data, scenes, vocab, force=False, limit=None):
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

    # Check ComfyUI is reachable
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

        scene_data = scenes[word]
        positive = scene_data.get("prompt_base") or scene_data.get("prompt") or build_prompt(entry, scene_data.get("scene", ""))
        negative = scene_data.get("negative") or NEGATIVE
        scene_data["prompt_base"] = positive
        scene_data["negative"]    = negative

        image_bytes = comfy_generate(positive, negative)
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
        save_json(str(VOCAB_PATH), vocab)
        generated += 1

    print(f"\nPhase 2 done. Generated: {generated}  Errors: {errors}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(limit=None, force=False, words=None):
    scenes_path = str(BASE_DIR.parent / "scenes.json")

    vocab = load_json(str(VOCAB_PATH), {})
    if not vocab:
        print(f"ERROR: No vocab found at {VOCAB_PATH}. Run extract.py first.")
        return

    if words:
        word_set = {w.lower() for w in words}
        data  = [v for k, v in vocab.items() if k in word_set]
        force = True
    else:
        data = list(vocab.values())

    IMAGEN_DIR.mkdir(parents=True, exist_ok=True)

    scenes = load_json(scenes_path, {})

    phase1_generate_scenes(data, scenes, scenes_path, force=force, limit=limit)
    phase2_generate_images(data, scenes, vocab, force=force, limit=limit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int,  default=None, help="Process at most N words")
    parser.add_argument("--force", action="store_true",    help="Regenerate even if image exists")
    parser.add_argument("--words", nargs="+", default=None, help="Only process these words (implies --force)")
    parser.add_argument("--test",  type=str,  default=None, metavar="WORD", help="Generate and print scene+prompt for WORD, no image")
    args = parser.parse_args()

    if args.test:
        word = args.test
        data = load_json(str(VOCAB_PATH), {})
        entry = data.get(word.lower()) or next(
            (v for v in data.values() if v.get("word", "").lower() == word.lower()),
            {"word": word}
        )
        definition = entry.get("definition", "")
        context = f"{entry.get('prev_context','')} {entry.get('next_context','')}".strip()
        print(f"\nWord:       {word}")
        if definition:
            print(f"Definition: {definition}")
        print("\n── Generating scene via Ollama… ──\n")
        scene = generate_scene(word, definition, context)
        print(scene)
        prompt = build_prompt(entry, scene)
        print(f"\n── SDXL prompt ──\n{prompt}\n")
        print(f"── Style (separate CLIP pass) ──\n{STYLE}\n")
    else:
        run(limit=args.limit, force=args.force, words=args.words)
