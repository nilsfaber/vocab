#!/usr/bin/env bash
# Vocab builder setup — run once from the repo root.
set -e

PASS=0; WARN=0; FAIL=0

ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
warn() { echo "  ⚠️  $1"; WARN=$((WARN+1)); }
fail() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

echo ""
echo "── Python ──────────────────────────────────────────────"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>/dev/null; then
  ok "Python $(python3 --version 2>&1 | cut -d' ' -f2)"
else
  fail "Python 3.9+ required ($(python3 --version 2>&1))"
fi

echo ""
echo "── Python packages ─────────────────────────────────────"
if python3 -c "import requests" 2>/dev/null; then
  ok "requests"
else
  echo "  → installing requests…"
  pip3 install --quiet requests && ok "requests installed" || fail "could not install requests"
fi

echo ""
echo "── System tools ─────────────────────────────────────────"
if command -v pngquant &>/dev/null; then
  ok "pngquant $(pngquant --version 2>&1 | head -1)"
else
  fail "pngquant not found — install with: sudo apt install pngquant"
fi

if command -v adb &>/dev/null; then
  ok "adb $(adb version 2>&1 | head -1)"
else
  warn "adb not found — needed to pull from device (set ADB path in extract.py)"
fi

echo ""
echo "── Image generation (optional) ──────────────────────────"
if command -v ollama &>/dev/null; then
  ok "ollama"
else
  warn "ollama not found — needed for image generation (wordimage.py)"
fi

if curl -sf http://127.0.0.1:8188/system_stats &>/dev/null; then
  ok "ComfyUI reachable at :8188"
else
  warn "ComfyUI not running — start with: python ComfyUI/main.py"
fi

echo ""
echo "── Directories ──────────────────────────────────────────"
mkdir -p data docs/images docs/images/hires
ok "data/  docs/images/  docs/images/hires/"

echo ""
echo "────────────────────────────────────────────────────────"
echo "  ✅ $PASS ok   ⚠️  $WARN warnings   ❌ $FAIL errors"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  Fix the errors above before running extract.py"
  exit 1
else
  echo "  Ready. Next steps:"
  echo "    1. Connect your device via USB"
  echo "    2. python extract.py"
  echo "    3. cd docs && python -m http.server 8000"
  echo ""
fi
