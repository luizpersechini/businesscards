"""
Abstract base class for all vision/LLM providers.
Defines the contract that all providers must implement.
"""

import abc
import base64
import re
import time
import numpy as np
import cv2
from PIL import Image
from io import BytesIO
from typing import Optional, Dict, List

from ..models import ContactInfo, ProviderType, ProviderStatus, ProviderConfig, ScanResult


# ─── CJK→Latin character repair ──────────────────────────────────────────────
# GLM-OCR (Chinese-origin model) occasionally substitutes accented Latin
# characters with visually-vaguely-similar CJK ideographs during generation
# of Portuguese/Spanish/French text. Symptoms observed in production:
#   André → Andr矇 ('é' → U+77C7)
#   Reboucas → Rebou癟as ('ç' → U+765F)
#   São → S瓊o ('ã' → U+74CA)
# We post-process the parsed JSON to repair known substitutions. Unknown
# CJK characters in Latin-context fields are replaced with the unaccented
# vowel guess (a, e, i, o, u) or '?' as a last resort.
_CJK_TO_LATIN: Dict[str, str] = {
    # confirmed in production data
    "矇": "é",
    "癟": "ç",
    "瓊": "ã",
    # extend as new substitutions are observed
}
# Match any CJK Unified Ideograph (the block where most substitutions occur).
# Includes the main block (4E00-9FFF) and the radicals/symbols blocks.
_CJK_RE = re.compile(r"[　-〿㐀-䶿一-鿿豈-﫿]")
# Fields that should never contain CJK characters (Latin-context).
_LATIN_FIELDS = {
    "firstName",
    "lastName",
    "fullName",
    "title",
    "company",
    "email",
    "phone",
    "mobile",
    "website",
    "linkedin",
    "address",
    "city",
    "state",
    "zip",
    "country",
    "notes",
}


def _repair_cjk_in_text(text: str) -> str:
    """Replace CJK chars with their likely Latin original (or '?' if unknown)."""
    if not isinstance(text, str) or not _CJK_RE.search(text):
        return text
    out = []
    for ch in text:
        if _CJK_RE.match(ch):
            out.append(_CJK_TO_LATIN.get(ch, "?"))
        else:
            out.append(ch)
    return "".join(out)


def repair_cjk_substitutions(contact_dict: Optional[Dict]) -> Optional[Dict]:
    """Apply CJK→Latin repair to every Latin-context string field in-place.
    Safe to call with None or non-dict input."""
    if not isinstance(contact_dict, dict):
        return contact_dict
    for k, v in list(contact_dict.items()):
        if k in _LATIN_FIELDS and isinstance(v, str):
            contact_dict[k] = _repair_cjk_in_text(v)
    return contact_dict


# ─── Title-in-name detection ─────────────────────────────────────────────────
# Vision models routinely confuse a job title for the person's name when the
# title is the largest text block on the card (common layout). We detect by
# matching against a wordlist of role tokens in EN / PT / ES / FR / DE / IT.
# Match policy: a string is "title-like" if (a) ≥50 % of its tokens are role
# tokens, OR (b) it starts with an unambiguous role token (CEO, Manager,
# Diretor, etc.) and contains no honorific. Tokens are matched case-folded.
_ROLE_TOKENS = frozenset(
    t.lower()
    for t in (
        # English — exec / mgmt
        "CEO",
        "CTO",
        "CFO",
        "COO",
        "CIO",
        "CMO",
        "CISO",
        "CSO",
        "CDO",
        "President",
        "Vice",
        "VP",
        "EVP",
        "SVP",
        "Director",
        "Manager",
        "Head",
        "Lead",
        "Chief",
        "Officer",
        "Executive",
        "Founder",
        "Co-Founder",
        "Cofounder",
        "Owner",
        "Partner",
        "Principal",
        "Associate",
        "Assistant",
        "Deputy",
        "Senior",
        "Sr",
        "Junior",
        "Jr",
        # English — function / role
        "Engineer",
        "Architect",
        "Designer",
        "Developer",
        "Programmer",
        "Consultant",
        "Analyst",
        "Specialist",
        "Coordinator",
        "Supervisor",
        "Administrator",
        "Representative",
        "Rep",
        "Agent",
        "Broker",
        "Salesperson",
        "Salesman",
        "Saleswoman",
        "Sales",
        "Marketing",
        "Operations",
        "Finance",
        "Accounting",
        "Legal",
        "Recruiter",
        "Counsel",
        "Attorney",
        "Lawyer",
        "Account",
        "Project",
        "Product",
        "Program",
        "Business",
        "Technical",
        "Solutions",
        "Strategy",
        "Strategic",
        "Global",
        "Regional",
        "Country",
        "General",
        "Customer",
        "Client",
        "Service",
        "Support",
        "Development",
        "Software",
        "Hardware",
        "Field",
        # Honorific-as-title edge cases
        "Dr",
        "Prof",
        "Professor",
        # Portuguese
        "Diretor",
        "Diretora",
        "Diretoria",
        "Gerente",
        "Coordenador",
        "Coordenadora",
        "Supervisor",
        "Supervisora",
        "Analista",
        "Engenheiro",
        "Engenheira",
        "Consultor",
        "Consultora",
        "Vendedor",
        "Vendedora",
        "Comercial",
        "Vendas",
        "Presidente",
        "Sócio",
        "Socio",
        "Proprietário",
        "Proprietario",
        "Dono",
        "Chefe",
        "Líder",
        "Lider",
        "Assistente",
        "Auxiliar",
        "Estagiário",
        "Estagiaria",
        "Operações",
        "Operacoes",
        "Financeiro",
        "Financeira",
        "Recursos",
        "Humanos",
        "RH",
        # Spanish
        "Gerente",
        "Director",
        "Directora",
        "Jefe",
        "Jefa",
        "Vendedor",
        "Asesor",
        "Asesora",
        "Encargado",
        "Encargada",
        "Ingeniero",
        "Ingeniera",
        # French
        "Directeur",
        "Directrice",
        "Responsable",
        "Chargé",
        "Charge",
        "Ingénieur",
        "Ingenieur",
        "Commercial",
        "Commerciale",
        # German
        "Geschäftsführer",
        "Geschaeftsfuehrer",
        "Leiter",
        "Leiterin",
        "Vertrieb",
        "Verkauf",
        "Einkauf",
        # Italian
        "Direttore",
        "Responsabile",
        "Venditore",
        "Ingegnere",
    )
)

# Strong-signal tokens — appearance of any one of these alone (regardless of
# the rest of the string) is enough to demote the value to title.
_ROLE_STRONG = frozenset(
    t.lower()
    for t in (
        "CEO",
        "CTO",
        "CFO",
        "COO",
        "CIO",
        "CMO",
        "CISO",
        "CSO",
        "CDO",
        "VP",
        "EVP",
        "SVP",
        "President",
        "Director",
        "Manager",
        "Diretor",
        "Diretora",
        "Gerente",
        "Geschäftsführer",
        "Geschaeftsfuehrer",
        "Directeur",
        "Direttore",
        "Presidente",
        "Founder",
        "Cofounder",
        "Co-Founder",
    )
)

# Honorifics & person-name signals — presence vetoes the demotion (the string
# is probably actually a name even if it shares a token with a role list).
_NAME_SIGNALS = frozenset(
    t.lower()
    for t in (
        "Mr",
        "Mrs",
        "Ms",
        "Miss",
        "Sir",
        "Dame",
        "Sr.",
        "Sra",
        "Sra.",
        "Srta",
        "Mlle",
        "Mme",
        "M.",
        "Herr",
        "Frau",
        "Signor",
        "Signora",
    )
)

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][\w'\-]*", re.UNICODE)


def _looks_like_title(value: str) -> bool:
    """Return True if `value` reads more like a job title than a person name."""
    if not value or not isinstance(value, str):
        return False
    tokens = [t.lower() for t in _TOKEN_RE.findall(value)]
    if not tokens or len(tokens) > 6:
        # >6 tokens is unusual for either a title or a name; skip.
        return False
    # Veto if any honorific or other name-signal is present.
    if any(t in _NAME_SIGNALS for t in tokens):
        return False

    role_hits = sum(1 for t in tokens if t in _ROLE_TOKENS)

    # A single strong token on its own ("CEO", "Director", "Diretor") is
    # an unambiguous title. But a strong token mixed WITH a non-role token
    # is most likely a person whose surname collides with a role word —
    # e.g. "Mike Director", "Anna Presidente". For those, fall through to
    # the density rule rather than blanking a real name. So: strong-alone
    # demotes only when every token is a role token (which also covers
    # multi-word all-role titles like "Vice President" / "Sales Director").
    has_strong = any(t in _ROLE_STRONG for t in tokens)
    if has_strong and role_hits == len(tokens):
        return True

    # Otherwise demand >=50% of tokens be role-like AND >=2 role tokens
    # (single weak match like "global" alone shouldn't demote).
    return role_hits >= 2 and role_hits / len(tokens) >= 0.5


def demote_title_misplaced_as_name(contact_dict: Optional[Dict]) -> Optional[Dict]:
    """If `fullName` (or first/last) looks like a job title and `title` is
    empty, move it over and clear the name field. Operates in-place. Safe
    on None / non-dict.

    Rationale: vision models frequently latch onto the largest text block
    on a card (often the role) and emit it as the person's name. Caught
    here so it never reaches the contacts repo / VCF export.
    """
    if not isinstance(contact_dict, dict):
        return contact_dict

    full = (contact_dict.get("fullName") or "").strip()
    existing_title = (contact_dict.get("title") or "").strip()

    if full and _looks_like_title(full):
        # Only promote into title if title is empty — never overwrite a
        # legitimate title the model also caught.
        if not existing_title:
            contact_dict["title"] = full
        contact_dict["fullName"] = None
        # Mirror clear on firstName/lastName if they came from the same
        # title string (heuristic: their concatenation matches full).
        first = (contact_dict.get("firstName") or "").strip()
        last = (contact_dict.get("lastName") or "").strip()
        joined = f"{first} {last}".strip()
        if joined and joined.lower() == full.lower():
            contact_dict["firstName"] = None
            contact_dict["lastName"] = None
        return contact_dict

    # Also catch the firstName+lastName-only case (no fullName populated).
    if not full:
        first = (contact_dict.get("firstName") or "").strip()
        last = (contact_dict.get("lastName") or "").strip()
        joined = f"{first} {last}".strip()
        if joined and _looks_like_title(joined):
            if not existing_title:
                contact_dict["title"] = joined
            contact_dict["firstName"] = None
            contact_dict["lastName"] = None

    return contact_dict


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

        if not image.flags["C_CONTIGUOUS"]:
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
        if format.upper() == "JPEG" and pil_image.mode == "RGBA":
            bg = Image.new("RGB", pil_image.size, (255, 255, 255))
            bg.paste(pil_image, mask=pil_image.split()[3])
            pil_image = bg

        pil_image.save(buffer, format=format.upper())
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    @staticmethod
    def image_to_base64_compressed(
        image: np.ndarray, max_size: int = 1024, quality: int = 85
    ) -> str:
        """
        Convert image to base64 JPEG with aggressive size reduction.
        Uses cv2.imencode (not PIL) to guarantee a valid JPEG byte stream.
        Use for local models (Ollama, vLLM) to cut inference time on CPU/low-VRAM.
        """
        if image is None or image.size == 0:
            raise ValueError("Invalid or empty image")

        if not image.flags["C_CONTIGUOUS"]:
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
        success, buffer = cv2.imencode(".jpg", image, encode_params)
        if not success:
            raise RuntimeError("cv2.imencode failed to produce JPEG")

        return base64.b64encode(buffer.tobytes()).decode("utf-8")

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

        prompt += """Extract all contact information from this business card image and return it as a JSON object.

Read EVERY piece of text visible in the image and fill in this JSON with the actual values from the card:
{
  "firstName": null,
  "lastName": null,
  "fullName": null,
  "title": null,
  "company": null,
  "email": null,
  "phone": null,
  "mobile": null,
  "address": null,
  "city": null,
  "state": null,
  "zip": null,
  "country": null,
  "website": null,
  "linkedin": null,
  "notes": null
}

Rules:
- Replace null ONLY with values you can actually read from the card image — never invent or guess values
- Leave as null any field not visible on the card
- firstName + lastName OR fullName (not both)
- Keep phone numbers exactly as printed; add country code only if shown (+55 for Brazil)
- Portuguese job titles: Gerente=Manager, Diretor=Director, Presidente=President
- CRITICAL: Use ONLY Latin characters (a-z, A-Z) with proper Western European accents (é, è, ê, à, ã, â, ç, ñ, ü, ö, ô). NEVER substitute non-Latin characters (Chinese 矇/癟/瓊, Japanese, Korean, etc.) for accented Latin letters. If unsure, use the unaccented letter instead.
- Return ONLY the JSON object. No markdown, no explanation, no extra text."""
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
            start = response_text.index("{")
            end = response_text.rindex("}") + 1
            return json.loads(response_text[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        return None

    def _make_scan_result(
        self,
        contact_dict: Optional[Dict],
        start_time: float,
        qr_used: bool = False,
        error: Optional[str] = None,
    ) -> ScanResult:
        """Helper to create a ScanResult from extraction output."""
        elapsed_ms = int((time.time() - start_time) * 1000)

        if error or not contact_dict:
            return ScanResult(
                contact=ContactInfo(),
                confidence=0.0,
                provider_used=self.provider_type,
                processing_time_ms=elapsed_ms,
                qr_data_used=qr_used,
                error=error or "No contact data extracted",
            )

        # Repair CJK substitutions (also reapplied centrally in
        # CardProcessor.extract_contact for the QR-only fast path).
        contact_dict = repair_cjk_substitutions(contact_dict)
        # Catch the common vision-model failure mode where the role text is
        # emitted as fullName. Moves it to title (if title was empty) and
        # blanks the name fields so a real name still gets pulled later.
        contact_dict = demote_title_misplaced_as_name(contact_dict)
        contact = ContactInfo.from_legacy_dict(contact_dict)
        confidence = 0.9 if contact.has_minimum_data() else 0.3

        return ScanResult(
            contact=contact,
            confidence=confidence,
            provider_used=self.provider_type,
            processing_time_ms=elapsed_ms,
            qr_data_used=qr_used,
        )
