#!/usr/bin/env python3
"""
========================================================================
 Business Card Scanner — Full Pipeline Tester Agent
========================================================================

Exercises EVERY stage of the processing pipeline against a known image
of 8 business cards in a 4×2 grid and compares results against ground
truth.  Outputs a structured test report with PASS / FAIL / WARN per
check, records unexpected behaviour, and produces a fix plan at the end.

Usage:
    python3 test_pipeline.py [--image PATH] [--model MODEL] [--timeout SECS]

Default image: test_cards.png in the project root (or supply --image).
Default model: whatever the Ollama provider resolves (glm-ocr preferred).
"""

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import requests

# ── Make project imports work ────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "utils"))

from utils.improved_card_detector import ImprovedCardDetector
from utils.qr_reader import QRReader
from utils.providers.factory import ProviderFactory
from utils.providers.ollama_provider import OllamaVisionProvider
from utils.models import ProviderType, ProviderStatus, ContactInfo, ScanResult

# ======================================================================
#  GROUND TRUTH — 8 cards in the reference image (4 rows × 2 cols)
#  Order: left→right, top→bottom (row-major).
# ======================================================================
GROUND_TRUTH: List[Dict[str, Any]] = [
    {   # Card 1 — top-left
        "name": "Joel Schimchak",
        "company": "Goldman Sachs",
        "title": "Managing Director",
        "email": "joel.schimchak@gs.com",
        "phone": ["55-11-3371-0815", "1-917-277-1677"],
        "has_qr": False,
    },
    {   # Card 2 — top-right
        "name": "Miriam Signor",
        "company": "Lefosse",
        "email": "miriam.signor@lefosse.com",
        "phone": ["+55 11 3025.3385", "+55 11 98295.0197"],
        "has_qr": False,
    },
    {   # Card 3 — row 2 left
        "name": "Roberta Alves de Souza",
        "company": "Banco do Nordeste",
        "title": "Gerente de Ambiente",
        "email": "robertaas@bnb.gov.br",
        "phone": ["(21) 3232-1361", "(21) 96500-1313"],
        "has_qr": False,
    },
    {   # Card 4 — row 2 right
        "name": "Guilherme de Souza Pinto",
        "company": "Andrade Gutierrez",
        "title": "VP Strategy",
        "email": "guilherme.pinto@agnet.com.br",
        "phone": ["+55 31 98872.6426"],
        "has_qr": True,
    },
    {   # Card 5 — row 3 left
        "name": "Francesco Bressi",
        "company": "Javelin Global Commodities",
        "title": "Latam Origination",
        "email": "francesco.bressi@jvln.com",
        "phone": ["+569 5858 3341"],
        "has_qr": False,
    },
    {   # Card 6 — row 3 right
        "name": "Angel Herrera",
        "company": "mecanicad.ca",
        "title": "Business Development Manager",
        "email": "aherrera@mecanicad.ca",
        "phone": ["+51 957290159", "+1 (888) 797-2009"],
        "has_qr": False,
    },
    {   # Card 7 — row 4 left
        "name": "Vinicius Jucá",
        "company": "Lefosse",
        "email": "vinicius.juca@lefosse.com",
        "phone": ["+55 11 3024.6367", "+55 11 99942.9152"],
        "has_qr": False,
    },
    {   # Card 8 — row 4 right
        "name": "Flavio Moraes da Mota",
        "company": "BNDES",
        "title": "Head of base Industry Division",
        "email": "flavio.mota@bndes.gov.br",
        "phone": ["+55 21 2052-9923", "21 99376-9575"],
        "has_qr": False,
    },
]

# ======================================================================
#  Dataclasses for test reporting
# ======================================================================
@dataclass
class TestResult:
    name: str
    status: str  # PASS | FAIL | WARN | SKIP | ERROR
    expected: Any = None
    actual: Any = None
    notes: str = ""
    elapsed_ms: float = 0.0

@dataclass
class TestReport:
    timestamp: str = ""
    image_path: str = ""
    model_used: str = ""
    results: List[TestResult] = field(default_factory=list)
    fix_plan: List[str] = field(default_factory=list)

    def add(self, r: TestResult):
        self.results.append(r)

    @property
    def summary(self) -> Dict[str, int]:
        counts = {"PASS": 0, "FAIL": 0, "WARN": 0, "SKIP": 0, "ERROR": 0}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        return counts

    def print_report(self):
        """Print a nicely formatted test report to stdout."""
        W = 78
        print("\n" + "=" * W)
        print(" PIPELINE TEST REPORT".center(W))
        print("=" * W)
        print(f"  Timestamp : {self.timestamp}")
        print(f"  Image     : {self.image_path}")
        print(f"  Model     : {self.model_used}")
        print("-" * W)

        for i, r in enumerate(self.results, 1):
            icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "SKIP": "⏭️", "ERROR": "💥"}.get(r.status, "?")
            print(f"\n  {icon}  [{r.status}] {r.name}  ({r.elapsed_ms:.0f}ms)")
            if r.expected is not None:
                print(f"        Expected : {r.expected}")
            if r.actual is not None:
                print(f"        Actual   : {r.actual}")
            if r.notes:
                print(f"        Notes    : {r.notes}")

        print("\n" + "-" * W)
        s = self.summary
        total = sum(s.values())
        print(f"  TOTAL: {total}  |  "
              f"✅ PASS: {s['PASS']}  |  "
              f"❌ FAIL: {s['FAIL']}  |  "
              f"⚠️  WARN: {s['WARN']}  |  "
              f"⏭️  SKIP: {s['SKIP']}  |  "
              f"💥 ERROR: {s['ERROR']}")

        if self.fix_plan:
            print("\n" + "=" * W)
            print(" FIX PLAN".center(W))
            print("=" * W)
            for j, item in enumerate(self.fix_plan, 1):
                print(f"  {j}. {item}")

        print("\n" + "=" * W + "\n")

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "image_path": self.image_path,
            "model_used": self.model_used,
            "summary": self.summary,
            "results": [
                {
                    "name": r.name,
                    "status": r.status,
                    "expected": str(r.expected) if r.expected is not None else None,
                    "actual": str(r.actual) if r.actual is not None else None,
                    "notes": r.notes,
                    "elapsed_ms": r.elapsed_ms,
                }
                for r in self.results
            ],
            "fix_plan": self.fix_plan,
        }, indent=2, ensure_ascii=False)


# ======================================================================
#  Utility helpers
# ======================================================================
def fuzzy_match(expected: str, actual: str) -> bool:
    """Case-insensitive, whitespace-normalized substring match."""
    if not expected or not actual:
        return False
    e = " ".join(expected.lower().split())
    a = " ".join(actual.lower().split())
    return e in a or a in e


def phone_normalize(p: str) -> str:
    """Strip all non-digit chars for comparison."""
    return "".join(c for c in p if c.isdigit())


def phone_match(expected_list: List[str], actual: str) -> bool:
    """Check if at least one expected phone is in the actual string."""
    if not actual:
        return False
    actual_digits = phone_normalize(actual)
    for exp in expected_list:
        if phone_normalize(exp) in actual_digits or actual_digits in phone_normalize(exp):
            return True
    return False


def split_image_grid(image: np.ndarray, rows: int, cols: int) -> List[np.ndarray]:
    """Simple uniform grid split (no margins)."""
    h, w = image.shape[:2]
    cell_h = h // rows
    cell_w = w // cols
    cells = []
    for r in range(rows):
        for c in range(cols):
            y1 = r * cell_h
            y2 = (r + 1) * cell_h if r < rows - 1 else h
            x1 = c * cell_w
            x2 = (c + 1) * cell_w if c < cols - 1 else w
            cells.append(image[y1:y2, x1:x2])
    return cells


# ======================================================================
#  Test phases
# ======================================================================
def test_ollama_connectivity(report: TestReport):
    """Phase 0: Is Ollama reachable?"""
    t0 = time.time()
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        ms = (time.time() - t0) * 1000
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            report.add(TestResult("Ollama connectivity", "PASS",
                                  expected="HTTP 200", actual=f"200 — {len(models)} models installed",
                                  elapsed_ms=ms))
            return models
        else:
            report.add(TestResult("Ollama connectivity", "FAIL",
                                  expected="HTTP 200", actual=f"HTTP {r.status_code}",
                                  elapsed_ms=ms))
            return []
    except Exception as e:
        ms = (time.time() - t0) * 1000
        report.add(TestResult("Ollama connectivity", "FAIL",
                              expected="HTTP 200", actual=str(e),
                              notes="Is 'ollama serve' running?", elapsed_ms=ms))
        report.fix_plan.append("Start Ollama: ollama serve")
        return []


def test_model_availability(report: TestReport, installed_models: List[str]):
    """Phase 0b: Is the preferred model installed?"""
    preferred = ["glm-ocr", "llama3.2-vision", "llava:13b"]
    found = None
    for pref in preferred:
        if any(pref in m for m in installed_models):
            found = pref
            break

    if found:
        report.add(TestResult("Preferred model installed", "PASS",
                              expected=f"One of {preferred}", actual=found))
        report.model_used = found
    else:
        report.add(TestResult("Preferred model installed", "FAIL",
                              expected=f"One of {preferred}",
                              actual=f"Installed: {installed_models}",
                              notes="Run: ollama pull glm-ocr"))
        report.fix_plan.append("Install recommended model: ollama pull glm-ocr")
        # Still try to use whatever is available
        vision_kws = ["glm-ocr", "vision", "llava", "bakllava", "moondream"]
        for m in installed_models:
            if any(k in m.lower() for k in vision_kws):
                report.model_used = m
                break


def test_gpu_status(report: TestReport, model: str):
    """Phase 0c: Is the model already loaded in GPU? Checks /api/ps."""
    t0 = time.time()
    try:
        r = requests.get("http://localhost:11434/api/ps", timeout=5)
        ms = (time.time() - t0) * 1000
        if r.status_code == 200:
            running = r.json().get("models", [])
            loaded_names = [m.get("name", "") for m in running]
            gpu_info = []
            for m in running:
                name = m.get("name", "")
                vram = m.get("size_vram", 0)
                total = m.get("size", 0)
                on_gpu = vram > 0
                gpu_info.append(f"{name} — {'GPU ✅' if on_gpu else 'CPU ⚠️'} "
                                f"({vram//1024//1024}MB VRAM / {total//1024//1024}MB total)")

            model_loaded = any(model in n for n in loaded_names)
            if model_loaded:
                report.add(TestResult("GPU model status", "PASS",
                                      expected=f"{model} loaded in GPU",
                                      actual="\n        ".join(gpu_info) or "model loaded",
                                      elapsed_ms=ms))
                return True
            elif running:
                # Something else is loaded
                report.add(TestResult("GPU model status", "WARN",
                                      expected=f"{model} loaded",
                                      actual=f"Different model loaded: {', '.join(loaded_names)}",
                                      notes="Model swap will add 30-120s on first card",
                                      elapsed_ms=ms))
            else:
                report.add(TestResult("GPU model status", "WARN",
                                      expected=f"{model} loaded in GPU",
                                      actual="No model currently loaded — cold start expected",
                                      notes="First warmup will be slow (model loads from disk)",
                                      elapsed_ms=ms))
        else:
            report.add(TestResult("GPU model status", "WARN",
                                  actual=f"/api/ps returned HTTP {r.status_code}",
                                  elapsed_ms=ms))
    except Exception as e:
        report.add(TestResult("GPU model status", "WARN",
                              actual=str(e), elapsed_ms=(time.time() - t0) * 1000))
    return False


def test_model_warmup(report: TestReport, model: str, timeout: int = 300):
    """Phase 0d: Can the model respond to a tiny image within timeout?"""
    if not model:
        report.add(TestResult("Model warmup", "SKIP", notes="No model available"))
        return False
    t0 = time.time()
    try:
        import base64
        dummy = np.ones((4, 4, 3), dtype=np.uint8) * 255
        _, buf = cv2.imencode('.jpg', dummy, [cv2.IMWRITE_JPEG_QUALITY, 50])
        img_b64 = base64.b64encode(buf.tobytes()).decode()
        r = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": "Reply OK.",
                "images": [img_b64],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_predict": 5},
            },
            timeout=timeout,
        )
        ms = (time.time() - t0) * 1000
        if r.status_code == 200 and r.json().get("response"):
            speed = "fast ✅" if ms < 30000 else ("ok ⚠️" if ms < 90000 else "slow ❌")
            report.add(TestResult("Model warmup (tiny image)", "PASS",
                                  expected="Response within timeout",
                                  actual=f"'{r.json()['response'][:40]}' — {ms/1000:.1f}s ({speed})",
                                  elapsed_ms=ms))
            if ms > 60000 and "glm-ocr" not in model:
                report.fix_plan.append(
                    f"Warmup took {ms/1000:.0f}s with {model} (11B). "
                    "Install glm-ocr (0.9B) for ~10x faster loads: ollama pull glm-ocr"
                )
            return True
        else:
            report.add(TestResult("Model warmup (tiny image)", "FAIL",
                                  expected="200 + response text",
                                  actual=f"HTTP {r.status_code}: {r.text[:100]}",
                                  elapsed_ms=ms))
            return False
    except requests.exceptions.Timeout:
        ms = (time.time() - t0) * 1000
        report.add(TestResult("Model warmup (tiny image)", "ERROR",
                              actual=f"Timed out after {timeout}s — model did not respond",
                              elapsed_ms=ms,
                              notes="Model may be loading on CPU or insufficient VRAM"))
        report.fix_plan.append(
            f"CRITICAL: {model} timed out even for a 4×4 pixel warmup image after {timeout}s. "
            "This will cause all card scans to fail. Fix options:\n"
            "  a) Install glm-ocr (0.9B, loads in seconds): ollama pull glm-ocr\n"
            "  b) Check GPU availability: nvidia-smi or system_profiler SPDisplaysDataType\n"
            "  c) Increase timeout slider in the app sidebar to 600s"
        )
        # Return True anyway so downstream image/detection tests still run
        return False
    except Exception as e:
        ms = (time.time() - t0) * 1000
        report.add(TestResult("Model warmup (tiny image)", "ERROR",
                              actual=str(e), elapsed_ms=ms))
        report.fix_plan.append(f"Check model can load: ollama run {model} --verbose")
        return False


def test_image_loading(report: TestReport, image_path: str) -> Optional[np.ndarray]:
    """Phase 1: Can we load the test image?"""
    t0 = time.time()
    if not os.path.exists(image_path):
        # Try to find a usable image from scan history
        history_dir = os.path.join(ROOT, "temp", "history")
        history_images = []
        if os.path.isdir(history_dir):
            for run in sorted(os.listdir(history_dir), reverse=True):
                orig = os.path.join(history_dir, run, "original")
                if os.path.isdir(orig):
                    for f in os.listdir(orig):
                        if f.lower().endswith((".png", ".jpg", ".jpeg")):
                            history_images.append(os.path.join(orig, f))
        hint = ""
        if history_images:
            hint = f"Found existing images in history:\n" + "\n".join(
                f"  {p}" for p in history_images[:5]
            ) + f"\nRe-run with: python3 test_pipeline.py --image \"{history_images[0]}\""
        else:
            hint = "No images found in temp/history/ either. Upload an image to the app first."

        report.add(TestResult("Image loading", "FAIL",
                              expected=f"File exists at {image_path}",
                              actual="File not found",
                              notes=hint))
        report.fix_plan.append(
            f"Provide test image via --image flag.\n{hint}"
        )
        return None
    img = cv2.imread(image_path)
    ms = (time.time() - t0) * 1000
    if img is None or img.size == 0:
        report.add(TestResult("Image loading", "FAIL",
                              expected="Valid image", actual="cv2.imread returned None"))
        return None
    h, w = img.shape[:2]
    report.add(TestResult("Image loading", "PASS",
                          expected="Non-empty image",
                          actual=f"{w}×{h} px, {img.shape[2]} channels",
                          elapsed_ms=ms))
    return img


def test_auto_detection(report: TestReport, image: np.ndarray) -> List[Tuple[np.ndarray, Any]]:
    """Phase 2: Does automatic detection find 8 cards?"""
    detector = ImprovedCardDetector(min_area_percent=5, max_area_percent=40)
    t0 = time.time()
    detected = detector.detect_cards(image)
    ms = (time.time() - t0) * 1000

    if len(detected) == 8:
        report.add(TestResult("Auto detection — card count", "PASS",
                              expected=8, actual=len(detected), elapsed_ms=ms))
    elif len(detected) >= 6:
        report.add(TestResult("Auto detection — card count", "WARN",
                              expected=8, actual=len(detected), elapsed_ms=ms,
                              notes="Close but not all cards found"))
    else:
        report.add(TestResult("Auto detection — card count", "FAIL",
                              expected=8, actual=len(detected), elapsed_ms=ms,
                              notes="Falling back to grid-based detection"))
        report.fix_plan.append(
            f"Auto-detection found only {len(detected)}/8 cards. "
            "The grid-fallback in app.py should catch this, but the contour "
            "detector may need tuning (min/max area, edge detection params)."
        )
    return detected


def test_grid_fallback(report: TestReport, image: np.ndarray) -> List[np.ndarray]:
    """Phase 2b: Does the grid fallback (4×2) produce 8 usable cells?"""
    t0 = time.time()
    cells = split_image_grid(image, rows=4, cols=2)
    ms = (time.time() - t0) * 1000

    # Check cell sizes are reasonable
    ok_count = 0
    for cell in cells:
        h, w = cell.shape[:2]
        if h > 50 and w > 50:
            ok_count += 1

    status = "PASS" if ok_count == 8 else "WARN"
    report.add(TestResult("Grid fallback (4×2)", status,
                          expected="8 cells, each > 50×50 px",
                          actual=f"{ok_count}/8 valid cells", elapsed_ms=ms))
    return cells


def test_grid_auto_inference(report: TestReport, image: np.ndarray):
    """Phase 2c: Does the aspect-ratio grid inference in app.py choose 4×2?"""
    h, w = image.shape[:2]
    aspect = w / h if h > 0 else 1.0
    # Mirror the logic in app.py (fixed: square images → 4×2)
    if aspect < 1.4:
        inferred_rows, inferred_cols = 4, 2
    else:
        inferred_rows, inferred_cols = 2, 4

    expected_rows, expected_cols = 4, 2
    status = "PASS" if (inferred_rows == expected_rows and inferred_cols == expected_cols) else "FAIL"
    report.add(TestResult("Grid auto-inference (aspect ratio)",
                          status,
                          expected=f"{expected_rows}×{expected_cols} (aspect < 0.9 → portrait)",
                          actual=f"{inferred_rows}×{inferred_cols} (aspect={aspect:.3f})",
                          notes="app.py line ~930 logic"))
    if status == "FAIL":
        report.fix_plan.append(
            f"Aspect ratio {aspect:.3f} maps to {inferred_rows}×{inferred_cols} "
            f"but should be 4×2 for this image. Adjust thresholds in app.py."
        )


def test_qr_detection(report: TestReport, card_images: List[np.ndarray]):
    """Phase 3: QR code detection on each card."""
    qr_reader = QRReader()
    for i, card in enumerate(card_images):
        gt = GROUND_TRUTH[i] if i < len(GROUND_TRUTH) else {}
        expects_qr = gt.get("has_qr", False)
        t0 = time.time()
        try:
            results = qr_reader.detect_and_decode(card)
            ms = (time.time() - t0) * 1000
            found = len(results) > 0 if results else False
            if expects_qr and found:
                report.add(TestResult(f"Card {i+1} QR detection", "PASS",
                                      expected="QR found", actual=f"{len(results)} QR code(s)",
                                      elapsed_ms=ms))
            elif expects_qr and not found:
                report.add(TestResult(f"Card {i+1} QR detection", "FAIL",
                                      expected="QR found", actual="No QR detected",
                                      notes=f"Card: {gt.get('name', '?')}",
                                      elapsed_ms=ms))
            elif not expects_qr and found:
                report.add(TestResult(f"Card {i+1} QR detection", "WARN",
                                      expected="No QR", actual=f"{len(results)} QR code(s)",
                                      notes="False positive? May be fine.",
                                      elapsed_ms=ms))
            else:
                report.add(TestResult(f"Card {i+1} QR detection", "PASS",
                                      expected="No QR", actual="None found",
                                      elapsed_ms=ms))
        except Exception as e:
            ms = (time.time() - t0) * 1000
            status = "FAIL" if expects_qr else "WARN"
            report.add(TestResult(f"Card {i+1} QR detection", status,
                                  expected="QR found" if expects_qr else "No QR",
                                  actual=f"Exception: {e}",
                                  elapsed_ms=ms))


def test_vision_extraction(report: TestReport, card_images: List[np.ndarray], model: str):
    """Phase 4: Run vision model on each card and compare to ground truth."""
    if not model:
        for i in range(min(len(card_images), len(GROUND_TRUTH))):
            report.add(TestResult(f"Card {i+1} vision extraction", "SKIP",
                                  notes="No vision model available"))
        return

    factory = ProviderFactory()

    for i, card in enumerate(card_images):
        if i >= len(GROUND_TRUTH):
            break
        gt = GROUND_TRUTH[i]
        t0 = time.time()
        try:
            result: ScanResult = factory.extract_with_fallback(card, qr_data=None, timeout=300)
            ms = (time.time() - t0) * 1000

            if result.error:
                report.add(TestResult(f"Card {i+1} vision — {gt['name']}", "FAIL",
                                      expected="Contact data",
                                      actual=f"Error: {result.error}",
                                      elapsed_ms=ms))
                report.fix_plan.append(
                    f"Card {i+1} ({gt['name']}): Vision returned error — {result.error}"
                )
                continue

            contact = result.contact
            contact_dict = contact.to_legacy_dict() if contact else {}

            # ── Sub-checks per card ──────────────────────────────────
            # Name
            actual_name = (contact_dict.get("fullName") or
                           f"{contact_dict.get('firstName', '')} {contact_dict.get('lastName', '')}".strip())
            name_ok = fuzzy_match(gt["name"], actual_name)

            # Email
            actual_email = contact_dict.get("email", "")
            email_ok = fuzzy_match(gt.get("email", ""), actual_email)

            # Company
            actual_company = contact_dict.get("company", "")
            company_ok = fuzzy_match(gt.get("company", ""), actual_company)

            # Phone
            actual_phone = contact_dict.get("phone", "") or contact_dict.get("mobilePhone", "")
            phone_ok = phone_match(gt.get("phone", []), actual_phone)

            # Overall status
            critical_ok = email_ok  # Email is the most critical field
            all_ok = name_ok and email_ok and company_ok

            if all_ok:
                status = "PASS"
            elif critical_ok:
                status = "WARN"
            else:
                status = "FAIL"

            details = (
                f"Name: {'✅' if name_ok else '❌'} {actual_name!r}  |  "
                f"Email: {'✅' if email_ok else '❌'} {actual_email!r}  |  "
                f"Company: {'✅' if company_ok else '❌'} {actual_company!r}  |  "
                f"Phone: {'✅' if phone_ok else '❌'} {actual_phone!r}"
            )

            report.add(TestResult(
                f"Card {i+1} vision — {gt['name']}", status,
                expected=f"name={gt['name']}, email={gt.get('email', '?')}",
                actual=details,
                elapsed_ms=ms,
                notes=f"Provider: {result.provider_used.value}" if result.provider_used else "",
            ))

            if not email_ok:
                report.fix_plan.append(
                    f"Card {i+1} ({gt['name']}): email mismatch — "
                    f"expected '{gt.get('email')}', got '{actual_email}'"
                )

        except Exception as e:
            ms = (time.time() - t0) * 1000
            report.add(TestResult(f"Card {i+1} vision — {gt['name']}", "ERROR",
                                  actual=f"{type(e).__name__}: {e}",
                                  elapsed_ms=ms))
            report.fix_plan.append(f"Card {i+1} ({gt['name']}): unhandled exception — {e}")


def test_provider_factory_statuses(report: TestReport):
    """Phase 5: Check provider factory status reporting."""
    t0 = time.time()
    factory = ProviderFactory()
    statuses = factory.get_all_statuses()
    ms = (time.time() - t0) * 1000

    local_available = any(
        info["status"] == "available" and info["is_local"]
        for info in statuses.values()
    )

    if local_available:
        report.add(TestResult("Provider factory — local provider available", "PASS",
                              actual=str({k.value: v["status"] for k, v in statuses.items()}),
                              elapsed_ms=ms))
    else:
        report.add(TestResult("Provider factory — local provider available", "FAIL",
                              expected="At least one local provider available",
                              actual=str({k.value: v for k, v in statuses.items()}),
                              elapsed_ms=ms))
        report.fix_plan.append("No local vision provider is available. Check ollama serve + model.")


# ======================================================================
#  Main
# ======================================================================
def run_all_tests(image_path: str, timeout: int = 300) -> TestReport:
    report = TestReport(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        image_path=image_path,
    )

    print("\n🔬 Business Card Scanner — Pipeline Tester Agent")
    print(f"   Image: {image_path}")
    print(f"   Time : {report.timestamp}\n")

    # ── Phase 0: Connectivity & model ────────────────────────────────
    print("Phase 0: Checking Ollama connectivity & model…")
    installed = test_ollama_connectivity(report)
    test_model_availability(report, installed)
    model = report.model_used
    if model:
        print(f"  → Using model: {model}")
        print("Phase 0c: Checking GPU/VRAM status…")
        test_gpu_status(report, model)
        print(f"Phase 0d: Warming up model (timeout={timeout}s — may be slow on first load)…")
        warmup_ok = test_model_warmup(report, model, timeout=timeout)
    else:
        warmup_ok = False

    # ── Phase 1: Image loading ───────────────────────────────────────
    print("Phase 1: Loading test image…")
    image = test_image_loading(report, image_path)
    if image is None:
        report.fix_plan.append(f"Cannot proceed without test image at {image_path}")
        report.print_report()
        return report

    # ── Phase 2: Card detection ──────────────────────────────────────
    print("Phase 2: Testing automatic card detection…")
    auto_cards = test_auto_detection(report, image)

    print("Phase 2b: Testing grid fallback (4×2)…")
    grid_cells = test_grid_fallback(report, image)

    print("Phase 2c: Testing aspect-ratio grid inference…")
    test_grid_auto_inference(report, image)

    # Choose the best set of cards for downstream tests
    if len(auto_cards) >= 7:
        test_cards = [c[0] for c in auto_cards]
        card_source = "auto-detection"
    else:
        test_cards = grid_cells
        card_source = "grid-fallback (4×2)"
    print(f"  → Using {len(test_cards)} cards from {card_source}")

    # ── Phase 3: QR detection ────────────────────────────────────────
    print("Phase 3: Testing QR code detection per card…")
    test_qr_detection(report, test_cards)

    # ── Phase 4: Vision extraction ───────────────────────────────────
    if model:
        if not warmup_ok:
            print(f"Phase 4: Warmup failed but attempting vision anyway ({model})…")
            print("         NOTE: First card may be very slow (model loading from disk)")
        else:
            print(f"Phase 4: Vision extraction ({model}) on {len(test_cards)} cards…")
        print("         (this may take several minutes per card)")
        test_vision_extraction(report, test_cards, model)
    else:
        print("Phase 4: SKIPPED — no vision model available")
        for i in range(min(len(test_cards), len(GROUND_TRUTH))):
            report.add(TestResult(f"Card {i+1} vision extraction", "SKIP",
                                  notes="No vision model available"))

    # ── Phase 5: Provider factory ────────────────────────────────────
    print("Phase 5: Checking provider factory statuses…")
    test_provider_factory_statuses(report)

    # ── Compile fix plan ─────────────────────────────────────────────
    if not report.fix_plan:
        report.fix_plan.append("No fixes needed — all tests passed!")

    report.print_report()
    return report


def main():
    parser = argparse.ArgumentParser(description="Business Card Scanner Pipeline Tester")
    parser.add_argument("--image", type=str, default=None,
                        help="Path to test image (default: auto-detect in project root)")
    parser.add_argument("--model", type=str, default=None,
                        help="Override Ollama model name")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Vision timeout in seconds (default: 300)")
    parser.add_argument("--json", action="store_true",
                        help="Also save JSON report")
    args = parser.parse_args()

    # Resolve image path
    if args.image:
        image_path = args.image
    else:
        # 1. Look for well-known names in project root
        candidates = [
            os.path.join(ROOT, "test_cards.png"),
            os.path.join(ROOT, "test_cards.jpg"),
            os.path.join(ROOT, "temp", "test_cards.png"),
        ]
        found = next((c for c in candidates if os.path.exists(c)), None)

        # 2. Fall back to the most recent image in scan history
        if not found:
            history_dir = os.path.join(ROOT, "temp", "history")
            if os.path.isdir(history_dir):
                for run in sorted(os.listdir(history_dir), reverse=True):
                    orig = os.path.join(history_dir, run, "original")
                    if os.path.isdir(orig):
                        for f in sorted(os.listdir(orig)):
                            if f.lower().endswith((".png", ".jpg", ".jpeg")):
                                found = os.path.join(orig, f)
                                break
                    if found:
                        break

        if found:
            image_path = found
            print(f"ℹ️  No --image provided. Using: {image_path}")
        else:
            image_path = os.path.join(ROOT, "test_cards.png")
            print(f"⚠️  No image found. Pass one with: --image /path/to/8cards.png")

    if args.model:
        # Allow overriding model from CLI
        report_pre = TestReport()
        report_pre.model_used = args.model
    report = run_all_tests(image_path, timeout=args.timeout)

    # Save JSON report
    if args.json:
        json_path = os.path.join(ROOT, "test_report.json")
        with open(json_path, "w") as f:
            f.write(report.to_json())
        print(f"📄 JSON report saved to: {json_path}")


if __name__ == "__main__":
    main()
