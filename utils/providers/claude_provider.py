"""
Claude Vision Provider - CLOUD FALLBACK.
Uses Anthropic's Claude API with structured outputs for business card extraction.
Only used when local providers (Ollama, vLLM) are unavailable.
"""

import time
import json
import os
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ProviderType, ProviderStatus, ProviderConfig, ScanResult, ContactInfo


class ClaudeVisionProvider(VisionProvider):
    """Anthropic Claude-based vision provider (cloud fallback)."""

    SUPPORTED_MODELS = [
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ]

    def __init__(self, config: Optional[ProviderConfig] = None):
        if config is None:
            config = ProviderConfig(
                provider_type=ProviderType.CLAUDE,
                model_name="claude-sonnet-4-6",
                api_url="https://api.anthropic.com",
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                timeout=30,
                priority=10,  # Lower priority than local
            )
        super().__init__(config)
        self._client = None

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.CLAUDE

    def _get_client(self):
        """Lazy-initialize Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
                if not api_key:
                    raise ValueError("ANTHROPIC_API_KEY not set")
                self._client = anthropic.Anthropic(api_key=api_key)
            except ImportError:
                raise ImportError("Install anthropic SDK: pip install anthropic")
        return self._client

    def check_availability(self) -> ProviderStatus:
        """Check if Claude API is accessible."""
        try:
            api_key = self.config.api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                self._last_error = "ANTHROPIC_API_KEY not set. Set env var or pass api_key in config."
                return ProviderStatus.UNAVAILABLE

            # Try to import the SDK
            try:
                import anthropic
            except ImportError:
                self._last_error = "anthropic SDK not installed. Run: pip install anthropic"
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
        """Extract contact info using Claude Vision API."""
        start_time = time.time()

        if card_image is None or card_image.size == 0:
            return self._make_scan_result(None, start_time, error="Invalid or empty image")

        try:
            client = self._get_client()
            image_b64 = self.image_to_base64(card_image, format="PNG")
            prompt = self.build_extraction_prompt(qr_data)

            # Use Claude's native vision capability
            message = client.messages.create(
                model=self.config.model_name,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_b64,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            }
                        ],
                    }
                ],
                temperature=self.config.temperature,
            )

            response_text = message.content[0].text
            contact_dict = self.parse_json_response(response_text)

            result = self._make_scan_result(contact_dict, start_time, qr_used=bool(qr_data))
            # Claude typically has higher confidence
            if result.contact.has_minimum_data():
                result.confidence = 0.95
            return result

        except Exception as e:
            return self._make_scan_result(None, start_time, error=str(e))

    def get_available_models(self) -> List[str]:
        """Return supported Claude models."""
        return self.SUPPORTED_MODELS.copy()
