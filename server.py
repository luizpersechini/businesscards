"""
FastAPI server for Business Card Reader — modern React UI frontend.

Serves the frontend at / and exposes REST/SSE endpoints the UI calls.
All heavy lifting is delegated to the existing utils/ modules.
"""

import asyncio
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import requests as _requests
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

# ── Bootstrap sys.path so utils/ imports work ────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

from utils.card_processor import CardProcessor
from utils.contacts_repository import ContactsRepository
from utils.export_processor import ExportProcessor
from utils.history_manager import HistoryManager, history_entry_to_dict
from utils.providers.factory import ProviderFactory

# ── App & singletons ─────────────────────────────────────────────────────────
app = FastAPI(title="Business Card Reader")

_provider_factory = ProviderFactory()
_history = HistoryManager()
_contacts = ContactsRepository()
_exporter = ExportProcessor()

# Cancellation flag for the in-flight scan. Single-scan-at-a-time assumption
# (this is a desktop-style local app). Set by POST /api/scan/stop, cleared
# by _scan_generator at the start of each scan.
_scan_cancel_event = threading.Event()

FRONTEND_DIR = Path(__file__).parent / "frontend"
TEMP_DIR = Path(__file__).parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Serve static assets if we add them later
if (FRONTEND_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR / "static")), name="static")


# Thumbnail cache (in-memory, keyed by card_id)
_thumbnail_cache = {}
THUMBNAIL_DIR = os.path.join(os.path.dirname(__file__), "temp", "thumbnails")
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# PATH-TRAVERSAL GUARDS (security audit 2026-05-20)
# ═══════════════════════════════════════════════════════════
import re as _re  # noqa: E402

# run_id is generated as "%Y%m%d_%H%M%S" + "_" + 6 hex chars (history_manager).
_RUN_ID_RE = _re.compile(r"^\d{8}_\d{6}_[0-9a-f]{6}$")
# card_id is "<run_id>_<idx>" or "card_<idx>_<ts>" — alnum + underscore only.
_CARD_ID_RE = _re.compile(r"^[A-Za-z0-9_]{1,128}$")


def _safe_run_id(run_id: str) -> str:
    """Reject any run_id that isn't the exact generated format. Blocks
    path traversal (.., /, %2e) on /api/history/{run_id} routes."""
    if not _RUN_ID_RE.match(run_id or ""):
        raise HTTPException(status_code=404, detail="Run not found")
    return run_id


def _safe_thumb_path(card_id: str) -> str:
    """Validate card_id charset AND confirm the resolved path stays inside
    THUMBNAIL_DIR (defense in depth). Blocks /api/thumbnails/{card_id}
    traversal like ..%2F..%2Fcontacts_repository."""
    if not _CARD_ID_RE.match(card_id or ""):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    base = os.path.realpath(THUMBNAIL_DIR)
    candidate = os.path.realpath(os.path.join(base, f"{card_id}.jpg"))
    if candidate != base and not candidate.startswith(base + os.sep):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return candidate


# ═══════════════════════════════════════════════════════════
# UPLOAD VALIDATION (security audit 2026-05-20)
# Cap size + allow-list extensions + magic-byte sniff before any bytes
# reach cv2.imdecode / fitz.open (PyMuPDF), both of which have a history
# of memory-corruption CVEs on crafted input.
# ═══════════════════════════════════════════════════════════
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))  # 25 MB
_ALLOWED_UPLOAD_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".pdf"}
# Leading byte signatures for the simple, fixed-prefix formats. HEIC / WEBP
# are handled separately below because their ftyp/RIFF container boxes have
# variable lengths.
_MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"%PDF": "pdf",
}
# ISOBMFF ftyp "brand" codes that indicate a HEIF/HEIC family file. The first
# 4 bytes of the file are the box length (variable), bytes 4-7 are "ftyp",
# bytes 8-11 are the major brand. We accept the full HEIF / HEIC brand list
# rather than guessing specific box lengths (the previous check was too narrow
# and rejected legitimate HEIC files from newer iOS versions).
_HEIF_BRANDS = {
    b"heic",
    b"heix",
    b"hevc",
    b"hevx",
    b"heim",
    b"heis",
    b"hevm",
    b"hevs",
    b"mif1",
    b"msf1",
    b"heif",
    b"avif",
    b"avis",
}


def _validate_upload(filename: str, raw: bytes, skip_size_check: bool = False) -> Optional[str]:
    """Return None if the upload is acceptable, else an error message string.

    `skip_size_check=True` is used by the relaunch path: those files came
    from our own archive (already validated when first uploaded), so the
    MAX_UPLOAD_BYTES cap — which exists to protect the upload endpoint
    from arbitrary inbound traffic — doesn't apply.
    """
    ext = os.path.splitext((filename or "").lower())[1]
    if ext not in _ALLOWED_UPLOAD_EXTS:
        return f"Unsupported file type {ext!r} (allowed: {sorted(_ALLOWED_UPLOAD_EXTS)})"
    if len(raw) == 0:
        return "Empty file"
    if not skip_size_check and len(raw) > MAX_UPLOAD_BYTES:
        return f"File too large ({len(raw)} bytes > {MAX_UPLOAD_BYTES} limit)"

    head = raw[:32]

    # Simple fixed-prefix sniff: JPEG / PNG / PDF
    if any(head.startswith(sig) for sig in _MAGIC):
        return None
    # WEBP: RIFF<size>WEBP — RIFF at 0, WEBP at 8
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return None
    # HEIC / HEIF / AVIF: ISOBMFF — bytes 4-7 are 'ftyp', bytes 8-11 are
    # the major brand. Box length (bytes 0-3) varies by brand list, so we
    # don't constrain it.
    if head[4:8] == b"ftyp" and head[8:12] in _HEIF_BRANDS:
        return None

    return "File content does not match a supported image/PDF format"


# ═══════════════════════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════════════════════


@app.get("/api/status")
async def get_status():
    """Check Ollama availability and active model."""
    try:
        r = _requests.get("http://localhost:11434/api/tags", timeout=2)
        if r.status_code == 200:
            tags = r.json().get("models", [])
            models = [m.get("name", "") for m in tags]
            glm_ready = any("glm" in m.lower() for m in models)
            first_model = models[0].split(":")[0] if models else "unknown"
            return {
                "ollama": "ready",
                "model": "glm-ocr" if glm_ready else first_model,
                "models": models,
            }
    except Exception:
        pass
    return {"ollama": "offline", "model": "none", "models": []}


# ═══════════════════════════════════════════════════════════
# SCAN  (SSE streaming)
# ═══════════════════════════════════════════════════════════


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _load_image(raw: bytes, filename: str):
    """Return (bgr, rgb) numpy arrays from raw bytes. Handles JPG/PNG/PDF page 0."""
    if filename.lower().endswith(".pdf"):
        try:
            import fitz

            doc = fitz.open(stream=raw, filetype="pdf")
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            if pix.n == 4:
                img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)
            rgb = img_array
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            return bgr, rgb
        except ImportError:
            raise ValueError("PDF support requires PyMuPDF (pip install pymupdf)")
    else:
        # Try cv2 first (fast path for JPG/PNG); fall back to Pillow for
        # HEIC/HEIF/WEBP and anything else cv2 can't decode.
        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            try:
                # Register HEIF/HEIC opener if available (no-op if already registered)
                try:
                    from pillow_heif import register_heif_opener

                    register_heif_opener()
                except ImportError:
                    pass
                pil_img = Image.open(io.BytesIO(raw))
                # Drop alpha; convert to RGB
                if pil_img.mode != "RGB":
                    pil_img = pil_img.convert("RGB")
                rgb = np.array(pil_img)
                bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
                return bgr, rgb
            except Exception as pil_err:
                raise ValueError(f"Could not decode image: {filename} ({pil_err})")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return bgr, rgb


def _pdf_to_images(
    raw: bytes, filename: str, dpi: int = 200
) -> List[Tuple[np.ndarray, np.ndarray]]:
    """
    Convert all pages of a PDF to (bgr, rgb) numpy arrays.

    Args:
        raw: PDF file bytes
        filename: Original filename
        dpi: DPI for rendering

    Returns:
        List of (bgr, rgb) tuples for each page
    """
    if not filename.lower().endswith(".pdf"):
        raise ValueError(f"Not a PDF file: {filename}")

    try:
        import fitz
    except ImportError:
        raise ValueError("PDF support requires PyMuPDF (pip install pymupdf)")

    doc = fitz.open(stream=raw, filetype="pdf")
    pages = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        pix = page.get_pixmap(dpi=dpi)
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)

        if pix.n == 4:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGBA2RGB)

        rgb = img_array
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        pages.append((bgr, rgb))

    doc.close()
    return pages


def _deskew_to_card_cluster(bgr: np.ndarray, min_area_ratio: float = 0.25) -> np.ndarray:
    """
    For photographed images of multiple cards on a table:
    find the convex region containing all cards, then warp it to an
    axis-aligned rectangle that fills the frame. Returns the original
    image unchanged if no clear card cluster is found or the cluster
    is small / already axis-aligned.

    Strategy:
      1. Edge map (Canny) of a downsampled copy for speed
      2. Heavy dilation/close to merge per-card edges into one blob
      3. Largest external contour = card cluster
      4. minAreaRect → 4 corners → four_point_transform
    """
    from utils.improved_card_detector import ImprovedCardDetector

    h, w = bgr.shape[:2]
    # Downsample for the search (≤1000 px on long edge)
    scale = min(1.0, 1000.0 / max(h, w))
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 150)
    # Merge per-card edges into one large blob covering the whole grid
    kx = max(15, small.shape[1] // 40)
    ky = max(15, small.shape[0] // 40)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kx, ky))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    closed = cv2.dilate(closed, kernel, iterations=1)
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return bgr
    largest = max(contours, key=cv2.contourArea)
    area_ratio = cv2.contourArea(largest) / (small.shape[0] * small.shape[1])
    if area_ratio < min_area_ratio:
        return bgr  # not a confident cluster
    rect = cv2.minAreaRect(largest)
    # Skip if the cluster is already axis-aligned (no work to do)
    angle = rect[-1]
    angle_dev = min(abs(angle), abs(90 - abs(angle)))
    bbox_w, bbox_h = rect[1]
    if bbox_w < 5 or bbox_h < 5:
        return bgr
    aabb_w = max(bbox_w, bbox_h) * (1.0)  # axis-aligned bounding box would be similar
    # Compute pixel waste vs an axis-aligned bbox of the same contour
    x, y, bw, bh = cv2.boundingRect(largest)
    aabb_area = bw * bh
    rot_area = bbox_w * bbox_h
    if angle_dev < 1.5 and rot_area > 0.95 * aabb_area:
        return bgr  # negligible rotation
    box = cv2.boxPoints(rect)
    # Scale corners back up to original image coordinates
    box = box / scale
    detector = ImprovedCardDetector()
    try:
        deskewed = detector.four_point_transform(bgr, box)
    except Exception:
        return bgr
    # Sanity: deskewed must be non-trivial
    if deskewed is None or deskewed.size == 0:
        return bgr
    return deskewed


def _create_thumbnail(
    card_image: np.ndarray, max_size: Tuple[int, int] = (1400, 1400)
) -> Optional[bytes]:
    """
    Create a thumbnail from card image.

    Sized for both list-row (44 × 44) and click-to-magnify lightbox use
    (~95 vw). 1400 px on the long edge keeps the file under ~200 kB at
    JPEG q=92 while looking sharp on a Retina display when magnified.

    Args:
        card_image: Card image in RGB format (numpy array)
        max_size: Maximum (width, height) for thumbnail

    Returns:
        JPEG bytes or None if no image
    """
    if card_image is None:
        return None

    try:
        # Convert numpy array to PIL Image
        pil_img = Image.fromarray(card_image)

        # Create thumbnail (preserves aspect ratio). Only downsample if
        # the source is bigger than the cap — never upscale.
        if max(pil_img.size) > max(max_size):
            pil_img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Convert to JPEG bytes. Quality 92 = visually lossless for cards
        # while still <200 kB at 1400 px on the long edge.
        img_byte_arr = io.BytesIO()
        pil_img.save(img_byte_arr, format="JPEG", quality=92, optimize=True)
        return img_byte_arr.getvalue()
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None


def _contact_data_to_frontend(
    card: dict, source_file: str, idx: int, run_id: Optional[str] = None
) -> dict:
    """Map CardProcessor output dict to the shape the React frontend expects."""
    cd = card.get("contact_data") or {}

    # Name the model that ACTUALLY ran, not a hardcoded "GLM-OCR" — the badge
    # used to lie whenever any other model was selected (or substituted).
    # Popped so it never reaches the saved contact.
    model_used = cd.pop("_model_used", None) if isinstance(cd, dict) else None
    model_label = model_used or "Vision"

    via_qr = card.get("via_qr")
    if via_qr is True:
        via = "QR Code"
    elif via_qr == "hybrid":
        via = f"QR + {model_label}"
    else:
        via = model_label
    # Real wall-clock seconds, set by CardProcessor.process_single_card.
    # (Was a hardcoded 1.0 s placeholder — every card reported "1.0s".)
    processing_time = card.get("processing_time", 0.0)

    # Create thumbnail if card image exists
    thumbnail = None
    card_image = card.get("card_image")
    has_thumbnail = False
    card_id = None

    if card_image is not None:
        thumbnail = _create_thumbnail(card_image)
        if thumbnail is not None:
            # Use pre-generated card_id if available, otherwise generate one
            card_id = card.get("_card_id") or (
                f"{run_id}_{idx}" if run_id else f"card_{idx}_{int(time.time())}"
            )
            _thumbnail_cache[card_id] = thumbnail
            # Persist thumbnail to disk for survival across restarts
            try:
                thumb_path = os.path.join(THUMBNAIL_DIR, f"{card_id}.jpg")
                with open(thumb_path, "wb") as f:
                    f.write(thumbnail)
            except Exception as e:
                print(f"Error saving thumbnail to disk: {e}")
            has_thumbnail = True

    # Lift language hint out of contact_data (set by the post-correction
    # router) so the frontend can show it on the card without it polluting
    # the saved contact dict.
    detected_lang = cd.pop("_detected_lang", None) if isinstance(cd, dict) else None

    # Lift the pending QR URL (set by card_processor when the card's QR code
    # encodes a link rather than inline fields). The frontend shows a "Fetch
    # contact data" button for it; nothing is fetched until the user clicks.
    qr_url = cd.pop("_qr_url", None) if isinstance(cd, dict) else None

    return {
        "id": idx + 1,
        "cardId": card_id,
        "filename": card.get("filename", f"card_{idx + 1}.vcf"),
        "locked": bool(card.get("_locked", False)),
        "repoId": card.get("_repo_id", ""),
        "repoStatus": card.get("_repo_status", ""),  # added|updated|merged|conflict
        "additions": card.get("_additions") or {},
        "conflicts": card.get("_conflicts") or [],
        "detectedLang": detected_lang,
        "qrUrl": qr_url,
        "source": source_file,
        "via": via,
        "time": round(processing_time, 1),
        "thumbnail": has_thumbnail,
        "contact": {
            "fullName": (
                cd.get("fullName")
                or cd.get("full_name")
                or " ".join(
                    p for p in [cd.get("firstName", ""), cd.get("lastName", "")] if p
                ).strip()
                or " ".join(
                    p for p in [cd.get("first_name", ""), cd.get("last_name", "")] if p
                ).strip()
                or cd.get("name", "")
            ),
            "title": cd.get("title", ""),
            "company": cd.get("company", ""),
            "email": cd.get("email", ""),
            "phone": cd.get("phone", ""),
            "mobile": cd.get("mobile", ""),
            "website": cd.get("website", ""),
            "linkedin": cd.get("linkedin", ""),
            "address": cd.get("address", ""),
        },
        "vcfContent": card.get("vcf_content", ""),
    }


def _refine_tile_to_card(tile_bgr: np.ndarray) -> np.ndarray:
    """
    A grid tile typically contains a single card plus some surrounding
    table/gap pixels (because the grid lines fall in inter-card gutters,
    not on card edges). Find the actual card boundary inside the tile and
    crop+deskew to it. Returns the tile unchanged if no clear card boundary
    is found, so this is always safe to call.

    Algorithm:
      1. Multi-strategy edge detection (Canny low/high + adaptive threshold)
      2. Pick the largest 4–8-corner contour whose area is 25–98% of the tile
      3. If it's a quadrilateral, four-point-warp to deskew
      4. Otherwise crop to its bounding rect (with a small inset)
    """
    from utils.improved_card_detector import ImprovedCardDetector

    h, w = tile_bgr.shape[:2]
    if h < 100 or w < 100:
        return tile_bgr
    gray = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2GRAY)
    # CLAHE to boost contrast on washed-out / mostly-white cards
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    eq = clahe.apply(gray)
    blurred = cv2.GaussianBlur(eq, (5, 5), 0)

    edge_maps = [
        cv2.Canny(blurred, 30, 100),
        cv2.Canny(blurred, 60, 150),
        cv2.adaptiveThreshold(
            blurred,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            15,
            4,
        ),
    ]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    tile_area = h * w
    best = None
    best_score = 0
    for em in edge_maps:
        closed = cv2.morphologyEx(em, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 0.25 * tile_area or area > 0.98 * tile_area:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            n = len(approx)
            if n < 4 or n > 8:
                continue
            # Score: area * (1 if quadrilateral) * (1 - distance from card-like aspect)
            x, y, bw, bh = cv2.boundingRect(c)
            if bw == 0 or bh == 0:
                continue
            aspect = bw / bh
            # Business cards: aspect ~1.6–1.8 (or 0.55–0.625 if portrait)
            aspect_score = 0
            for target in (1.7, 1 / 1.7):
                aspect_score = max(aspect_score, 1.0 - min(1.0, abs(aspect - target) / target))
            quad_bonus = 1.5 if n == 4 else 1.0
            score = area * quad_bonus * (0.5 + 0.5 * aspect_score)
            if score > best_score:
                best_score = score
                best = (n, approx, c)

    if best is None:
        return tile_bgr

    n, approx, contour = best
    detector = ImprovedCardDetector()
    if n == 4:
        try:
            return detector.four_point_transform(tile_bgr, approx.reshape(4, 2))
        except Exception:
            pass
    # Fallback: tight bounding rect with small inset
    x, y, bw, bh = cv2.boundingRect(contour)
    pad = 2
    return tile_bgr[
        max(0, y - pad) : y + bh + pad,
        max(0, x - pad) : x + bw + pad,
    ]


def _process_custom_tiles(
    processor,
    image_bgr,
    image_rgb,
    h_lines,
    v_lines,
    top,
    bottom,
    left,
    right,
    vision_model,
    vision_timeout,
    cancel_check,
):
    """Crop image into tiles using normalized line positions, then run
    process_single_card on each tile. Returns a list of card dicts."""
    h, w = image_bgr.shape[:2]
    rects = _grid_rects_from_lines(w, h, h_lines, v_lines, top, bottom, left, right)
    results = []
    for x, y, bw, bh in rects:
        if cancel_check():
            break
        tile_bgr_raw = image_bgr[y : y + bh, x : x + bw]
        # Refine: find the actual card inside the tile (trims gap/background)
        tile_bgr = _refine_tile_to_card(tile_bgr_raw)
        # rgb mirrors whatever bgr ended up as (refined or raw)
        tile_rgb = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
        card = processor.process_single_card(
            tile_bgr, tile_rgb, vision_model=vision_model, vision_timeout=vision_timeout
        )
        if card:
            results.append(card)
    return results


def _gap_detect_and_regularize(bgr: np.ndarray) -> list:
    """
    Replicates the preview's gap-based grid inference + regularization
    (drop tiny outer bands, split oversized bands using inner gap detection).
    Returns a list of (x, y, w, h) tile rectangles tiling the whole image.
    """
    from utils.improved_card_detector import ImprovedCardDetector

    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    h_proj = np.sum(edges, axis=1).astype(float)
    v_proj = np.sum(edges, axis=0).astype(float)
    h_smooth = np.convolve(h_proj, np.ones(3) / 3, mode="same")
    v_smooth = np.convolve(v_proj, np.ones(3) / 3, mode="same")
    d = ImprovedCardDetector()
    row_splits = d._find_gap_positions(h_smooth, h, cross_length=w)
    col_splits = d._find_gap_positions(v_smooth, w, cross_length=h)
    if not (row_splits or col_splits):
        return []
    row_bounds = [0] + row_splits + [h]
    col_bounds = [0] + col_splits + [w]

    def find_inner_gaps(slice_bgr, axis, expected_count):
        if expected_count < 1:
            return []
        g = cv2.cvtColor(slice_bgr, cv2.COLOR_BGR2GRAY)
        e = cv2.Canny(g, 50, 150)
        if axis == "row":
            proj = np.sum(e, axis=1).astype(float)
            length = slice_bgr.shape[0]
            cross = slice_bgr.shape[1]
        else:
            proj = np.sum(e, axis=0).astype(float)
            length = slice_bgr.shape[1]
            cross = slice_bgr.shape[0]
        sm = np.convolve(proj, np.ones(3) / 3, mode="same")
        d2 = ImprovedCardDetector()
        splits = d2._find_gap_positions(sm, length, cross_length=cross)
        if len(splits) >= expected_count:
            scored = sorted(splits, key=lambda p: sm[max(0, min(len(sm) - 1, p))])
            return sorted(scored[:expected_count])
        return splits

    def regularize(bounds, axis):
        if len(bounds) < 3:
            return bounds
        spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        median = sorted(spans)[len(spans) // 2]
        if spans[0] < 0.5 * median:
            bounds = bounds[1:]
            spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        if spans and spans[-1] < 0.5 * median:
            bounds = bounds[:-1]
            spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        bounds[0] = 0
        out = [bounds[0]]
        for i in range(len(bounds) - 1):
            a, b = bounds[i], bounds[i + 1]
            span = b - a
            n_sub = max(1, int(round(span / median)))
            if n_sub > 1:
                sl = bgr[a:b] if axis == "row" else bgr[:, a:b]
                inner = find_inner_gaps(sl, axis, n_sub - 1)
                if len(inner) == n_sub - 1:
                    for s in inner:
                        out.append(a + s)
                else:
                    for k in range(1, n_sub):
                        out.append(a + int(round(k * span / n_sub)))
            out.append(b)
        return out

    row_bounds = regularize(row_bounds, "row")
    col_bounds = regularize(col_bounds, "col")
    row_bounds[0] = 0
    row_bounds[-1] = h
    col_bounds[0] = 0
    col_bounds[-1] = w
    rects = []
    for r in range(len(row_bounds) - 1):
        for c in range(len(col_bounds) - 1):
            y1, y2 = row_bounds[r], row_bounds[r + 1]
            x1, x2 = col_bounds[c], col_bounds[c + 1]
            if y2 - y1 < 80 or x2 - x1 < 80:
                continue
            rects.append((x1, y1, x2 - x1, y2 - y1))

    # Drop slivers relative to the typical tile, not an absolute pixel
    # floor: the inter-card gutter on a 4032px phone photo is ~80-100px
    # tall and sailed past the 80px check above, surfacing as a bogus
    # "card". Anything under 30% of the median width/height is a gutter.
    if len(rects) >= 2:
        med_w = float(np.median([w for _, _, w, _ in rects]))
        med_h = float(np.median([h for _, _, _, h in rects]))
        rects = [(x, y, w, h) for x, y, w, h in rects if w >= 0.3 * med_w and h >= 0.3 * med_h]
    return rects


def _card_has_real_contact(card: dict) -> bool:
    """True if a result card carries an actual person/contact field (not just
    a QR URL). Used to tell a real card from a spurious QR-region card."""
    cd = card.get("contact_data") or {}
    return any(
        cd.get(k)
        for k in ("firstName", "lastName", "fullName", "email", "phone", "mobile", "company")
    )


def _consolidate_qr_only_cards(results: list) -> list:
    """Fold a spurious 'QR-only' card back into the real card.

    In Automatic mode the detector can pick up a card's QR code as its own
    rectangular region. That region yields a card with only a website/notes
    and a pending `_qr_url` (no name/email/phone) — a duplicate of the real
    card on the same image.

    When there is exactly ONE real (rich) card, we transfer the QR URL (and
    website) onto it and drop the QR-only card(s), so the user gets a single
    card with the 'Fetch contact data' affordance instead of two.

    Guard: only fires with a single rich card. With multiple rich cards (a
    batch scan) we can't tell which one a stray QR belongs to, so we leave
    everything untouched.
    """
    if len(results) < 2:
        return results
    rich = [c for c in results if _card_has_real_contact(c)]
    qr_only = [
        c
        for c in results
        if not _card_has_real_contact(c) and (c.get("contact_data") or {}).get("_qr_url")
    ]
    if len(rich) != 1 or not qr_only:
        return results

    target = rich[0]
    tcd = target.setdefault("contact_data", {})
    for q in qr_only:
        qcd = q.get("contact_data") or {}
        if qcd.get("_qr_url") and not tcd.get("_qr_url"):
            tcd["_qr_url"] = qcd["_qr_url"]
        if qcd.get("website") and not tcd.get("website"):
            tcd["website"] = qcd["website"]

    drop = {id(c) for c in qr_only}
    return [c for c in results if id(c) not in drop]


def _process_with_refinement(
    processor,
    image_bgr,
    image_rgb,
    detection_mode,
    vision_model,
    vision_timeout,
    grid_rows,
    grid_cols,
    cancel_check,
):
    """
    Auto/single-mode equivalent of process_batch, but:
      - When the detector returns 4-corner contours, use them as-is
        (already deskewed via four_point_transform).
      - When the detector returns rectangular tiles (contour=None) AND
        very few of them, override with our own gap-detection +
        regularization, which catches missed gaps and rejects margins.
      - Always refine each rect tile to its actual card boundary before
        passing to the vision model (trims inter-card gap pixels).
    """
    detected = processor.detect_cards(image_bgr, detection_mode, grid_rows, grid_cols, 0, 0, 0, 0)
    contour_polys = [c for _, c in detected if c is not None]

    # Decide which set of tile rectangles to process
    use_overlay_grid = False
    overlay_rects = []
    if not contour_polys and detection_mode == "Automatic":
        # Detector fell back to rectangular tiles. Run our own gap +
        # regularize pass to catch any missed rows/cols.
        overlay_rects = _gap_detect_and_regularize(image_bgr)
        # Only let a gap-inferred tiling override the detector when it
        # looks like a real sheet (>= 4 tiles). A 2-3 tile result is the
        # classic false split of a single card along a crease/shadow.
        if len(overlay_rects) >= 4 and len(overlay_rects) > len(detected):
            use_overlay_grid = True

    results = []
    if use_overlay_grid:
        for x, y, bw, bh in overlay_rects:
            if cancel_check and cancel_check():
                break
            tile_bgr = image_bgr[y : y + bh, x : x + bw]
            tile_bgr = _refine_tile_to_card(tile_bgr)
            tile_rgb = cv2.cvtColor(tile_bgr, cv2.COLOR_BGR2RGB)
            card = processor.process_single_card(
                tile_bgr,
                tile_rgb,
                vision_model=vision_model,
                vision_timeout=vision_timeout,
            )
            if card:
                results.append(card)
    else:
        for card_image_bgr, contour in detected:
            if cancel_check and cancel_check():
                break
            if contour is None:
                card_image_bgr = _refine_tile_to_card(card_image_bgr)
            card_rgb = cv2.cvtColor(card_image_bgr, cv2.COLOR_BGR2RGB)
            card = processor.process_single_card(
                card_image_bgr,
                card_rgb,
                vision_model=vision_model,
                vision_timeout=vision_timeout,
            )
            if card:
                results.append(card)
    return _consolidate_qr_only_cards(results)


async def _scan_generator(
    files: List[UploadFile],
    model: str,
    mode: str,
    rows: int,
    cols: int,
    timeout: int,
    row_lines: str = "",
    col_lines: str = "",
    margin_top: float = 0.0,
    margin_bottom: float = 1.0,
    margin_left: float = 0.0,
    margin_right: float = 1.0,
    deskew: bool = False,
    skip_size_check: bool = False,
):
    """Async generator that yields SSE events for the scan pipeline."""
    # Reset the cancel flag for this scan
    _scan_cancel_event.clear()

    yield _sse({"stage": "warmup", "progress": 5, "message": "Loading model…"})
    await asyncio.sleep(0)

    processor = CardProcessor(provider_factory=_provider_factory)
    cancel_check = _scan_cancel_event.is_set

    # Map frontend mode strings to CardProcessor detection_mode
    mode_map = {"auto": "Automatic", "single": "Single Card", "grid": "Manual - Grid Layout"}
    detection_mode = mode_map.get(mode, "Automatic")

    # Parse custom grid line positions. When set and mode==grid, we crop tiles
    # ourselves and bypass the detector.
    h_lines = _parse_line_positions(row_lines)
    v_lines = _parse_line_positions(col_lines)
    cropped = (
        margin_top > 0.001 or margin_bottom < 0.999 or margin_left > 0.001 or margin_right < 0.999
    )
    use_custom_tiles = mode == "grid" and (h_lines or v_lines or cropped)
    if mode == "grid" and not (h_lines or v_lines):
        # Fill in equally-spaced defaults within the (possibly cropped) outer box
        h_lines = [
            margin_top + (i + 1) * (margin_bottom - margin_top) / rows for i in range(rows - 1)
        ]
        v_lines = [
            margin_left + (i + 1) * (margin_right - margin_left) / cols for i in range(cols - 1)
        ]
        use_custom_tiles = True

    all_cards = []
    total_files = len(files)
    run_id = None
    file_payloads: List[dict] = []  # for history persistence — preserved bytes

    try:
        for file_idx, upload in enumerate(files):
            if cancel_check():
                yield _sse({"stage": "stopped", "message": "Scan cancelled by user"})
                return
            raw = await upload.read()
            filename = upload.filename or f"file_{file_idx}"

            # Upload validation (size cap + extension + magic bytes) BEFORE
            # any bytes reach cv2.imdecode / fitz.open. Skip bad files.
            # Relaunch path (`skip_size_check=True`) bypasses the size cap
            # because the file already passed validation once and lives in
            # our own archive — the cap is for protecting the upload
            # endpoint from arbitrary inbound traffic, not for re-scans.
            _upload_err = _validate_upload(filename, raw, skip_size_check=skip_size_check)
            if _upload_err:
                yield _sse(
                    {
                        "stage": "warning",
                        "message": f"Skipped '{filename}': {_upload_err}",
                    }
                )
                continue

            file_payloads.append(
                {
                    "name": filename,
                    "data": raw,
                    "media_type": "pdf" if filename.lower().endswith(".pdf") else "image",
                }
            )

            progress_base = 10 + int(file_idx / total_files * 30)

            # Check if file is PDF
            is_pdf = filename.lower().endswith(".pdf")

            if is_pdf:
                # Process all pages of PDF
                yield _sse(
                    {
                        "stage": "detect",
                        "progress": progress_base,
                        "message": f"Processing PDF '{filename}'…",
                    }
                )
                await asyncio.sleep(0)

                try:
                    # Get all pages from PDF
                    pages = _pdf_to_images(raw, filename, dpi=200)
                except ValueError as e:
                    yield _sse({"stage": "error", "message": str(e)})
                    return

                pdf_cards = []
                for page_idx, (bgr, rgb) in enumerate(pages):
                    if cancel_check():
                        yield _sse({"stage": "stopped", "message": "Scan cancelled by user"})
                        return
                    if deskew:
                        bgr = _deskew_to_card_cluster(bgr)
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    yield _sse(
                        {
                            "stage": "extract",
                            "progress": progress_base + int((page_idx + 1) / len(pages) * 10),
                            "message": f"Extracting data from page {page_idx + 1} of {len(pages)}…",
                        }
                    )
                    await asyncio.sleep(0)

                    # Process this page
                    loop = asyncio.get_event_loop()
                    if use_custom_tiles:
                        page_cards = await loop.run_in_executor(
                            None,
                            lambda b=bgr, r=rgb: _process_custom_tiles(
                                processor,
                                b,
                                r,
                                h_lines,
                                v_lines,
                                margin_top,
                                margin_bottom,
                                margin_left,
                                margin_right,
                                vision_model=model,
                                vision_timeout=timeout,
                                cancel_check=cancel_check,
                            ),
                        )
                    else:
                        page_cards = await loop.run_in_executor(
                            None,
                            lambda b=bgr, r=rgb: _process_with_refinement(
                                processor,
                                b,
                                r,
                                detection_mode,
                                vision_model=model,
                                vision_timeout=timeout,
                                grid_rows=rows,
                                grid_cols=cols,
                                cancel_check=cancel_check,
                            ),
                        )

                    for card in page_cards:
                        card["_source_file"] = f"{filename} (page {page_idx + 1})"
                    pdf_cards.extend(page_cards)

                # Add all cards from PDF pages
                all_cards.extend(pdf_cards)

            else:
                # Process single image file
                yield _sse(
                    {
                        "stage": "detect",
                        "progress": progress_base,
                        "message": f"Detecting cards in {filename}…",
                    }
                )
                await asyncio.sleep(0)

                try:
                    bgr, rgb = _load_image(raw, filename)
                except ValueError as e:
                    yield _sse({"stage": "error", "message": str(e)})
                    return

                if deskew:
                    bgr = _deskew_to_card_cluster(bgr)
                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

                yield _sse(
                    {
                        "stage": "extract",
                        "progress": progress_base + 10,
                        "message": f"Extracting data from {filename}…",
                    }
                )
                await asyncio.sleep(0)

                # Run synchronously in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                if use_custom_tiles:
                    cards = await loop.run_in_executor(
                        None,
                        lambda b=bgr, r=rgb: _process_custom_tiles(
                            processor,
                            b,
                            r,
                            h_lines,
                            v_lines,
                            margin_top,
                            margin_bottom,
                            margin_left,
                            margin_right,
                            vision_model=model,
                            vision_timeout=timeout,
                            cancel_check=cancel_check,
                        ),
                    )
                else:
                    cards = await loop.run_in_executor(
                        None,
                        lambda b=bgr, r=rgb: _process_with_refinement(
                            processor,
                            b,
                            r,
                            detection_mode,
                            vision_model=model,
                            vision_timeout=timeout,
                            grid_rows=rows,
                            grid_cols=cols,
                            cancel_check=cancel_check,
                        ),
                    )

                for card in cards:
                    card["_source_file"] = filename
                all_cards.extend(cards)
                if cancel_check():
                    yield _sse({"stage": "stopped", "message": "Scan cancelled by user"})
                    return

        yield _sse({"stage": "generate", "progress": 90, "message": "Generating VCF files…"})
        await asyncio.sleep(0)

        # Persist to history
        run_id = None
        try:
            settings = {
                "vision_model": model,
                "detection_mode": detection_mode,
                "vision_timeout": timeout,
            }
            # Build the processed_cards payload that HistoryManager expects.
            processed_cards_payload = [
                {
                    "filename": c.get("filename", f"card_{i + 1}.vcf"),
                    "source_file": c.get("_source_file", ""),
                    "locked": False,
                    "contact_data": c.get("contact_data") or {},
                    "vcf_content": c.get("vcf_content"),
                    "card_image": c.get("card_image"),
                }
                for i, c in enumerate(all_cards)
                if (c.get("contact_data") or {})
            ]

            loop = asyncio.get_event_loop()
            run_id = await loop.run_in_executor(
                None,
                lambda: (
                    _history.create_run(
                        settings=settings,
                        original_files=file_payloads,
                        processed_cards=processed_cards_payload,
                    ).run_id
                ),
            )

            # Tag cards with stable IDs and mirror to the contacts repository.
            for idx, card in enumerate(all_cards):
                cd = card.get("contact_data") or {}
                if not cd:
                    continue
                card_id = f"{run_id}_{idx}"
                card["_card_id"] = card_id
                add_result = await loop.run_in_executor(
                    None,
                    lambda c=card, cid=card_id: _contacts.add_contact(
                        contact_data=c.get("contact_data", {}),
                        source_file=c.get("_source_file", ""),
                        card_id=cid,
                    ),
                )
                # Attach merge / conflict info to the card so the frontend
                # can show a banner. add_contact returns:
                #   {id, status: added|updated|merged|conflict,
                #    additions, conflicts, locked}
                card["_repo_status"] = add_result.get("status", "added")
                card["_repo_id"] = add_result.get("id", "")
                card["_locked"] = add_result.get("locked", False)
                if add_result.get("additions"):
                    card["_additions"] = add_result["additions"]
                if add_result.get("conflicts"):
                    card["_conflicts"] = add_result["conflicts"]
        except Exception as hist_err:
            # History persistence failure is non-fatal for the user-facing scan,
            # but we log it so silent breakage doesn't hide bugs.
            import traceback

            print(f"[history] save failed: {hist_err}", flush=True)
            traceback.print_exc()

        # Build frontend card list
        frontend_cards = [
            _contact_data_to_frontend(card, card.get("_source_file", ""), i, run_id)
            for i, card in enumerate(all_cards)
        ]

        yield _sse(
            {
                "stage": "done",
                "progress": 100,
                "cards": frontend_cards,
                "runId": run_id,
            }
        )

    except Exception as exc:
        yield _sse({"stage": "error", "message": str(exc)})


def _parse_line_positions(s: str) -> list:
    """Parse comma-separated float positions in [0,1], return sorted unique list."""
    if not s:
        return []
    out = []
    for part in s.split(","):
        try:
            v = float(part.strip())
            if 0.0 < v < 1.0:
                out.append(v)
        except ValueError:
            continue
    return sorted(set(out))


def _grid_rects_from_lines(
    w: int,
    h: int,
    h_fracs: list,
    v_fracs: list,
    top: float = 0.0,
    bottom: float = 1.0,
    left: float = 0.0,
    right: float = 1.0,
) -> list:
    """Build tile rectangles from normalized internal line positions.
    h_fracs are horizontal-line y-positions (row dividers), v_fracs are
    vertical-line x-positions (col dividers). The outer crop box is defined
    by top/bottom/left/right (all 0..1). Returns list of (x, y, w, h)."""
    # Clamp + order outer bounds defensively
    top = max(0.0, min(1.0, top))
    bottom = max(0.0, min(1.0, bottom))
    left = max(0.0, min(1.0, left))
    right = max(0.0, min(1.0, right))
    if bottom <= top:
        bottom = min(1.0, top + 0.01)
    if right <= left:
        right = min(1.0, left + 0.01)
    # Drop any internal lines that fall outside the outer box
    h_fracs = [f for f in h_fracs if top < f < bottom]
    v_fracs = [f for f in v_fracs if left < f < right]
    ys = [int(round(top * h))] + [int(round(f * h)) for f in h_fracs] + [int(round(bottom * h))]
    xs = [int(round(left * w))] + [int(round(f * w)) for f in v_fracs] + [int(round(right * w))]
    rects = []
    for ri in range(len(ys) - 1):
        for ci in range(len(xs) - 1):
            x1, x2 = xs[ci], xs[ci + 1]
            y1, y2 = ys[ri], ys[ri + 1]
            if x2 > x1 and y2 > y1:
                rects.append((x1, y1, x2 - x1, y2 - y1))
    return rects


def _annotate_image(
    bgr: np.ndarray,
    mode: str,
    rows: int,
    cols: int,
    h_lines: list = None,
    v_lines: list = None,
    top: float = 0.0,
    bottom: float = 1.0,
    left: float = 0.0,
    right: float = 1.0,
) -> tuple:
    """
    Run detection only, draw card boundaries on a copy of the image,
    return (annotated_jpeg_bytes, card_count, lines_dict).

    h_lines/v_lines: optional normalized internal line positions (0..1).
    top/bottom/left/right: optional outer crop bounds (0..1), default full image.
    When provided in grid mode, override default equal-spacing.
    """
    from utils.improved_card_detector import ImprovedCardDetector
    from utils.ui_components import split_image_grid

    h, w = bgr.shape[:2]
    annotated = bgr.copy()
    boxes = []  # list of (x, y, w, h) or polygon
    lines_out = {
        "h": [],
        "v": [],
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
    }
    inferred_grid = None  # (rows, cols) if auto detector chose a grid layout

    if mode == "single":
        boxes.append(("rect", (0, 0, w, h)))
    elif mode == "grid":
        # Determine internal line positions
        if not h_lines:
            h_lines = [top + (i + 1) * (bottom - top) / rows for i in range(rows - 1)]
        if not v_lines:
            v_lines = [left + (i + 1) * (right - left) / cols for i in range(cols - 1)]
        lines_out = {
            "h": list(h_lines),
            "v": list(v_lines),
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
        }
        for rect in _grid_rects_from_lines(w, h, h_lines, v_lines, top, bottom, left, right):
            boxes.append(("rect", rect))
    else:
        # Use CardProcessor.detect_cards so preview matches the real scan
        processor = CardProcessor(provider_factory=_provider_factory)
        detected = processor.detect_cards(bgr, "Automatic", rows, cols, 0, 0, 0, 0)

        contour_polys = [c for _, c in detected if c is not None]
        if contour_polys:
            # We have real polygon contours — draw them
            for c in contour_polys:
                boxes.append(("poly", c))
        elif detected:
            # Detector fell back to a non-contour split (gap-based or uniform
            # grid). To show TRUE positions (not a re-inferred uniform grid),
            # replicate the detector's gap-detection logic to get actual
            # row/col bounds; if gap detection finds nothing, fall back to
            # uniform inference + blank filter.
            from utils.improved_card_detector import _is_blank_cell

            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            h_proj = np.sum(edges, axis=1).astype(float)
            v_proj = np.sum(edges, axis=0).astype(float)
            h_smooth = np.convolve(h_proj, np.ones(3) / 3, mode="same")
            v_smooth = np.convolve(v_proj, np.ones(3) / 3, mode="same")

            _gap_detector = ImprovedCardDetector()
            row_splits = _gap_detector._find_gap_positions(h_smooth, h, cross_length=w)
            col_splits = _gap_detector._find_gap_positions(v_smooth, w, cross_length=h)

            used_gap_split = bool(row_splits or col_splits)
            if used_gap_split:
                # Gap-detection found real edges between cards. Don't apply
                # the blank-cell filter (tuned for uniform-grid fallback;
                # over-rejects sparse white cards like Marcos's Spanish
                # consulate card).
                row_bounds = [0] + row_splits + [h]
                col_bounds = [0] + col_splits + [w]

                # ─── Post-process: regularize rows/cols ─────────────────
                # The gap detector often (a) treats the outer margin as a
                # row separator, creating a tiny empty band at the top/
                # bottom; (b) misses the gap between two card rows,
                # producing a band that's > 1.6× the median. Fix:
                #   1. Drop bands < 50% of median (margins)
                #   2. For an oversized band, re-run gap detection on
                #      JUST that slice with relaxed thresholds to find
                #      the missed gap. If that fails, fall back to even
                #      splitting as a last resort.
                def find_inner_gaps(bgr_slice, axis, expected_count):
                    """Look for `expected_count` actual gaps inside a slice."""
                    if expected_count < 1:
                        return []
                    g = cv2.cvtColor(bgr_slice, cv2.COLOR_BGR2GRAY)
                    e = cv2.Canny(g, 50, 150)
                    if axis == "row":
                        proj = np.sum(e, axis=1).astype(float)
                        length = bgr_slice.shape[0]
                        cross = bgr_slice.shape[1]
                    else:
                        proj = np.sum(e, axis=0).astype(float)
                        length = bgr_slice.shape[1]
                        cross = bgr_slice.shape[0]
                    sm = np.convolve(proj, np.ones(3) / 3, mode="same")
                    d2 = ImprovedCardDetector()
                    splits = d2._find_gap_positions(sm, length, cross_length=cross)
                    if len(splits) >= expected_count:
                        # Keep the deepest `expected_count` gaps (lowest
                        # smoothed projection at each candidate position)
                        scored = sorted(splits, key=lambda p: sm[max(0, min(len(sm) - 1, p))])
                        return sorted(scored[:expected_count])
                    return splits

                def regularize(bounds: list, axis: str) -> list:
                    if len(bounds) < 3:
                        return bounds
                    spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
                    median = sorted(spans)[len(spans) // 2]
                    # Drop tiny outer bands (top/bottom margin only)
                    if spans[0] < 0.5 * median:
                        bounds = bounds[1:]
                        spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
                    if spans and spans[-1] < 0.5 * median:
                        bounds = bounds[:-1]
                        spans = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
                    # Re-anchor first to image edge
                    bounds[0] = 0
                    # Split bands that look like N merged rows
                    out = [bounds[0]]
                    for i in range(len(bounds) - 1):
                        a, b = bounds[i], bounds[i + 1]
                        span = b - a
                        n_sub = max(1, int(round(span / median)))
                        if n_sub > 1:
                            # Try to find the real gaps inside this slice
                            if axis == "row":
                                sl = bgr[a:b]
                            else:
                                sl = bgr[:, a:b]
                            inner = find_inner_gaps(sl, axis, n_sub - 1)
                            if len(inner) == n_sub - 1:
                                for s in inner:
                                    out.append(a + s)
                            else:
                                # Fallback: even split
                                for k in range(1, n_sub):
                                    out.append(a + int(round(k * span / n_sub)))
                        out.append(b)
                    return out

                row_bounds = regularize(row_bounds, "row")
                col_bounds = regularize(col_bounds, "col")
                # Re-anchor to image extent so we don't lose pixels
                row_bounds[0] = 0
                row_bounds[-1] = h
                col_bounds[0] = 0
                col_bounds[-1] = w

                inferred_grid = (len(row_bounds) - 1, len(col_bounds) - 1)
                for r in range(len(row_bounds) - 1):
                    for c in range(len(col_bounds) - 1):
                        y1, y2 = row_bounds[r], row_bounds[r + 1]
                        x1, x2 = col_bounds[c], col_bounds[c + 1]
                        if y2 - y1 < 80 or x2 - x1 < 80:
                            continue
                        boxes.append(("rect", (x1, y1, x2 - x1, y2 - y1)))
            else:
                # Last-resort uniform grid (no gaps found at all)
                sample_h, sample_w = detected[0][0].shape[:2]
                grid_rows = max(1, round(h / sample_h))
                grid_cols = max(1, round(w / sample_w))
                inferred_grid = (grid_rows, grid_cols)
                ch = h // grid_rows
                cw = w // grid_cols
                for r in range(grid_rows):
                    for c in range(grid_cols):
                        x1 = c * cw
                        y1 = r * ch
                        x2 = (c + 1) * cw if c < grid_cols - 1 else w
                        y2 = (r + 1) * ch if r < grid_rows - 1 else h
                        tile = bgr[y1:y2, x1:x2]
                        if not _is_blank_cell(tile):
                            boxes.append(("rect", (x1, y1, x2 - x1, y2 - y1)))

    # In grid mode the React overlay draws everything (outer crop, internal
    # dividers, dim mask, drag handles, tile numbers) — skip server-side
    # annotation to avoid double-rendering. Just report the count + lines.
    if mode == "grid":
        if w > 1400:
            scale = 1400 / w
            annotated = cv2.resize(annotated, (1400, int(h * scale)))
        ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise ValueError("Failed to encode preview JPEG")
        return bytes(buf), len(boxes), lines_out, inferred_grid

    # Draw (auto / single modes)
    GREEN = (60, 200, 90)
    thickness = max(3, int(min(w, h) * 0.004))
    font_scale = max(1.0, min(w, h) * 0.001)
    for i, (kind, data) in enumerate(boxes):
        label = str(i + 1)
        if kind == "rect":
            x, y, bw, bh = data
            cv2.rectangle(annotated, (x, y), (x + bw, y + bh), GREEN, thickness)
            cx, cy = x + 40, y + 60
        else:
            cv2.drawContours(annotated, [data], -1, GREEN, thickness)
            M = cv2.moments(data)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"]) - 20
                cy = int(M["m01"] / M["m00"]) + 20
            else:
                cx, cy = 40, 60
        # Filled label background for legibility
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        cv2.rectangle(annotated, (cx - 8, cy - th - 8), (cx + tw + 8, cy + 8), GREEN, -1)
        cv2.putText(
            annotated,
            label,
            (cx, cy),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness,
        )

    # Resize for transport (max 1400 px wide)
    if w > 1400:
        scale = 1400 / w
        annotated = cv2.resize(annotated, (1400, int(h * scale)))
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise ValueError("Failed to encode preview JPEG")
    return bytes(buf), len(boxes), lines_out, inferred_grid


def _clamp01(v: float, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


@app.post("/api/preview")
async def preview(
    files: List[UploadFile] = File(...),
    mode: str = Form("auto"),
    rows: int = Form(4),
    cols: int = Form(2),
    row_lines: str = Form(""),
    col_lines: str = Form(""),
    margin_top: float = Form(0.0),
    margin_bottom: float = Form(1.0),
    margin_left: float = Form(0.0),
    margin_right: float = Form(1.0),
    deskew: bool = Form(False),
):
    """Run detection only (no vision/LLM) and return annotated previews.
    Optional row_lines/col_lines: comma-separated floats in (0,1) for manual
    grid line positions (only used when mode=grid).
    margin_top/bottom/left/right: outer crop bounds (0..1).
    deskew: if true, find the card-cluster region and warp it to axis-aligned
    rectangle before detection. Helpful for photographed images."""
    import base64

    h_lines = _parse_line_positions(row_lines)
    v_lines = _parse_line_positions(col_lines)
    mt = _clamp01(margin_top, 0.0)
    mb = _clamp01(margin_bottom, 1.0)
    ml = _clamp01(margin_left, 0.0)
    mr = _clamp01(margin_right, 1.0)

    previews = []
    for upload in files:
        raw = await upload.read()
        filename = upload.filename or "upload"
        err = _validate_upload(filename, raw)
        if err:
            previews.append({"filename": filename, "error": err})
            continue
        try:
            # PDFs: detect on page 0 only for preview
            bgr, _ = _load_image(raw, filename)
            if deskew:
                bgr = _deskew_to_card_cluster(bgr)
            loop = asyncio.get_event_loop()
            jpeg_bytes, count, lines, inferred = await loop.run_in_executor(
                None,
                lambda: _annotate_image(bgr, mode, rows, cols, h_lines, v_lines, mt, mb, ml, mr),
            )
            b64 = base64.b64encode(jpeg_bytes).decode("ascii")
            previews.append(
                {
                    "filename": filename,
                    "cardCount": count,
                    "imageDataUrl": f"data:image/jpeg;base64,{b64}",
                    "lines": lines,  # {h, v, top, bottom, left, right}
                    "inferredGrid": (
                        {"rows": inferred[0], "cols": inferred[1]} if inferred else None
                    ),
                }
            )
        except Exception as e:
            previews.append({"filename": filename, "error": str(e)})
    total = sum(p.get("cardCount", 0) for p in previews)
    return {"previews": previews, "totalCards": total}


@app.post("/api/scan")
async def scan(
    files: List[UploadFile] = File(...),
    model: str = Form("qwen2.5vl:7b"),
    mode: str = Form("auto"),
    rows: int = Form(4),
    cols: int = Form(2),
    timeout: int = Form(300),
    row_lines: str = Form(""),
    col_lines: str = Form(""),
    margin_top: float = Form(0.0),
    margin_bottom: float = Form(1.0),
    margin_left: float = Form(0.0),
    margin_right: float = Form(1.0),
    deskew: bool = Form(False),
):
    """Stream scan progress via SSE (text/event-stream)."""
    return StreamingResponse(
        _scan_generator(
            files,
            model,
            mode,
            rows,
            cols,
            timeout,
            row_lines,
            col_lines,
            _clamp01(margin_top, 0.0),
            _clamp01(margin_bottom, 1.0),
            _clamp01(margin_left, 0.0),
            _clamp01(margin_right, 1.0),
            deskew,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/scan/stop")
async def stop_scan():
    """Signal the in-flight scan to stop at the next safe checkpoint.

    The current in-flight card finishes (Ollama HTTP requests can't be killed
    cleanly mid-call), then no further cards or pages are processed.
    """
    _scan_cancel_event.set()
    return {"status": "stopping"}


# ═══════════════════════════════════════════════════════════
# MODEL BENCHMARK  (SSE streaming)
# ═══════════════════════════════════════════════════════════

_bench_cancel_event = threading.Event()


async def _benchmark_generator(models: List[str], items: list, timeout: int):
    """Run each model over each locked-contact card image, scoring against
    the human-verified contact data. Yields SSE progress + a final results
    event. QR data is deliberately not passed — vision quality only."""
    from utils.model_benchmark import BenchAccumulator, score_card

    loop = asyncio.get_event_loop()
    total_steps = max(1, len(models) * len(items))
    step = 0
    results = []

    for m_idx, model in enumerate(models):
        acc = BenchAccumulator(model)
        for i_idx, item in enumerate(items):
            if _bench_cancel_event.is_set():
                yield _sse({"stage": "stopped", "message": "Benchmark cancelled"})
                return
            step += 1
            yield _sse(
                {
                    "stage": "bench",
                    "progress": int(100 * (step - 1) / total_steps),
                    "message": f"{model} — card {i_idx + 1}/{len(items)} ({item['label']})",
                    "model": model,
                    "card": i_idx + 1,
                    "totalCards": len(items),
                    "modelIndex": m_idx + 1,
                    "totalModels": len(models),
                }
            )
            await asyncio.sleep(0)

            img = cv2.imread(item["image_path"])
            if img is None:
                acc.add(score_card(item["truth"], {}), 0, failed=True)
                continue

            try:
                result = await loop.run_in_executor(
                    None,
                    lambda im=img, mo=model: _provider_factory.extract_with_fallback(
                        im, None, timeout=timeout, model=mo
                    ),
                )
                extracted = result.contact.to_legacy_dict() if result.contact else {}
                failed = bool(result.error) or not result.contact.has_minimum_data()
                acc.add(
                    score_card(item["truth"], extracted),
                    result.processing_time_ms,
                    failed=failed,
                )
            except Exception as e:
                logger_msg = f"benchmark extract failed ({model}): {e}"
                print(logger_msg)
                acc.add(score_card(item["truth"], {}), 0, failed=True)

        results.append(acc.summary())

    results.sort(key=lambda r: r["overall"]["pct"], reverse=True)
    yield _sse({"stage": "done", "results": results, "items": len(items)})


@app.post("/api/benchmark")
async def run_model_benchmark(request: Request):
    """Benchmark vision models against locked (human-verified) contacts.

    Body: {"models": ["glm-ocr", ...], "limit": 10, "timeout": 180}
    Returns the same SSE event shape as /api/scan. Ground truth = locked
    contacts whose card_id resolves to an archived card image.
    """
    from utils.model_benchmark import collect_items

    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    models = [m for m in (body.get("models") or []) if isinstance(m, str) and m.strip()]
    if not models:
        raise HTTPException(status_code=400, detail="No models given")
    limit = max(1, min(int(body.get("limit") or 10), 200))
    timeout = max(10, min(int(body.get("timeout") or 180), 600))

    items = collect_items(_contacts.get_all(), THUMBNAIL_DIR, limit)
    if not items:
        raise HTTPException(
            status_code=400,
            detail="No benchmark items — lock some contacts first (locked contacts with an archived card image are the ground truth).",
        )

    _bench_cancel_event.clear()
    return StreamingResponse(
        _benchmark_generator(models, items, timeout),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/benchmark/stop")
async def stop_benchmark():
    """Stop the in-flight benchmark after the current card finishes."""
    _bench_cancel_event.set()
    return {"status": "stopping"}


# ═══════════════════════════════════════════════════════════
# CONTACTS
# ═══════════════════════════════════════════════════════════


def _contact_to_api(entry: dict) -> dict:
    """Normalise a repository contact entry for the frontend."""
    cd = entry.get("contact_data") or {}
    card_id = entry.get("card_id", "")
    # Check if thumbnail exists on disk
    has_thumbnail = False
    if card_id:
        thumb_path = os.path.join(THUMBNAIL_DIR, f"{card_id}.jpg")
        has_thumbnail = os.path.exists(thumb_path)
        # Also load into memory cache if found on disk
        if has_thumbnail and card_id not in _thumbnail_cache:
            try:
                with open(thumb_path, "rb") as f:
                    _thumbnail_cache[card_id] = f.read()
            except Exception:
                has_thumbnail = False
    return {
        "id": entry.get("id", ""),
        "cardId": card_id,
        "addedAt": (entry.get("added_at") or "")[:10],
        "source": entry.get("source_file", ""),
        "vcf": True,
        "thumbnail": has_thumbnail,
        "locked": bool(entry.get("locked", False)),
        "contact": {
            "fullName": (
                cd.get("fullName")
                or cd.get("full_name")
                or " ".join(
                    p for p in [cd.get("firstName", ""), cd.get("lastName", "")] if p
                ).strip()
                or " ".join(
                    p for p in [cd.get("first_name", ""), cd.get("last_name", "")] if p
                ).strip()
                or cd.get("name", "")
            ),
            "title": cd.get("title", ""),
            "company": cd.get("company", ""),
            "email": cd.get("email", ""),
            "phone": cd.get("phone", ""),
            "website": cd.get("website", ""),
            "linkedin": cd.get("linkedin", ""),
            "address": cd.get("address", ""),
        },
    }


@app.get("/api/contacts")
async def list_contacts():
    contacts = _contacts.get_all()
    return [_contact_to_api(c) for c in contacts]


@app.get("/api/contacts/duplicates")
async def list_duplicate_contacts():
    """Groups of suspected-duplicate contacts (conservative detection).
    Each group: {reason, contacts: [api-shaped, newest first]}."""
    groups = _contacts.find_duplicates()
    return [
        {"reason": g["reason"], "contacts": [_contact_to_api(c) for c in g["contacts"]]}
        for g in groups
    ]


@app.post("/api/contacts/merge")
async def merge_duplicate_contacts(payload: dict):
    """Merge source contacts into a target. Body:
    {"targetId": "...", "sourceIds": ["...", ...]}. Non-destructive on the
    target; sources are deleted after their fields are folded in."""
    target_id = (payload or {}).get("targetId")
    source_ids = (payload or {}).get("sourceIds") or []
    if not target_id or not isinstance(source_ids, list) or not source_ids:
        raise HTTPException(status_code=400, detail="targetId and sourceIds required")
    merged = _contacts.merge_contacts(target_id, source_ids)
    if not merged:
        raise HTTPException(status_code=404, detail="Target contact not found")
    return {"ok": True, "contact": _contact_to_api(merged)}


@app.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    removed = _contacts.remove_contact(contact_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True}


@app.post("/api/contacts")
async def create_contact(contact_data: dict):
    """Create a new contact or update existing by email."""
    # Validate required fields
    if not contact_data.get("contact"):
        raise HTTPException(status_code=400, detail="Missing contact data")

    # Pass camelCase through unchanged — the repository, VCFGenerator
    # and merge logic all key on camelCase. Filter to an allowlist so
    # we never persist junk fields from a misbehaving client.
    frontend_contact = contact_data["contact"]
    allowed = {
        "fullName",
        "firstName",
        "lastName",
        "title",
        "company",
        "email",
        "phone",
        "mobile",
        "website",
        "linkedin",
        "address",
        "city",
        "state",
        "zip",
        "country",
        "notes",
    }
    repo_contact = {k: v for k, v in frontend_contact.items() if k in allowed}

    # add_contact returns a dict: {id, status, additions, conflicts, locked}
    add_result = _contacts.add_contact(
        contact_data=repo_contact,
        source_file=contact_data.get("source", ""),
        vcf_content=contact_data.get("vcfContent", ""),
    )
    contact_id = add_result.get("id")

    contacts = _contacts.get_all()
    created = next((c for c in contacts if c.get("id") == contact_id), None)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create contact")

    return {
        "ok": True,
        "contact": _contact_to_api(created),
        "status": add_result.get("status", "added"),
        "additions": add_result.get("additions", {}),
        "conflicts": add_result.get("conflicts", []),
    }


@app.put("/api/contacts/{contact_id}/lock")
async def set_contact_lock(contact_id: str, payload: dict):
    """Toggle lock status on a contact. Body: {"locked": true|false}.
    A locked contact will not be overwritten by future scans — only
    additive fields are merged and conflicts are surfaced."""
    locked = bool(payload.get("locked", True))
    if not _contacts.set_locked(contact_id, locked):
        raise HTTPException(status_code=404, detail="Contact not found")
    contacts = _contacts.get_all()
    updated = next((c for c in contacts if c.get("id") == contact_id), None)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found after update")
    return {"ok": True, "contact": _contact_to_api(updated)}


@app.post("/api/contacts/{contact_id}/resolve")
async def resolve_contact_conflicts(contact_id: str, payload: dict):
    """Apply partial field updates from the interactive conflict-resolution UI.

    Body: {"updates": {"field": "value", ...}}
    Pass None/"" as a value to clear a field. Returns the updated contact.
    """
    updates = payload.get("updates") or {}
    if not isinstance(updates, dict) or not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    updated = _contacts.apply_field_updates(contact_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"ok": True, "contact": _contact_to_api(updated)}


@app.post("/api/resolve-qr-url")
async def resolve_qr_url_endpoint(payload: dict):
    """User-initiated: fetch a contact page that a card's QR code links to,
    and return the extracted contact fields.

    Body: {"url": "https://..."}
    The URL is validated against an SSRF / scheme / port guard (and an
    optional Google Safe Browsing check) BEFORE any request is made. On
    success returns the extracted fields mapped to the frontend contact
    shape. On a blocked or empty URL returns {"ok": false, "reason": ...}.
    """
    url = (payload or {}).get("url", "")
    if not isinstance(url, str) or not url.strip():
        raise HTTPException(status_code=400, detail="Missing url")

    # Runs blocking network I/O — push to a thread so the event loop is free.
    loop = asyncio.get_event_loop()
    try:
        from utils.qr_url_resolver import resolve_qr_url

        result = await loop.run_in_executor(None, resolve_qr_url, url.strip())
    except Exception as e:  # defensive — resolver shouldn't raise, but be safe
        return {"ok": False, "reason": f"Resolver error: {e}", "contact": {}}

    if not result.get("ok"):
        return {
            "ok": False,
            "reason": result.get("reason") or "Could not resolve URL",
            "contact": {},
        }

    # Map the qr_data-shaped fields to the frontend contact shape.
    from utils.ui_components import qr_to_contact_data

    contact = qr_to_contact_data(result.get("fields") or {})
    # Don't let the resolved page's own URL clobber the original card website
    # unless the page actually provided one; qr_to_contact_data already maps
    # any 'url' field to 'website'.
    return {
        "ok": True,
        "contact": contact,
        "source": result.get("source", ""),
        "finalUrl": result.get("final_url", url),
    }


@app.put("/api/contacts/{contact_id}")
async def update_contact(contact_id: str, contact_data: dict):
    """Update an existing contact.

    Uses a partial-merge against the existing record (via
    `apply_field_updates`) so fields the Edit modal doesn't expose
    — firstName, lastName, notes, city, state, zip, country — are
    preserved instead of being silently wiped.

    Frontend sends camelCase keys; the repository's canonical schema
    is also camelCase (`_MERGEABLE_FIELDS`, VCFGenerator, merge logic
    all key on `fullName`/`firstName`/etc.). No translation needed.
    """
    if not contact_data.get("contact"):
        raise HTTPException(status_code=400, detail="Missing contact data")

    frontend_contact = contact_data["contact"]

    # Allowlist of fields that the Edit modal can write. Pass through
    # with original camelCase keys. Anything else stays untouched on
    # the stored record.
    allowed = {
        "fullName",
        "firstName",
        "lastName",
        "title",
        "company",
        "email",
        "phone",
        "mobile",
        "website",
        "linkedin",
        "address",
        "city",
        "state",
        "zip",
        "country",
        "notes",
    }
    updates = {k: v for k, v in frontend_contact.items() if k in allowed}

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    updated = _contacts.apply_field_updates(contact_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")

    return {"ok": True, "contact": _contact_to_api(updated)}


@app.get("/api/contacts/export/vcf")
async def export_contacts_vcf():
    vcf_text = _contacts.get_all_vcf()
    return StreamingResponse(
        io.BytesIO(vcf_text.encode("utf-8")),
        media_type="text/vcard",
        headers={"Content-Disposition": 'attachment; filename="contacts.vcf"'},
    )


@app.get("/api/contacts/export/xlsx")
async def export_contacts_xlsx():
    contacts = _contacts.get_contact_dicts()
    xlsx_bytes = _exporter.export_to_excel(contacts)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="contacts.xlsx"'},
    )


@app.get("/api/contacts/export/csv")
async def export_contacts_csv():
    contacts = _contacts.get_contact_dicts()
    csv_bytes = _exporter.export_to_outlook_csv(contacts)
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="contacts_outlook.csv"'},
    )


# ─── Export just-scanned cards (Results panel) ─────────────────────────
# Frontend POSTs the cards array from the most recent scan; we return
# the file as a streaming download. This is separate from the contacts
# repository exports so the user can export *this run's* output without
# committing it to the persistent repo.

from fastapi import Body
from pydantic import BaseModel as _BaseModel


class _ScanCard(_BaseModel):
    fullName: Optional[str] = ""
    title: Optional[str] = ""
    company: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    mobile: Optional[str] = ""
    website: Optional[str] = ""
    linkedin: Optional[str] = ""
    address: Optional[str] = ""


class _ScanExportBody(_BaseModel):
    cards: List[dict]  # each item has at least {contact: {...}, vcfContent?: str, filename?: str}


def _frontend_card_to_legacy_dict(card: dict) -> dict:
    """Convert a frontend card (nested .contact shape) to the flat dict
    that ExportProcessor and VCFGenerator expect."""
    c = card.get("contact") or {}
    # Map fullName → full_name, etc.
    return {
        "full_name": c.get("fullName", ""),
        "title": c.get("title", ""),
        "company": c.get("company", ""),
        "email": c.get("email", ""),
        "phone": c.get("phone", ""),
        "mobile": c.get("mobile", ""),
        "website": c.get("website", ""),
        "linkedin": c.get("linkedin", ""),
        "address": c.get("address", ""),
    }


@app.post("/api/scan/export/{fmt}")
async def export_scan(fmt: str, body: _ScanExportBody):
    fmt = fmt.lower()
    if not body.cards:
        raise HTTPException(status_code=400, detail="No cards to export")

    if fmt == "vcf":
        # Prefer the cached vcfContent (already generated during scan), else
        # regenerate from the contact dict.
        from utils.vcf_generator import VCFGenerator

        gen = VCFGenerator()
        parts = []
        for card in body.cards:
            vcf = card.get("vcfContent")
            if not vcf:
                vcf = gen.generate_vcf_string(_frontend_card_to_legacy_dict(card))
            parts.append(vcf)
        payload = "\r\n".join(parts).encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="text/vcard",
            headers={"Content-Disposition": 'attachment; filename="scan_contacts.vcf"'},
        )

    legacy = [_frontend_card_to_legacy_dict(c) for c in body.cards]

    if fmt in ("xlsx", "excel"):
        xlsx_bytes = _exporter.export_to_excel(legacy)
        return StreamingResponse(
            io.BytesIO(xlsx_bytes),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="scan_contacts.xlsx"'},
        )

    if fmt == "csv":
        csv_bytes = _exporter.export_to_outlook_csv(legacy)
        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="scan_contacts_outlook.csv"'},
        )

    if fmt == "zip":
        # Build a ZIP containing all three formats + per-card VCFs
        import zipfile
        from utils.vcf_generator import VCFGenerator

        gen = VCFGenerator()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Combined VCF
            combined_vcf = "\r\n".join(
                card.get("vcfContent")
                or gen.generate_vcf_string(_frontend_card_to_legacy_dict(card))
                for card in body.cards
            )
            zf.writestr("contacts.vcf", combined_vcf)
            zf.writestr("contacts.xlsx", _exporter.export_to_excel(legacy))
            zf.writestr("contacts_outlook.csv", _exporter.export_to_outlook_csv(legacy))
            # Per-card individual VCFs
            for i, card in enumerate(body.cards):
                vcf = card.get("vcfContent") or gen.generate_vcf_string(
                    _frontend_card_to_legacy_dict(card)
                )
                fname = (card.get("filename") or f"card_{i + 1}").replace("/", "_")
                if not fname.endswith(".vcf"):
                    fname += ".vcf"
                zf.writestr(f"per_card/{fname}", vcf)
        return StreamingResponse(
            io.BytesIO(buf.getvalue()),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="scan_results.zip"'},
        )

    raise HTTPException(status_code=400, detail=f"Unknown format: {fmt}")


# ═══════════════════════════════════════════════════════════
# HISTORY
# ═══════════════════════════════════════════════════════════


def _run_to_api(entry) -> dict:
    """Convert HistoryEntry to frontend RunCard shape."""
    d = history_entry_to_dict(entry)
    cards_out = []
    for card in d.get("cards", []):
        cd = card.get("contact_data") or {}
        cards_out.append(
            {
                "contact": {
                    "fullName": (
                        cd.get("fullName")
                        or cd.get("full_name")
                        or " ".join(
                            p for p in [cd.get("firstName", ""), cd.get("lastName", "")] if p
                        ).strip()
                        or " ".join(
                            p for p in [cd.get("first_name", ""), cd.get("last_name", "")] if p
                        ).strip()
                        or cd.get("name", "")
                    ),
                    "company": cd.get("company", ""),
                    "email": cd.get("email", ""),
                    "phone": cd.get("phone", ""),
                }
            }
        )
    exports_out = [
        f.get("name", "") for f in d.get("files", []) if f.get("media_type") not in ("image",)
    ]
    original_files = d.get("settings", {}).get("_original_files", []) or []
    return {
        "id": d["run_id"],
        "createdAt": d["created_at"].replace("T", "T")
        if "T" in d.get("created_at", "")
        else d.get("created_at", "") + "T00:00:00",
        "settings": d.get("settings", {}),
        "cards": cards_out,
        "originalFiles": original_files,
        "exports": exports_out,
    }


@app.get("/api/history")
async def list_history():
    try:
        # _history.list_runs() already returns newest-to-oldest (sorted by mtime desc).
        runs = _history.list_runs()
        return [_run_to_api(r) for r in runs]
    except Exception:
        return []


@app.delete("/api/history/{run_id}")
async def delete_history(run_id: str):
    run_id = _safe_run_id(run_id)  # path-traversal guard
    try:
        _history.delete_run(run_id)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@app.get("/api/history/{run_id}/zip")
async def download_history_zip(run_id: str):
    run_id = _safe_run_id(run_id)  # path-traversal guard
    try:
        zip_bytes = _history.build_run_package(run_id)
        return StreamingResponse(
            io.BytesIO(zip_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="run_{run_id}.zip"'},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


# Map back from CardProcessor's detection_mode strings to the frontend's
# short codes ("Automatic" -> "auto", etc.).
_MODE_REVERSE_MAP = {
    "Automatic": "auto",
    "Single Card": "single",
    "Manual - Single Card": "single",
    "Manual - Grid Layout": "grid",
}


class _SyntheticUpload:
    """Minimal UploadFile-shaped wrapper around in-memory bytes.

    `_scan_generator` only needs `.filename` and `await .read()`, so we
    provide just those two. Used by the relaunch endpoint to feed files
    that were loaded from disk through the same pipeline UploadFile-
    backed scans use, without changing the generator's signature.
    """

    def __init__(self, data: bytes, filename: str):
        self._data = data
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


@app.post("/api/history/{run_id}/relaunch")
async def relaunch_history(run_id: str, request: Request):
    """
    Re-run a past scan against its archived original files.

    Body (all optional — defaults come from the original run's saved settings):
      {
        "model":   "glm-ocr",
        "mode":    "auto" | "single" | "grid",
        "rows":    4, "cols": 2,
        "timeout": 300,
        "row_lines": "0.25,0.5,0.75", "col_lines": "0.5",
        "margin_top": 0.0, "margin_bottom": 1.0,
        "margin_left": 0.0, "margin_right": 1.0,
        "deskew":  false
      }

    Returns the same SSE event stream as `POST /api/scan`. The resulting
    cards are saved as a new history run (so the original run is
    preserved) and merged into the contacts repository following the
    standard lock / merge / conflict rules.
    """
    run_id = _safe_run_id(run_id)

    # Locate the run on disk
    try:
        entry = _history.get_run(run_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")

    settings = entry.settings or {}

    # Find originals
    run_dir = _history._run_path(run_id)
    orig_dir = run_dir / "original"
    if not orig_dir.exists():
        raise HTTPException(
            status_code=400,
            detail="No original files archived for this run — cannot relaunch.",
        )
    orig_files = sorted(p for p in orig_dir.iterdir() if p.is_file())
    if not orig_files:
        raise HTTPException(status_code=400, detail="Original files directory is empty.")

    # Parse body overrides (may be empty)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
    except Exception:
        body = {}

    # Resolve effective settings: body override -> archived setting -> default
    saved_mode = _MODE_REVERSE_MAP.get(settings.get("detection_mode", ""), "auto")
    model = body.get("model") or settings.get("vision_model") or "qwen2.5vl:7b"
    mode = body.get("mode") or saved_mode
    rows = int(body.get("rows", 4))
    cols = int(body.get("cols", 2))
    timeout = int(body.get("timeout") or settings.get("vision_timeout") or 300)
    row_lines = body.get("row_lines", "") or ""
    col_lines = body.get("col_lines", "") or ""
    mt = _clamp01(body.get("margin_top", 0.0), 0.0)
    mb = _clamp01(body.get("margin_bottom", 1.0), 1.0)
    ml = _clamp01(body.get("margin_left", 0.0), 0.0)
    mr = _clamp01(body.get("margin_right", 1.0), 1.0)
    deskew = bool(body.get("deskew", False))

    # Wrap the disk files as SyntheticUploads so _scan_generator can
    # treat them identically to fresh uploads.
    synthetic_files = []
    for p in orig_files:
        try:
            synthetic_files.append(_SyntheticUpload(p.read_bytes(), p.name))
        except Exception:
            continue

    if not synthetic_files:
        raise HTTPException(status_code=500, detail="Could not read any archived original files.")

    return StreamingResponse(
        _scan_generator(
            synthetic_files,
            model,
            mode,
            rows,
            cols,
            timeout,
            row_lines,
            col_lines,
            mt,
            mb,
            ml,
            mr,
            deskew,
            skip_size_check=True,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ═══════════════════════════════════════════════════════════
# THUMBNAIL ENDPOINTS
# ═══════════════════════════════════════════════════════════


@app.get("/api/thumbnails/{card_id}")
async def get_thumbnail(card_id: str, request: Request):
    """Get thumbnail image for a card.

    Cache strategy: emit an ETag built from the on-disk mtime so that
    re-rendered thumbnails (e.g. after a quality-bump migration)
    invalidate the browser cache automatically — no hard-reload needed.
    """
    # Path-traversal guard: validate card_id and resolve a contained path.
    thumb_path = _safe_thumb_path(card_id)

    # Pull the on-disk mtime for ETag generation, if the file exists.
    try:
        mtime = os.path.getmtime(thumb_path) if os.path.exists(thumb_path) else 0
    except OSError:
        mtime = 0
    etag = f'W/"{int(mtime)}"' if mtime else None

    # If client already has this version, short-circuit before reading.
    if etag and request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    thumbnail = _thumbnail_cache.get(card_id)

    # Re-read from disk whenever the disk file is newer than the
    # cached bytes (or the cache is empty). Keying on mtime means the
    # cache stays consistent if the file is regenerated out-of-band.
    cache_mtime = getattr(_thumbnail_cache, "_mtimes", {}).get(card_id, 0)
    if thumbnail is None or mtime > cache_mtime:
        if os.path.exists(thumb_path):
            try:
                with open(thumb_path, "rb") as f:
                    thumbnail = f.read()
                _thumbnail_cache[card_id] = thumbnail
                if not hasattr(_thumbnail_cache, "_mtimes"):
                    _thumbnail_cache._mtimes = {}
                _thumbnail_cache._mtimes[card_id] = mtime
            except Exception:
                pass

    if thumbnail is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    headers = {"Cache-Control": "public, max-age=60, must-revalidate"}
    if etag:
        headers["ETag"] = etag
    return StreamingResponse(
        io.BytesIO(thumbnail),
        media_type="image/jpeg",
        headers=headers,
    )


# ═══════════════════════════════════════════════════════════
# HTML FRONTEND
# ═══════════════════════════════════════════════════════════


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html not found")
    return HTMLResponse(content=index.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    # Default 9247 — deliberately NOT 8501 (Streamlit's default port),
    # which collides with the user's Streamlit projects. Override with
    # the PORT env var if needed.
    port = int(os.environ.get("PORT", "9247"))

    # Auto-reload is OFF by default. With reload=True uvicorn runs a reloader
    # parent that binds the socket and a child that serves. If the child dies
    # hard (e.g. a native segfault in an image/QR library), the parent keeps
    # the port bound: the browser's TCP connect succeeds but no HTTP response
    # ever arrives, so the page just hangs forever with no error anywhere.
    # Without the reloader a crash simply ends the process and frees the port,
    # which fails loudly instead of silently. Set RELOAD=1 for dev.
    reload = os.environ.get("RELOAD", "").strip().lower() in ("1", "true", "yes")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=reload)
