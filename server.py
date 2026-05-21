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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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
# (ext) -> tuple of acceptable leading magic byte sequences
_MAGIC = {
    b"\xff\xd8\xff": "jpeg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"RIFF": "webp",  # RIFF....WEBP
    b"%PDF": "pdf",
    b"\x00\x00\x00\x18ftyp": "heic",
    b"\x00\x00\x00\x1cftyp": "heic",
}


def _validate_upload(filename: str, raw: bytes) -> Optional[str]:
    """Return None if the upload is acceptable, else an error message string."""
    ext = os.path.splitext((filename or "").lower())[1]
    if ext not in _ALLOWED_UPLOAD_EXTS:
        return f"Unsupported file type {ext!r} (allowed: {sorted(_ALLOWED_UPLOAD_EXTS)})"
    if len(raw) == 0:
        return "Empty file"
    if len(raw) > MAX_UPLOAD_BYTES:
        return f"File too large ({len(raw)} bytes > {MAX_UPLOAD_BYTES} limit)"
    # Magic-byte sniff (best-effort; HEIC/WEBP have ftyp/RIFF containers)
    head = raw[:16]
    if not any(head.startswith(sig) or sig in head[:16] for sig in _MAGIC):
        return "File content does not match a supported image/PDF format"
    return None


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
        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError(f"Could not decode image: {filename}")
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


def _create_thumbnail(
    card_image: np.ndarray, max_size: Tuple[int, int] = (200, 200)
) -> Optional[bytes]:
    """
    Create a thumbnail from card image.

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

        # Create thumbnail (preserves aspect ratio)
        pil_img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Convert to JPEG bytes
        img_byte_arr = io.BytesIO()
        pil_img.save(img_byte_arr, format="JPEG", quality=85)
        return img_byte_arr.getvalue()
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None


def _contact_data_to_frontend(
    card: dict, source_file: str, idx: int, run_id: Optional[str] = None
) -> dict:
    """Map CardProcessor output dict to the shape the React frontend expects."""
    cd = card.get("contact_data") or {}
    via_qr = card.get("via_qr")
    if via_qr is True:
        via = "QR Code"
    elif via_qr == "hybrid":
        via = "QR + GLM-OCR"
    else:
        via = "GLM-OCR"
    processing_time = card.get("processing_time", 1.0)

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

    return {
        "id": idx + 1,
        "cardId": card_id,
        "filename": card.get("filename", f"card_{idx + 1}.vcf"),
        "locked": False,
        "source": source_file,
        "via": via,
        "time": round(processing_time, 1),
        "thumbnail": has_thumbnail,
        "contact": {
            "fullName": cd.get("full_name") or cd.get("name", ""),
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


async def _scan_generator(
    files: List[UploadFile],
    model: str,
    mode: str,
    rows: int,
    cols: int,
    timeout: int,
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
            _upload_err = _validate_upload(filename, raw)
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
                    page_cards = await loop.run_in_executor(
                        None,
                        lambda b=bgr, r=rgb: processor.process_batch(
                            image_bgr=b,
                            image_rgb=r,
                            detection_mode=detection_mode,
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
                cards = await loop.run_in_executor(
                    None,
                    lambda b=bgr, r=rgb: processor.process_batch(
                        image_bgr=b,
                        image_rgb=r,
                        detection_mode=detection_mode,
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
                await loop.run_in_executor(
                    None,
                    lambda c=card, cid=card_id: _contacts.add_contact(
                        contact_data=c.get("contact_data", {}),
                        source_file=c.get("_source_file", ""),
                        card_id=cid,
                    ),
                )
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


@app.post("/api/scan")
async def scan(
    files: List[UploadFile] = File(...),
    model: str = Form("glm-ocr"),
    mode: str = Form("auto"),
    rows: int = Form(4),
    cols: int = Form(2),
    timeout: int = Form(300),
):
    """Stream scan progress via SSE (text/event-stream)."""
    return StreamingResponse(
        _scan_generator(files, model, mode, rows, cols, timeout),
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
        "contact": {
            "fullName": cd.get("full_name") or cd.get("name", ""),
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

    # Convert frontend field names to repository format
    frontend_contact = contact_data["contact"]
    repo_contact = {}

    # Map field names
    field_map = {
        "fullName": "full_name",
        "title": "title",
        "company": "company",
        "email": "email",
        "phone": "phone",
        "mobile": "mobile",
        "website": "website",
        "linkedin": "linkedin",
        "address": "address",
    }

    for frontend_key, repo_key in field_map.items():
        if frontend_key in frontend_contact:
            repo_contact[repo_key] = frontend_contact[frontend_key]

    # Add contact (add_contact handles duplicates by email)
    contact_id = _contacts.add_contact(
        contact_data=repo_contact,
        source_file=contact_data.get("source", ""),
        vcf_content=contact_data.get("vcfContent", ""),
    )

    # Find the created/updated contact
    contacts = _contacts.get_all()
    created = next((c for c in contacts if c.get("id") == contact_id), None)
    if not created:
        raise HTTPException(status_code=500, detail="Failed to create contact")

    return {"ok": True, "contact": _contact_to_api(created)}


@app.put("/api/contacts/{contact_id}")
async def update_contact(contact_id: str, contact_data: dict):
    """Update an existing contact."""
    # Validate required fields
    if not contact_data.get("contact"):
        raise HTTPException(status_code=400, detail="Missing contact data")

    # Convert frontend field names to repository format
    frontend_contact = contact_data["contact"]
    repo_contact = {}

    # Map field names
    field_map = {
        "fullName": "full_name",
        "title": "title",
        "company": "company",
        "email": "email",
        "phone": "phone",
        "mobile": "mobile",
        "website": "website",
        "linkedin": "linkedin",
        "address": "address",
    }

    for frontend_key, repo_key in field_map.items():
        if frontend_key in frontend_contact:
            repo_contact[repo_key] = frontend_contact[frontend_key]

    # Update contact
    updated = _contacts.update_contact(contact_id, repo_contact)
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
                    "fullName": cd.get("full_name") or cd.get("name", ""),
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


# ═══════════════════════════════════════════════════════════
# THUMBNAIL ENDPOINTS
# ═══════════════════════════════════════════════════════════


@app.get("/api/thumbnails/{card_id}")
async def get_thumbnail(card_id: str):
    """Get thumbnail image for a card."""
    # Path-traversal guard: validate card_id and resolve a contained path.
    thumb_path = _safe_thumb_path(card_id)

    thumbnail = _thumbnail_cache.get(card_id)

    # Fallback: try loading from disk (path already validated + contained)
    if thumbnail is None:
        if os.path.exists(thumb_path):
            try:
                with open(thumb_path, "rb") as f:
                    thumbnail = f.read()
                _thumbnail_cache[card_id] = thumbnail
            except Exception:
                pass

    if thumbnail is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return StreamingResponse(
        io.BytesIO(thumbnail),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
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

    port = int(os.environ.get("PORT", "8501"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
