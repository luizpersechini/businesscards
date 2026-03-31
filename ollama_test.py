#!/usr/bin/env python3
"""
Ollama Diagnostic Script
Run this BEFORE launching the app to confirm Ollama is working correctly.

Usage:
    python3 ollama_test.py
    python3 ollama_test.py --model llama3.2-vision
    python3 ollama_test.py --model moondream
"""

import sys
import time
import base64
import argparse
import requests
import numpy as np

OLLAMA_URL = "http://localhost:11434"


def ok(msg):  print(f"  ✅ {msg}")
def fail(msg): print(f"  ❌ {msg}")
def info(msg): print(f"  ℹ️  {msg}")
def step(msg): print(f"\n{'─'*60}\n{msg}")


# ── Test 1: Is Ollama running? ────────────────────────────────
step("TEST 1 — Ollama service")
try:
    r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    if r.status_code == 200:
        ok(f"Ollama is running at {OLLAMA_URL}")
    else:
        fail(f"Ollama returned HTTP {r.status_code}")
        sys.exit(1)
except requests.exceptions.ConnectionError:
    fail("Cannot connect to Ollama. Is it running?")
    info("Start it with:  ollama serve")
    sys.exit(1)
except Exception as e:
    fail(f"Unexpected error: {e}")
    sys.exit(1)


# ── Test 2: Which models are installed? ───────────────────────
step("TEST 2 — Installed models")
models_data = r.json().get("models", [])
model_names = [m["name"] for m in models_data]

if not model_names:
    fail("No models installed at all.")
    info("Install a vision model:  ollama pull llama3.2-vision")
    sys.exit(1)

for name in model_names:
    size_gb = models_data[[m["name"] for m in models_data].index(name)].get("size", 0) / 1e9
    info(f"{name}  ({size_gb:.1f} GB)")

vision_keywords = ["vision", "llava", "bakllava", "moondream"]
vision_models = [n for n in model_names if any(k in n.lower() for k in vision_keywords)]

if vision_models:
    ok(f"Vision models found: {vision_models}")
else:
    fail("No vision models installed!")
    info("Install one:  ollama pull llama3.2-vision  (or ollama pull moondream for a faster option)")
    sys.exit(1)


# ── Parse args ────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--model", default=vision_models[0],
                    help=f"Model to test (default: {vision_models[0]})")
args = parser.parse_args()
MODEL = args.model

if MODEL not in model_names:
    fail(f"Model '{MODEL}' is not installed. Available: {model_names}")
    sys.exit(1)

info(f"Using model: {MODEL}")


# ── Test 3: Text-only response (no image) ─────────────────────
step("TEST 3 — Text-only generation (no image, should be fast)")
payload_text = {
    "model": MODEL,
    "prompt": "Reply with the single word: HELLO",
    "stream": False,
    "keep_alive": -1,
    "options": {"num_predict": 5},
}
t0 = time.time()
try:
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload_text, timeout=120)
    elapsed = time.time() - t0
    if resp.status_code == 200:
        reply = resp.json().get("response", "").strip()
        ok(f"Got response in {elapsed:.1f}s:  '{reply}'")
    else:
        fail(f"HTTP {resp.status_code} after {elapsed:.1f}s: {resp.text[:200]}")
        sys.exit(1)
except requests.exceptions.Timeout:
    fail(f"Text prompt timed out after {time.time()-t0:.0f}s — model may be severely under-resourced")
    sys.exit(1)


# ── Test 4: Tiny image (1×1 white pixel) ──────────────────────
step("TEST 4 — Tiny image (1×1 px) — tests vision pipeline")
pixel = np.ones((1, 1, 3), dtype=np.uint8) * 255
try:
    import cv2
    _, buf = cv2.imencode(".jpg", pixel, [cv2.IMWRITE_JPEG_QUALITY, 90])
    img_b64 = base64.b64encode(buf.tobytes()).decode()
    ok(f"Encoded 1×1 JPEG: {len(img_b64)} bytes")
except Exception as e:
    fail(f"Image encoding failed: {e}")
    sys.exit(1)

payload_img = {
    "model": MODEL,
    "prompt": "Describe what you see in one word.",
    "images": [img_b64],
    "stream": False,
    "keep_alive": -1,
    "options": {"num_predict": 10},
}
t0 = time.time()
try:
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload_img, timeout=300)
    elapsed = time.time() - t0
    if resp.status_code == 200:
        reply = resp.json().get("response", "").strip()
        ok(f"Vision response in {elapsed:.1f}s:  '{reply}'")
    else:
        fail(f"HTTP {resp.status_code} after {elapsed:.1f}s: {resp.text[:300]}")
except requests.exceptions.Timeout:
    fail(f"Vision timed out after {time.time()-t0:.0f}s")
    info("Possible causes:")
    info("  • Model is running on CPU — no GPU acceleration (very slow for vision)")
    info("  • Not enough RAM — model is swapping to disk")
    info("  • Try a lighter model:  ollama pull moondream")
    info("Check GPU usage with:  sudo powermetrics --samplers gpu_power -n 1")
    info("Check memory:          vm_stat | head -5")
    sys.exit(1)


# ── Test 5: Real-size business card image ─────────────────────
step("TEST 5 — Business-card sized image (600×400 px)")
card = np.ones((400, 600, 3), dtype=np.uint8) * 245
try:
    import cv2
    cv2.putText(card, "John Doe", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (0,0,0), 3)
    cv2.putText(card, "john@example.com", (50, 250), cv2.FONT_HERSHEY_SIMPLEX, 1, (60,60,60), 2)
    cv2.putText(card, "+1 555 123-4567", (50, 330), cv2.FONT_HERSHEY_SIMPLEX, 1, (60,60,60), 2)

    _, buf = cv2.imencode(".jpg", card, [cv2.IMWRITE_JPEG_QUALITY, 85])
    img_b64 = base64.b64encode(buf.tobytes()).decode()
    ok(f"Encoded 600×400 JPEG: {len(img_b64)} bytes ({len(img_b64)//1024} KB)")
except Exception as e:
    fail(f"Card image encoding failed: {e}")
    sys.exit(1)

payload_card = {
    "model": MODEL,
    "prompt": (
        "Extract contact info from this business card. "
        "Return ONLY valid JSON with fields: firstName, lastName, email, phone. "
        "Start with { and end with }."
    ),
    "images": [img_b64],
    "stream": False,
    "keep_alive": -1,
    "options": {"num_predict": 150, "temperature": 0},
}
t0 = time.time()
try:
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload_card, timeout=300)
    elapsed = time.time() - t0
    if resp.status_code == 200:
        reply = resp.json().get("response", "").strip()
        ok(f"Card response in {elapsed:.1f}s")
        info(f"Raw output: {reply[:300]}")
        if "{" in reply and "}" in reply:
            import json
            try:
                start, end = reply.index("{"), reply.rindex("}") + 1
                parsed = json.loads(reply[start:end])
                ok(f"Valid JSON extracted: {parsed}")
            except Exception:
                info("JSON parse failed — but model responded")
    else:
        fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
except requests.exceptions.Timeout:
    fail(f"Card extraction timed out after {time.time()-t0:.0f}s")
    info("The model is too slow for this hardware configuration.")
    info("Options:")
    info("  1. Use a lighter model:  ollama pull moondream")
    info("  2. Enable GPU:  check https://ollama.ai/docs — Mac M-series needs Metal")
    info("  3. Use a cloud provider (set ANTHROPIC_API_KEY or OPENAI_API_KEY)")


# ── Summary ───────────────────────────────────────────────────
step("SUMMARY")
ok("Ollama is running and vision model is responding.")
info(f"Model tested: {MODEL}")
info("If card extraction was slow (>30s), consider:")
info("  • ollama pull moondream   (much lighter, ~1.7GB)")
info("  • Check Metal/GPU is active on Mac:  ollama ps")
info("  • Use cloud fallback:  export ANTHROPIC_API_KEY=sk-ant-...")
print()
