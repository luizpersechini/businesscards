"""
QR URL resolver — safely fetch a contact page that a business-card QR code
points to, and extract structured contact data from it.

Threat model: the user scans a business card whose QR encodes a URL (a
hosted vCard, a digital-business-card page, etc.) instead of inline contact
fields. We must NOT let a malicious QR turn the app into an SSRF vector
against the user's own machine / LAN, nor pull down arbitrary huge or
dangerous payloads.

Safety controls (all enforced BEFORE and DURING the fetch):
  - Scheme allowlist: http / https only.
  - No embedded credentials (user:pass@host).
  - SSRF guard: every hostname is resolved and each resulting IP is checked
    against private / loopback / link-local / reserved ranges. localhost and
    non-80/443 ports are rejected outright.
  - Redirects are followed manually (max 3 hops); every hop is re-validated
    so a public URL can't bounce to an internal one.
  - Response caps: connect/read timeout, max byte size, content-type allowlist.
  - Optional Google Safe Browsing lookup — only if GOOGLE_SAFE_BROWSING_API_KEY
    is set in the environment; skipped silently otherwise.

Residual risk: a determined attacker could attempt DNS rebinding (validate a
public IP, then re-resolve to a private one for the actual connection). For a
local single-user desktop app whose threat is "scanned a sketchy QR" this is
an accepted, documented risk; the guard still blocks the overwhelmingly common
case of a QR that directly encodes an internal URL.

Public API:
    validate_url_safe(url) -> (ok: bool, reason: str)
    resolve_qr_url(url)    -> dict  (see resolve_qr_url docstring)
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

import requests

logger = logging.getLogger(__name__)

# ── Limits / allowlists ──────────────────────────────────────────────────────
_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443, None}  # None = scheme default
_MAX_BYTES = 2_000_000  # 2 MB
_TIMEOUT = 8  # seconds (connect + read)
_MAX_REDIRECTS = 3
_ALLOWED_CONTENT_TYPES = (
    "text/vcard",
    "text/x-vcard",
    "text/directory",
    "text/html",
    "application/xhtml+xml",
    "application/json",
    "text/plain",
    # vCard download endpoints (e.g. WordPress "save contact" / Mobiz /vcard)
    # very commonly serve the .vcf as a generic binary stream. We still only
    # *parse* it as a vCard if the body starts with BEGIN:VCARD, and the
    # 2 MB cap applies, so accepting this type is safe.
    "application/octet-stream",
)
_USER_AGENT = "BusinessCardScanner/1.0 (+local; QR contact resolver)"


# ── URL safety ───────────────────────────────────────────────────────────────


def _ip_is_blocked(ip_str: str) -> bool:
    """True if the IP is in a range we must never connect to."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparseable → treat as unsafe
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        # IPv6-mapped IPv4 (e.g. ::ffff:127.0.0.1) — unwrap and re-check
        or (getattr(ip, "ipv4_mapped", None) is not None and _ip_is_blocked(str(ip.ipv4_mapped)))
    )


def _resolve_host_ips(host: str) -> List[str]:
    """Resolve a hostname to all its IPs (v4 + v6). Raises socket.gaierror."""
    infos = socket.getaddrinfo(host, None)
    return list({info[4][0] for info in infos})


def validate_url_safe(url: str) -> Tuple[bool, str]:
    """Validate a URL against the SSRF / scheme / port guard.

    Returns (ok, reason). reason is a human-readable string when ok is False.
    Does NOT make an HTTP request — only DNS resolution.
    """
    if not url or not isinstance(url, str):
        return False, "Empty URL"
    url = url.strip()
    if len(url) > 2048:
        return False, "URL too long"

    try:
        p = urlparse(url)
    except Exception:
        return False, "Unparseable URL"

    if p.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"Blocked scheme {p.scheme!r} (only http/https allowed)"
    if p.username or p.password:
        return False, "Embedded credentials are not allowed"
    host = p.hostname
    if not host:
        return False, "No host in URL"
    if host.lower() == "localhost":
        return False, "localhost is blocked"

    port = p.port
    if port not in _ALLOWED_PORTS:
        return False, f"Blocked port {port} (only 80/443 allowed)"

    # If the host is a literal IP, check it directly.
    try:
        ipaddress.ip_address(host)
        if _ip_is_blocked(host):
            return False, f"Host IP {host} is in a private/reserved range"
        return True, ""
    except ValueError:
        pass  # hostname, resolve below

    try:
        ips = _resolve_host_ips(host)
    except socket.gaierror:
        return False, f"Could not resolve host {host!r}"
    if not ips:
        return False, f"Host {host!r} resolved to no addresses"
    for ip in ips:
        if _ip_is_blocked(ip):
            return False, f"Host {host!r} resolves to a private/reserved IP ({ip})"
    return True, ""


def _check_safe_browsing(url: str) -> Tuple[bool, str]:
    """Optional Google Safe Browsing lookup. No-op (returns safe) when no
    GOOGLE_SAFE_BROWSING_API_KEY is configured."""
    api_key = os.environ.get("GOOGLE_SAFE_BROWSING_API_KEY", "").strip()
    if not api_key:
        return True, ""  # feature disabled — treat as safe
    try:
        endpoint = "https://safebrowsing.googleapis.com/v4/threatMatches:find?key=" + api_key
        body = {
            "client": {"clientId": "businesscardscanner", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": [
                    "MALWARE",
                    "SOCIAL_ENGINEERING",
                    "UNWANTED_SOFTWARE",
                    "POTENTIALLY_HARMFUL_APPLICATION",
                ],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        r = requests.post(endpoint, json=body, timeout=5)
        if r.status_code == 200 and r.json().get("matches"):
            return False, "URL flagged by Google Safe Browsing"
    except Exception as e:  # network/credential failure → don't hard-block
        logger.warning("Safe Browsing check failed (non-fatal): %s", e)
    return True, ""


# ── Fetch ────────────────────────────────────────────────────────────────────


def _safe_get(url: str) -> Tuple[Optional[requests.Response], str]:
    """Fetch a URL with manual, re-validated redirect handling and size caps.

    Returns (response, reason). response is None on failure (reason explains).
    """
    current = url
    for hop in range(_MAX_REDIRECTS + 1):
        ok, reason = validate_url_safe(current)
        if not ok:
            return None, reason
        ok, reason = _check_safe_browsing(current)
        if not ok:
            return None, reason
        try:
            resp = requests.get(
                current,
                stream=True,
                allow_redirects=False,
                timeout=_TIMEOUT,
                headers={"User-Agent": _USER_AGENT, "Accept": ", ".join(_ALLOWED_CONTENT_TYPES)},
            )
        except requests.RequestException as e:
            return None, f"Request failed: {e}"

        # Manual redirect handling so each hop is re-validated.
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            resp.close()
            if not loc:
                return None, "Redirect with no Location header"
            current = urljoin(current, loc)
            continue
        return resp, ""
    return None, f"Too many redirects (> {_MAX_REDIRECTS})"


def _read_capped(resp: requests.Response) -> Tuple[Optional[str], str]:
    """Read a response body up to _MAX_BYTES, enforcing content-type."""
    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype and not any(ctype == c for c in _ALLOWED_CONTENT_TYPES):
        return None, f"Disallowed content-type {ctype!r}"

    clen = resp.headers.get("Content-Length")
    if clen and clen.isdigit() and int(clen) > _MAX_BYTES:
        return None, f"Response too large ({clen} bytes > {_MAX_BYTES})"

    chunks = []
    total = 0
    try:
        for chunk in resp.iter_content(chunk_size=16384):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_BYTES:
                return None, f"Response exceeded {_MAX_BYTES} bytes"
            chunks.append(chunk)
    except requests.RequestException as e:
        return None, f"Read failed: {e}"
    finally:
        resp.close()

    raw = b"".join(chunks)
    encoding = resp.encoding or "utf-8"
    try:
        return raw.decode(encoding, errors="replace"), ctype
    except (LookupError, ValueError):
        return raw.decode("utf-8", errors="replace"), ctype


# ── Parsing ──────────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}")
_TEL_RE = re.compile(r"tel:\+?[0-9().\-\s]{6,}", re.I)


def _parse_vcard_text(text: str) -> Dict:
    """Minimal vCard parser → qr_data-shaped dict (self-contained, no cv2)."""
    out: Dict = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.split(";")[0].upper()  # drop params like TYPE=
        value = value.strip()
        if not value:
            continue
        if key == "FN":
            out["full_name"] = value
        elif key == "N":
            parts = value.split(";")
            if len(parts) >= 2:
                out.setdefault("last_name", parts[0])
                out.setdefault("first_name", parts[1])
        elif key == "ORG":
            out["organization"] = value.split(";")[0]
        elif key == "TITLE":
            out["title"] = value
        elif key == "ROLE":
            # Some vCards (e.g. Mobiz) put the job title in ROLE, not TITLE.
            # TITLE wins if both are present.
            out.setdefault("title", value)
        elif key == "TEL":
            out.setdefault("phones", []).append(value)
        elif key == "EMAIL":
            out.setdefault("emails", []).append(value)
        elif key == "ADR":
            out.setdefault("address", value.replace(";", ", ").strip(", "))
        elif key == "URL":
            out.setdefault("url", value)
    return out


def _parse_mecard_text(text: str) -> Dict:
    """Minimal MECARD parser → qr_data-shaped dict."""
    out: Dict = {}
    body = text[len("MECARD:") :] if text.upper().startswith("MECARD:") else text
    for field in body.split(";"):
        if ":" not in field:
            continue
        key, value = field.split(":", 1)
        key = key.strip().upper()
        value = value.strip()
        if not value:
            continue
        if key == "N":
            if "," in value:
                last, first = value.split(",", 1)
                out["last_name"] = last.strip()
                out["first_name"] = first.strip()
                out["full_name"] = f"{first.strip()} {last.strip()}".strip()
            else:
                out["full_name"] = value
        elif key == "ORG":
            out["organization"] = value
        elif key == "TEL":
            out.setdefault("phones", []).append(value)
        elif key == "EMAIL":
            out.setdefault("emails", []).append(value)
        elif key == "ADR":
            out["address"] = value
        elif key == "URL":
            out["url"] = value
        elif key == "TITLE":
            out["title"] = value
    return out


def _flatten_jsonld(obj) -> List[Dict]:
    """Yield all dict nodes from a JSON-LD object (handles @graph + lists)."""
    nodes: List[Dict] = []
    if isinstance(obj, list):
        for item in obj:
            nodes.extend(_flatten_jsonld(item))
    elif isinstance(obj, dict):
        if "@graph" in obj:
            nodes.extend(_flatten_jsonld(obj["@graph"]))
        nodes.append(obj)
    return nodes


def _parse_jsonld_person(data) -> Dict:
    """Extract contact fields from schema.org Person/Organization JSON-LD."""
    out: Dict = {}
    for node in _flatten_jsonld(data):
        t = node.get("@type", "")
        types = t if isinstance(t, list) else [t]
        types = [str(x).lower() for x in types]
        is_person = any("person" in x for x in types)
        is_org = any("organization" in x for x in types)
        if not (is_person or is_org):
            continue
        # Skip the page's WordPress author / publisher Person node — on
        # CMS-hosted digital business cards (Mobiz, WordPress) the JSON-LD
        # often carries the *site author* (e.g. the agency that built the
        # card) as a Person, which is NOT the card's subject. Identify it by
        # its author-archive URL/@id and ignore it.
        node_url = str(node.get("url") or node.get("@id") or "")
        if is_person and "/author/" in node_url:
            continue
        name = node.get("name")
        if name and "full_name" not in out and is_person:
            out["full_name"] = str(name)
        if node.get("givenName"):
            out.setdefault("first_name", str(node["givenName"]))
        if node.get("familyName"):
            out.setdefault("last_name", str(node["familyName"]))
        if node.get("jobTitle"):
            out.setdefault("title", str(node["jobTitle"]))
        email = node.get("email")
        if email:
            out.setdefault("emails", []).append(str(email).replace("mailto:", ""))
        tel = node.get("telephone")
        if tel:
            out.setdefault("phones", []).append(str(tel).replace("tel:", ""))
        url = node.get("url")
        if url:
            out.setdefault("url", str(url))
        # Organization name → organization field
        if is_org and node.get("name") and "organization" not in out:
            out["organization"] = str(node["name"])
        worksFor = node.get("worksFor")
        if isinstance(worksFor, dict) and worksFor.get("name"):
            out.setdefault("organization", str(worksFor["name"]))
    return out


def _parse_html(html: str, base_url: str) -> Tuple[Dict, Optional[str]]:
    """Extract contact data from an HTML page.

    Returns (fields, vcf_url). vcf_url, when set, is a discovered link to a
    downloadable .vcf the caller may fetch (re-validated) for richer data.
    """
    out: Dict = {}
    vcf_url: Optional[str] = None
    try:
        from bs4 import BeautifulSoup
    except Exception:
        BeautifulSoup = None

    if BeautifulSoup is None:
        # Degraded fallback: regex the raw HTML for an email + tel.
        m = _EMAIL_RE.search(html)
        if m:
            out.setdefault("emails", []).append(m.group(0))
        return out, None

    soup = BeautifulSoup(html, "html.parser")

    # 1. JSON-LD blocks (richest, structured)
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        merged = _parse_jsonld_person(data)
        for k, v in merged.items():
            if k in ("emails", "phones"):
                out.setdefault(k, []).extend(v)
            else:
                out.setdefault(k, v)

    # 2. A downloadable vCard link (HiHello/Popl-style "Save contact")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".vcf") or "vcard" in href.lower():
            vcf_url = urljoin(base_url, href)
            break

    # 3. mailto: / tel: links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()
        if low.startswith("mailto:"):
            email = href[len("mailto:") :].split("?")[0].strip()
            if email and "@" in email:
                out.setdefault("emails", []).append(email)
        elif low.startswith("tel:"):
            phone = href[len("tel:") :].strip()
            if phone:
                out.setdefault("phones", []).append(phone)

    # 4. og:title — on digital business cards this is the card owner, in the
    #    form "Name | Company" (or "Name - Company"). It's more reliable than
    #    a stray JSON-LD Person node, so when it has that separator pattern we
    #    let it OVERRIDE the name and fill the company. Without a separator we
    #    only use it as a last-resort name.
    og = soup.find("meta", attrs={"property": "og:title"})
    og_title = (og.get("content") or "").strip() if og else ""
    if og_title:
        parts = re.split(r"\s+[|\-–—]\s+", og_title, maxsplit=1)
        if len(parts) == 2:
            name_part, org_part = parts[0].strip(), parts[1].strip()
            if name_part:
                out["full_name"] = name_part  # override (authoritative)
            if org_part:
                out.setdefault("organization", org_part)
        elif "full_name" not in out:
            out["full_name"] = og_title

    # Dedup list fields
    for k in ("emails", "phones"):
        if k in out:
            seen = []
            for v in out[k]:
                if v and v not in seen:
                    seen.append(v)
            out[k] = seen
    return out, vcf_url


# ── Orchestration ────────────────────────────────────────────────────────────


def resolve_qr_url(url: str) -> Dict:
    """Fetch and parse a QR-linked contact page.

    Returns a dict:
        {
          "ok": bool,
          "reason": str,            # populated when ok is False
          "source": str,            # "vcard" | "mecard" | "json-ld/html" | ...
          "fields": dict,           # qr_data-shaped extracted fields
          "final_url": str,         # the URL actually fetched (post-redirect)
        }
    Never raises for expected failures — they come back as ok=False.
    """
    result = {"ok": False, "reason": "", "source": "", "fields": {}, "final_url": url}

    ok, reason = validate_url_safe(url)
    if not ok:
        result["reason"] = reason
        return result

    resp, reason = _safe_get(url)
    if resp is None:
        result["reason"] = reason
        return result
    result["final_url"] = resp.url or url

    body, ctype = _read_capped(resp)
    if body is None:
        result["reason"] = ctype  # ctype carries the error reason here
        return result

    stripped = body.lstrip()

    # vCard / MECARD (by content or by sniffing the body)
    if ctype in ("text/vcard", "text/x-vcard", "text/directory") or stripped.upper().startswith(
        "BEGIN:VCARD"
    ):
        result["fields"] = _parse_vcard_text(body)
        result["source"] = "vcard"
    elif stripped.upper().startswith("MECARD:"):
        result["fields"] = _parse_mecard_text(body)
        result["source"] = "mecard"
    elif ctype == "application/json":
        try:
            result["fields"] = _parse_jsonld_person(json.loads(body))
            result["source"] = "json"
        except ValueError:
            result["reason"] = "Invalid JSON body"
            return result
    else:
        # HTML (or text/plain treated as HTML-ish)
        fields, vcf_url = _parse_html(body, result["final_url"])
        result["source"] = "json-ld/html"
        # If we found a downloadable vCard, prefer its (richer) data.
        if vcf_url:
            ok2, _ = validate_url_safe(vcf_url)
            if ok2:
                vresp, _ = _safe_get(vcf_url)
                if vresp is not None:
                    vbody, _ = _read_capped(vresp)
                    if vbody and vbody.lstrip().upper().startswith("BEGIN:VCARD"):
                        vcard_fields = _parse_vcard_text(vbody)
                        # vCard wins; keep HTML-only extras as fallback
                        for k, v in fields.items():
                            vcard_fields.setdefault(k, v)
                        fields = vcard_fields
                        result["source"] = "vcard (linked)"
        result["fields"] = fields

    # Final fallback: if we still have nothing, scan the body for an email.
    if not result["fields"]:
        m = _EMAIL_RE.search(body)
        if m:
            result["fields"] = {"emails": [m.group(0)]}

    if not result["fields"]:
        result["reason"] = "No contact data found at URL"
        return result

    result["ok"] = True
    return result
