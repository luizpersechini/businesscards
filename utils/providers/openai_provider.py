"""
OpenAI Vision Provider - CLOUD FALLBACK.
Uses OpenAI's GPT-4o/GPT-4-vision for business card extraction.
Only used when local providers and Claude are unavailable.
"""

import time
import json
import os
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ProviderType, ProviderStatus, ProviderConfig, ScanResult


class OpenAIVisionProvider(VisionProvider):
    """OpenAI GPT-4o based vision provider (cloud fallback)."""

    SUPPORTED_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
    ]

    def __init__(self, config: Optional[ProviderConfig] = None):
        if config is None:
            config = ProviderConfig(
                provider_type=ProviderType.OPENAI,
                model_name="gpt-4o",
                api_url="https://api.openai.com",
                api_key=os.environ.get("OPENAI_API_KEY"),
                timeout=30,
                priority=20,  # Lowest priority
            )
        super().__init__(config)

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI

    def check_availability(self) -> ProviderStatus:
        """Check if OpenAI API is accessible."""
        try:
            api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY")
            if not api_key:
                self._last_error = "OPENAI_API_KEY not set"
                return ProviderStatus.UNAVAILABLE

            try:
                import openai
            except ImportError:
                self._last_error = "openai SDK not installed. Run: pip install openai"
                return ProviderStatus.UNAVAILABLE

            return ProviderStatus.AVAILABLE

        except Exception as e:
            self._last_error = str(e)
            return ProviderStatus.ERROR

    def extract_contact(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
    ) -> ScanResult:
        """Extract contact info using OpenAI Vision API."""
        start_time = time.time()

        if card_image is None or card_image.size == 0:
            return self._make_scan_result(None, start_time, error="Invalid or empty image")

        try:
            import openai

            api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY")
            client = openai.OpenAI(api_key=api_key)

            image_b64 = self.image_to_base64(card_image, format="JPEG")
            prompt = self.build_extraction_prompt(qr_data)

            response = client.chat.completions.create(
                model=self.config.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1024,
                temperature=self.config.temperature,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            contact_dict = self.parse_json_response(content)

            result = self._make_scan_result(contact_dict, start_time, qr_used=bool(qr_data))
            if result.contact.has_minimum_data():
                result.confidence = 0.93
            return result

        except Exception as e:
            return self._make_scan_result(None, start_time, error=str(e))

    def get_available_models(self) -> List[str]:
        return self.SUPPORTED_MODELS.copy()
