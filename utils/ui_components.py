"""
Image and grid helper functions for Business Card Scanner.
Framework-agnostic helpers consumed by the FastAPI/React backend (server.py)
and by utils/card_processor.py.
"""

import cv2
import numpy as np
from PIL import Image
from typing import Dict, List, Tuple, Optional
from io import BytesIO


def load_image(uploaded_file) -> np.ndarray:
    """
    Load an uploaded image file (supports HEIC/HEIF from iPhones).

    Args:
        uploaded_file: A file-like object with .read() (e.g. FastAPI UploadFile.file).

    Returns:
        Image as numpy array in RGB format
    """
    # Register HEIC/HEIF support if available
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:
        pass  # pillow-heif not installed; HEIC won't work but other formats still fine

    image = Image.open(uploaded_file)
    # HEIC files may lack mode or come as RGBA — normalise to RGB
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    return np.array(image)


def draw_grid_overlay(
    image: np.ndarray,
    rows: int,
    cols: int,
    margin_top: int = 0,
    margin_bottom: int = 0,
    margin_left: int = 0,
    margin_right: int = 0
) -> np.ndarray:
    """
    Draw grid lines on image for visualization.
    
    Args:
        image: Input image (BGR format)
        rows: Number of rows
        cols: Number of columns
        margin_top: Top margin as percentage
        margin_bottom: Bottom margin as percentage
        margin_left: Left margin as percentage
        margin_right: Right margin as percentage
        
    Returns:
        Image with grid overlay (BGR format)
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
    Criteria (any one is enough):
      - Has a valid email address
      - Has a full name AND a phone number
      - Has a full name AND an organization
    
    Args:
        qr_data: QR code extracted data dict
        
    Returns:
        True if QR data is sufficient, False otherwise
    """
    if not qr_data:
        return False
    
    # Criterion 1: Has email
    emails = qr_data.get('emails', [])
    if isinstance(emails, list) and any(e and '@' in e for e in emails):
        return True
    email = qr_data.get('email', '')
    if isinstance(email, str) and '@' in email:
        return True
    
    # Criterion 2: Has full name + phone
    has_name = bool(qr_data.get('full_name') or qr_data.get('first_name'))
    phones = qr_data.get('phones', [])
    if has_name and phones and len(phones) > 0:
        return True
    
    # Criterion 3: Has full name + organization
    org = qr_data.get('organization', '')
    if has_name and org and org.strip():
        return True

    # Criterion 4: Has at least one phone or email AND an organization.
    # Many minimalist business cards put the org in the QR alongside a
    # single contact channel — saves the vision call when the model would
    # have produced the same data.
    if org and org.strip() and (phones or qr_data.get('emails') or qr_data.get('email')):
        return True
    
    return False


def qr_to_contact_data(qr_data: dict) -> dict:
    """
    Convert QR code data to contact data format.
    
    Args:
        qr_data: QR code extracted data
        
    Returns:
        Contact data dictionary in standard format
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


def split_image_grid(
    image: np.ndarray,
    rows: int,
    cols: int,
    margin_top: int = 0,
    margin_bottom: int = 0,
    margin_left: int = 0,
    margin_right: int = 0
) -> List[Tuple[np.ndarray, None]]:
    """
    Split an image into a grid of cards with margin support.
    
    Args:
        image: Input image (BGR format)
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
    """
    Prepare metadata payload for history entries.
    
    Args:
        vision_model: Vision model name
        vision_timeout: Vision processing timeout
        detection_mode: Card detection mode
        grid_rows: Grid rows
        grid_cols: Grid columns
        min_percent: Minimum card area percentage
        max_percent: Maximum card area percentage
        margin_top: Top margin percentage
        margin_bottom: Bottom margin percentage
        margin_left: Left margin percentage
        margin_right: Right margin percentage
        
    Returns:
        Dictionary with history metadata
    """
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


class HistoryFileWrapper:
    """Wrapper to mimic Streamlit's UploadedFile for history replays."""

    def __init__(self, data: bytes, name: str) -> None:
        if isinstance(data, str):
            self._data = data.encode('utf-8')
        else:
            self._data = data
        self.name = name

    def getvalue(self) -> bytes:
        """Get file contents as bytes."""
        return self._data
