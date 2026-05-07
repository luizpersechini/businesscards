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
import requests
import numpy as np
from typing import Optional, Dict, List

from .base import VisionProvider

from ..models import ProviderType, ProviderStatus, ProviderConfig, ScanResult

# Models that are OCR-specialised and respond to plain "read text" prompts,
# NOT to JSON schema / instruction-following prompts.
_OCR_ONLY_MODELS = ("glm-ocr",)


class OllamaVisionProvider(VisionProvider):
    """Ollama-based vision provider for local model inference."""

    DEFAULT_VISION_MODELS = [
        'glm-ocr',          # OCR-specialised, default (#1 OmniDocBench)
        'qwen2.5vl',        # Strong general VLM fallback (96.4% DocVQA, 88.8% OCRBench)
        'llama3.2-vision',
        'llava:13b',
        'llava',
        'bakllava',
        'moondream',
    ]

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
                    if any(kw in name.lower() for kw in ["glm-ocr", "qwen", "vision", "llava", "bakllava", "moondream"]):
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
                    if any(kw in name.lower() for kw in ['glm-ocr', 'qwen', 'vision', 'llava', 'bakllava', 'moondream']):
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

        # ── Compile shared regexes ────────────────────────────────────────
        # Improved company detection regex with better patterns
        # 1. Company suffixes (must be at end of line or before punctuation)
        # 2. Strong company indicators
        # 3. Weak company indicators (need additional context)
        corp_re = re.compile(
            # Company suffixes (strong indicators)
            r'(?:^|\s)(?:ltda|ltd\.?|s\.?a\.?|inc\.?|corp\.?|corporation|incorporated|gmbh|ag|co\.?|plc|nv|spa|bv|ab|oyj)\.?\s*$',
            re.I
        )
        company_strong_kw = re.compile(
            # Strong company keywords (rarely appear in person names)
            # Use (?:^|\W) and (?:\W|$) instead of \b so we match infix too
            # (e.g. "bank" in "Citibank", "tech" in "Infotech")
            r'(?:^|\W)(?:banco|bank|financeira|finance|seguros|insurance|holding'
            r'|tecnologia|technology|sistemas|systems|construção|construction'
            r'|imóveis|realty|imobiliária|agroindustrial|agrícola|mineração'
            r'|petróleo|petroleum|energia|energy|telecomunicações|telecom'
            r'|transportes|transport|logística|logistics|distribuição|distribution'
            r'|varejo|retail|atacado|wholesale|indústria|industry|fábrica|factory'
            r'|laboratório|laboratory|clínica|clinic|hospital|universidade|university'
            r'|escola|school|faculdade|college|instituto|institute|centro|center'
            r'|fundação|foundation|associação|association|cooperativa|cooperative'
            r'|consórcio|consortium|conglomerado|conglomerate|multinacional|multinational'
            # Well-known Brazilian and global bank/finance brands
            r'|citibank|citi|bradesco|itau|itaú|santander|nubank|inter|caixa'
            r'|bb\s+seguros|bancodo\s*brasil|banco\s+do\s+brasil'
            r'|hsbc|jpmorgan|jpmc|morgan\s*stanley|goldman\s*sachs|deutsche'
            r'|ubs|credit\s*suisse|barclays|bnp\s*paribas|societe\s*generale'
            r'|btg\s*pactual|xp\s*investimentos|safra|bmg|pan\s+americano'
            r'|merrill\s*lynch|wells\s*fargo|bank\s*of\s*america)(?:\W|$)',
            re.I
        )
        company_weak_kw = re.compile(
            # Weak company keywords (can appear in person names, titles, or companies)
            # Use (?:^|\W) and (?:\W|$) instead of \b for infix matching
            r'(?:^|\W)(?:consultoria|consulting|soluções|solutions|serviços|services'
            r'|grupo|group|global|internacional|international|nacional|national'
            r'|brasileira|brazilian|americana|american|europeia|european|mundial|worldwide'
            r'|digital|online|web|software|hardware|cloud|data|info|media|marketing'
            r'|comunicação|communication|publicidade|advertising|design|arquitetura|architecture'
            r'|engenharia|engineering|projetos|projects|gestão|management|administração|administration'
            r'|recursos|resources|capital|investimentos|investments|desenvolvimento|development'
            r'|pesquisa|research|inovação|innovation|qualidade|quality|segurança|security)(?:\W|$)',
            re.I
        )
        title_kw = re.compile(
            r'\b(gerente|diretor|director|manager|ceo|cto|cfo|coo|cso|cmo|cpo'
            r'|vp|vice.president|vice.presidente|president|presidente'
            r'|coordinator|coordenador|engenheiro|engineer'
            r'|analista|analyst|consultor|consultant|vendas|sales|técnico|technician'
            r'|representative|representante|supervisor|especialista|specialist'
            r'|executive|executiv|account|associate|assistente|assistant'
            r'|contador|accountant|advogado|lawyer|médico|doctor|enfermeiro'
            # English seniority / function words that appear in titles
            r'|officer|chief|head|leader|principal|partner|founder|co-founder'
            r'|chairman|treasurer|controller|strategist|advisor|adviser'
            r'|developer|architect|scientist|researcher|analyst|intern'
            r'|treasurer|director|managing|senior|junior|staff|lead'
            # Finance / banking specific
            r'|banker|trader|broker|underwriter|portfolio|relationship'
            r'|structured|project\s+finance|corporate\s+development'
            r'|treasury|securities|decarbonization|commercial)\b',
            re.I
        )
        # Brazilian ZIP (CEP): NNNNN-NNN — used to identify ZIP lines below.
        cep_re = re.compile(r'^\d{5}-\d{3}$')

        # ── Phone numbers (Google libphonenumber) ────────────────────────────
        # PhoneNumberMatcher handles +55, mobile-9 prefix, area codes, intl
        # formats, and importantly REJECTS CEPs (NNNNN-NNN) automatically.
        try:
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
        except ImportError:
            # phonenumbers not installed — leave phone fields empty rather
            # than fall back to the brittle regex that misidentified CEPs.
            pass

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
            r'\b(?:av\.?|avenida|rua|r\.|alameda|al\.|travessa|tv\.'
            r'|estrada|rodovia|blvd|boulevard|praça|pca\.'
            r'|street|st\.|avenue|ave\.?|road|rd\.'
            r'|drive|dr\.|lane|ln\.|suite|ste\.?|apt\.?|floor|fl\.?'
            r'|andar|sala|cj\.?|conjunto|loja)\b',
            re.I
        )
        # "City, ST" or "City - ST" patterns (2-letter state/province code)
        city_state_re = re.compile(
            r'^[A-ZÀ-Ú][A-Za-zÀ-ú\s\-]+(?:,\s*|-\s*)[A-Z]{2}$'
        )
        # Country: match only when the whole line IS the country name
        # (prevents "Banco do Brasil" from triggering on "brasil")
        country_re = re.compile(
            r'^(?:brasil|brazil|usa|united\s+states|estados\s+unidos'
            r'|argentina|portugal|mexico|méxico|chile|colômbia|colombia'
            r'|france|germany|espanha|spain|italia|italy|canada)\s*$',
            re.I
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
                parts = re.split(r',\s*|-\s*', stripped, 1)
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
        pp_results: Dict[int, tuple] = {}   # idx -> (kind, parsed_dict)
        try:
            import probablepeople as pp  # type: ignore
            from probableparsing import RepeatedLabelError  # type: ignore
            for i, line in enumerate(lines):
                if i in consumed:
                    continue
                line_stripped = line.strip()
                words = line_stripped.split()
                if not (1 <= len(words) <= 6):
                    continue
                if re.search(r'\d', line_stripped):
                    continue
                if re.search(r'[@#&/\\|<>{}[\]()=+*%$!^~;]', line_stripped):
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
        except ImportError:
            pass

        # ── Name detection (probablepeople Person classification) ──────────
        for i, (kind, parsed) in pp_results.items():
            if kind != "Person":
                continue
            # GivenName + (MiddleName) + Surname + (SuffixGenerational)
            given = parsed.get("GivenName", "")
            surname_parts = [
                parsed.get("MiddleName", ""),       # e.g. "da", "de", middle
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
                if re.search(r'\d', line):
                    continue
                if re.search(r'[@#&/\\|<>{}[\]()=+*%$!^~;]', line):
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
        _free_domains = {"gmail", "yahoo", "hotmail", "outlook", "icloud",
                         "live", "msn", "uol", "bol", "terra", "ig", "protonmail",
                         "aol", "zoho", "yandex", "mail", "gmx", "tutanota"}

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
            has_name_before = any(j < i and (lines[j] in consumed or 
                                            (contact.get("firstName") and 
                                             lines[j].find(contact["firstName"]) >= 0)) 
                                 for j in range(max(0, i-3), i))
            has_title_before = any(j < i and title_kw.search(lines[j]) for j in range(max(0, i-2), i))
            
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
                        common_last_names = {'silva', 'santos', 'oliveira', 'souza', 'rodrigues', 
                                           'ferreira', 'alves', 'pereira', 'lima', 'gomes', 
                                           'ribeiro', 'martins', 'carvalho', 'almeida', 'lopes',
                                           'smith', 'johnson', 'williams', 'brown', 'jones',
                                           'garcia', 'miller', 'davis', 'rodriguez', 'martinez'}
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
                        domain_stem.upper() if len(domain_stem) <= 3
                        else domain_stem.capitalize()
                    )
            except (IndexError, AttributeError):
                pass

        return contact

    def get_available_models(self) -> List[str]:
        """Get list of available vision models from Ollama."""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=3)
            if response.status_code == 200:
                models = response.json().get('models', [])
                vision_keywords = ['glm-ocr', 'qwen', 'vision', 'llava', 'bakllava', 'moondream']
                return [
                    m['name'] for m in models
                    if any(kw in m['name'].lower() for kw in vision_keywords)
                ]
        except Exception:
            pass
        return []
