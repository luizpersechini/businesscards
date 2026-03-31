"""
Abstract base class for all vision/LLM providers.
Defines the contract that all providers must implement.
"""

import abc
import base64
import time
import numpy as np
import cv2
from PIL import Image
from io import BytesIO
from typing import Optional, Dict, List

# Import from parent
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ContactInfo, ProviderType, ProviderStatus, ProviderConfig, ScanResult


class VisionProvider(abc.ABC):
    """Abstract base class for vision/LLM providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._last_error: Optional[str] = None

    @property
    @abc.abstractmethod
    def provider_type(self) -> ProviderType:
        """Return the provider type enum."""
        ...

    @abc.abstractmethod
    def check_availability(self) -> ProviderStatus:
        """Check if this provider is currently available."""
        ...

    @abc.abstractmethod
    def extract_contact(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
    ) -> ScanResult:
        """
        Extract contact information from a business card image.

        Args:
            card_image: OpenCV image (BGR format numpy array)
            qr_data: Optional QR code data to supplement extraction

        Returns:
            ScanResult with extracted contact info
        """
        ...

    @abc.abstractmethod
    def get_available_models(self) -> List[str]:
        """Return list of available models for this provider."""
        ...

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @staticmethod
    def image_to_base64(image: np.ndarray, format: str = "PNG") -> str:
        """Convert OpenCV BGR image to base64 string."""
        if image is None or image.size == 0:
            raise ValueError("Invalid or empty image")

        if not image.flags['C_CONTIGUOUS']:
            image = np.ascontiguousarray(image)

        # Convert to RGB
        if len(image.shape) == 2:
            rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif image.shape[2] == 4:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        else:
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        if rgb.dtype != np.uint8:
            rgb = rgb.astype(np.uint8)

        pil_image = Image.fromarray(rgb)

        # Resize if too large
        max_size = 4096
        if pil_image.width > max_size or pil_image.height > max_size:
            pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buffer = BytesIO()
        if format.upper() == "JPEG" and pil_image.mode == 'RGBA':
            bg = Image.new('RGB', pil_image.size, (255, 255, 255))
            bg.paste(pil_image, mask=pil_image.split()[3])
            pil_image = bg

        pil_image.save(buffer, format=format.upper())
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    @staticmethod
    def image_to_base64_compressed(image: np.ndarray, max_size: int = 1024, quality: int = 85) -> str:
        """
        Convert image to base64 JPEG with aggressive size reduction.
        Uses cv2.imencode (not PIL) to guarantee a valid JPEG byte stream.
        Use for local models (Ollama, vLLM) to cut inference time on CPU/low-VRAM.
        """
        if image is None or image.size == 0:
            raise ValueError("Invalid or empty image")

        if not image.flags['C_CONTIGUOUS']:
            image = np.ascontiguousarray(image)

        # Ensure BGR uint8 — cv2.imencode expects BGR
        if image.dtype != np.uint8:
            image = image.astype(np.uint8)

        if len(image.shape) == 2:
            # Grayscale → BGR
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        # Downscale on the longest edge
        h, w = image.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Encode with cv2 — produces a strictly valid JPEG byte stream
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        success, buffer = cv2.imencode('.jpg', image, encode_params)
        if not success:
            raise RuntimeError("cv2.imencode failed to produce JPEG")

        return base64.b64encode(buffer.tobytes()).decode('utf-8')

    @staticmethod
    def build_extraction_prompt(qr_data: Optional[Dict] = None) -> str:
        """Build the standard contact extraction prompt."""
        prompt = """You are an expert at extracting contact information from business card images.

Analyze this business card image carefully and extract all visible contact information.

"""
        if qr_data:
            import json
            prompt += f"""QR CODE DATA FOUND (use this as primary source):
{json.dumps(qr_data, indent=2)}

"""

        prompt += """Extract and return ONLY a valid JSON object with these fields. Use null for missing information:

{
  "firstName": "first name only",
  "lastName": "last name only",
  "fullName": "complete name (use this if you can't split first/last)",
  "title": "job title (e.g., CEO, Manager, Director, Engineer)",
  "company": "company or organization name",
  "email": "email address",
  "phone": "primary phone with country code if present",
  "mobile": "mobile/cell phone if different from main phone",
  "address": "street address",
  "city": "city name",
  "state": "state or province",
  "zip": "postal/ZIP code",
  "country": "country name",
  "website": "website URL",
  "linkedin": "LinkedIn URL",
  "notes": "any other relevant info"
}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON - no explanations, no markdown, no extra text
2. Look at the image carefully - read ALL visible text
3. Portuguese titles: "Presidente" = President, "Diretor" = Director, "Gerente" = Manager
4. Phone format: Keep country code (+55 for Brazil), format as +55 (XX) XXXXX-XXXX
5. Company identifiers: Ltda, S.A., Inc, LLC, ministry names
6. Addresses: Look for Rua, Avenida, Av., Street, numbers, CEP, ZIP
7. If QR code data exists, use it as primary source and fill gaps from image
8. Handle rotated or skewed text as best as possible
9. Multiple names may indicate full name (e.g., "João da Silva Santos")
10. Look for social media icons and URLs (LinkedIn, Facebook, Twitter)

Return ONLY the JSON object, starting with { and ending with }. No markdown code blocks."""
        return prompt

    @staticmethod
    def parse_json_response(response_text: str) -> Optional[Dict]:
        """Parse JSON from LLM response with multiple fallback strategies."""
        import json

        # Strategy 1: Direct parse
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Strategy 2: Extract from markdown code blocks
        if "```json" in response_text:
            try:
                start = response_text.index("```json") + 7
                end = response_text.index("```", start)
                return json.loads(response_text[start:end].strip())
            except (ValueError, json.JSONDecodeError):
                pass

        if "```" in response_text:
            try:
                start = response_text.index("```") + 3
                end = response_text.index("```", start)
                return json.loads(response_text[start:end].strip())
            except (ValueError, json.JSONDecodeError):
                pass

        # Strategy 3: Find JSON by braces
        try:
            start = response_text.index('{')
            end = response_text.rindex('}') + 1
            return json.loads(response_text[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        return None

    def _make_scan_result(self, contact_dict: Optional[Dict], start_time: float,
                          qr_used: bool = False, error: Optional[str] = None) -> ScanResult:
        """Helper to create a ScanResult from extraction output."""
        elapsed_ms = int((time.time() - start_time) * 1000)

        if error or not contact_dict:
            return ScanResult(
                contact=ContactInfo(),
                confidence=0.0,
                provider_used=self.provider_type,
                processing_time_ms=elapsed_ms,
                qr_data_used=qr_used,
                error=error or "No contact data extracted"
            )

        contact = ContactInfo.from_legacy_dict(contact_dict)
        confidence = 0.9 if contact.has_minimum_data() else 0.3

        return ScanResult(
            contact=contact,
            confidence=confidence,
            provider_used=self.provider_type,
            processing_time_ms=elapsed_ms,
            qr_data_used=qr_used,
        )
