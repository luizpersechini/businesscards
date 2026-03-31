"""
vLLM Vision Provider - LOCAL priority.
Supports vLLM's OpenAI-compatible API for serving local vision models.
"""

import time
import json
import base64
import requests
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ProviderType, ProviderStatus, ProviderConfig, ScanResult


class VLLMVisionProvider(VisionProvider):
    """vLLM-based vision provider using OpenAI-compatible API."""

    def __init__(self, config: Optional[ProviderConfig] = None):
        if config is None:
            config = ProviderConfig(
                provider_type=ProviderType.VLLM,
                model_name="llava-hf/llava-v1.6-mistral-7b-hf",
                api_url="http://localhost:8000",
                timeout=120,
                priority=1,  # Second priority after Ollama
            )
        super().__init__(config)
        self.api_url = (config.api_url or "http://localhost:8000").rstrip('/')

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.VLLM

    def check_availability(self) -> ProviderStatus:
        """Check if vLLM server is running."""
        try:
            response = requests.get(f"{self.api_url}/v1/models", timeout=3)
            if response.status_code == 200:
                models = response.json().get('data', [])
                if models:
                    # Auto-select first available model if configured one isn't found
                    model_ids = [m.get('id', '') for m in models]
                    if self.config.model_name not in model_ids and model_ids:
                        self.config.model_name = model_ids[0]
                    return ProviderStatus.AVAILABLE

                self._last_error = "vLLM is running but no models loaded"
                return ProviderStatus.UNAVAILABLE

            self._last_error = f"vLLM returned status {response.status_code}"
            return ProviderStatus.ERROR
        except requests.exceptions.ConnectionError:
            self._last_error = "vLLM server not running. Start with: vllm serve <model>"
            return ProviderStatus.UNAVAILABLE
        except Exception as e:
            self._last_error = str(e)
            return ProviderStatus.ERROR

    def extract_contact(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
    ) -> ScanResult:
        """Extract contact info using vLLM's OpenAI-compatible vision API."""
        start_time = time.time()

        if card_image is None or card_image.size == 0:
            return self._make_scan_result(None, start_time, error="Invalid or empty image")

        try:
            image_b64 = self.image_to_base64(card_image, format="JPEG")
            prompt = self.build_extraction_prompt(qr_data)

            # vLLM uses OpenAI-compatible chat completions API
            payload = {
                "model": self.config.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 1024,
                "temperature": self.config.temperature,
            }

            response = requests.post(
                f"{self.api_url}/v1/chat/completions",
                json=payload,
                timeout=self.config.timeout
            )

            if response.status_code == 200:
                result = response.json()
                content = result['choices'][0]['message']['content']
                contact_dict = self.parse_json_response(content)
                return self._make_scan_result(contact_dict, start_time, qr_used=bool(qr_data))
            else:
                return self._make_scan_result(
                    None, start_time,
                    error=f"vLLM API error {response.status_code}: {response.text[:200]}"
                )

        except requests.exceptions.Timeout:
            return self._make_scan_result(None, start_time, error=f"Timeout after {self.config.timeout}s")
        except Exception as e:
            return self._make_scan_result(None, start_time, error=str(e))

    def get_available_models(self) -> List[str]:
        """Get list of available models from vLLM."""
        try:
            response = requests.get(f"{self.api_url}/v1/models", timeout=3)
            if response.status_code == 200:
                return [m['id'] for m in response.json().get('data', [])]
        except Exception:
            pass
        return []
