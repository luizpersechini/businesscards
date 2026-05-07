"""
Business Card Scanner Application
Main Streamlit interface for processing business cards and generating VCF files.
"""

import streamlit as st
import cv2
import numpy as np
from PIL import Image
import os
import sys
import threading
from io import BytesIO
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

# Add utils to path
sys.path.append(os.path.dirname(__file__))

from utils.improved_card_detector import ImprovedCardDetector
from utils.qr_reader import QRReader
from utils.providers.factory import ProviderFactory
from utils.providers.base import VisionProvider
from utils.models import ProviderType, ProviderStatus, ContactInfo, ScanResult
from utils.ms_graph import MSGraphContactManager
from utils.vcf_generator import VCFGenerator
from utils.export_processor import ExportProcessor
from utils.history_manager import HistoryManager


# Page configuration
st.set_page_config(
    page_title="Business Card Scanner",
    page_icon="📇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .step-header {
        font-size: 1.5rem;
        font-weight: bold;
        color: #2ca02c;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
    }
    .status-success {
        color: #2ca02c;
        font-weight: bold;
    }
    .status-processing {
        color: #ff7f0e;
        font-weight: bold;
    }
    .status-warning {
        color: #d62728;
        font-weight: bold;
    }
    .contact-preview {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

history_manager = HistoryManager()

# Initialize provider factory (LOCAL-FIRST priority)
provider_factory = ProviderFactory()

# Initialize MS Graph manager (lazy - only if configured)
ms_graph_manager = MSGraphContactManager()


def _background_preload_ollama(model: str = "glm-ocr") -> None:
    """
    Fire-and-forget background thread: loads the target Ollama vision model
    into GPU/RAM via a tiny keep_alive=-1 request.  Runs once at app startup
    so the model is warm before the user submits their first card.
    """
    try:
        import requests, base64
        dummy = np.ones((4, 4, 3), dtype=np.uint8) * 255
        _, buf = cv2.imencode('.jpg', dummy, [cv2.IMWRITE_JPEG_QUALITY, 50])
        img_b64 = base64.b64encode(buf.tobytes()).decode()
        requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": "OK",
                "images": [img_b64],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_predict": 1},
            },
            timeout=300,
        )
    except Exception:
        pass  # Non-blocking — failures are silent


def initialize_session_state():
    """Initialize session state variables."""
    if 'processed_cards' not in st.session_state:
        st.session_state.processed_cards = []
    if 'processing_complete' not in st.session_state:
        st.session_state.processing_complete = False
    if 'current_history_run' not in st.session_state:
        st.session_state.current_history_run = None
    if 'history_runs_dirty' not in st.session_state:
        st.session_state.history_runs_dirty = True
    if 'history_runs_cache' not in st.session_state:
        st.session_state.history_runs_cache = []
    if 'history_delete_request' not in st.session_state:
        st.session_state.history_delete_request = None
    if 'history_message' not in st.session_state:
        st.session_state.history_message = None
    if 'history_relaunch_payload' not in st.session_state:
        st.session_state.history_relaunch_payload = None
    if 'history_active_files_data' not in st.session_state:
        st.session_state.history_active_files_data = None
    if 'history_view_run' not in st.session_state:
        st.session_state.history_view_run = None
    if 'history_recorded_exports' not in st.session_state:
        st.session_state.history_recorded_exports = set()
    if 'ollama_preload_started' not in st.session_state:
        st.session_state.ollama_preload_started = False
    # Outlook / MS Graph two-step auth flow
    if 'outlook_auth_flow' not in st.session_state:
        st.session_state.outlook_auth_flow = None    # pending MSAL device flow dict
    if 'outlook_auth_code' not in st.session_state:
        st.session_state.outlook_auth_code = None    # user_code to display
    if 'outlook_auth_uri' not in st.session_state:
        st.session_state.outlook_auth_uri = None     # verification_uri


def load_image(uploaded_file):
    """Load an uploaded image file."""
    image = Image.open(uploaded_file)
    return np.array(image)


def draw_grid_overlay(image: np.ndarray, rows: int, cols: int,
                      margin_top: int = 0, margin_bottom: int = 0,
                      margin_left: int = 0, margin_right: int = 0) -> np.ndarray:
    """
    Draw grid lines on image for visualization.
    
    Args:
        image: Input image
        rows: Number of rows
        cols: Number of columns
        margin_top/bottom/left/right: Margins as percentages
        
    Returns:
        Image with grid overlay
    """
    overlay = image.copy()
    height, width = overlay.shape[:2]
    
    # Calculate margins
    top_skip = int(height * margin_top / 100)
    bottom_skip = int(height * margin_bottom / 100)
    left_skip = int(width * margin_left / 100)
    right_skip = int(width * margin_right / 100)
    
    # Working area
    working_height = height - top_skip - bottom_skip
    working_width = width - left_skip - right_skip
    
    card_height = working_height // rows
    card_width = working_width // cols
    
    # Draw margin boundaries (red dashed)
    if margin_top > 0:
        cv2.line(overlay, (0, top_skip), (width, top_skip), (0, 0, 255), 2)
    if margin_bottom > 0:
        cv2.line(overlay, (0, height - bottom_skip), (width, height - bottom_skip), (0, 0, 255), 2)
    if margin_left > 0:
        cv2.line(overlay, (left_skip, 0), (left_skip, height), (0, 0, 255), 2)
    if margin_right > 0:
        cv2.line(overlay, (width - right_skip, 0), (width - right_skip, height), (0, 0, 255), 2)
    
    # Draw grid lines (green)
    # Horizontal lines
    for row in range(1, rows):
        y = top_skip + (row * card_height)
        cv2.line(overlay, (left_skip, y), (width - right_skip, y), (0, 255, 0), 3)
    
    # Vertical lines
    for col in range(1, cols):
        x = left_skip + (col * card_width)
        cv2.line(overlay, (x, top_skip), (x, height - bottom_skip), (0, 255, 0), 3)
    
    # Draw outer box (yellow)
    cv2.rectangle(overlay, (left_skip, top_skip), 
                 (width - right_skip, height - bottom_skip), (0, 255, 255), 3)
    
    # Add labels
    card_num = 1
    for row in range(rows):
        for col in range(cols):
            y = top_skip + (row * card_height) + card_height // 2
            x = left_skip + (col * card_width) + card_width // 2
            cv2.putText(overlay, f'Card {card_num}', (x - 40, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 255), 3)
            card_num += 1
    
    return overlay


def qr_data_is_sufficient(qr_data: Optional[dict]) -> bool:
    """
    Return True if QR data has enough info to skip vision analysis.
    Criterion: must contain at least one valid email address.
    """
    if not qr_data:
        return False
    # Check 'emails' list
    emails = qr_data.get('emails', [])
    if isinstance(emails, list) and any(e and '@' in e for e in emails):
        return True
    # Check plain 'email' key
    email = qr_data.get('email', '')
    if isinstance(email, str) and '@' in email:
        return True
    return False


def qr_to_contact_data(qr_data: dict) -> dict:
    """
    Convert QR code data to contact data format.
    
    Args:
        qr_data: QR code extracted data
        
    Returns:
        Contact data dictionary
    """
    contact = {}
    
    # Extract from vCard format if present
    if 'full_name' in qr_data:
        contact['fullName'] = qr_data['full_name']
    if 'first_name' in qr_data:
        contact['firstName'] = qr_data['first_name']
    if 'last_name' in qr_data:
        contact['lastName'] = qr_data['last_name']
    if 'organization' in qr_data:
        contact['company'] = qr_data['organization']
    if 'title' in qr_data:
        contact['title'] = qr_data['title']
    
    # Handle emails (can be list)
    if 'emails' in qr_data and qr_data['emails']:
        if isinstance(qr_data['emails'], list):
            contact['email'] = qr_data['emails'][0]
        else:
            contact['email'] = qr_data['emails']
    
    # Handle phones (can be list)
    if 'phones' in qr_data and qr_data['phones']:
        if isinstance(qr_data['phones'], list):
            contact['phone'] = qr_data['phones'][0]
            if len(qr_data['phones']) > 1:
                contact['mobile'] = qr_data['phones'][1]
        else:
            contact['phone'] = qr_data['phones']
    
    # URL
    if 'url' in qr_data:
        contact['website'] = qr_data['url']
    
    # Address (usually semicolon separated in vCard)
    if 'address' in qr_data:
        addr = qr_data['address']
        if isinstance(addr, str):
            contact['address'] = addr.replace(', ', '\n')
        else:
            contact['address'] = str(addr)
    
    # Add note if QR data was used
    contact['notes'] = 'Contact extracted from QR code'
    
    return contact


def split_image_grid(image: np.ndarray, rows: int, cols: int,
                     margin_top: int = 0, margin_bottom: int = 0,
                     margin_left: int = 0, margin_right: int = 0) -> List[Tuple[np.ndarray, None]]:
    """
    Split an image into a grid of cards with margin support.
    
    Args:
        image: Input image
        rows: Number of rows
        cols: Number of columns
        margin_top: Top margin as percentage
        margin_bottom: Bottom margin as percentage
        margin_left: Left margin as percentage
        margin_right: Right margin as percentage
        
    Returns:
        List of (card_image, None) tuples
    """
    height, width = image.shape[:2]
    
    # Apply margins
    top_skip = int(height * margin_top / 100)
    bottom_skip = int(height * margin_bottom / 100)
    left_skip = int(width * margin_left / 100)
    right_skip = int(width * margin_right / 100)
    
    # Working area after margins
    working_height = height - top_skip - bottom_skip
    working_width = width - left_skip - right_skip
    
    card_height = working_height // rows
    card_width = working_width // cols
    
    cards = []
    
    for row in range(rows):
        for col in range(cols):
            y1 = top_skip + (row * card_height)
            y2 = top_skip + ((row + 1) * card_height) if row < rows - 1 else (height - bottom_skip)
            x1 = left_skip + (col * card_width)
            x2 = left_skip + ((col + 1) * card_width) if col < cols - 1 else (width - right_skip)
            
            card_image = image[y1:y2, x1:x2]
            cards.append((card_image, None))
    
    return cards


def build_history_settings(
    vision_model: str,
    vision_timeout: int,
    detection_mode: str,
    grid_rows: int,
    grid_cols: int,
    min_percent: int,
    max_percent: int,
    margin_top: int,
    margin_bottom: int,
    margin_left: int,
    margin_right: int,
) -> dict:
    """Prepare metadata payload for history entries."""
    return {
        "vision_model": vision_model,
        "vision_timeout": vision_timeout,
        "detection_mode": detection_mode,
        "grid_rows": grid_rows,
        "grid_cols": grid_cols,
        "min_card_percent": min_percent,
        "max_card_percent": max_percent,
        "margins": {
            "top": margin_top,
            "bottom": margin_bottom,
            "left": margin_left,
            "right": margin_right,
        },
    }


def save_history_run(processed_cards: List[dict], uploaded_files, settings: dict) -> Optional[str]:
    """Persist the current processing results into the history archive."""
    if not processed_cards:
        return None

    original_files_payload = []
    for uploaded in uploaded_files:
        try:
            data = uploaded.getvalue()
        except Exception:
            data = None

        if not data:
            continue

        original_files_payload.append(
            {
                "name": getattr(uploaded, "name", f"source_{len(original_files_payload)+1}.png"),
                "data": data,
                "media_type": "image",
            }
        )

    if not original_files_payload:
        st.warning("⚠️ Could not capture original upload files for history archive.")

    try:
        entry = history_manager.create_run(
            settings=settings,
            original_files=original_files_payload,
            processed_cards=processed_cards,
        )
        st.session_state.current_history_run = entry.run_id
        st.session_state.history_runs_dirty = True
        st.session_state.history_recorded_exports = set()
        return entry.run_id
    except Exception as err:
        st.warning(f"⚠️ Could not store history entry: {err}")
        return None


def update_history_card_entry(
    card_index: int,
    contact_data: Optional[dict] = None,
    locked: Optional[bool] = None,
    vcf_content: Optional[str] = None,
    card_image: Optional[np.ndarray] = None,
    filename: Optional[str] = None,
) -> None:
    """Update a single card entry inside the persisted history run."""
    run_id = st.session_state.get("current_history_run")
    if not run_id:
        return

    try:
        history_manager.update_card(
            run_id=run_id,
            card_index=card_index,
            contact_data=contact_data,
            locked=locked,
            vcf_content=vcf_content,
            card_image=card_image,
            filename=filename,
        )
        st.session_state.history_runs_dirty = True
    except Exception as err:
        st.warning(f"⚠️ Could not update history card {card_index}: {err}")


def archive_export(filename: str, data: Any, media_type: str) -> None:
    """Persist export artifacts to the history archive (once per run)."""
    run_id = st.session_state.get("current_history_run")
    if not run_id or data is None:
        return

    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data

    if not data_bytes:
        return

    recorded = st.session_state.setdefault("history_recorded_exports", set())
    key = f"{run_id}:{filename}"
    if key in recorded:
        return

    try:
        history_manager.register_export(run_id, filename, data_bytes, media_type=media_type)
        recorded.add(key)
        st.session_state.history_runs_dirty = True
    except Exception as err:
        st.warning(f"⚠️ Could not archive '{filename}': {err}")


class HistoryFileWrapper(BytesIO):
    """Wrapper to mimic Streamlit's UploadedFile for history replays."""

    def __init__(self, data: bytes, name: str) -> None:
        super().__init__(data)
        self.name = name

    def getvalue(self) -> bytes:  # type: ignore[override]
        return super().getvalue()


def get_cached_history_runs():
    """Fetch cached history runs, refreshing from disk when marked dirty."""
    if st.session_state.get("history_runs_dirty", True):
        try:
            st.session_state.history_runs_cache = history_manager.list_runs()
        except Exception as err:
            st.warning(f"⚠️ Could not load scan history: {err}")
            st.session_state.history_runs_cache = []
        st.session_state.history_runs_dirty = False
    return st.session_state.history_runs_cache


def handle_history_delete_request() -> None:
    """Delete history entries flagged for removal."""
    run_id = st.session_state.get("history_delete_request")
    if not run_id:
        return

    try:
        history_manager.delete_run(run_id)
        st.session_state.history_runs_dirty = True
        st.session_state.history_message = f"🗑️ Removed history entry {run_id}"
    except Exception as err:
        st.session_state.history_message = f"⚠️ Failed to delete history entry {run_id}: {err}"
    finally:
        st.session_state.history_delete_request = None


def schedule_history_relaunch(run_id: str, files_data: List[Dict[str, Any]], settings: Dict[str, Any]) -> None:
    """Store payload for history replay and trigger rerun."""
    if not files_data:
        st.warning("⚠️ No stored files available for this history entry.")
        return
    st.session_state.history_relaunch_payload = {
        "run_id": run_id,
        "files": files_data,
        "settings": settings,
    }
    st.session_state.history_active_files_data = files_data
    st.rerun()


def render_history_panel() -> None:
    """Render the history sidebar/section with filters and actions."""
    st.markdown("## 🗂️ Scan History")
    with st.expander("🗂️ View Saved Runs", expanded=False):
        history_runs = get_cached_history_runs()
        if not history_runs:
            st.info("History is empty. Process cards to build your archive.")
            return

        run_datetimes = []
        for entry in history_runs:
            try:
                run_datetimes.append(datetime.fromisoformat(entry.created_at))
            except Exception:
                run_datetimes.append(datetime.now())

        min_date = min(run_datetimes).date()
        max_date = max(run_datetimes).date()

        filter_col1, filter_col2 = st.columns([1.6, 1.2])
        with filter_col1:
            date_range = st.date_input(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key="history_date_filter",
            )
        with filter_col2:
            status_filter = st.selectbox(
                "Entries to show",
                options=["All entries", "With contacts only", "Empty runs"],
                index=0,
                key="history_status_filter",
            )

        if isinstance(date_range, tuple):
            start_date, end_date = date_range
        else:
            start_date = end_date = date_range

        filtered = []
        for entry, run_dt in zip(history_runs, run_datetimes):
            run_date = run_dt.date()
            if start_date and run_date < start_date:
                continue
            if end_date and run_date > end_date:
                continue

            total_cards = len(entry.cards)
            if status_filter == "With contacts only" and total_cards == 0:
                continue
            if status_filter == "Empty runs" and total_cards > 0:
                continue

            filtered.append((entry, run_dt))

        if not filtered:
            st.warning("No history entries match the selected filters.")
            return

        for entry, run_dt in filtered:
            total_cards = len(entry.cards)
            emails = sum(1 for card in entry.cards if card.contact_data.get("email"))
            phones = sum(1 for card in entry.cards if card.contact_data.get("phone"))
            originals = len(entry.original_files)

            st.markdown("---")
            header_cols = st.columns([2.8, 1.2, 1.2, 1.2])
            with header_cols[0]:
                st.markdown(f"**{run_dt.strftime('%Y-%m-%d %H:%M:%S')}**")
                st.caption(f"`{entry.run_id}` · {entry.settings.get('detection_mode', 'Automatic')} · {entry.settings.get('vision_model', 'llava:13b')}")
            with header_cols[1]:
                st.markdown(f"**Cards:** {total_cards}")
                st.caption(f"{emails} emails · {phones} phones")
            with header_cols[2]:
                st.markdown(f"**Images:** {originals}")
                st.caption("Stored uploads")
            with header_cols[3]:
                st.markdown("**Exports:**")
                st.caption(f"{len(entry.exports)} file(s)")

            action_cols = st.columns([1, 1, 1, 1])
            view_key = f"history_view_{entry.run_id}"
            download_key = f"history_download_{entry.run_id}"
            relaunch_key = f"history_relaunch_{entry.run_id}"
            delete_key = f"history_delete_{entry.run_id}"

            with action_cols[0]:
                if st.button("👀 View", key=view_key):
                    if st.session_state.history_view_run == entry.run_id:
                        st.session_state.history_view_run = None
                    else:
                        st.session_state.history_view_run = entry.run_id
                    st.rerun()

            with action_cols[1]:
                try:
                    zip_bytes = history_manager.build_run_package(entry.run_id)
                    st.download_button(
                        label="💾 ZIP",
                        data=zip_bytes,
                        file_name=f"history_{entry.run_id}.zip",
                        mime="application/zip",
                        key=download_key,
                    )
                except Exception as err:
                    st.warning(f"⚠️ ZIP unavailable: {err}")

            with action_cols[2]:
                if st.button("🔁 Relaunch", key=relaunch_key):
                    run_path = history_manager.base_dir / entry.run_id
                    files_data = []
                    for file_info in entry.original_files:
                        file_path = run_path / file_info.path
                        if file_path.exists():
                            try:
                                files_data.append(
                                    {
                                        "name": file_info.name,
                                        "data": file_path.read_bytes(),
                                    }
                                )
                            except Exception:
                                continue
                    schedule_history_relaunch(entry.run_id, files_data, entry.settings)

            with action_cols[3]:
                if st.button("🗑️ Delete", key=delete_key):
                    st.session_state.history_delete_request = entry.run_id
                    st.rerun()

            if st.session_state.history_view_run == entry.run_id:
                with st.container():
                    st.write("**Contacts saved:**")
                    if entry.cards:
                        for card in entry.cards:
                            contact = card.contact_data
                            name = contact.get("fullName") or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                            company = contact.get("company", "—")
                            email = contact.get("email", "—")
                            phone = contact.get("phone", "—")
                            st.markdown(f"- **{name}** · {company} · ✉️ {email} · ☎️ {phone}")
                    else:
                        st.caption("This run stored no contacts.")

                    if entry.exports:
                        st.write("**Stored export files:**")
                        for export_file in entry.exports:
                            st.caption(f"- {export_file.name} ({export_file.media_type})")
                    else:
                        st.caption("No export files archived yet.")


def handle_history_relaunch(
    current_vision_model: str,
    current_vision_timeout: int,
    current_detection_mode: str,
    current_grid_rows: int,
    current_grid_cols: int,
    min_card_percent: int,
    max_card_percent: int,
    margin_top: int,
    margin_bottom: int,
    margin_left: int,
    margin_right: int,
) -> Optional[List[HistoryFileWrapper]]:
    """Reprocess a stored history entry if a relaunch payload is queued."""
    payload = st.session_state.get("history_relaunch_payload")
    if not payload:
        return None

    st.session_state.history_relaunch_payload = None

    files_data = payload.get("files") or []
    if not files_data:
        st.warning("⚠️ History entry has no stored files to reprocess.")
        return None

    payload_settings = payload.get("settings") or {}
    margins = payload_settings.get("margins") or {}

    vision_model = payload_settings.get("vision_model", current_vision_model)
    vision_timeout = payload_settings.get("vision_timeout", current_vision_timeout)
    detection_mode = payload_settings.get("detection_mode", current_detection_mode)
    grid_rows = payload_settings.get("grid_rows", current_grid_rows)
    grid_cols = payload_settings.get("grid_cols", current_grid_cols)
    min_percent = payload_settings.get("min_card_percent", min_card_percent)
    max_percent = payload_settings.get("max_card_percent", max_card_percent)
    margin_top_val = margins.get("top", margin_top)
    margin_bottom_val = margins.get("bottom", margin_bottom)
    margin_left_val = margins.get("left", margin_left)
    margin_right_val = margins.get("right", margin_right)

    wrappers = [HistoryFileWrapper(file["data"], file["name"]) for file in files_data]

    with st.spinner("🔁 Reprocessing saved history entry..."):
        processed_cards = process_business_cards(
            wrappers,
            vision_model,
            vision_timeout,
            detection_mode,
            grid_rows,
            grid_cols,
            min_percent,
            max_percent,
            margin_top_val,
            margin_bottom_val,
            margin_left_val,
            margin_right_val,
        )

    st.session_state.processed_cards = processed_cards
    st.session_state.processing_complete = True
    st.session_state.history_active_files_data = files_data

    history_settings = build_history_settings(
        vision_model,
        vision_timeout,
        detection_mode,
        grid_rows,
        grid_cols,
        min_percent,
        max_percent,
        margin_top_val,
        margin_bottom_val,
        margin_left_val,
        margin_right_val,
    )
    run_id = save_history_run(processed_cards, wrappers, history_settings)
    if run_id:
        st.session_state.history_message = f"🔁 Reprocessed history run {payload.get('run_id')} → new run {run_id}"
    else:
        st.session_state.history_message = f"🔁 Reprocessed history run {payload.get('run_id')}"

    return wrappers
def process_single_card_retry(card_image_rgb, vision_model, vision_timeout):
    """
    Retry processing a single card.
    
    Args:
        card_image_rgb: Card image in RGB format
        vision_model: Ollama vision model name
        vision_timeout: Timeout for vision processing
    
    Returns:
        Dictionary with reprocessed card data or None if failed
    """
    try:
        # Convert RGB to BGR for OpenCV
        card_image = cv2.cvtColor(card_image_rgb, cv2.COLOR_RGB2BGR)
        
        # Initialize processors
        qr_reader = QRReader()
        vcf_generator = VCFGenerator()

        # QR Code Detection
        qr_data = None
        try:
            qr_results = qr_reader.detect_and_decode(card_image)
            if qr_results:
                qr_data = qr_reader.extract_contact_info(qr_results)
        except Exception as e:
            st.warning(f"⚠️ QR code reading failed: {str(e)}")
        
        # QR-FIRST: skip vision entirely when QR has sufficient data
        if qr_data_is_sufficient(qr_data):
            st.info("⚡ QR code has complete data — skipping vision analysis.")
            contact_data = qr_to_contact_data(qr_data)
        else:
            # Extract contact information (Vision mode)
            # Use provider factory with local-first fallback
            selected_provider = st.session_state.get('selected_provider', None)
            scan_result = provider_factory.extract_with_fallback(
                card_image,
                qr_data,
                preferred=selected_provider,
                timeout=vision_timeout
            )
            contact_data = scan_result.contact.to_legacy_dict() if scan_result.contact and scan_result.contact.has_minimum_data() else (scan_result.error or {})
            if isinstance(contact_data, str):
                contact_data = {"error": contact_data}

            if 'error' in contact_data:
                if qr_data:
                    st.warning("⚠️ Vision failed — falling back to QR code data.")
                    contact_data = qr_to_contact_data(qr_data)
                else:
                    st.error(f"❌ Vision processing error: {contact_data.get('error', 'Unknown')}")
                    return None

        if not contact_data or 'error' in contact_data:
            return None
        
        # Generate VCF
        vcf_string = vcf_generator.generate_vcf_string(contact_data)
        filename = vcf_generator.contact_to_filename(contact_data)
        
        return {
            'filename': filename,
            'contact_data': contact_data,
            'vcf_content': vcf_string
        }
    
    except Exception as e:
        st.error(f"❌ Retry failed: {str(e)}")
        return None


def process_business_cards(uploaded_files, vision_model, vision_timeout, detection_mode, grid_rows, grid_cols, min_percent, max_percent, margin_top, margin_bottom, margin_left, margin_right):
    """
    Main processing pipeline for business cards.
    
    Args:
        uploaded_files: List of uploaded image files
        vision_model: Vision model name
        vision_timeout: Timeout for vision processing
        detection_mode: Detection mode (Automatic/Manual)
        grid_rows: Number of rows for grid layout
        grid_cols: Number of columns for grid layout
        min_percent: Minimum card size percentage
        max_percent: Maximum card size percentage
        margin_top/bottom/left/right: Margins for grid layout
    """
    # Initialize processors
    improved_detector = ImprovedCardDetector(min_area_percent=min_percent, max_area_percent=max_percent)
    qr_reader = QRReader()
    vcf_generator = VCFGenerator()

    # --- Vision warmup: force model into RAM before processing cards ---
    # Uses st.status for step-by-step visibility so the user knows exactly
    # what is happening during the (potentially slow) first model load.
    import time as _time

    warmup_ok = False
    warmup_provider = "none"

    with st.status("🔥 Preparing vision model...", expanded=True) as _warmup_status:
        # Step 1 — quick connectivity + model availability check
        st.write("🔍 Step 1/3 — Checking provider availability...")
        all_statuses = provider_factory.get_all_statuses()

        available_local = [
            (pt, info) for pt, info in all_statuses.items()
            if info.get("is_local") and info.get("status") == "available"
        ]
        available_cloud = [
            (pt, info) for pt, info in all_statuses.items()
            if not info.get("is_local") and info.get("status") == "available"
        ]

        for pt, info in all_statuses.items():
            icon = "✅" if info["status"] == "available" else "❌"
            kind = "local" if info["is_local"] else "cloud"
            err = f" — {info['error']}" if info.get("error") else ""
            st.write(f"  {icon} **{pt.value}** ({kind}, priority {info['priority']}){err}")

        if not available_local and not available_cloud:
            _warmup_status.update(
                label="❌ No vision providers available — check Ollama / API keys",
                state="error", expanded=True
            )
        else:
            # Step 2 — determine which provider will be used
            if available_local:
                chosen_pt, chosen_info = available_local[0]
                st.write(f"📦 Step 2/3 — Selected **{chosen_pt.value}** "
                         f"(model: `{chosen_info['model']}`)")
            else:
                chosen_pt, chosen_info = available_cloud[0]
                st.write(f"☁️ Step 2/3 — No local model available. "
                         f"Using cloud: **{chosen_pt.value}**")

            # Step 3 — actual warmup (slow: model loads from disk into RAM)
            st.write("🚀 Step 3/3 — Loading model into memory "
                     "(first run can take 30–120 s)...")
            _t0 = _time.time()
            warmup_ok, warmup_provider = provider_factory.warmup_best_provider()
            _elapsed = int(_time.time() - _t0)

            if warmup_ok:
                _warmup_status.update(
                    label=f"✅ Vision model ready ({warmup_provider}) — loaded in {_elapsed}s",
                    state="complete", expanded=False
                )
            else:
                st.write(
                    f"⚠️ Warmup returned failure after {_elapsed}s. "
                    "Processing will still attempt all configured providers."
                )
                _warmup_status.update(
                    label="⚠️ Warmup inconclusive — will attempt processing anyway",
                    state="error", expanded=True
                )
    
    all_processed_cards = []
    
    # Process each uploaded file
    for file_idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 📄 Processing: {uploaded_file.name}")
        
        # Create columns for progress display
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("#### Original Image")
            image = load_image(uploaded_file)
            st.image(image)
        
        # Convert to OpenCV format
        cv_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # Step 1: Detect cards
        if detection_mode == "Manual - Single Card":
            with st.spinner("📋 Processing as single card..."):
                detected_cards = [(cv_image, None)]
                st.success(f"✅ Processing entire image as 1 card")
        
        elif detection_mode == "Manual - Grid Layout":
            with st.spinner(f"✂️ Splitting into {grid_rows}x{grid_cols} grid..."):
                detected_cards = split_image_grid(cv_image, grid_rows, grid_cols,
                                                 margin_top, margin_bottom, margin_left, margin_right)
                st.success(f"✅ Split into {len(detected_cards)} cards from grid")
        
        elif detection_mode == "Automatic":
            with st.spinner("✨ Detecting cards with document scanner algorithm..."):
                detected_cards = improved_detector.detect_cards(cv_image)

                # Grid-layout fallback: if auto-detection found very few cards
                # but the image looks like a multi-card scan (tall or wide),
                # infer a grid from the image aspect ratio and split uniformly —
                # the same logic used by "Manual - Grid Layout".
                if len(detected_cards) < 4:
                    h_img, w_img = cv_image.shape[:2]
                    aspect = w_img / h_img if h_img > 0 else 1.0
                    # Infer grid from aspect ratio.
                    # Portrait (tall): 4 rows × 2 cols
                    # Square / near-square: 4 rows × 2 cols (most common scan layout)
                    # Landscape (wide): 2 rows × 4 cols
                    if aspect < 1.4:
                        inferred_rows, inferred_cols = 4, 2
                    else:
                        inferred_rows, inferred_cols = 2, 4

                    grid_cards = split_image_grid(cv_image, inferred_rows, inferred_cols)
                    if len(grid_cards) > len(detected_cards):
                        detected_cards = grid_cards
                        st.info(
                            f"🔲 Auto-detected {len(detected_cards)} cards using "
                            f"{inferred_rows}×{inferred_cols} grid layout "
                            f"(inferred from image aspect ratio {aspect:.2f})"
                        )
                    else:
                        st.success(f"✅ Detected {len(detected_cards)} card(s) with automatic detection")
                else:
                    st.success(f"✅ Detected {len(detected_cards)} card(s) with automatic detection")
        
        # Process each detected card
        for card_idx, (card_image, contour) in enumerate(detected_cards):
            st.markdown(f"#### 📇 Card {card_idx + 1}")
            
            card_col1, card_col2 = st.columns([1, 1])
            
            with card_col1:
                st.markdown("**Detected Card Image**")
                card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
                st.image(card_rgb)
            
            with card_col2:
                qr_data = None
                contact_data = {}
                
                # Step 2: QR Code Detection - ALWAYS TRY FIRST
                with st.spinner("📱 Checking for QR codes..."):
                    try:
                        qr_results = qr_reader.detect_and_decode(card_image)
                        
                        if qr_results:
                            method_used = qr_results[0].get('method', 'unknown')
                            qr_data = qr_reader.extract_contact_info(qr_results)
                            
                            # Clean status display
                            st.markdown(f'''
                            <div style="
                                background-color: #d4edda;
                                color: #155724;
                                padding: 0.75rem;
                                border-radius: 0.25rem;
                                border-left: 4px solid #28a745;
                                margin: 0.5rem 0;
                            ">
                                ✅ <strong>Found {len(qr_results)} QR code(s)</strong> ({method_used})
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            if qr_data:
                                # Show QR data fields in a clean way
                                with st.expander("📱 QR Code Data", expanded=False):
                                    qr_fields = ', '.join(qr_data.keys())
                                    st.markdown(f"**Available fields:** {qr_fields}")
                                    for qr in qr_results:
                                        st.json(qr['parsed'])
                        else:
                            st.markdown('''
                            <div style="
                                background-color: #f8f9fa;
                                color: #6c757d;
                                padding: 0.75rem;
                                border-radius: 0.25rem;
                                border-left: 4px solid #6c757d;
                                margin: 0.5rem 0;
                            ">
                                ℹ️ No QR codes detected
                            </div>
                            ''', unsafe_allow_html=True)
                    
                    except RuntimeError as e:
                        st.error(f"❌ QR code reading failed: {str(e)}")
                        st.markdown('''
                        <div style="
                            background-color: #fff3cd;
                            color: #856404;
                            padding: 0.75rem;
                            border-radius: 0.25rem;
                            border-left: 4px solid #ffc107;
                            margin: 0.5rem 0;
                        ">
                            💡 <strong>Fix:</strong> Restart with <code>./start_app.sh</code>
                        </div>
                        ''', unsafe_allow_html=True)
                    except Exception as e:
                        st.warning(f"⚠️ QR scan error: {str(e)}")
                
                # Step 3: Contact extraction — QR-first, vision as fallback
                st.markdown("---")

                if qr_data_is_sufficient(qr_data):
                    # ⚡ QR has email → skip vision entirely
                    st.markdown("**⚡ QR Code Priority**")
                    st.markdown(f'''
                    <div style="
                        background-color: #d4edda;
                        color: #155724;
                        padding: 0.75rem;
                        border-radius: 0.25rem;
                        border-left: 4px solid #28a745;
                        margin: 0.5rem 0;
                    ">
                        ⚡ <strong>QR code has complete data (email found) — vision skipped.</strong>
                    </div>
                    ''', unsafe_allow_html=True)
                    contact_data = qr_to_contact_data(qr_data)
                else:
                    # Vision analysis needed
                    st.markdown("**👁️ Vision Analysis**")
                    with st.spinner(f"🤖 Analyzing card image (timeout: {vision_timeout}s)..."):
                        selected_provider = st.session_state.get('selected_provider', None)
                        scan_result = provider_factory.extract_with_fallback(
                            card_image,
                            qr_data,
                            preferred=selected_provider,
                            timeout=vision_timeout
                        )
                        contact_data = scan_result.contact.to_legacy_dict() if scan_result.contact and scan_result.contact.has_minimum_data() else (scan_result.error or {})
                        if isinstance(contact_data, str):
                            contact_data = {"error": contact_data}

                        if 'error' in contact_data:
                            error_msg = contact_data.get('error', 'Unknown')
                            st.error(f"❌ Vision processing error: {error_msg}")

                            # Fall back to QR data if available (even without email)
                            if qr_data:
                                st.warning("⚠️ Vision failed — falling back to QR code data.")
                                contact_data = qr_to_contact_data(qr_data)
                                st.success("✅ Contact info extracted from QR code!")
                            else:
                                is_timeout = 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower()
                                if is_timeout:
                                    st.markdown(f'''
                                    <div style="
                                        background-color: #fff3cd;
                                        color: #856404;
                                        padding: 0.75rem;
                                        border-radius: 0.25rem;
                                        border-left: 4px solid #ffc107;
                                        margin: 0.5rem 0;
                                    ">
                                        ⏱️ <strong>Ollama timed out.</strong> The model is installed but took too long.<br>
                                        Try again — subsequent runs are faster once the model is loaded in memory.
                                    </div>
                                    ''', unsafe_allow_html=True)
                                else:
                                    st.markdown(f'''
                                    <div style="
                                        background-color: #fff3cd;
                                        color: #856404;
                                        padding: 0.75rem;
                                        border-radius: 0.25rem;
                                        border-left: 4px solid #ffc107;
                                        margin: 0.5rem 0;
                                    ">
                                        💡 <strong>Tip:</strong> Install vision model:<br>
                                        <code>ollama pull {vision_model}</code>
                                    </div>
                                    ''', unsafe_allow_html=True)
                                continue
                        else:
                            st.success("✅ Vision analysis complete!")
                
                if not contact_data or 'error' in contact_data:
                    st.warning("⚠️ Could not extract contact information")
                    continue
            
            # Step 5: Display Contact Preview
            st.markdown("---")
            st.markdown("### 👤 **Extracted Contact Information**")
            preview_col1, preview_col2 = st.columns([2, 1])
            
            with preview_col1:
                preview = vcf_generator.preview_vcard(contact_data)
                # Better styled preview with high contrast
                st.markdown(f'''
                <div style="
                    background-color: white;
                    color: black;
                    padding: 1.5rem;
                    border-radius: 0.5rem;
                    border: 2px solid #1f77b4;
                    font-family: monospace;
                    font-size: 14px;
                    line-height: 1.8;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">
                {preview.replace(chr(10), "<br>")}
                </div>
                ''', unsafe_allow_html=True)
            
            with preview_col2:
                # Option to view raw contact data
                with st.expander("✏️ **View Raw Data**", expanded=False):
                    st.caption("JSON representation of extracted data:")
                    st.json(contact_data)
            
            # Generate VCF
            vcf_string = vcf_generator.generate_vcf_string(contact_data)
            filename = vcf_generator.contact_to_filename(contact_data)
            
            # Store processed card
            all_processed_cards.append({
                'filename': filename,
                'contact_data': contact_data,
                'vcf_content': vcf_string,
                'card_image': card_rgb,
                'source_file': uploaded_file.name,
                'locked': False  # Unlocked by default, user can lock successful ones
            })
            
            st.success("✅ Card processed successfully!")
            st.markdown("---")
    
    return all_processed_cards


def main():
    """Main application function."""
    initialize_session_state()

    # Background preload: load llama3.2-vision into Ollama RAM once per session
    # so the model is warm before the user submits their first card.
    if not st.session_state.ollama_preload_started:
        st.session_state.ollama_preload_started = True
        threading.Thread(
            target=_background_preload_ollama,
            args=("glm-ocr",),
            daemon=True,
        ).start()

    handle_history_delete_request()
    
    # Header
    st.markdown('<div class="main-header">📇 Business Card Scanner</div>', unsafe_allow_html=True)
    st.markdown("Upload business card images to extract contact information and generate VCF files for Outlook.")

    if st.session_state.get("history_message"):
        st.info(st.session_state.history_message)
        st.session_state.history_message = None
    
    # Sidebar configuration
    st.sidebar.title("⚙️ Configuration")
    
    # Vision Settings (always use Vision mode now)
    st.sidebar.markdown("### 🔬 Vision Settings")
    
    # Build model list dynamically from Ollama (/api/ps then /api/tags)
    # so the dropdown always reflects what's actually installed — and
    # puts the currently-loaded GPU model first to avoid a costly swap.
    _vision_keywords = ["glm-ocr", "vision", "llava", "bakllava", "moondream"]
    _fallback_models  = ["glm-ocr", "llama3.2-vision", "llava:13b", "llava", "bakllava", "moondream"]

    def _fetch_ollama_vision_models():
        """Return (model_list, loaded_model_or_None)."""
        loaded = None
        models = []
        try:
            # Running models first
            ps = requests.get("http://localhost:11434/api/ps", timeout=2)
            if ps.status_code == 200:
                for m in ps.json().get("models", []):
                    n = m.get("name", "")
                    if any(k in n.lower() for k in _vision_keywords):
                        loaded = n
                        models.append(n)
            # All installed models
            tags = requests.get("http://localhost:11434/api/tags", timeout=2)
            if tags.status_code == 200:
                for m in tags.json().get("models", []):
                    n = m.get("name", "")
                    if any(k in n.lower() for k in _vision_keywords) and n not in models:
                        models.append(n)
        except Exception:
            pass
        return models or _fallback_models, loaded

    _available_vision_models, _loaded_model = _fetch_ollama_vision_models()
    # Default index: the currently-loaded model (no swap) or first in list
    _default_idx = 0
    if _loaded_model and _loaded_model in _available_vision_models:
        _default_idx = _available_vision_models.index(_loaded_model)

    if _loaded_model:
        st.sidebar.success(f"🟢 Loaded in GPU: **{_loaded_model}**")
    else:
        st.sidebar.info("⚪ No model currently loaded — first run will be slow")

    vision_model = st.sidebar.selectbox(
        "Vision Model",
        _available_vision_models,
        index=_default_idx,
        key="widget_vision_model",
        help="Models installed in Ollama. The GPU-loaded model (🟢) is selected by default — switching triggers a model swap."
    )

    vision_timeout = st.sidebar.slider(
        "Vision Timeout (seconds)",
        min_value=60,
        max_value=600,
        value=300,
        step=30,
        key="widget_vision_timeout",
        help="Time to wait for vision model response. Increase for slower systems or complex cards."
    )
    
    st.sidebar.caption(f"⏱️ Timeout: {vision_timeout}s (~{vision_timeout//60} min)")

    # ---- Provider Status Section ----
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔌 Provider Status")

    statuses = provider_factory.get_all_statuses()
    for ptype, info in statuses.items():
        icon = "🟢" if info["status"] == "available" else "🔴"
        local_tag = " (Local)" if info["is_local"] else " (Cloud)"
        st.sidebar.text(f"{icon} {ptype.value}{local_tag}: {info['model']}")

    # Provider preference
    available_providers = [
        pt for pt, info in statuses.items()
        if info["status"] == "available"
    ]

    if available_providers:
        provider_names = [p.value for p in available_providers]
        selected_provider_name = st.sidebar.selectbox(
            "Preferred Provider",
            provider_names,
            index=0,
            key="widget_provider_select",
            help="Local providers have priority. Cloud providers are fallback."
        )
        # Defensive: selectbox can return a stale integer index from session
        # state after a widget tree change. Always coerce to string first.
        try:
            selected_provider = ProviderType(str(selected_provider_name))
        except ValueError:
            selected_provider = ProviderType(provider_names[0])
        st.session_state.selected_provider = selected_provider  # Store in session
    else:
        selected_provider = None
        st.session_state.selected_provider = None
        st.sidebar.warning("⚠️ No providers available!")


    # Card Detection Settings
    st.sidebar.markdown("### Detection Settings")
    
    detection_mode = st.sidebar.radio(
        "Detection Mode",
        ["Automatic", "Manual - Single Card", "Manual - Grid Layout"],
        help="Choose how to detect cards"
    )
    
    if detection_mode == "Automatic":
        st.sidebar.success("✨ Document scanner algorithm")
        st.sidebar.info("Filters out QR codes & logos")
    
    manual_grid_rows = 1
    manual_grid_cols = 1
    
    if detection_mode == "Manual - Grid Layout":
        st.sidebar.info("Specify how cards are arranged")
        manual_grid_cols = st.sidebar.number_input("Columns", min_value=1, max_value=5, value=2)
        manual_grid_rows = st.sidebar.number_input("Rows", min_value=1, max_value=5, value=4)
        st.sidebar.success(f"Will extract {manual_grid_cols * manual_grid_rows} cards")
        
        st.sidebar.markdown("#### Fine-tune Grid")
        margin_top = st.sidebar.slider("Top Margin (%)", 0, 30, 0, help="Skip % from top")
        margin_bottom = st.sidebar.slider("Bottom Margin (%)", 0, 30, 0, help="Skip % from bottom")
        margin_left = st.sidebar.slider("Left Margin (%)", 0, 30, 0, help="Skip % from left")
        margin_right = st.sidebar.slider("Right Margin (%)", 0, 30, 0, help="Skip % from right")
        
        if margin_top or margin_bottom or margin_left or margin_right:
            st.sidebar.info(f"Active area: {100-margin_top-margin_bottom}% × {100-margin_left-margin_right}%")
    else:
        margin_top = margin_bottom = margin_left = margin_right = 0
    
    # Better controls for automatic detection
    if detection_mode == "Automatic":
        st.sidebar.markdown("#### Size Filters")
        min_card_percent = st.sidebar.slider(
            "Min Card Size (%)", 
            min_value=2, 
            max_value=20, 
            value=5,
            help="Minimum card size as % of total image (filters out small logos/QR codes)"
        )
        max_card_percent = st.sidebar.slider(
            "Max Card Size (%)", 
            min_value=20, 
            max_value=60, 
            value=40,
            help="Maximum card size as % of total image"
        )
        st.sidebar.info(f"Cards must be {min_card_percent}-{max_card_percent}% of image")
    else:
        min_card_percent = 5
        max_card_percent = 40

    # ---- Microsoft Graph Integration ----
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📧 Outlook Integration")

    if ms_graph_manager.is_configured:
        if ms_graph_manager.is_authenticated:
            me = ms_graph_manager.get_me()
            user_label = me.get("displayName") or me.get("mail", "user") if me else "user"
            st.sidebar.success(f"✅ Connected as {user_label}")
            if st.sidebar.button("🔓 Disconnect Outlook", key="btn_outlook_disconnect"):
                ms_graph_manager.logout()
                st.session_state.outlook_auth_flow = None
                st.session_state.outlook_auth_code = None
                st.session_state.outlook_auth_uri = None
                st.rerun()
        else:
            # ── Step 1: initiate device code flow ─────────────────────────
            if st.session_state.outlook_auth_flow is None:
                if st.sidebar.button("🔑 Connect to Outlook", key="btn_outlook_connect"):
                    try:
                        app_obj = ms_graph_manager._get_msal_app()
                        flow = app_obj.initiate_device_flow(
                            scopes=ms_graph_manager.SCOPES
                        )
                        if "user_code" in flow:
                            st.session_state.outlook_auth_flow = flow
                            st.session_state.outlook_auth_code = flow["user_code"]
                            st.session_state.outlook_auth_uri = flow.get(
                                "verification_uri", "https://microsoft.com/devicelogin"
                            )
                        else:
                            st.sidebar.error(flow.get("error_description", "Failed to start auth flow"))
                        st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"Error: {e}")
            else:
                # ── Step 2: show code, wait for user, then confirm ─────────
                code = st.session_state.outlook_auth_code
                uri  = st.session_state.outlook_auth_uri
                st.sidebar.markdown(
                    f"**1.** Open [{uri}]({uri})  \n"
                    f"**2.** Enter this code:"
                )
                st.sidebar.code(code, language=None)
                col1, col2 = st.sidebar.columns(2)
                with col1:
                    confirm = st.button("✅ Done", key="btn_outlook_confirm",
                                        help="Click after entering the code in your browser",
                                        width='stretch')
                with col2:
                    cancel = st.button("✖ Cancel", key="btn_outlook_cancel",
                                       width='stretch')

                if cancel:
                    st.session_state.outlook_auth_flow = None
                    st.session_state.outlook_auth_code = None
                    st.session_state.outlook_auth_uri = None
                    st.rerun()

                if confirm:
                    with st.spinner("Verifying sign-in…"):
                        try:
                            app_obj = ms_graph_manager._get_msal_app()
                            result = app_obj.acquire_token_by_device_flow(
                                st.session_state.outlook_auth_flow
                            )
                        except Exception as e:
                            result = {"error_description": str(e)}

                    if "access_token" in result:
                        import time as _time
                        ms_graph_manager._access_token = result["access_token"]
                        ms_graph_manager._token_expires_at = (
                            _time.time() + result.get("expires_in", 3600)
                        )
                        ms_graph_manager._account = result.get("id_token_claims", {})
                        ms_graph_manager._save_token_cache()
                        st.session_state.outlook_auth_flow = None
                        st.session_state.outlook_auth_code = None
                        st.session_state.outlook_auth_uri = None
                        st.sidebar.success("✅ Outlook connected!")
                        st.rerun()
                    else:
                        err = result.get("error_description", "Authentication failed")
                        st.sidebar.error(err)
                        if "expired" in err.lower() or "timeout" in err.lower():
                            st.session_state.outlook_auth_flow = None
                            st.session_state.outlook_auth_code = None
                            st.session_state.outlook_auth_uri = None
    else:
        st.sidebar.caption("💡 Set MS_GRAPH_CLIENT_ID env var to enable direct Outlook sync")

    relaunch_wrappers = handle_history_relaunch(
        vision_model,
        vision_timeout,
        detection_mode,
        manual_grid_rows,
        manual_grid_cols,
        min_card_percent,
        max_card_percent,
        margin_top,
        margin_bottom,
        margin_left,
        margin_right,
    )
    
    # Upload section
    st.markdown("## 📤 Upload Business Cards")
    uploaded_files = st.file_uploader(
        "Choose business card image(s)",
        type=['png', 'jpg', 'jpeg', 'bmp'],
        accept_multiple_files=True,
        help="Upload one or more images containing business cards"
    )

    if uploaded_files:
        if not isinstance(uploaded_files[0], HistoryFileWrapper):
            st.session_state.history_active_files_data = None

    if not uploaded_files:
        if relaunch_wrappers:
            uploaded_files = relaunch_wrappers
        elif st.session_state.get("history_active_files_data"):
            history_wrappers = [
                HistoryFileWrapper(file["data"], file["name"])
                for file in st.session_state.history_active_files_data
            ]
            uploaded_files = history_wrappers
    
    if uploaded_files:
        st.info(f"📊 {len(uploaded_files)} file(s) uploaded")
        
        # Show grid preview for Manual Grid Layout mode
        if detection_mode == "Manual - Grid Layout" and len(uploaded_files) > 0:
            st.markdown("### 🎯 Grid Preview")
            st.info("👁️ Preview shows where cards will be extracted (adjust margins to align with cards)")
            
            preview_file = uploaded_files[0]  # Show preview for first image
            preview_image = load_image(preview_file)
            preview_cv = cv2.cvtColor(preview_image, cv2.COLOR_RGB2BGR)
            
            # Draw grid overlay
            overlay = draw_grid_overlay(preview_cv, manual_grid_rows, manual_grid_cols,
                                       margin_top, margin_bottom, margin_left, margin_right)
            overlay_rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
            
            st.image(overlay_rgb, caption=f"Grid Preview: {manual_grid_cols}x{manual_grid_rows}")
            
            st.markdown("""
            **Legend:**
            - 🟢 **Green lines**: Grid splits between cards
            - 🟡 **Yellow box**: Active card area
            - 🔴 **Red lines**: Margins (excluded area)
            - 🟣 **Purple labels**: Card numbers
            """)
        
        # Process button
        if st.button("🚀 Process Business Cards", type="primary"):
            with st.spinner("Processing..."):
                processed_cards = process_business_cards(
                    uploaded_files, vision_model, vision_timeout,
                    detection_mode, manual_grid_rows, manual_grid_cols,
                    min_card_percent, max_card_percent,
                    margin_top, margin_bottom, margin_left, margin_right
                )
                st.session_state.processed_cards = processed_cards
                st.session_state.processing_complete = True

                history_settings = build_history_settings(
                    vision_model,
                    vision_timeout,
                    detection_mode,
                    manual_grid_rows,
                    manual_grid_cols,
                    min_card_percent,
                    max_card_percent,
                    margin_top,
                    margin_bottom,
                    margin_left,
                    margin_right,
                )
                save_history_run(processed_cards, uploaded_files, history_settings)
        
        # Download section
        if st.session_state.processing_complete and st.session_state.processed_cards:
            # Handle individual card retry requests (moved inside download section)
            for idx in range(len(st.session_state.processed_cards)):
                if st.session_state.get(f'retry_card_{idx}', False):
                    # Clear the retry flag
                    st.session_state[f'retry_card_{idx}'] = False
                    
                    card = st.session_state.processed_cards[idx]
                    st.info(f"🔄 Retrying card {idx+1}: {card['filename']}...")
                    
                    with st.spinner(f"Re-processing card {idx+1}..."):
                        # Get current settings from sidebar (they're already in scope)
                        retry_result = process_single_card_retry(
                            card['card_image'],
                            vision_model,
                            vision_timeout
                        )
                        
                        if retry_result:
                            # Update the card with new data
                            st.session_state.processed_cards[idx]['contact_data'] = retry_result['contact_data']
                            st.session_state.processed_cards[idx]['vcf_content'] = retry_result['vcf_content']
                            st.session_state.processed_cards[idx]['filename'] = retry_result['filename']
                            update_history_card_entry(
                                card_index=idx + 1,
                                contact_data=retry_result['contact_data'],
                                vcf_content=retry_result['vcf_content'],
                                filename=retry_result['filename'],
                            )
                            st.success(f"✅ Card {idx+1} reprocessed successfully!")
                        else:
                            st.error(f"❌ Failed to reprocess card {idx+1}")
                    
                    st.rerun()
            
            # Download section UI
            st.markdown("## 💾 Download Contacts")
            
            # Initialize export processor
            export_processor = ExportProcessor()
            
            # Export format selection
            st.markdown("### 📦 Choose Export Formats")
            export_col1, export_col2, export_col3 = st.columns(3)
            
            with export_col1:
                include_vcf = st.checkbox("VCF (Outlook/Contacts)", value=True, help="vCard format for contact managers")
            with export_col2:
                include_excel = st.checkbox("Excel (XLSX)", value=True, help="Microsoft Excel format")
            with export_col3:
                outlook_csv = st.checkbox("Outlook Import CSV", value=True, help="Special CSV format for Outlook import")
            
            # Set include_csv to False since we removed regular CSV option
            include_csv = False
            
            # Outlook CSV format options
            outlook_simplified = False
            outlook_email_field = 'E-mail Address'
            outlook_phone_field = 'Business Phone'
            outlook_use_quotes = True
            
            if outlook_csv:
                with st.expander("⚙️ Outlook CSV Options", expanded=False):
                    outlook_simplified = st.checkbox(
                        "Use Simplified Format", 
                        value=False,
                        help="Minimal fields only (First Name, Last Name, Company, Email, Phone) for maximum compatibility"
                    )
                    
                    outlook_email_field = st.selectbox(
                        "Email Field Name",
                        options=['E-mail Address', 'Email Address', 'Email'],
                        index=0,
                        help="Field name for email column. Try different options if import fails."
                    )
                    
                    outlook_phone_field = st.selectbox(
                        "Phone Field Name",
                        options=['Business Phone', 'Phone', 'Work Phone'],
                        index=0,
                        help="Field name for phone column. Try different options if import fails."
                    )
                    
                    outlook_use_quotes = st.checkbox(
                        "Quote Fields",
                        value=True,
                        help="Wrap all fields in quotes. Disable if Outlook has issues with quoted fields."
                    )
                    
                    # Show diagnostic info
                    st.caption("💡 **Tip:** If email/phone don't import, try different field names or simplified format.")
            
            # Prepare export data
            contacts = [card['contact_data'] for card in st.session_state.processed_cards]
            for i, card in enumerate(st.session_state.processed_cards):
                contacts[i]['source'] = card.get('source_file', 'Unknown')
            
            # Show stats
            stats = export_processor.get_export_stats(contacts)
            st.info(f"📊 **Export Summary:** {stats['total']} contacts | "
                   f"{stats['with_email']} with email | {stats['with_phone']} with phone | "
                   f"{stats['with_company']} with company")
            
            st.markdown("---")
            
            # Individual Cards Management Section
            st.markdown("### 📄 Individual Cards Management")
            st.caption("💡 **Lock cards with good results** to prevent re-processing. **Retry** failed extractions individually.")
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Individual card management - Compact list format
            for idx, card in enumerate(st.session_state.processed_cards):
                is_locked = card.get('locked', False)
                contact = card['contact_data']
                
                # Get contact info
                name = contact.get('fullName') or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                company = contact.get('company', '') or ''
                email = contact.get('email', '') or ''
                phone = contact.get('phone', '') or ''
                
                # Truncate long values for compact display
                name_display = name[:30] + "..." if len(name) > 30 else name
                company_display = company[:25] + "..." if len(company) > 25 else company
                email_display = email[:25] + "..." if len(email) > 25 else email
                phone_display = phone[:18] + "..." if len(phone) > 18 else phone
                
                # Compact list row layout
                row_col1, row_col2, row_col3, row_col4, row_col5, row_col6 = st.columns([0.8, 2.5, 2, 2.5, 2, 3])
                
                with row_col1:
                    # Lock status icon (smaller)
                    lock_icon = "🔒" if is_locked else "🔓"
                    st.markdown(f'<div style="text-align: center; font-size: 16px;">{lock_icon}</div>', unsafe_allow_html=True)
                
                with row_col2:
                    # Name
                    st.markdown(f'<div style="font-weight: 600;">{name_display}</div>', unsafe_allow_html=True)
                
                with row_col3:
                    # Company
                    if company:
                        st.markdown(f'<div style="color: #666; font-size: 0.9em;">{company_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col4:
                    # Email
                    if email:
                        st.markdown(f'<div style="color: #666; font-size: 0.85em;">✉️ {email_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col5:
                    # Phone
                    if phone:
                        st.markdown(f'<div style="color: #666; font-size: 0.85em;">☎️ {phone_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col6:
                    # Action buttons in compact row
                    action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 1])
                    
                    with action_col1:
                        # Lock/Unlock button (smaller)
                        btn_label = "🔓" if is_locked else "🔒"
                        if st.button(btn_label, key=f"lock_{idx}",
                                   help="Lock/Unlock" if not is_locked else "Lock/Unlock",
                                   width='stretch'):
                            st.session_state.processed_cards[idx]['locked'] = not is_locked
                            update_history_card_entry(
                                card_index=idx + 1,
                                locked=st.session_state.processed_cards[idx]['locked']
                            )
                            st.rerun()
                    
                    with action_col2:
                        # Retry button (smaller)
                        retry_disabled = is_locked
                        if st.button("🔄", key=f"retry_{idx}",
                                   disabled=retry_disabled,
                                   help="Retry" if not retry_disabled else "Unlock first",
                                   width='stretch'):
                            st.session_state[f'retry_card_{idx}'] = True
                            st.rerun()
                    
                    with action_col3:
                        # VCF download (smaller)
                        if include_vcf:
                            st.download_button(
                                label="📥",
                                data=card['vcf_content'],
                                file_name=f"{card['filename']}.vcf",
                                mime="text/vcard",
                                key=f"vcf_{idx}_{card['filename']}",
                                help="Download VCF",
                                width='stretch'
                            )
                    
                    with action_col4:
                        # Outlook CSV download (smaller)
                        if outlook_csv:
                            if outlook_simplified:
                                single_outlook_csv = export_processor.export_to_outlook_csv_simple(
                                    [card['contact_data']],
                                    email_field_name=outlook_email_field,
                                    phone_field_name=outlook_phone_field,
                                    use_quotes=outlook_use_quotes
                                )
                            else:
                                single_outlook_csv = export_processor.export_to_outlook_csv(
                                    [card['contact_data']],
                                    email_field_name=outlook_email_field,
                                    phone_field_name=outlook_phone_field
                                )
                            st.download_button(
                                label="📧",
                                data=single_outlook_csv,
                                file_name=f"{card['filename']}.csv",
                                mime="text/csv",
                                key=f"outlook_csv_{idx}_{card['filename']}",
                                help="Download Outlook CSV",
                                width='stretch'
                            )
                
                # Add subtle divider between items
                if idx < len(st.session_state.processed_cards) - 1:
                    st.markdown('<hr style="margin: 8px 0; border: none; border-top: 1px solid #e0e0e0;">', unsafe_allow_html=True)
            
            # Clear visual separation
            st.markdown("<br>", unsafe_allow_html=True)
            st.divider()
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Bulk Downloads Section
            st.markdown("### 📦 Bulk Downloads")
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            bulk_col1, bulk_col2 = st.columns(2)
            
            with bulk_col1:
                # Excel Export
                if include_excel:
                    excel_data = export_processor.export_to_excel(contacts)
                    archive_export("contacts.xlsx", excel_data, "xlsx")
                    st.download_button(
                        label="📗 Download Excel (XLSX)",
                        data=excel_data,
                        file_name=f"contacts_{timestamp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="Microsoft Excel format with formatting",
                        width='stretch'
                    )
                
                # Combined VCF
                if include_vcf:
                    combined_vcf = "\n".join(card['vcf_content'] for card in st.session_state.processed_cards)
                    archive_export("contacts_combined.vcf", combined_vcf, "vcf")
                    st.download_button(
                        label="📋 Download Combined VCF",
                        data=combined_vcf,
                        file_name=f"all_contacts_{timestamp}.vcf",
                        mime="text/vcard",
                        help="All contacts in one VCF file",
                        width='stretch'
                    )
            
            with bulk_col2:
                # Outlook CSV Export
                if outlook_csv:
                    if outlook_simplified:
                        outlook_csv_data = export_processor.export_to_outlook_csv_simple(
                            contacts,
                            email_field_name=outlook_email_field,
                            phone_field_name=outlook_phone_field,
                            use_quotes=outlook_use_quotes
                        )
                    else:
                        outlook_csv_data = export_processor.export_to_outlook_csv(
                            contacts,
                            email_field_name=outlook_email_field,
                            phone_field_name=outlook_phone_field
                        )
                    csv_filename = "outlook_simple.csv" if outlook_simplified else "outlook.csv"
                    archive_export(csv_filename, outlook_csv_data, "csv")
                    
                    st.download_button(
                        label="📧 Download Outlook CSV",
                        data=outlook_csv_data,
                        file_name=f"outlook_import_{timestamp}.csv",
                        mime="text/csv",
                        help="Import this CSV directly into Outlook",
                        width='stretch'
                    )
                    
                    # Show diagnostic report if CSV validator is available
                    try:
                        from utils.csv_validator import CSVValidator
                        validator = CSVValidator()
                        diagnostic_report = validator.generate_diagnostic_report(outlook_csv_data)
                        
                        with st.expander("📋 CSV Diagnostic Report", expanded=False):
                            st.code(diagnostic_report, language='text')
                    except Exception as e:
                        pass  # Skip diagnostic if validator fails
                
                # Complete Package (ZIP)
                if include_vcf or include_excel or outlook_csv:
                    st.markdown("---")
                    st.markdown("**🎁 Complete Package:**")
                    vcf_files = [(f"{card['filename']}.vcf", card['vcf_content']) 
                                for card in st.session_state.processed_cards]
                    
                    package_data = export_processor.create_export_package(
                        contacts=contacts,
                        vcf_files=vcf_files if include_vcf else [],
                        include_csv=False,  # Regular CSV removed
                        include_excel=include_excel,
                        include_outlook_csv=outlook_csv
                    )
                    
                    archive_export("contacts_package.zip", package_data, "zip")
                    
                    st.download_button(
                        label="🎁 Download ZIP Package",
                        data=package_data,
                        file_name=f"contacts_package_{timestamp}.zip",
                        mime="application/zip",
                        help="ZIP file with all selected formats",
                        width='stretch'
                    )

            # Push to Outlook button
            st.markdown("---")
            st.markdown("### 📧 Outlook Integration")
            if ms_graph_manager.is_configured and ms_graph_manager.is_authenticated:
                if st.button("📧 Push All to Outlook", key="push_outlook"):
                    with st.spinner("Creating contacts in Outlook..."):
                        all_contacts = [
                            card.get('contact_data', {})
                            for card in st.session_state.processed_cards
                            if card.get('contact_data') and not card['contact_data'].get('error')
                        ]
                        if all_contacts:
                            result = ms_graph_manager.batch_create_contacts(all_contacts)
                            st.success(
                                f"✅ Created {result['created']} contacts in Outlook "
                                f"({result['skipped']} skipped, {result['failed']} failed)"
                            )
                        else:
                            st.warning("No valid contacts to push")
            else:
                st.info("Configure and authenticate Outlook integration in the sidebar to use this feature")

            # Summary
            st.markdown("### 📊 Processing Summary")
            st.success(f"Successfully processed {len(st.session_state.processed_cards)} business card(s)!")
            
            # Show summary table
            summary_data = []
            for card in st.session_state.processed_cards:
                contact = card['contact_data']
                name = contact.get('fullName') or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                company = contact.get('company', 'N/A')
                email = contact.get('email', 'N/A')
                
                summary_data.append({
                    'Name': name,
                    'Company': company,
                    'Email': email,
                    'Source': card['source_file']
                })
            
            st.table(summary_data)
            
            # Reset button
            if st.button("🔄 Process More Cards"):
                st.session_state.processed_cards = []
                st.session_state.processing_complete = False
                st.session_state.history_active_files_data = None
                st.session_state.history_recorded_exports = set()
                st.rerun()
    
    else:
        # Instructions when no files uploaded
        st.markdown("""
        ### 📋 Instructions
        
        1. **Upload Images**: Click the upload button above to select business card images
        2. **Configure Settings**: Adjust settings in the sidebar if needed
        3. **Process**: Click the "Process Business Cards" button
        4. **Review**: Check the extracted contact information
        5. **Download**: Get individual VCF files or download all at once
        
        ### ⚙️ Setup Requirements
        
        **For best results:**
        - Install Ollama and pull the recommended model: `ollama pull glm-ocr`
        - Start Ollama: `ollama serve`
        - Ensure clear, well-lit images of business cards
        
        **Without Ollama:**
        - The app will use regex-based fallback extraction
        - Results may be less accurate but still functional
        """)
        
        # System status
        st.sidebar.markdown("### 📊 System Status")

        # Provider status via factory
        if provider_factory:
            statuses = provider_factory.get_all_statuses()
            for ptype, info in statuses.items():
                if not info['enabled']:
                    continue
                label = ptype.value.capitalize()
                if info['status'] == 'available':
                    st.sidebar.success(f"✅ {label}: {info['model']}")
                elif info['status'] == 'unavailable':
                    if info['is_local']:
                        st.sidebar.warning(f"⚠️ {label}: Not running")
                    # Cloud providers silently absent (no API key) — skip noise
                elif info['status'] == 'error':
                    st.sidebar.error(f"❌ {label}: {info.get('error', 'error')[:60]}")

        # Check QR Reader
        qr_test = QRReader()
        try:
            test_img = np.zeros((100, 100), dtype=np.uint8)
            qr_test.detect_and_decode(test_img)
            st.sidebar.success("✅ QR Code Reader: Working")
        except RuntimeError:
            st.sidebar.error("❌ QR Reader: Not working")
            with st.sidebar.expander("Fix QR Reading"):
                st.code("./start_app.sh", language="bash")
                st.caption("Or restart with library path set")
                st.code("export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH\nstreamlit run app.py")
        except Exception:
            st.sidebar.warning("⚠️ QR Reader: Status unknown")

    render_history_panel()


if __name__ == "__main__":
    main()

