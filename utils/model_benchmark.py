"""
Model benchmark — score vision models against the user's locked contacts.

Locked contacts are human-verified ground truth: the user reviewed them,
corrected the fields, and locked them. Each one carries a `card_id` that
resolves to the cropped card image the contact was extracted from
(temp/thumbnails/<card_id>.jpg, 1400 px JPEG). Re-running extraction on
those images with different models and diffing against the locked data
gives a field-level accuracy score per model — on the user's *real* cards,
not a public benchmark.

Scoring is deliberately simple and explainable:
  - Only fields the ground truth actually has are evaluated.
  - A field scores 1 when the normalized values match, else 0.
  - Normalization: accent-fold + casefold + whitespace/punctuation collapse
    for text fields; digits-only suffix match for phones (tolerates missing
    country codes); scheme/www stripping for websites.
  - phone/mobile are pooled — models frequently swap which slot a number
    lands in, and that is not an extraction error.

QR data is NOT passed to the models: the point is to compare vision
extraction quality, and a QR would let every model "cheat" identically.
Post-processing (CJK repair, permutation fix, title demotion) IS included —
it runs inside the provider pipeline, so scores reflect what the user
actually gets.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Dict, List, Optional

# Fields evaluated, in display order. phone/mobile pool each other's values.
BENCH_FIELDS = ("fullName", "title", "company", "email", "phone", "mobile", "website")

_MIN_PHONE_DIGITS = 8


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _norm_text(s: str) -> str:
    """Accent-fold, casefold, collapse everything non-alphanumeric."""
    return " ".join(re.findall(r"[a-z0-9]+", _fold(s)))


def _norm_email(s: str) -> str:
    return s.strip().lower()


def _norm_phone(s: str) -> str:
    return re.sub(r"\D", "", s)


def _norm_website(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def _phones_match(a: str, b: str) -> bool:
    """Digits-only suffix match — '+55 31 3555 7300' == '31 3555-7300'."""
    da, db = _norm_phone(a), _norm_phone(b)
    if len(da) < _MIN_PHONE_DIGITS or len(db) < _MIN_PHONE_DIGITS:
        return False
    return da.endswith(db) or db.endswith(da)


def field_matches(field: str, truth_value: str, extracted: Dict) -> bool:
    """Does the extracted contact match ground truth for one field?"""
    if not truth_value:
        return False
    if field in ("phone", "mobile"):
        # Pool: a truth phone found in EITHER extracted slot counts.
        pool = [extracted.get("phone") or "", extracted.get("mobile") or ""]
        return any(_phones_match(truth_value, v) for v in pool if v)
    value = (extracted.get(field) or "").strip()
    if not value:
        return False
    if field == "email":
        return _norm_email(truth_value) == _norm_email(value)
    if field == "website":
        return _norm_website(truth_value) == _norm_website(value)
    # Text fields: exact normalized match, OR one fully contains the other
    # ("Sandvik" vs "Sandvik Mining and Rock Solutions" is not an error the
    # user cares about when ranking models).
    nt, nv = _norm_text(truth_value), _norm_text(value)
    if not nt or not nv:
        return False
    return nt == nv or f" {nt} " in f" {nv} " or f" {nv} " in f" {nt} "


def score_card(truth: Dict, extracted: Dict) -> Dict[str, bool]:
    """Per-field match map, only for fields the truth has populated."""
    out: Dict[str, bool] = {}
    for f in BENCH_FIELDS:
        tv = (truth.get(f) or "").strip()
        if tv:
            out[f] = field_matches(f, tv, extracted or {})
    return out


def collect_items(contacts: List[Dict], thumb_dir: str, limit: Optional[int] = None) -> List[Dict]:
    """Locked contacts that resolve to a card image → benchmark items.

    Returns [{contact_id, label, image_path, truth}], newest first (matching
    get_all() ordering), capped at `limit`.
    """
    items: List[Dict] = []
    for c in contacts:
        if not c.get("locked"):
            continue
        card_id = (c.get("card_id") or "").strip()
        if not card_id:
            continue
        path = os.path.join(thumb_dir, f"{card_id}.jpg")
        if not os.path.exists(path):
            continue
        cd = c.get("contact_data") or {}
        if not any((cd.get(f) or "").strip() for f in BENCH_FIELDS):
            continue
        label = (
            (cd.get("fullName") or "").strip()
            or f"{(cd.get('firstName') or '').strip()} {(cd.get('lastName') or '').strip()}".strip()
            or (cd.get("email") or "").strip()
            or card_id
        )
        items.append(
            {
                "contact_id": c.get("id", ""),
                "label": label,
                "image_path": path,
                "truth": cd,
            }
        )
        if limit and len(items) >= limit:
            break
    return items


class BenchAccumulator:
    """Accumulates per-model, per-field tallies across cards."""

    def __init__(self, model: str):
        self.model = model
        self.per_field: Dict[str, List[int]] = {f: [0, 0] for f in BENCH_FIELDS}  # [ok, total]
        self.cards = 0
        self.failures = 0
        self.total_ms = 0

    def add(self, matches: Dict[str, bool], elapsed_ms: int, failed: bool = False):
        self.cards += 1
        self.total_ms += max(0, int(elapsed_ms))
        if failed:
            self.failures += 1
        for f, ok in matches.items():
            self.per_field[f][1] += 1
            if ok:
                self.per_field[f][0] += 1

    def summary(self) -> Dict:
        fields = {}
        ok_sum = total_sum = 0
        for f, (ok, total) in self.per_field.items():
            if total:
                fields[f] = {"ok": ok, "total": total, "pct": round(100.0 * ok / total, 1)}
                ok_sum += ok
                total_sum += total
        return {
            "model": self.model,
            "fields": fields,
            "overall": {
                "ok": ok_sum,
                "total": total_sum,
                "pct": round(100.0 * ok_sum / total_sum, 1) if total_sum else 0.0,
            },
            "cards": self.cards,
            "failures": self.failures,
            "avg_ms": int(self.total_ms / self.cards) if self.cards else 0,
        }
