"""
Ollama Vision Provider - LOCAL FIRST priority.
Refactored from the original vision_processor.py to implement the VisionProvider interface.

Strategy:
  - GLM-OCR and other pure-OCR models: use a simple "read all text" prompt, then
    parse the raw output with Python regexes (OCR-first path).
  - LLM-based vision models (llama3.2-vision, llava, etc.): use the structured JSON
    extraction prompt from the base class.
"""

import json
import logging
import os
import re
import time
import requests
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider, detect_cjk_script, _CJK_ANY_RE

from ..models import ProviderType, ProviderStatus, ProviderConfig, ScanResult

logger = logging.getLogger(__name__)

# Probe optional OCR-parser dependencies once at import time so we can:
#   1. Log a clear, actionable warning if any are missing (instead of
#      silently dropping fields, which is what `except ImportError: pass`
#      used to do — and led to undetected production regressions).
#   2. Skip the per-card try/import overhead.
try:
    import phonenumbers as _phonenumbers  # noqa: F401

    PHONENUMBERS_AVAILABLE = True
except ImportError as _e:
    PHONENUMBERS_AVAILABLE = False
    logger.error(
        "phonenumbers missing — phone numbers will NOT be extracted. "
        "Install with: pip install phonenumbers  (error: %s)",
        _e,
    )

try:
    import probablepeople as _pp  # noqa: F401
    from probableparsing import RepeatedLabelError as _RLE  # noqa: F401

    PROBABLEPEOPLE_AVAILABLE = True
except ImportError as _e:
    PROBABLEPEOPLE_AVAILABLE = False
    logger.error(
        "probablepeople missing — name/company classification will degrade "
        "to a brittle regex fallback that often misclassifies. "
        "Install with: pip install probablepeople  (error: %s)",
        _e,
    )

# Models that are OCR-specialised and respond to plain "read text" prompts,
# NOT to JSON schema / instruction-following prompts.
_OCR_ONLY_MODELS = ("glm-ocr",)


class OllamaVisionProvider(VisionProvider):
    """Ollama-based vision provider for local model inference."""

    DEFAULT_VISION_MODELS = [
        # Ordered by measured accuracy on the user's own locked-contact
        # benchmark (see /api/benchmark). qwen2.5vl wins overall; glm-ocr is
        # fast but scores 0% on names (OCR-only, no field reasoning), so it's
        # demoted from the historical default.
        "qwen2.5vl",  # best overall (83.6% field accuracy on our cards)
        "minicpm-v",  # balanced; best on names, ~2x faster than qwen
        "glm-ocr",  # fastest, but weak on names — OCR-specialised
        "llama3.2-vision",
        "llava:13b",
        "llava",
        "bakllava",
        "moondream",
    ]

    def __init__(self, config: Optional[ProviderConfig] = None):
        if config is None:
            config = ProviderConfig(
                provider_type=ProviderType.OLLAMA,
                model_name="qwen2.5vl:7b",
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
                    if any(
                        kw in name.lower()
                        for kw in ["glm-ocr", "qwen", "vision", "llava", "bakllava", "moondream"]
                    ):
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
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]

                # Configured model installed?
                if any(self.config.model_name in name for name in model_names):
                    return ProviderStatus.AVAILABLE

                # Any vision model installed?
                for name in model_names:
                    if any(
                        kw in name.lower()
                        for kw in ["glm-ocr", "qwen", "vision", "llava", "bakllava", "moondream"]
                    ):
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
            return self._make_scan_result(
                None, start_time, error=f"Image too small: {card_image.shape}"
            )

        try:
            # Encode image — use compressed JPEG at 1024px max to keep payload small
            # and dramatically reduce inference time on CPU / low-VRAM machines.
            image_b64 = self.image_to_base64_compressed(card_image, max_size=1024, quality=85)

            # ── Constrained JSON path (default for ALL models) ──────────────
            # We used to gate this on `not _is_ocr_model()` because earlier
            # schemas embedded example values that glm-ocr would parrot
            # verbatim instead of reading the card. Our schema now uses only
            # null defaults — no values to copy — and A/B testing showed
            # glm-ocr returns *strictly better* output when constrained:
            # valid JSON, more populated fields, less hallucinated markdown.
            # So we apply the schema universally and fall back to the OCR
            # regex parser only if the model still emits non-JSON for some
            # reason.
            #
            # Opt-out for emergencies: set OLLAMA_DISABLE_JSON_SCHEMA=1 to
            # revert to the old raw-OCR-text path for the named OCR models.
            use_json_schema = os.environ.get("OLLAMA_DISABLE_JSON_SCHEMA", "").strip() != "1"
            if use_json_schema:
                prompt = self.build_extraction_prompt(qr_data)
                num_predict = 512
            elif self._is_ocr_model():
                prompt = self._build_ocr_prompt()
                num_predict = 400
            else:
                prompt = self.build_extraction_prompt(qr_data)
                num_predict = 512

            payload = {
                "model": self.config.model_name,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "keep_alive": -1,  # keep model loaded in memory between requests
                "options": {
                    "temperature": self.config.temperature,
                    "top_p": 0.9,
                    "num_predict": num_predict,
                },
            }
            if use_json_schema:
                payload["format"] = self._contact_json_schema()

            response = requests.post(
                f"{self.api_url}/api/generate", json=payload, timeout=self.config.timeout
            )

            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()

                # Parse strategy:
                #  - JSON-schema path (default): direct JSON parse; the
                #    schema guarantees parseable output. If that somehow
                #    fails on a model that doesn't honour the format
                #    constraint, fall back to the OCR regex parser as a
                #    safety net for OCR-named models.
                #  - Raw-OCR path (OLLAMA_DISABLE_JSON_SCHEMA=1, OCR
                #    models only): use the regex parser as before.
                contact_dict = None
                if use_json_schema:
                    contact_dict = self.parse_json_response(response_text)
                    if not contact_dict and self._is_ocr_model():
                        # Schema-promised JSON didn't materialise — last
                        # ditch, run the raw OCR parser anyway.
                        contact_dict = self._parse_ocr_to_contact(response_text)
                elif self._is_ocr_model():
                    contact_dict = self._parse_ocr_to_contact(response_text)
                    if qr_data:
                        for k, v in qr_data.items():
                            if v and not contact_dict.get(k):
                                contact_dict[k] = v
                else:
                    contact_dict = self.parse_json_response(response_text)

                # Diagnostic: when the model's reply yields no usable contact
                # (no name, no email) the factory only reports "extracted no
                # usable contact data" — the raw reply is otherwise lost.
                # Log enough to tell a parse failure from a genuine blank.
                _cd = contact_dict or {}
                _has_person = any(_cd.get(k) for k in ("fullName", "firstName", "lastName", "email"))
                _has_corporate = _cd.get("company") and any(
                    _cd.get(k) for k in ("phone", "mobile", "website", "address")
                )
                if not _has_person and not _has_corporate:
                    msg = (
                        f"⚠ {self.config.model_name}: reply produced no name/email "
                        f"(json_schema={use_json_schema}, parsed_keys="
                        f"{sorted(k for k, v in _cd.items() if v)}, "
                        f"reply_len={len(response_text)}). Raw head: "
                        f"{response_text[:500]!r}"
                    )
                    h_, w_ = card_image.shape[:2]
                    msg += f" | crop={w_}x{h_}"
                    # Keep the exact crop the model saw — without it a failure
                    # on a user upload is unreproducible (uploads aren't
                    # archived when a scan yields zero cards).
                    try:
                        import cv2 as _cv2

                        dbg_dir = os.path.join(
                            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                            "temp",
                            "debug",
                        )
                        os.makedirs(dbg_dir, exist_ok=True)
                        dbg_path = os.path.join(dbg_dir, f"failed_crop_{int(time.time())}.png")
                        _cv2.imwrite(dbg_path, card_image)
                        msg += f" | saved {dbg_path}"
                    except Exception as _e:  # never let diagnostics break a scan
                        msg += f" | (crop not saved: {_e})"
                    logger.warning(msg)
                    print(msg)

                # CJK cards (Japanese/Chinese/Korean): the fields came back in
                # the printed script. Second pass on the same crop asks the
                # model for Latin versions (romaji name, English company and
                # title); originals are preserved in notes. Off with
                # OLLAMA_CJK_TRANSLATE=0. Latin cards never pay for this.
                script = detect_cjk_script(contact_dict)
                if script and contact_dict:
                    contact_dict["_detected_lang"] = script
                    if os.environ.get("OLLAMA_CJK_TRANSLATE", "1").strip() != "0":
                        contact_dict = self._translate_cjk_fields(image_b64, contact_dict, script)

                # Optional LLM post-correction with language-aware routing.
                # Off by default. Configure per-language model overrides:
                #   OCR_POST_CORRECTION_MODEL_EN=qwen2.5:3b
                #   OCR_POST_CORRECTION_MODEL_PT=gemma3:1b-pt
                #   OCR_POST_CORRECTION_MODEL_ES=qwen2.5:3b
                # Falls back to the generic `OCR_POST_CORRECTION_MODEL` for
                # any language without a specific override. When neither is
                # set, no correction runs.
                lang, correction_model = self._pick_correction_model(response_text)
                if correction_model and contact_dict:
                    if lang:
                        contact_dict["_detected_lang"] = lang
                    contact_dict = (
                        self._llm_post_correct(
                            raw_text=response_text,
                            parsed=contact_dict,
                            model=correction_model,
                        )
                        or contact_dict
                    )

                return self._make_scan_result(contact_dict, start_time, qr_used=bool(qr_data))
            else:
                return self._make_scan_result(
                    None,
                    start_time,
                    error=f"Ollama API error {response.status_code}: {response.text[:200]}",
                )

        except requests.exceptions.Timeout:
            return self._make_scan_result(
                None,
                start_time,
                error=f"Timeout after {self.config.timeout}s. Try a faster model or increase timeout.",
            )
        except Exception as e:
            return self._make_scan_result(None, start_time, error=str(e))

    # ── CJK translation pass ───────────────────────────────────────────────

    _CJK_SCRIPT_NAMES = {"ja": "Japanese", "zh": "Chinese", "ko": "Korean"}
    _CJK_TRANSLATE_FIELDS = ("firstName", "lastName", "fullName", "company", "title")

    @classmethod
    def _cjk_translation_schema(cls) -> Dict:
        nullable_string = {"type": ["string", "null"]}
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {k: nullable_string for k in cls._CJK_TRANSLATE_FIELDS},
        }

    @staticmethod
    def _cjk_original_line(contact: Dict) -> str:
        name = contact.get("fullName") or " ".join(
            p for p in (contact.get("lastName"), contact.get("firstName")) if p
        )
        parts = [p for p in (name, contact.get("company"), contact.get("title")) if p]
        return " · ".join(parts)

    @staticmethod
    def _reconcile_name_with_email(contact: Dict) -> None:
        """The model often romanizes only the furigana (the given-name
        reading) and then splits it into two words — "きみあき" → "Kimi Aki"
        while the email says kimiaki.tsuden@. When the email local part is
        `a.b` / `a_b` and the romanized name collapses to exactly one of
        those parts, take both names from the email (first.last order)."""
        email = contact.get("email") or ""
        local = email.split("@", 1)[0].lower() if "@" in email else ""
        parts = [p for p in re.split(r"[._-]", local) if p.isalpha()]
        if len(parts) != 2:
            return
        name_tokens = [
            t for t in re.split(r"\s+", (contact.get("fullName") or "").strip()) if t
        ] or [t for t in (contact.get("firstName"), contact.get("lastName")) if t]
        joined = "".join(name_tokens).lower()
        if not joined or joined == "".join(parts):
            return
        if joined in parts:
            contact["firstName"] = parts[0].capitalize()
            contact["lastName"] = parts[1].capitalize()
            contact["fullName"] = f"{contact['firstName']} {contact['lastName']}"

    def _translate_cjk_fields(self, image_b64: str, contact: Dict, script: str) -> Dict:
        """Ask the vision model for Latin-script name/company/title of a CJK
        card. Replaces those fields only with values that are genuinely
        Latin; keeps the printed originals in `notes` ("原文: …"). Any
        failure leaves the contact untouched."""
        lang = self._CJK_SCRIPT_NAMES.get(script, "CJK")
        extracted = {k: contact.get(k) for k in self._CJK_TRANSLATE_FIELDS if contact.get(k)}
        email = contact.get("email")
        romaji = "Hepburn romaji" if script == "ja" else (
            "Revised Romanization" if script == "ko" else "Hanyu pinyin"
        )
        prompt = (
            f"This business card is printed in {lang}. Fields already read from it:\n"
            f"{json.dumps(extracted, ensure_ascii=False)}\n"
            + (f"Email on the card: {email}\n" if email else "")
            + "Give Latin-script versions:\n"
            f"- firstName / lastName: the person's name in {romaji}, given name in firstName, "
            "family name in lastName. If the card prints a romanized or English name, or the "
            "email local part spells it, use exactly that spelling. Capitalize normally.\n"
            "- fullName: firstName + space + lastName. On Japanese cards the family name is "
            "printed first; small kana above or beside the name is its reading (furigana), not "
            "an extra name.\n"
            "- company: the company's official English name if printed on the card or well "
            "known; otherwise a faithful romanization.\n"
            "- title: the job title translated to English.\n"
            "Use only Latin letters. Return null for anything you cannot determine. "
            "Return ONLY the JSON object."
        )
        payload = {
            "model": self.config.model_name,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
            "keep_alive": -1,
            "format": self._cjk_translation_schema(),
            "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 256},
        }
        try:
            resp = requests.post(
                f"{self.api_url}/api/generate", json=payload, timeout=self.config.timeout
            )
            if resp.status_code != 200:
                logger.warning("CJK translation pass failed: HTTP %s", resp.status_code)
                return contact
            latin = self.parse_json_response(resp.json().get("response", "")) or {}
        except Exception as e:  # never let the extra pass break the scan
            logger.warning("CJK translation pass failed: %s", e)
            return contact

        original_line = self._cjk_original_line(contact)
        changed = False
        for k in self._CJK_TRANSLATE_FIELDS:
            v = latin.get(k)
            if isinstance(v, str) and v.strip() and not _CJK_ANY_RE.search(v):
                contact[k] = v.strip()
                changed = True
        if changed and (latin.get("firstName") or latin.get("lastName")) and not latin.get("fullName"):
            contact["fullName"] = " ".join(
                p for p in (contact.get("firstName"), contact.get("lastName")) if p
            )
        if changed:
            self._reconcile_name_with_email(contact)
        if changed and original_line:
            prefix = f"原文: {original_line}"
            notes = contact.get("notes")
            contact["notes"] = f"{prefix}\n{notes}" if notes else prefix
        return contact

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
    def _detect_language(text: str) -> Optional[str]:
        """Best-effort 2-letter ISO 639-1 language code for `text`.
        Returns None if `langdetect` is not installed, the text is too
        short to classify, or detection fails. Mostly we care about
        'en', 'pt', 'es' for business-card routing.

        We seed langdetect for determinism — short multilingual text
        can otherwise yield different codes on repeated runs.
        """
        if not text or len(text.strip()) < 12:
            return None
        try:
            from langdetect import detect, DetectorFactory  # type: ignore

            DetectorFactory.seed = 0
            return detect(text)
        except Exception:
            return None

    @classmethod
    def _pick_correction_model(cls, raw_text: str) -> tuple:
        """Decide which post-correction model to use based on language.

        Lookup order:
          1. OCR_POST_CORRECTION_MODEL_<UPPER>  (e.g. ..._PT, ..._EN, ..._ES)
          2. OCR_POST_CORRECTION_MODEL          (generic fallback)

        Returns (detected_lang_code_or_None, model_name_or_empty).
        Caller treats empty model_name as "skip correction".
        """
        lang = cls._detect_language(raw_text)
        if lang:
            specific = os.environ.get(f"OCR_POST_CORRECTION_MODEL_{lang.upper()}", "").strip()
            if specific:
                return lang, specific
        generic = os.environ.get("OCR_POST_CORRECTION_MODEL", "").strip()
        return lang, generic

    @staticmethod
    def _contact_json_schema() -> Dict:
        """JSON schema enforced by Ollama's `format` field for LLM vision
        models. Mirrors the keys used by ContactInfo.from_legacy_dict so
        existing downstream code keeps working unchanged.

        What this schema enforces:
          - Object shape: exactly the 16 contact fields, nothing else.
          - Field types: each field is `string | null`. The model can no
            longer return a nested object, an array, or a number for a
            name / email / etc.
          - additionalProperties: false — extra keys are rejected so the
            model can't invent "department" or "extension" on the side.

        What this schema does NOT enforce (intentionally, see below):
          - Regex `pattern` constraints on email / phone / website etc.
            Ollama 0.24's grammar backend compiles patterns through a
            JSON-Schema → GBNF path that hangs the server on anything
            non-trivial (every pattern we tried, even `^.{1,5}$`, caused
            RemoteDisconnected within 10s). We rely on downstream
            validators (`phonenumbers`, `email_validator`) instead.
            Revisit if/when Ollama merges full XGrammar regex support.
        """

        nullable_string = {"type": ["string", "null"]}
        all_keys = [
            "firstName",
            "lastName",
            "fullName",
            "title",
            "company",
            "email",
            "phone",
            "mobile",
            "address",
            "city",
            "state",
            "zip",
            "country",
            "website",
            "linkedin",
            "notes",
        ]
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {k: nullable_string for k in all_keys},
        }

    def _llm_post_correct(
        self,
        raw_text: str,
        parsed: Dict,
        model: str,
    ) -> Optional[Dict]:
        """Optional: ask a small LLM to clean up the regex parser's output.

        Sends the raw OCR text plus our best-guess structured fields and
        asks the model to fix typos, restore lost diacritics, and reassign
        any obviously misplaced fields. Uses Ollama's `format=` schema so
        the response is guaranteed to be valid JSON.

        Returns the corrected dict, or None on any failure (caller falls
        back to the original parsed dict).
        """
        prompt = (
            "You are a JSON-only assistant. Below is the raw text read off "
            "a business card by an OCR engine, and a draft contact record "
            "extracted from it. Return the SAME JSON object, fixed: "
            "restore lost diacritics, fix obvious typos against the raw "
            "text, and move misplaced values into the right fields. Do not "
            "invent values that aren't in the raw text. Output JSON only.\n\n"
            f"RAW OCR TEXT:\n{raw_text}\n\n"
            f"DRAFT JSON:\n{json.dumps(parsed, ensure_ascii=False)}\n"
        )
        try:
            resp = requests.post(
                f"{self.api_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": -1,
                    "format": self._contact_json_schema(),
                    "options": {"temperature": 0.0, "num_predict": 600},
                },
                timeout=self.config.timeout,
            )
            if resp.status_code != 200:
                return None
            text = resp.json().get("response", "").strip()
            corrected = self.parse_json_response(text)
            if not isinstance(corrected, dict):
                return None
            # Drop nulls so we never overwrite a real value with None
            return {k: v for k, v in corrected.items() if v}
        except Exception:
            return None

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
            "firstName": None,
            "lastName": None,
            "fullName": None,
            "title": None,
            "company": None,
            "email": None,
            "phone": None,
            "mobile": None,
            "address": None,
            "city": None,
            "state": None,
            "zip": None,
            "country": None,
            "website": None,
            "linkedin": None,
            "notes": None,
        }

        if not raw_text:
            return contact

        # Strip markdown formatting characters
        clean = re.sub(r"[*_#`>]", " ", raw_text)
        lines = [l.strip() for l in clean.split("\n") if l.strip()]

        consumed: set = set()  # line indices already assigned to a field

        # ── Email ──────────────────────────────────────────────────────────
        email_re = re.compile(r"[\w.+%-]+@[\w.-]+\.[a-zA-Z]{2,}", re.I)
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
            if "linkedin.com" in line.lower():
                contact["linkedin"] = line.strip()
                consumed.add(i)
                break

        # ── Website ────────────────────────────────────────────────────────
        # Priority order is enforced project-wide: Name > Company > Email >
        # Phone > Website > others. Website runs AFTER email/linkedin (so
        # email lines are excluded) but BEFORE phone/name/company detection
        # so a URL line can't accidentally be claimed as a company name.
        # Broaden the TLD list to cover the common ones we see in business
        # cards: country TLDs (br, fr, de, es, uk, au, jp, ca, mx, ar, …),
        # generic TLDs (com, net, org, info, biz, io, co, app, ai, dev),
        # plus government / academic (gov, gov.br, gouv, edu, mil) and the
        # Brazilian compound TLDs (com.br, org.br, gov.br, mg.gov.br, ...).
        web_re = re.compile(
            # 1. Explicit scheme or www. prefix — strongest signal
            r"(?:https?://|www\.)[A-Za-z0-9._~:/?#@!$&'()*+,;=%\-]+"
            # 2. Bare domain with known TLD. Allow 1+ labels before the
            #    final TLD so both `acme.com` and `sub.acme.gov.br` match.
            r"|\b[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)*"
            r"\.(?:com|net|org|info|biz|io|co|app|ai|dev|me|tv|us|uk|fr|de|es|it|pt|nl|be|ch|se|no|fi|dk|au|jp|cn|kr|mx|ar|cl|pe|ve|br|ca|ru|in|pl|cz|tr|gov|gouv|edu|mil)\b",
            re.I,
        )

        # Helper: prefer matches with a scheme/www, then longer matches.
        def _score_website(s: str) -> tuple:
            s_low = s.lower()
            scheme = s_low.startswith("http://") or s_low.startswith("https://")
            www = s_low.startswith("www.")
            return (scheme, www, len(s))

        url_prefix_re = re.compile(
            r"^(?:url|web(?:site|page)?|site|link|home(?:page)?)\s*[:\-]\s*", re.I
        )
        candidates: List[tuple] = []  # (line_idx, match)
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            line_clean = url_prefix_re.sub("", line.strip())
            if "@" in line_clean:
                continue  # skip email lines outright
            if "linkedin.com" in line_clean.lower():
                continue  # LinkedIn handled separately
            m = web_re.search(line_clean)
            if not m:
                continue
            url = m.group(0).rstrip(".,;:)]>\"'/ ")
            # Reject obvious non-URLs the regex caught: bare two-word names
            # ending in a TLD letter pair (e.g. "Ltd Co" wouldn't pass but
            # something like "investment.io" with a known TLD does — keep
            # those since they're real URLs).
            if "." not in url or url.count(".") == 0:
                continue
            candidates.append((i, url))

        if candidates:
            # Pick the best candidate by score (scheme > www > length)
            best_idx, best_url = max(candidates, key=lambda c: _score_website(c[1]))
            contact["website"] = best_url
            consumed.add(best_idx)

        # ── Compile shared regexes ────────────────────────────────────────
        # Improved company detection regex with better patterns
        # 1. Company suffixes (must be at end of line or before punctuation)
        # 2. Strong company indicators
        # 3. Weak company indicators (need additional context)
        corp_re = re.compile(
            # Company suffixes (strong indicators)
            r"(?:^|\s)(?:ltda|ltd\.?|s\.?a\.?|inc\.?|corp\.?|corporation|incorporated|gmbh|ag|co\.?|plc|nv|spa|bv|ab|oyj)\.?\s*$",
            re.I,
        )
        company_strong_kw = re.compile(
            # Strong company keywords (rarely appear in person names)
            # Use (?:^|\W) and (?:\W|$) instead of \b so we match infix too
            # (e.g. "bank" in "Citibank", "tech" in "Infotech")
            r"(?:^|\W)(?:banco|bank|financeira|finance|seguros|insurance|holding"
            r"|tecnologia|technology|sistemas|systems|construção|construction"
            r"|imóveis|realty|imobiliária|agroindustrial|agrícola|mineração"
            r"|petróleo|petroleum|energia|energy|telecomunicações|telecom"
            r"|transportes|transport|logística|logistics|distribuição|distribution"
            r"|varejo|retail|atacado|wholesale|indústria|industry|fábrica|factory"
            r"|laboratório|laboratory|clínica|clinic|hospital|universidade|university"
            r"|escola|school|faculdade|college|instituto|institute|centro|center"
            r"|fundação|foundation|associação|association|cooperativa|cooperative"
            r"|consórcio|consortium|conglomerado|conglomerate|multinacional|multinational"
            # Well-known Brazilian and global bank/finance brands
            r"|citibank|citi|bradesco|itau|itaú|santander|nubank|inter|caixa"
            r"|bb\s+seguros|bancodo\s*brasil|banco\s+do\s+brasil"
            r"|hsbc|jpmorgan|jpmc|morgan\s*stanley|goldman\s*sachs|deutsche"
            r"|ubs|credit\s*suisse|barclays|bnp\s*paribas|societe\s*generale"
            r"|btg\s*pactual|xp\s*investimentos|safra|bmg|pan\s+americano"
            r"|merrill\s*lynch|wells\s*fargo|bank\s*of\s*america)(?:\W|$)",
            re.I,
        )
        company_weak_kw = re.compile(
            # Weak company keywords (can appear in person names, titles, or companies)
            # Use (?:^|\W) and (?:\W|$) instead of \b for infix matching
            r"(?:^|\W)(?:consultoria|consulting|soluções|solutions|serviços|services"
            r"|grupo|group|global|internacional|international|nacional|national"
            r"|brasileira|brazilian|americana|american|europeia|european|mundial|worldwide"
            r"|digital|online|web|software|hardware|cloud|data|info|media|marketing"
            r"|comunicação|communication|publicidade|advertising|design|arquitetura|architecture"
            r"|engenharia|engineering|projetos|projects|gestão|management|administração|administration"
            r"|recursos|resources|capital|investimentos|investments|desenvolvimento|development"
            r"|pesquisa|research|inovação|innovation|qualidade|quality|segurança|security)(?:\W|$)",
            re.I,
        )
        title_kw = re.compile(
            r"\b(gerente|diretor|director|manager|ceo|cto|cfo|coo|cso|cmo|cpo"
            r"|vp|vice.president|vice.presidente|president|presidente"
            r"|coordinator|coordenador|engenheiro|engineer"
            r"|analista|analyst|consultor|consultant|vendas|sales|técnico|technician"
            r"|representative|representante|supervisor|especialista|specialist"
            r"|executive|executiv|account|associate|assistente|assistant"
            r"|contador|accountant|advogado|lawyer|médico|doctor|enfermeiro"
            # English seniority / function words that appear in titles
            r"|officer|chief|head|leader|principal|partner|founder|co-founder"
            r"|chairman|treasurer|controller|strategist|advisor|adviser"
            r"|developer|architect|scientist|researcher|analyst|intern"
            r"|treasurer|director|managing|senior|junior|staff|lead"
            # Finance / banking specific
            r"|banker|trader|broker|underwriter|portfolio|relationship"
            r"|structured|project\s+finance|corporate\s+development"
            r"|treasury|securities|decarbonization|commercial)\b",
            re.I,
        )
        # Brazilian ZIP (CEP): NNNNN-NNN — used to identify ZIP lines below.
        cep_re = re.compile(r"^\d{5}-\d{3}$")

        # ── Phone numbers (Google libphonenumber) ────────────────────────────
        # PhoneNumberMatcher handles +55, mobile-9 prefix, area codes, intl
        # formats, and importantly REJECTS CEPs (NNNNN-NNN) automatically.
        # If phonenumbers is unavailable, the module-level probe at the top
        # of this file has already logged an actionable error; skip silently
        # here to avoid 18 redundant log lines per scan.
        if PHONENUMBERS_AVAILABLE:
            import phonenumbers

            phones_found: List[str] = []
            for i, line in enumerate(lines):
                if i in consumed:
                    continue
                if email_re.search(line):
                    continue
                for match in phonenumbers.PhoneNumberMatcher(line, "BR"):
                    formatted = phonenumbers.format_number(
                        match.number,
                        phonenumbers.PhoneNumberFormat.INTERNATIONAL,
                    )
                    phones_found.append(formatted)
                    consumed.add(i)
            if phones_found:
                contact["phone"] = phones_found[0]
                if len(phones_found) > 1:
                    contact["mobile"] = phones_found[1]

        # ── Store ZIP if found (look for CEP-format lines) ────────────────
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if cep_re.search(line.strip()):
                contact["zip"] = line.strip()
                consumed.add(i)
                break

        # ── Address lines (street, city/state, country) ───────────────────
        # Must run BEFORE company/name detection so address text is consumed
        # and never mistaken for a company or name.
        addr_kw_re = re.compile(
            r"\b(?:av\.?|avenida|rua|r\.|alameda|al\.|travessa|tv\."
            r"|estrada|rodovia|blvd|boulevard|praça|pca\."
            r"|street|st\.|avenue|ave\.?|road|rd\."
            r"|drive|dr\.|lane|ln\.|suite|ste\.?|apt\.?|floor|fl\.?"
            r"|andar|sala|cj\.?|conjunto|loja)\b",
            re.I,
        )
        # "City, ST" or "City - ST" patterns (2-letter state/province code)
        city_state_re = re.compile(r"^[A-ZÀ-Ú][A-Za-zÀ-ú\s\-]+(?:,\s*|-\s*)[A-Z]{2}$")
        # Country: match only when the whole line IS the country name
        # (prevents "Banco do Brasil" from triggering on "brasil")
        country_re = re.compile(
            r"^(?:brasil|brazil|usa|united\s+states|estados\s+unidos"
            r"|argentina|portugal|mexico|méxico|chile|colômbia|colombia"
            r"|france|germany|espanha|spain|italia|italy|canada)\s*$",
            re.I,
        )

        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if addr_kw_re.search(line):
                if not contact["address"]:
                    contact["address"] = line.strip()
                consumed.add(i)

        for i, line in enumerate(lines):
            if i in consumed:
                continue
            stripped = line.strip()
            if city_state_re.match(stripped):
                parts = re.split(r",\s*|-\s*", stripped, 1)
                if not contact["city"]:
                    contact["city"] = parts[0].strip()
                if len(parts) > 1 and not contact["state"]:
                    contact["state"] = parts[1].strip()
                consumed.add(i)

        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if country_re.match(line.strip()):
                if not contact["country"]:
                    contact["country"] = line.strip()
                consumed.add(i)

        # ── Pre-classify candidate lines with probablepeople (CRF model) ────
        # probablepeople.tag() returns kind in {"Person", "Corporation",
        # "Household"} along with structured fields (GivenName, Surname,
        # SuffixGenerational, CorporationName, CorporationLegalType, …).
        # We use it to drive BOTH name and company detection — eliminating
        # the brittle heuristics that previously misclassified e.g.
        # "Banco do Brasil" as a person.
        # If probablepeople is unavailable, the module-level probe at the
        # top of this file has already logged an actionable error. Fall
        # through to the regex-based fallbacks below — they're brittle but
        # not nothing.
        pp_results: Dict[int, tuple] = {}  # idx -> (kind, parsed_dict)
        if PROBABLEPEOPLE_AVAILABLE:
            import probablepeople as pp  # type: ignore
            from probableparsing import RepeatedLabelError  # type: ignore

            for i, line in enumerate(lines):
                if i in consumed:
                    continue
                line_stripped = line.strip()
                words = line_stripped.split()
                if not (1 <= len(words) <= 6):
                    continue
                if re.search(r"\d", line_stripped):
                    continue
                if re.search(r"[@#&/\\|<>{}[\]()=+*%$!^~;]", line_stripped):
                    continue
                # Skip all-caps logos / department headers — pp can't tell
                # them apart from company names reliably
                if line_stripped == line_stripped.upper() and len(line_stripped) > 3:
                    continue
                try:
                    parsed_list, kind = pp.tag(line_stripped)
                    pp_results[i] = (kind, dict(parsed_list))
                except RepeatedLabelError:
                    pass
                except Exception:
                    pass

        # ── Name detection (probablepeople Person classification) ──────────
        for i, (kind, parsed) in pp_results.items():
            if kind != "Person":
                continue
            # GivenName + (MiddleName) + Surname + (SuffixGenerational)
            given = parsed.get("GivenName", "")
            surname_parts = [
                parsed.get("MiddleName", ""),  # e.g. "da", "de", middle
                parsed.get("MiddleInitial", ""),
                parsed.get("Surname", ""),
                parsed.get("SuffixGenerational", ""),  # Jr., Sr., II
            ]
            surname = " ".join(p for p in surname_parts if p).strip()
            if given:
                contact["firstName"] = given
                contact["lastName"] = surname or None
                consumed.add(i)
                break
        else:
            # Fallback heuristic if probablepeople didn't tag any line as Person
            for i, line in enumerate(lines):
                if i in consumed:
                    continue
                words = line.split()
                if not (2 <= len(words) <= 5):
                    continue
                if re.search(r"\d", line):
                    continue
                if re.search(r"[@#&/\\|<>{}[\]()=+*%$!^~;]", line):
                    continue
                if line == line.upper() and len(line) > 3:
                    continue
                if corp_re.search(line) or title_kw.search(line):
                    continue
                if words[0] and words[0][0].isupper():
                    contact["firstName"] = words[0]
                    contact["lastName"] = " ".join(words[1:])
                    consumed.add(i)
                    break

        # ── Title (job role keywords) ──────────────────────────────────────
        for i, line in enumerate(lines):
            if i in consumed:
                continue
            if title_kw.search(line):
                contact["title"] = line.strip()
                consumed.add(i)
                break

        # ── Company detection ────────────────────────────────────────────
        # Priority ladder:
        # 1. probablepeople classified the line as "Corporation"
        # 2. Strong indicators: company suffixes (Inc., Ltd., Ltda, S.A.)
        # 3. Strong company keywords (Banco, Tecnologia, Bank...)
        # 4. Weak company keywords + position heuristic
        # 5. Email domain inference (last resort)

        # Free email domains (for domain-based company inference)
        _free_domains = {
            "gmail",
            "yahoo",
            "hotmail",
            "outlook",
            "icloud",
            "live",
            "msn",
            "uol",
            "bol",
            "terra",
            "ig",
            "protonmail",
            "aol",
            "zoho",
            "yandex",
            "mail",
            "gmx",
            "tutanota",
        }

        # Step 1: trust probablepeople's Corporation classification first.
        for i, (kind, _) in pp_results.items():
            if i in consumed:
                continue
            if kind == "Corporation":
                contact["company"] = lines[i].strip()
                consumed.add(i)
                break

        # Track potential company lines with confidence scores
        company_candidates = []

        for i, line in enumerate(lines):
            if i in consumed:
                continue

            line_stripped = line.strip()
            confidence = 0

            # 1. Strong indicators: company suffixes at end of line
            if corp_re.search(line_stripped):
                confidence = 100  # Very high confidence
                company_candidates.append((i, line_stripped, confidence))
                continue

            # 2. Strong company keywords in line
            if company_strong_kw.search(line_stripped):
                confidence = 80  # High confidence
                # Bonus if line contains multiple words (less likely to be person name)
                if len(line_stripped.split()) >= 2:
                    confidence += 10
                company_candidates.append((i, line_stripped, confidence))
                continue

            # 3. Weak company keywords - lower confidence
            if company_weak_kw.search(line_stripped):
                confidence = 40  # Medium confidence
                company_candidates.append((i, line_stripped, confidence))
                continue

            # 4. Position-based heuristic: lines after name/title are more likely companies
            # Find if we already detected a name or title before this line
            has_name_before = any(
                j < i
                and (
                    lines[j] in consumed
                    or (contact.get("firstName") and lines[j].find(contact["firstName"]) >= 0)
                )
                for j in range(max(0, i - 3), i)
            )
            has_title_before = any(
                j < i and title_kw.search(lines[j]) for j in range(max(0, i - 2), i)
            )

            if has_name_before or has_title_before:
                # This line appears after name/title - could be company
                # Check if it looks like a company (not like a person name)
                words = line_stripped.split()
                if 1 <= len(words) <= 4:  # Companies often 1-4 words
                    # Person names usually 2-3 words, rarely 4
                    # Companies can be single words (Apple, Google) or multi-word
                    if len(words) == 1:
                        # Single word - could be company or last name
                        # Check if it looks like a common last name vs company
                        common_last_names = {
                            "silva",
                            "santos",
                            "oliveira",
                            "souza",
                            "rodrigues",
                            "ferreira",
                            "alves",
                            "pereira",
                            "lima",
                            "gomes",
                            "ribeiro",
                            "martins",
                            "carvalho",
                            "almeida",
                            "lopes",
                            "smith",
                            "johnson",
                            "williams",
                            "brown",
                            "jones",
                            "garcia",
                            "miller",
                            "davis",
                            "rodriguez",
                            "martinez",
                        }
                        if line_stripped.lower() not in common_last_names:
                            confidence = 30
                            company_candidates.append((i, line_stripped, confidence))
                    elif len(words) >= 2:
                        # Multi-word - less likely to be person name (except with middle names)
                        # Check if words are all capitalized (common for company names)
                        if all(word and word[0].isupper() for word in words):
                            confidence = 50
                            company_candidates.append((i, line_stripped, confidence))

        # Sort candidates by confidence (highest first)
        company_candidates.sort(key=lambda x: x[2], reverse=True)

        # Select the best candidate (only if probablepeople didn't already
        # set a Corporation match in step 1).
        if not contact.get("company") and company_candidates:
            best_idx, best_line, best_conf = company_candidates[0]
            # Only accept if confidence is reasonable
            if best_conf >= 30:
                contact["company"] = best_line
                consumed.add(best_idx)

        # Fallback: if no company found, use domain inference from email
        if not contact["company"] and contact.get("email"):
            try:
                domain_stem = contact["email"].split("@")[1].split(".")[0].lower()
                if domain_stem and domain_stem not in _free_domains:
                    # Short stems (≤ 3 chars) stay ALL-CAPS; longer ones are Title-cased
                    contact["company"] = (
                        domain_stem.upper() if len(domain_stem) <= 3 else domain_stem.capitalize()
                    )
            except (IndexError, AttributeError):
                pass

        return contact

    def get_available_models(self) -> List[str]:
        """Get list of available vision models from Ollama."""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get("models", [])
                vision_keywords = ["glm-ocr", "qwen", "vision", "llava", "bakllava", "moondream"]
                return [
                    m["name"]
                    for m in models
                    if any(kw in m["name"].lower() for kw in vision_keywords)
                ]
        except Exception:
            pass
        return []
