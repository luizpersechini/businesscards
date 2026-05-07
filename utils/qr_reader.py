"""
QR Code Reader Module
Detects and decodes QR codes from business card images.
"""

import cv2
import numpy as np
from typing import List, Dict, Optional
import re

# Try to import pyzbar - force attempt with better error handling
import os
PYZBAR_AVAILABLE = False
PYZBAR_ERROR = None

# Set library path
os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')

try:
    from pyzbar import pyzbar
    PYZBAR_AVAILABLE = True
    print("✓ QR code reader loaded successfully")
except ImportError as e:
    PYZBAR_ERROR = str(e)
    print(f"⚠ pyzbar import failed: {e}")
except Exception as e:
    PYZBAR_ERROR = str(e)
    print(f"⚠ QR code reader error: {e}")


class QRReader:
    """Detects and reads QR codes from images."""
    
    def __init__(self, use_opencv_fallback: bool = True):
        """
        Initialize the QR reader.

        Args:
            use_opencv_fallback: Use OpenCV QR detector(s) if pyzbar fails
        """
        self.use_opencv_fallback = use_opencv_fallback
        self.opencv_detector = None
        self.opencv_aruco_detector = None   # more robust ArUco-based detector

        if self.use_opencv_fallback:
            try:
                self.opencv_detector = cv2.QRCodeDetector()
                print("✓ OpenCV QR detector initialized as fallback")
            except Exception:
                print("⚠ OpenCV QR detector not available")

            # QRCodeDetectorAruco (cv2 ≥ 4.8) handles skew, small size, and
            # coloured QR codes better than the basic detector.
            try:
                self.opencv_aruco_detector = cv2.QRCodeDetectorAruco()
                print("✓ OpenCV ArUco QR detector initialized")
            except Exception:
                pass   # Not fatal — basic detector is still available
    
    def detect_and_decode(self, image: np.ndarray) -> List[Dict]:
        """
        Detect and decode all QR codes in an image.
        Uses pyzbar first, falls back to OpenCV if available.
        
        Args:
            image: Input image as numpy array (BGR format)
            
        Returns:
            List of dictionaries containing QR code data:
                - 'data': Decoded data string
                - 'type': QR code type
                - 'rect': Bounding rectangle (x, y, w, h)
                - 'polygon': Polygon points
                - 'parsed': Parsed data if it's a vCard or URL
        """
        results = []
        
        # Try pyzbar first (best overall detection rate)
        if PYZBAR_AVAILABLE:
            try:
                results = self._detect_with_pyzbar(image)
                if results:
                    return results
            except Exception as e:
                print(f"⚠ pyzbar detection failed: {e}")

        # ArUco-based detector — more robust for coloured / skewed QR codes
        if self.use_opencv_fallback and self.opencv_aruco_detector is not None:
            try:
                results = self._detect_with_opencv(image, detector=self.opencv_aruco_detector)
                if results:
                    return results
            except Exception as e:
                print(f"⚠ OpenCV ArUco QR detection failed: {e}")

        # Basic OpenCV detector as final fallback
        if self.use_opencv_fallback and self.opencv_detector is not None:
            try:
                results = self._detect_with_opencv(image, detector=self.opencv_detector)
                if results:
                    return results
            except Exception as e:
                print(f"⚠ OpenCV QR detection failed: {e}")
        
        # If pyzbar is not available and no fallback, raise error
        if not PYZBAR_AVAILABLE and not (self.use_opencv_fallback and self.opencv_detector):
            raise RuntimeError(f"QR code library not available: {PYZBAR_ERROR}. Install: brew install zbar")
        
        return results
    
    @staticmethod
    def _build_preprocessing_variants(image: np.ndarray) -> List[np.ndarray]:
        """
        Build a list of preprocessed image variants to maximise QR detection.

        Handles:
        - Small/low-res crops (upscale to 1200px)
        - Low contrast (CLAHE, histogram equalisation)
        - Coloured / warm-tinted QR codes (extract individual colour channels;
          blue channel gives highest contrast for brown/gold/red QR modules)
        - Dirty or noisy prints (adaptive threshold, Otsu, morphological cleanup)
        - Inverted codes (light modules on dark background)
        """
        candidates: List[np.ndarray] = []

        # ── Original BGR (no conversion — highest fidelity) ───────────────
        if len(image.shape) == 3:
            candidates.append(image)          # original BGR
            candidates.append(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))  # RGB swap

        # ── Grayscale base ────────────────────────────────────────────────
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        candidates.append(gray)

        # ── Upscale small images ──────────────────────────────────────────
        # QR decoders need ≥ ~4 px per module; upscale if image is small.
        h, w = gray.shape[:2]
        target = 1200   # px on the longest edge
        if max(h, w) < target:
            scale = target / max(h, w)
            up = cv2.resize(gray, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_CUBIC)
            candidates.append(up)
            # Also try 2× beyond the target for very tiny crops
            up2 = cv2.resize(gray, None, fx=scale * 2, fy=scale * 2,
                             interpolation=cv2.INTER_CUBIC)
            candidates.append(up2)

        # ── Colour channel extraction ─────────────────────────────────────
        # Warm-coloured (brown/gold/red) QR codes have low contrast in
        # grayscale because the luminance of brown ≈ luminance of white.
        # Blue channel is the complement of warm tones and gives the
        # highest contrast for these codes.
        if len(image.shape) == 3:
            b, g, r = cv2.split(image)
            candidates.extend([b, g, r])          # blue first (best for warm tints)
            # Also try inverted channels
            candidates.append(cv2.bitwise_not(b))

        # ── Contrast enhancement ──────────────────────────────────────────
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        candidates.append(clahe.apply(gray))

        # Histogram equalisation (global)
        candidates.append(cv2.equalizeHist(gray))

        # ── Binarisation ──────────────────────────────────────────────────
        # Otsu's method — best for bimodal (black + white) QR patterns
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(otsu)
        candidates.append(cv2.bitwise_not(otsu))   # inverted Otsu

        # Adaptive threshold (handles uneven lighting)
        adapt = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 51, 10
        )
        candidates.append(adapt)

        # ── Sharpening ────────────────────────────────────────────────────
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        candidates.append(cv2.filter2D(gray, -1, kernel))

        # ── Morphological cleanup on Otsu result ─────────────────────────
        # Close small gaps in QR modules that noisy scans introduce
        morph_kernel = np.ones((2, 2), np.uint8)
        candidates.append(cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, morph_kernel))

        return candidates

    def _detect_with_pyzbar(self, image: np.ndarray) -> List[Dict]:
        """Detect QR codes using pyzbar library with multiple preprocessing strategies."""
        candidates = self._build_preprocessing_variants(image)

        detected_codes = []
        for candidate in candidates:
            codes = pyzbar.decode(candidate)
            if codes:
                detected_codes = codes
                break

        results = []
        for code in detected_codes:
            # Decode data
            data = code.data.decode('utf-8', errors='ignore')
            
            # Get bounding box
            rect = code.rect  # (x, y, width, height)
            polygon = code.polygon
            
            # Parse the data
            parsed_data = self._parse_qr_data(data)
            
            results.append({
                'data': data,
                'type': code.type,
                'rect': (rect.left, rect.top, rect.width, rect.height),
                'polygon': [(point.x, point.y) for point in polygon],
                'parsed': parsed_data,
                'method': 'pyzbar'
            })
        
        return results
    
    def _detect_with_opencv(self, image: np.ndarray, detector=None) -> List[Dict]:
        """Detect QR codes using an OpenCV QR detector.

        Args:
            image: Input image (BGR numpy array)
            detector: OpenCV QR detector instance (QRCodeDetector or
                      QRCodeDetectorAruco).  Defaults to self.opencv_detector.
        """
        if detector is None:
            detector = self.opencv_detector
        if detector is None:
            return []

        results = []
        images_to_try = self._build_preprocessing_variants(image)
        
        for img in images_to_try:
            try:
                # detectAndDecode for single QR code
                data, bbox, _ = detector.detectAndDecode(img)
                
                if data and bbox is not None:
                    # Convert bbox to integer coordinates
                    bbox = bbox.astype(int)
                    
                    # Get bounding rectangle
                    x, y, w, h = cv2.boundingRect(bbox)
                    
                    # Parse the data
                    parsed_data = self._parse_qr_data(data)
                    
                    results.append({
                        'data': data,
                        'type': 'QRCODE',
                        'rect': (x, y, w, h),
                        'polygon': [(int(p[0]), int(p[1])) for p in bbox[0]],
                        'parsed': parsed_data,
                        'method': 'opencv'
                    })
                    
                    # Found one, return it
                    break
                    
            except Exception as e:
                continue
        
        # Try detectMulti for multiple QR codes (if available)
        if not results:
            try:
                retval, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
                
                if retval and decoded_info:
                    for i, data in enumerate(decoded_info):
                        if data and points is not None and len(points) > i:
                            bbox = points[i].astype(int)
                            x, y, w, h = cv2.boundingRect(bbox)
                            
                            parsed_data = self._parse_qr_data(data)
                            
                            results.append({
                                'data': data,
                                'type': 'QRCODE',
                                'rect': (x, y, w, h),
                                'polygon': [(int(p[0]), int(p[1])) for p in bbox],
                                'parsed': parsed_data,
                                'method': 'opencv_multi'
                            })
            except:
                pass
        
        return results
    
    def _parse_qr_data(self, data: str) -> Dict:
        """
        Parse QR code data to extract structured information.
        
        Args:
            data: Raw QR code data string
            
        Returns:
            Dictionary with parsed information
        """
        parsed = {'type': 'unknown', 'data': {}}
        
        # Check if it's a vCard
        if data.startswith('BEGIN:VCARD'):
            parsed['type'] = 'vcard'
            parsed['data'] = self._parse_vcard(data)

        # Check if it's a MECARD (Japanese DoCoMo / industry-standard QR
        # format used on many business cards). MECARD uses the same field
        # vocabulary as vCard but a flat semicolon-separated layout, so we
        # parse it into the same dict shape vCard produces.
        elif data.upper().startswith('MECARD:'):
            parsed['type'] = 'vcard'   # treat downstream as vcard
            parsed['data'] = self._parse_mecard(data)

        # Check if it's a URL
        elif data.startswith('http://') or data.startswith('https://'):
            parsed['type'] = 'url'
            parsed['data'] = {'url': data}
        
        # Check if it's an email
        elif re.match(r'^mailto:', data, re.IGNORECASE):
            parsed['type'] = 'email'
            email = data.replace('mailto:', '').replace('MAILTO:', '')
            parsed['data'] = {'email': email}
        
        # Check if it's a phone number
        elif re.match(r'^tel:', data, re.IGNORECASE):
            parsed['type'] = 'phone'
            phone = data.replace('tel:', '').replace('TEL:', '')
            parsed['data'] = {'phone': phone}
        
        # Plain text
        else:
            parsed['type'] = 'text'
            parsed['data'] = {'text': data}
        
        return parsed
    
    def _parse_vcard(self, vcard_string: str) -> Dict:
        """
        Parse a vCard string into structured data.
        
        Args:
            vcard_string: vCard format string
            
        Returns:
            Dictionary with contact information
        """
        contact_data = {}
        
        lines = vcard_string.split('\n')
        for line in lines:
            line = line.strip()
            
            if ':' not in line:
                continue
            
            # Split on first colon
            key, value = line.split(':', 1)
            
            # Handle different vCard fields
            if key.startswith('FN'):
                contact_data['full_name'] = value
            elif key.startswith('N'):
                # Format: Last;First;Middle;Prefix;Suffix
                name_parts = value.split(';')
                if len(name_parts) >= 2:
                    contact_data['last_name'] = name_parts[0]
                    contact_data['first_name'] = name_parts[1]
            elif key.startswith('ORG'):
                contact_data['organization'] = value
            elif key.startswith('TITLE'):
                contact_data['title'] = value
            elif key.startswith('TEL'):
                # Can have multiple phone numbers
                if 'phones' not in contact_data:
                    contact_data['phones'] = []
                contact_data['phones'].append(value)
            elif key.startswith('EMAIL'):
                # Can have multiple emails
                if 'emails' not in contact_data:
                    contact_data['emails'] = []
                contact_data['emails'].append(value)
            elif key.startswith('ADR'):
                contact_data['address'] = value.replace(';', ', ')
            elif key.startswith('URL'):
                contact_data['url'] = value
        
        return contact_data

    def _parse_mecard(self, mecard_string: str) -> Dict:
        """
        Parse a MECARD string into the same dict shape as vCard.

        MECARD format example:
            MECARD:N:Silva,João;ORG:Acme;TEL:+5511999999999;EMAIL:joao@acme.com;URL:acme.com;ADR:Rua Augusta 100;NOTE:VIP;;
        """
        contact_data: Dict = {}
        body = mecard_string.split(':', 1)[1] if ':' in mecard_string else ''
        # MECARD fields are separated by ';' (terminated by ';;')
        for field in body.split(';'):
            field = field.strip()
            if not field or ':' not in field:
                continue
            key, value = field.split(':', 1)
            key = key.upper()
            if key == 'N':
                # MECARD uses Last,First (comma) — vCard uses Last;First.
                parts = [p.strip() for p in value.split(',')]
                if parts:
                    contact_data['last_name'] = parts[0]
                if len(parts) > 1:
                    contact_data['first_name'] = parts[1]
            elif key == 'ORG':
                contact_data['organization'] = value
            elif key in ('TITLE', 'ROLE'):
                contact_data['title'] = value
            elif key == 'TEL':
                contact_data.setdefault('phones', []).append(value)
            elif key == 'EMAIL':
                contact_data.setdefault('emails', []).append(value)
            elif key == 'ADR':
                contact_data['address'] = value.replace(';', ', ')
            elif key == 'URL':
                contact_data['url'] = value
            elif key == 'NOTE':
                contact_data['notes'] = value
        return contact_data

    def draw_qr_codes(self, image: np.ndarray, qr_results: List[Dict]) -> np.ndarray:
        """
        Draw bounding boxes around detected QR codes.
        
        Args:
            image: Original image
            qr_results: List of QR code detection results
            
        Returns:
            Image with QR codes highlighted
        """
        result = image.copy()
        
        for i, qr in enumerate(qr_results):
            # Draw polygon around QR code
            polygon = qr['polygon']
            points = np.array(polygon, dtype=np.int32)
            cv2.polylines(result, [points], True, (255, 0, 255), 3)
            
            # Draw label
            x, y = polygon[0]
            cv2.putText(result, f'QR Code {i+1}', (x, y-10),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
        
        return result
    
    def has_qr_code(self, image: np.ndarray) -> bool:
        """
        Quick check if image contains any QR codes.
        Uses all available detectors (pyzbar + OpenCV fallback).

        Args:
            image: Input image

        Returns:
            True if at least one QR code is detected
        """
        try:
            results = self.detect_and_decode(image)
            return len(results) > 0
        except Exception:
            return False
    
    def is_available(self) -> bool:
        """
        Check if QR code reading is available.
        
        Returns:
            True if pyzbar/zbar is available
        """
        return PYZBAR_AVAILABLE
    
    def enhance_for_qr_detection(self, image: np.ndarray) -> np.ndarray:
        """
        Enhance image to improve QR code detection.
        
        Args:
            image: Input image
            
        Returns:
            Enhanced image
        """
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Apply adaptive thresholding
        enhanced = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 51, 10
        )
        
        return enhanced
    
    def extract_contact_info(self, qr_results: List[Dict]) -> Optional[Dict]:
        """
        Extract contact information from QR code results.
        
        Args:
            qr_results: List of QR code detection results
            
        Returns:
            Merged contact information from all QR codes, or None if no contact data
        """
        contact_info = {}
        
        for qr in qr_results:
            parsed = qr.get('parsed', {})
            parsed_type = parsed.get('type')
            data = parsed.get('data', {})
            
            if parsed_type == 'vcard':
                # vCard has the most complete info
                contact_info.update(data)
            elif parsed_type == 'email':
                if 'emails' not in contact_info:
                    contact_info['emails'] = []
                contact_info['emails'].append(data.get('email'))
            elif parsed_type == 'phone':
                if 'phones' not in contact_info:
                    contact_info['phones'] = []
                contact_info['phones'].append(data.get('phone'))
            elif parsed_type == 'url':
                contact_info['url'] = data.get('url')
        
        return contact_info if contact_info else None

