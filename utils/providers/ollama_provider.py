"""
Ollama Vision Provider - LOCAL FIRST priority.
Refactored from the original vision_processor.py to implement the VisionProvider interface.
"""

import time
import json
import requests
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ProviderType, ProviderStatus, ProviderConfig, ScanResult


class OllamaVisionProvider(VisionProvider):
    """Ollama-based vision provider for local model inference."""

    DEFAULT_VISION_MODELS = ['glm-ocr', 'llama3.2-vision', 'llava:13b', 'llava', 'bakllava', 'moondream']

    def __init__(self, config: Optional[ProviderConfig] = None):
        if config is None:
            config = ProviderConfig(
                provider_type=ProviderType.OLLAMA,
                model_name="glm-ocr",
                api_url="http://localhost:11434",
                timeout=120,
                priority=0,  # Highest priority (local first)
            )
        super().__init__(config)
        self.api_url = config.api_url or "http://localhost:11434"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OLLAMA

    def _get_running_vision_model(self) -> Optional[str]:
        """
        Query /api/ps to find a vision model that is ALREADY loaded in GPU/RAM.
        Using a loaded model avoids the expensive model-swap that causes timeouts.
        Returns the model name, or None if nothing relevant is running.
        """
        try:
            resp = requests.get(f"{self.api_url}/api/ps", timeout=3)
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    name = m.get("name", "")
                    if any(kw in name.lower() for kw in ["glm-ocr", "vision", "llava", "bakllava", "moondream"]):
                        return name
        except Exception:
            pass
        return None

    def check_availability(self) -> ProviderStatus:
        """
        Check if Ollama is running and a vision model is available.
        Priority:
          1. A vision model already loaded in GPU/RAM  (/api/ps)  — no swap cost
          2. The configured model name  (/api/tags)
          3. Any other installed vision model  (/api/tags)
        """
        try:
            # ── Step 1: prefer already-loaded model (zero swap cost) ──────
            running = self._get_running_vision_model()
            if running:
                if self.config.model_name != running:
                    self._last_error = None
                self.config.model_name = running
                return ProviderStatus.AVAILABLE

            # ── Step 2: check installed models ────────────────────────────
            response = requests.get(f"{self.api_url}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get('models', [])
                model_names = [m.get('name', '') for m in models]

                # Configured model installed?
                if any(self.config.model_name in name for name in model_names):
                    return ProviderStatus.AVAILABLE

                # Any vision model installed?
                for name in model_names:
                    if any(kw in name.lower() for kw in ['glm-ocr', 'vision', 'llava', 'bakllava', 'moondream']):
                        self.config.model_name = name
                        return ProviderStatus.AVAILABLE

                self._last_error = f"No vision model found. Installed: {model_names}"
                return ProviderStatus.UNAVAILABLE

            self._last_error = f"Ollama returned status {response.status_code}"
            return ProviderStatus.ERROR
        except requests.exceptions.ConnectionError:
            self._last_error = "Ollama is not running. Start with: ollama serve"
            return ProviderStatus.UNAVAILABLE
        except Exception as e:
            self._last_error = str(e)
            return ProviderStatus.ERROR

    def extract_contact(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
    ) -> ScanResult:
        """Extract contact info using Ollama vision model."""
        start_time = time.time()

        # Validate input
        if card_image is None or card_image.size == 0:
            return self._make_scan_result(None, start_time, error="Invalid or empty image")

        if len(card_image.shape) < 2 or card_image.shape[0] < 10 or card_image.shape[1] < 10:
            return self._make_scan_result(None, start_time, error=f"Image too small: {card_image.shape}")

        try:
            # Encode image — use compressed JPEG at 1024px max to keep payload small
            # and dramatically reduce inference time on CPU / low-VRAM machines.
            image_b64 = self.image_to_base64_compressed(card_image, max_size=1024, quality=85)

            # Build prompt
            prompt = self.build_extraction_prompt(qr_data)

            # Call Ollama API
            payload = {
                "model": self.config.model_name,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "keep_alive": -1,   # keep model loaded in memory between requests
                "options": {
                    "temperature": self.config.temperature,
                    "top_p": 0.9,
                    "num_predict": 512,   # cap output tokens — contact JSON is short
                }
            }

            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.config.timeout
            )

            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '').strip()
                contact_dict = self.parse_json_response(response_text)
                return self._make_scan_result(contact_dict, start_time, qr_used=bool(qr_data))
            else:
                return self._make_scan_result(
                    None, start_time,
                    error=f"Ollama API error {response.status_code}: {response.text[:200]}"
                )

        except requests.exceptions.Timeout:
            return self._make_scan_result(
                None, start_time,
                error=f"Timeout after {self.config.timeout}s. Try a faster model or increase timeout."
            )
        except Exception as e:
            return self._make_scan_result(None, start_time, error=str(e))

    def warmup(self) -> bool:
        """
        Send a tiny dummy image to force the model to load into RAM.
        Call this once before batch processing so the first real card
        doesn't time out waiting for the model to initialise.
        Returns True if the model responded within the warmup window.
        """
        try:
            # 1×1 white pixel — minimal data, just enough to trigger model load
            dummy = np.ones((1, 1, 3), dtype=np.uint8) * 255
            image_b64 = self.image_to_base64_compressed(dummy, max_size=8, quality=50)
            payload = {
                "model": self.config.model_name,
                "prompt": "Reply with the word OK only.",
                "images": [image_b64],
                "stream": False,
                "keep_alive": -1,
                "options": {"num_predict": 5},
            }
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=self.config.timeout,
            )
            return response.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> List[str]:
        """Get list of available vision models from Ollama."""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get('models', [])
                vision_keywords = ['glm-ocr', 'vision', 'llava', 'bakllava', 'moondream']
                return [
                    m['name'] for m in models
                    if any(kw in m['name'].lower() for kw in vision_keywords)
                ]
        except Exception:
            pass
        return []
