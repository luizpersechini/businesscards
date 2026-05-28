"""
Contacts Repository — persistent store for all approved/confirmed business card contacts.

Contacts are saved to a single JSON file in temp/contacts_repository.json.
Each contact gets a unique UUID, a timestamp, and the full contact_data dict.
The repository supports:
  - Add / remove contacts
  - Search by name, email, company
  - Group by company
  - Bulk export to VCF, Outlook CSV, Excel
"""

import json
import os
import uuid
from datetime import datetime
from typing import List, Dict, Optional


class ContactsRepository:
    """Persistent JSON-backed store for approved contacts."""

    def __init__(self, repo_path: Optional[str] = None):
        if repo_path is None:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            repo_path = os.path.join(base, "temp", "contacts_repository.json")
        self.repo_path = repo_path
        self._contacts: List[Dict] = []
        self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self):
        """Load contacts from disk."""
        if os.path.exists(self.repo_path):
            try:
                with open(self.repo_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._contacts = data if isinstance(data, list) else []
            except (json.JSONDecodeError, IOError):
                self._contacts = []
        else:
            self._contacts = []

    def _save(self):
        """Persist contacts to disk."""
        os.makedirs(os.path.dirname(self.repo_path), exist_ok=True)
        with open(self.repo_path, "w", encoding="utf-8") as f:
            json.dump(self._contacts, f, indent=2, ensure_ascii=False)

    # ── CRUD ───────────────────────────────────────────────────────────────

    # Fields that count as "real data" for merge-conflict purposes. We
    # ignore casing + whitespace on comparison so "Acme Corp" vs "acme
    # corp" doesn't trip a conflict.
    _MERGEABLE_FIELDS = (
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
    )

    # Fields that are NEVER overwritten or surfaced as conflicts on a
    # locked contact. The user's stated invariant: "locked means I checked
    # it and I'm ok with most of it — never change name and email." If the
    # existing record has a value for any of these, the incoming value is
    # silently dropped (no conflict reported, no chance of override).
    # Additive merges still work — if existing is empty for one of these,
    # the incoming value can populate it.
    _LOCKED_PROTECTED_FIELDS = frozenset(
        (
            "firstName",
            "lastName",
            "fullName",
            "email",
        )
    )

    @staticmethod
    def _norm_field(v) -> str:
        if v is None or v == "":
            return ""
        try:
            return " ".join(str(v).strip().lower().split())
        except Exception:
            return ""

    def _merge_or_conflict(self, existing: Dict, incoming: Dict) -> Dict:
        """
        Compare an incoming contact_data dict against an existing one.
        Returns a dict with:
          - `additions`: {field: value} — fields the existing was missing
              that the incoming has; these are safe to merge in.
          - `conflicts`: [{field, existing, incoming}] — fields where
              both sides have a value and they differ. Caller decides
              how to resolve.

        Protected fields (`_LOCKED_PROTECTED_FIELDS` — name + email) on
        a contact that already has a value for them are silently skipped:
        no conflict reported, incoming value dropped. Empty protected
        fields can still be populated additively.
        """
        additions: Dict = {}
        conflicts: List[Dict] = []
        for k in self._MERGEABLE_FIELDS:
            ex = existing.get(k)
            inc = incoming.get(k)
            ex_norm = self._norm_field(ex)
            inc_norm = self._norm_field(inc)
            if not inc_norm:
                continue  # incoming has nothing useful for this field
            if not ex_norm:
                additions[k] = inc
            elif ex_norm != inc_norm:
                if k in self._LOCKED_PROTECTED_FIELDS:
                    # Protected: never overwrite, never surface as a
                    # conflict the user can override. Silently drop.
                    continue
                conflicts.append({"field": k, "existing": ex, "incoming": inc})
            # else: both equal → no-op
        return {"additions": additions, "conflicts": conflicts}

    def add_contact(
        self, contact_data: Dict, source_file: str = "", vcf_content: str = "", card_id: str = ""
    ) -> Dict:
        """
        Add (or merge into) a contact in the repository.

        Behaviour when an existing contact matches by email:
          - If the existing contact is **locked**: only fields that the
            existing doesn't already have are merged in (additive).
            Any field where existing and incoming disagree is reported
            as a conflict for the user to resolve manually. The
            existing record's `vcf_content`, `source_file`, `card_id`
            etc. are preserved.
          - If the existing contact is **unlocked**: the existing
            record is overwritten with the incoming data (legacy
            behaviour — this matches what users get when re-scanning
            a card to refresh extracted data).

        Returns a dict with:
          - `id`: the contact's repository UUID
          - `status`: one of "added", "updated", "merged", "conflict"
          - `additions`: dict of fields newly populated (locked path only)
          - `conflicts`: list of {field, existing, incoming} dicts
                         (locked path only; empty list otherwise)
        """
        email = (contact_data.get("email") or "").strip().lower()
        if email:
            for c in self._contacts:
                existing_email = (c.get("contact_data", {}).get("email") or "").strip().lower()
                if existing_email != email:
                    continue

                if c.get("locked", False):
                    # LOCKED — additive merge + conflict report.
                    result = self._merge_or_conflict(c.get("contact_data") or {}, contact_data)
                    if result["additions"]:
                        cd = c.setdefault("contact_data", {})
                        for k, v in result["additions"].items():
                            cd[k] = v
                        # Regenerate VCF from the merged data so exports
                        # include the new fields.
                        try:
                            from utils.vcf_generator import VCFGenerator

                            c["vcf_content"] = VCFGenerator().generate_vcf_string(cd)
                        except Exception:
                            pass
                        c["updated_at"] = datetime.now().isoformat()
                        self._save()
                    return {
                        "id": c["id"],
                        "status": "conflict" if result["conflicts"] else "merged",
                        "additions": result["additions"],
                        "conflicts": result["conflicts"],
                        "locked": True,
                    }

                # UNLOCKED — overwrite (legacy behaviour, refreshes on rescan).
                c["contact_data"] = contact_data
                c["source_file"] = source_file or c.get("source_file", "")
                c["vcf_content"] = vcf_content or c.get("vcf_content", "")
                c["card_id"] = card_id or c.get("card_id", "")
                c["updated_at"] = datetime.now().isoformat()
                self._save()
                return {
                    "id": c["id"],
                    "status": "updated",
                    "additions": {},
                    "conflicts": [],
                    "locked": False,
                }

        # No match — create a new entry. Default to unlocked.
        contact_id = str(uuid.uuid4())[:8]
        entry = {
            "id": contact_id,
            "card_id": card_id,
            "contact_data": contact_data,
            "source_file": source_file,
            "vcf_content": vcf_content,
            "locked": False,
            "added_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        self._contacts.append(entry)
        self._save()
        return {
            "id": contact_id,
            "status": "added",
            "additions": {},
            "conflicts": [],
            "locked": False,
        }

    def apply_field_updates(self, contact_id: str, updates: Dict) -> Optional[Dict]:
        """Apply a *partial* field-by-field update to a contact's data,
        used by the conflict-resolution flow when the user accepts the
        incoming value for specific fields after a scan/relaunch.

        Differs from `update_contact` (which replaces the whole
        contact_data dict). Pass `None` or `""` as a value to clear a
        field. Regenerates the VCF after the merge so exports stay
        consistent.

        Returns the updated contact, or None if no contact matches.
        """
        if not updates:
            return None
        for contact in self._contacts:
            if contact.get("id") != contact_id:
                continue
            cd = contact.setdefault("contact_data", {})
            is_locked = bool(contact.get("locked"))
            for k, v in updates.items():
                # Locked-contact protection: name + email are never
                # overwritten on a locked record, even via the explicit
                # resolve endpoint. Empty existing values can still be
                # populated.
                if is_locked and k in self._LOCKED_PROTECTED_FIELDS and self._norm_field(cd.get(k)):
                    continue
                if v is None or v == "":
                    cd.pop(k, None)
                else:
                    cd[k] = v
            try:
                from utils.vcf_generator import VCFGenerator

                contact["vcf_content"] = VCFGenerator().generate_vcf_string(cd)
            except Exception:
                pass
            contact["updated_at"] = datetime.now().isoformat()
            self._save()
            return contact
        return None

    def set_locked(self, contact_id: str, locked: bool) -> bool:
        """Toggle the lock flag on a contact. Returns True on success."""
        for c in self._contacts:
            if c.get("id") == contact_id:
                c["locked"] = bool(locked)
                c["updated_at"] = datetime.now().isoformat()
                self._save()
                return True
        return False

    def remove_contact(self, contact_id: str) -> bool:
        """Remove a contact by its UUID. Returns True if found and removed."""
        before = len(self._contacts)
        self._contacts = [c for c in self._contacts if c.get("id") != contact_id]
        if len(self._contacts) < before:
            self._save()
            return True
        return False

    def update_contact(self, contact_id: str, contact_data: Dict) -> Optional[Dict]:
        """Update a contact's data. Returns the updated contact or None if not found."""
        for contact in self._contacts:
            if contact.get("id") == contact_id:
                contact["contact_data"] = contact_data
                contact["updated_at"] = datetime.now().isoformat()
                # Regenerate VCF content if needed
                try:
                    from utils.vcf_generator import VCFGenerator

                    vcf_gen = VCFGenerator()
                    contact["vcf_content"] = vcf_gen.generate_vcf_string(contact_data)
                except:
                    # If VCF generation fails, keep existing or clear
                    contact["vcf_content"] = contact.get("vcf_content", "")
                self._save()
                return contact
        return None

    def clear_all(self) -> int:
        """Remove every contact. Returns the number of contacts deleted."""
        count = len(self._contacts)
        self._contacts = []
        self._save()
        return count

    def get_all(self) -> List[Dict]:
        """Return all contacts (newest first)."""
        return sorted(self._contacts, key=lambda c: c.get("added_at", ""), reverse=True)

    def fingerprint(self) -> str:
        """Cheap hash of current state — changes whenever contacts change."""
        return f"{len(self._contacts)}:{sum(hash(c.get('id', '')) for c in self._contacts)}"

    def count(self) -> int:
        return len(self._contacts)

    # ── Grouping ───────────────────────────────────────────────────────────

    def get_grouped_by_company(self) -> Dict[str, List[Dict]]:
        """
        Group contacts by company name (alphabetical).
        Contacts with no company go under "(No company)".
        """
        groups: Dict[str, List[Dict]] = {}
        for c in self._contacts:
            cd = c.get("contact_data", {})
            company = (cd.get("company") or "").strip()
            if not company:
                company = "(No company)"
            groups.setdefault(company, []).append(c)

        # Sort groups alphabetically, "(No company)" last
        sorted_groups = {}
        for key in sorted(groups.keys(), key=lambda k: (k == "(No company)", k.lower())):
            # Sort contacts within each group by name
            sorted_groups[key] = sorted(groups[key], key=lambda c: _display_name(c).lower())
        return sorted_groups

    # ── Search ─────────────────────────────────────────────────────────────

    def search(self, query: str) -> List[Dict]:
        """Search contacts by name, email, company, or phone."""
        q = query.lower().strip()
        if not q:
            return self.get_all()

        results = []
        for c in self._contacts:
            cd = c.get("contact_data", {})
            searchable = " ".join(
                [
                    cd.get("firstName", "") or "",
                    cd.get("lastName", "") or "",
                    cd.get("fullName", "") or "",
                    cd.get("email", "") or "",
                    cd.get("company", "") or "",
                    cd.get("phone", "") or "",
                    cd.get("mobile", "") or "",
                    cd.get("title", "") or "",
                ]
            ).lower()
            if q in searchable:
                results.append(c)
        return results

    # ── Export helpers ──────────────────────────────────────────────────────

    def get_contact_dicts(self, contact_ids: Optional[List[str]] = None) -> List[Dict]:
        """
        Return a list of contact_data dicts for export.
        If contact_ids is None, return all.
        """
        if contact_ids is None:
            return [c["contact_data"] for c in self._contacts]
        id_set = set(contact_ids)
        return [c["contact_data"] for c in self._contacts if c["id"] in id_set]

    def get_all_vcf(self, contact_ids: Optional[List[str]] = None) -> str:
        """Return concatenated VCF for all (or selected) contacts."""
        entries = (
            self._contacts
            if contact_ids is None
            else [c for c in self._contacts if c["id"] in set(contact_ids)]
        )
        vcfs = [c.get("vcf_content", "") for c in entries if c.get("vcf_content")]
        return "\r\n".join(vcfs)


# ── Helpers ────────────────────────────────────────────────────────────────


def _display_name(contact_entry: Dict) -> str:
    """Extract a display name from a repository entry."""
    cd = contact_entry.get("contact_data", {})
    name = cd.get("fullName") or ""
    if not name:
        first = cd.get("firstName") or ""
        last = cd.get("lastName") or ""
        name = f"{first} {last}".strip()
    return name or cd.get("email", "") or "(unknown)"
