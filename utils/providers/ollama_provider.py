"""
Ollama Vision Provider - LOCAL FIRST priority.
Refactored from the original vision_processor.py to implement the VisionProvider interface.

Strategy:
  - GLM-OCR and other pure-OCR models: use a simple "read all text" prompt, then
    parse the raw output with Python regexes (OCR-first path).
  - LLM-based vision models (llama3.2-vision, llava, etc.): use the structured JSON
    extraction prompt from the base class.
"""

import re
import time
import json
import requests
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import ProviderType, ProviderStatus, ProviderConfig, ScanResult

# Models that are OCR-specialised and respond to plain "read text" prompts,
# NOT to JSON schema / instruction-following prompts.
_OCR_ONLY_MODELS = ("glm-ocr",)


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

            # ── Route to OCR-first or JSON-instruction path ─────────────────
            if self._is_ocr_model():
                # Pure OCR models (glm-ocr): ask for raw text, parse with Python.
                # Do NOT send a JSON schema — these models copy example values
                # instead of reading the image.
                prompt = self._build_ocr_prompt()
                num_predict = 400   # raw text is shorter than JSON
            else:
                # Instruction-following LLM vision models (llama3.2-vision, llava…)
                prompt = self.build_extraction_prompt(qr_data)
                num_predict = 512

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
                    "num_predict": num_predict,
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

                if self._is_ocr_model():
                    # Merge QR data (higher confidence) on top of OCR parse
                    contact_dict = self._parse_ocr_to_contact(response_text)
                    if qr_data:
                        for k, v in qr_data.items():
                            if v and not contact_dict.get(k):
                                contact_dict[k] = v
                else:
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

    # ── OCR-first path (glm-ocr and similar models) ────────────────────────

    def _is_ocr_model(self) -> bool:
        """True for pure OCR models that output raw text, not JSON."""
        name = self.config.model_name.lower()
        return any(kw in name for kw in _OCR_ONLY_MODELS)

    @staticmethod
    def _build_ocr_prompt() -> str:
        """Minimal prompt for OCR-specialised models.

        GLM-OCR is trained to read document images and output the text it
        sees in markdown format.  Asking for JSON confuses it — it copies
        values from the prompt instead of reading the image.  So we ask for
        raw text and parse it ourselves.
        """
        return (
            "Read all text from this business card image. "
            "Output every word, number, email, phone number, and URL "
            "exactly as it appears on the card. "
            "Output the raw text only, one item per line."
        )

    @staticmethod
    def _parse_ocr_to_contact(raw_text: str) -> Dict:
        """Convert raw OCR text into a contact dict using regex heuristics.

        Designed for the kind of plain-text / markdown output that GLM-OCR
        produces, e.g.:
            Joel Schimchak
            Sales Manager
            Acme Corp
            joel@acme.com
            +1 (555) 234-5678
            www.acme.com
        """
        contact: Dict = {
            "firstName": None, "lastName": None, "fullName": None,
            "title": None, "company": None,
            "email": None, "phone": None, "mobile": None,
            "address": None, "city": None, "state": None,
            "zip": None, "country": None,
            "website": None, "linkedin": None, "notes": None,
        }

        if not raw_text:
            return contact

        # Strip markdown formatting characters
        clean = re.sub(r'[*_#`>]', ' ', raw_text)
        lines = [l.strip() for l in clean.split('\n') if l.strip()]

        consumed: set = set()   # line indices already assigned to a field

        # ── Email ──────────────────────────────────────────────────────────
        email_re = re.compile(r'[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}', re.I)
        for i, line in enumerate(lines):
            m = email_re.search(line)
            if m:
                contact["email"] = m.group(0).lower()
                consumed.add(i)
                break

        # ── LinkedIn ───────────────────────────────────────────────────────
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if 'linkedin.com' in line.lower():
                contact["linkedin"] = line.strip()
                consumed.add(i)
                break

        # ── Website ────────────────────────────────────────────────────────
        web_re = re.compile(
            r'(?:https?://|www\.)\S+|[\w.-]+\.(?:com|br|net|org|io|ca|co|app)\b',
            re.I
        )
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if 'linkedin.com' in line.lower():
                continue
            m = web_re.search(line)
            if m and '@' not in line:   # exclude email lines
                contact["website"] = m.group(0).rstrip('/')
                consumed.add(i)
                break

        # ── Phone numbers ──────────────────────────────────────────────────
        # Match common formats: +55 11 99999-9999, (11) 3456-7890, 555-1234, etc.
        phone_re = re.compile(
            r'(?:\+\d{1,3}[\s.-]?)?'          # optional country code
            r'(?:\(?\d{2,4}\)?[\s.-]?)?'       # optional area code
            r'\d{3,5}[\s.-]?\d{3,5}'           # core digits
        )
        phones_found: List[str] = []
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if email_re.search(line):
                continue
            for m in phone_re.finditer(line):
                candidate = m.group(0).strip()
                # Must have at least 7 digits
                if len(re.sub(r'\D', '', candidate)) >= 7:
                    phones_found.append(candidate)
                    consumed.add(i)
        if phones_found:
            contact["phone"] = phones_found[0]
            if len(phones_found) > 1:
                contact["mobile"] = phones_found[1]

        # ── Name (first "person name" looking line) ────────────────────────
        name_re = re.compile(r'^[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇÑ][a-záéíóúàâêôãõüçñA-Z]'
                             r'(?:[\w\'-]* ?){0,6}$')
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            words = line.split()
            # Candidate: 2-5 words, no digits, no special characters (except hyphen/apostrophe)
            if 2 <= len(words) <= 5:
                if re.search(r'\d', line):
                    continue
                if re.search(r'[@#&/\\|<>{}[\]()=+*%$!^~;]', line):
                    continue
                # Must start with uppercase
                if words[0][0].isupper():
                    full_name = line
                    contact["firstName"] = words[0]
                    contact["lastName"] = ' '.join(words[1:])
                    consumed.add(i)
                    break

        # ── Title (job role keywords) ──────────────────────────────────────
        title_kw = re.compile(
            r'\b(gerente|diretor|director|manager|ceo|cto|cfo|coo|vp|vice.president'
            r'|presidente|coordinator|coordenador|engenheiro|engineer'
            r'|analista|analyst|consultor|consultant|vendas|sales|técnico|technician'
            r'|representative|representante|supervisor|especialista|specialist'
            r'|executive|executiv|account|associate|assistente|assistant'
            r'|contador|accountant|advogado|lawyer|médico|doctor|enfermeiro)\b',
            re.I
        )
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if title_kw.search(line):
                contact["title"] = line.strip()
                consumed.add(i)
                break

        # ── Company ────────────────────────────────────────────────────────
        corp_re = re.compile(
            r'\b(ltda|ltd|s\.?a\.?|inc\.?|corp\.?|group|grupo|banco|bank'
            r'|consultoria|consulting|solucoes|solutions|tecnologia|technology'
            r'|services|serviços|sistemas|systems|network|networks|global'
            r'|associados|associates|partners|parceiros|agro|agência|agency'
            r'|financeira|finance|seguros|insurance|saúde|health|clinic|clínica'
            r'|construtora|construção|construction|imóveis|imobiliária|realty)\b',
            re.I
        )
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if corp_re.search(line):
                contact["company"] = line.strip()
                consumed.add(i)
                break

        # If no company found by keyword, use the second unconsumed non-phone/email line
        # (often the company name is just a proper noun with no suffix)
        if not contact["company"]:
            candidates = [
                lines[i] for i in range(len(lines))
                if i not in consumed
                and not re.search(r'\d', lines[i])
                and len(lines[i].split()) >= 2
                and lines[i][0].isupper()
            ]
            if candidates:
                contact["company"] = candidates[0]

        return contact

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
