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
    
    def __init__(self):
        """Initialize the QR reader."""
        pass
    
    def detect_and_decode(self, image: np.ndarray) -> List[Dict]:
        """
        Detect and decode all QR codes in an image.
        ALWAYS ATTEMPTS - will raise exception if library not available.
        
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
        # Force attempt - raise error if not available
        if not PYZBAR_AVAILABLE:
            raise RuntimeError(f"QR code library not available: {PYZBAR_ERROR}. Install: brew install zbar")
        
        # Convert to grayscale for better detection
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Detect QR codes
        detected_codes = pyzbar.decode(gray)
        
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
                'parsed': parsed_data
            })
        
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
        
        Args:
            image: Input image
            
        Returns:
            True if at least one QR code is detected
        """
        if not PYZBAR_AVAILABLE:
            return False
        results = self.detect_and_decode(image)
        return len(results) > 0
    
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

