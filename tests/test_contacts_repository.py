"""
Tests for ContactsRepository — persistent JSON store for approved contacts.

Run with: python3 -m pytest tests/test_contacts_repository.py -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from utils.contacts_repository import ContactsRepository, _display_name


class TestContactsRepository(unittest.TestCase):
    """Comprehensive tests for ContactsRepository CRUD, search, grouping, and exports."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        repo_path = str(Path(self.temp_dir.name) / "contacts.json")
        self.repo = ContactsRepository(repo_path=repo_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # ── Helpers ──────────────────────────────────────────────────────────

    # NOTE: add_contact returns a result dict
    # ({id, status, additions, conflicts, locked}) since the locked-contact
    # merge feature. These helpers unwrap the id so the assertions below
    # stay focused on the id contract.
    def _add_john(self) -> str:
        return self.repo.add_contact(
            {"fullName": "John Doe", "email": "john@example.com", "company": "Acme"},
            source_file="card1.png",
            vcf_content="BEGIN:VCARD\nFN:John Doe\nEND:VCARD",
        )["id"]

    def _add_jane(self) -> str:
        return self.repo.add_contact(
            {
                "fullName": "Jane Smith",
                "email": "jane@example.com",
                "phone": "555-0100",
                "company": "Beta Inc",
            },
            source_file="card2.png",
            vcf_content="BEGIN:VCARD\nFN:Jane Smith\nEND:VCARD",
        )["id"]

    def _add_nocompany(self) -> str:
        return self.repo.add_contact(
            {"firstName": "Bob", "lastName": "Empty", "email": "bob@test.com"},
            source_file="card3.png",
            vcf_content="BEGIN:VCARD\nFN:Bob Empty\nEND:VCARD",
        )["id"]

    # ── Initial state ────────────────────────────────────────────────────

    def test_empty_repository_count_zero(self):
        self.assertEqual(self.repo.count(), 0)

    def test_empty_repository_get_all_empty(self):
        self.assertEqual(self.repo.get_all(), [])

    def test_empty_repository_fingerprint(self):
        self.assertEqual(self.repo.fingerprint(), "0:0")

    def test_empty_repository_clear_all_returns_zero(self):
        self.assertEqual(self.repo.clear_all(), 0)

    def test_empty_repository_search_empty(self):
        self.assertEqual(self.repo.search("anything"), [])

    def test_empty_repository_grouped_empty(self):
        self.assertEqual(self.repo.get_grouped_by_company(), {})

    def test_empty_repository_get_contact_dicts_empty(self):
        self.assertEqual(self.repo.get_contact_dicts(), [])

    def test_empty_repository_get_all_vcf_empty(self):
        self.assertEqual(self.repo.get_all_vcf(), "")

    # ── Add contact ──────────────────────────────────────────────────────

    def test_add_contact_returns_id(self):
        cid = self._add_john()
        self.assertIsInstance(cid, str)
        self.assertEqual(len(cid), 8)
        self.assertEqual(self.repo.count(), 1)

    def test_add_contact_persists_to_disk(self):
        self._add_john()
        # Reload from disk
        repo2 = ContactsRepository(repo_path=self.repo.repo_path)
        self.assertEqual(repo2.count(), 1)

    def test_add_contact_stores_all_fields(self):
        cid = self._add_john()
        contacts = self.repo.get_all()
        self.assertEqual(len(contacts), 1)
        entry = contacts[0]
        self.assertEqual(entry["id"], cid)
        self.assertEqual(entry["contact_data"]["fullName"], "John Doe")
        self.assertEqual(entry["contact_data"]["email"], "john@example.com")
        self.assertEqual(entry["source_file"], "card1.png")
        self.assertEqual(entry["vcf_content"], "BEGIN:VCARD\nFN:John Doe\nEND:VCARD")
        self.assertIn("added_at", entry)
        self.assertIn("updated_at", entry)

    def test_add_contact_no_email_no_vcf(self):
        cid = self.repo.add_contact({"fullName": "Minimal Contact"})
        self.assertEqual(self.repo.count(), 1)
        contacts = self.repo.get_all()
        self.assertEqual(contacts[0]["vcf_content"], "")
        self.assertEqual(contacts[0]["source_file"], "")

    # ── Duplicate handling ────────────────────────────────────────────────

    def test_add_duplicate_email_updates_existing(self):
        cid1 = self._add_john()  # john@example.com
        cid2 = self.repo.add_contact(
            {"fullName": "John Updated", "email": "john@example.com", "company": "NewCo"},
            source_file="card_updated.png",
            vcf_content="BEGIN:VCARD\nFN:John Updated\nEND:VCARD",
        )["id"]
        self.assertEqual(cid1, cid2, "Should return the same id")
        self.assertEqual(self.repo.count(), 1, "Should still be one contact")
        entry = self.repo.get_all()[0]
        self.assertEqual(entry["contact_data"]["fullName"], "John Updated")
        self.assertEqual(entry["contact_data"]["company"], "NewCo")
        self.assertEqual(entry["source_file"], "card_updated.png")

    def test_add_duplicate_case_insensitive_email(self):
        self._add_john()  # john@example.com
        cid = self.repo.add_contact({"fullName": "JOHN CAPS", "email": "JOHN@EXAMPLE.COM"})
        self.assertEqual(self.repo.count(), 1)
        self.assertEqual(self.repo.get_all()[0]["contact_data"]["fullName"], "JOHN CAPS")

    def test_add_duplicate_preserves_vcf_when_new_is_empty(self):
        self._add_john()
        cid = self.repo.add_contact({"email": "john@example.com", "fullName": "John NoVCF"})
        entry = self.repo.get_all()[0]
        self.assertEqual(entry["vcf_content"], "BEGIN:VCARD\nFN:John Doe\nEND:VCARD")

    def test_add_duplicate_preserves_source_when_new_is_empty(self):
        self._add_john()
        self.repo.add_contact({"email": "john@example.com", "fullName": "John NoSrc"})
        entry = self.repo.get_all()[0]
        self.assertEqual(entry["source_file"], "card1.png")

    # ── Remove contact ────────────────────────────────────────────────────

    def test_remove_existing_contact(self):
        cid = self._add_john()
        result = self.repo.remove_contact(cid)
        self.assertTrue(result)
        self.assertEqual(self.repo.count(), 0)

    def test_remove_nonexistent_contact(self):
        self._add_john()
        result = self.repo.remove_contact("nonexist")
        self.assertFalse(result)
        self.assertEqual(self.repo.count(), 1)

    def test_remove_persists_to_disk(self):
        cid = self._add_john()
        self.repo.remove_contact(cid)
        repo2 = ContactsRepository(repo_path=self.repo.repo_path)
        self.assertEqual(repo2.count(), 0)

    # ── Clear all ─────────────────────────────────────────────────────────

    def test_clear_all_returns_count(self):
        self._add_john()
        self._add_jane()
        count = self.repo.clear_all()
        self.assertEqual(count, 2)
        self.assertEqual(self.repo.count(), 0)

    def test_clear_all_empty_repo(self):
        count = self.repo.clear_all()
        self.assertEqual(count, 0)

    # ── Get all (sorting) ─────────────────────────────────────────────────

    def test_get_all_sorted_newest_first(self):
        self._add_john()
        import time

        time.sleep(0.01)  # Ensure different timestamp
        self._add_jane()
        contacts = self.repo.get_all()
        self.assertEqual(len(contacts), 2)
        self.assertGreaterEqual(
            contacts[0]["added_at"],
            contacts[1]["added_at"],
            "Newest should come first",
        )

    # ── Fingerprint ───────────────────────────────────────────────────────

    def test_fingerprint_changes_on_add(self):
        fp1 = self.repo.fingerprint()
        self._add_john()
        fp2 = self.repo.fingerprint()
        self.assertNotEqual(fp1, fp2)

    def test_fingerprint_changes_on_remove(self):
        cid = self._add_john()
        fp1 = self.repo.fingerprint()
        self.repo.remove_contact(cid)
        fp2 = self.repo.fingerprint()
        self.assertNotEqual(fp1, fp2)

    # ── Count ─────────────────────────────────────────────────────────────

    def test_count_reflects_additions(self):
        self.assertEqual(self.repo.count(), 0)
        self._add_john()
        self.assertEqual(self.repo.count(), 1)
        self._add_jane()
        self.assertEqual(self.repo.count(), 2)

    # ── Grouping ──────────────────────────────────────────────────────────

    def test_grouped_by_company(self):
        self._add_john()  # Acme
        self._add_jane()  # Beta Inc
        self._add_nocompany()  # (No company)
        groups = self.repo.get_grouped_by_company()
        keys = list(groups.keys())
        self.assertIn("Acme", keys)
        self.assertIn("Beta Inc", keys)
        self.assertIn("(No company)", keys)
        self.assertEqual(len(groups["Acme"]), 1)
        self.assertEqual(groups["Acme"][0]["contact_data"]["fullName"], "John Doe")

    def test_grouped_no_company_last(self):
        self._add_john()  # Acme
        self._add_nocompany()  # (No company)
        groups = self.repo.get_grouped_by_company()
        keys = list(groups.keys())
        self.assertEqual(keys[-1], "(No company)", "(No company) should be last")

    def test_grouped_alphabetical_order(self):
        self.repo.add_contact({"fullName": "Zoe", "company": "Zeta"})
        self.repo.add_contact({"fullName": "Abe", "company": "Alpha"})
        self.repo.add_contact({"fullName": "Bob", "company": "Beta"})
        keys = list(self.repo.get_grouped_by_company().keys())
        self.assertEqual(keys, ["Alpha", "Beta", "Zeta"])

    def test_grouped_contacts_sorted_by_name_within_company(self):
        self.repo.add_contact({"fullName": "Charlie", "company": "Acme"})
        self.repo.add_contact({"fullName": "Alice", "company": "Acme"})
        self.repo.add_contact({"fullName": "Bob", "company": "Acme"})
        group = self.repo.get_grouped_by_company()["Acme"]
        names = [_display_name(c) for c in group]
        self.assertEqual(names, ["Alice", "Bob", "Charlie"])

    def test_grouped_strips_whitespace_from_company(self):
        self.repo.add_contact({"fullName": "Test", "company": "  SpacedCo  "})
        groups = self.repo.get_grouped_by_company()
        self.assertIn("SpacedCo", groups)
        self.assertNotIn("  SpacedCo  ", groups)

    # ── Search ────────────────────────────────────────────────────────────

    def test_search_by_name(self):
        self._add_john()
        self._add_jane()
        results = self.repo.search("John")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["contact_data"]["fullName"], "John Doe")

    def test_search_by_email(self):
        self._add_john()
        results = self.repo.search("john@example.com")
        self.assertEqual(len(results), 1)

    def test_search_by_company(self):
        self._add_jane()  # Beta Inc
        results = self.repo.search("Beta")
        self.assertEqual(len(results), 1)

    def test_search_by_phone(self):
        self._add_jane()
        results = self.repo.search("555-0100")
        self.assertEqual(len(results), 1)

    def test_search_by_mobile(self):
        self.repo.add_contact({"fullName": "MobileGuy", "mobile": "999-8888"})
        results = self.repo.search("999")
        self.assertEqual(len(results), 1)

    def test_search_by_title(self):
        self.repo.add_contact({"fullName": "CEO", "title": "Chief Executive Officer"})
        results = self.repo.search("Executive")
        self.assertEqual(len(results), 1)

    def test_search_case_insensitive(self):
        self._add_john()
        results = self.repo.search("JOHN")
        self.assertEqual(len(results), 1)

    def test_search_no_results(self):
        self._add_john()
        results = self.repo.search("NonExistentName")
        self.assertEqual(len(results), 0)

    def test_search_empty_query_returns_all(self):
        self._add_john()
        self._add_jane()
        results = self.repo.search("")
        self.assertEqual(len(results), 2)

    def test_search_partial_match(self):
        self._add_john()
        results = self.repo.search("joh")
        self.assertEqual(len(results), 1)

    # ── Get contact dicts ─────────────────────────────────────────────────

    def test_get_contact_dicts_all(self):
        self._add_john()
        self._add_jane()
        dicts = self.repo.get_contact_dicts()
        self.assertEqual(len(dicts), 2)
        self.assertIsInstance(dicts[0], dict)
        # get_contact_dicts returns insertion order (not newest-first like get_all)
        names = {d["fullName"] for d in dicts}
        self.assertEqual(names, {"John Doe", "Jane Smith"})

    def test_get_contact_dicts_by_ids(self):
        cid1 = self._add_john()
        self._add_jane()
        dicts = self.repo.get_contact_dicts(contact_ids=[cid1])
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["fullName"], "John Doe")

    def test_get_contact_dicts_nonexistent_id(self):
        self._add_john()
        dicts = self.repo.get_contact_dicts(contact_ids=["nonexistent"])
        self.assertEqual(len(dicts), 0)

    def test_get_contact_dicts_empty_ids(self):
        self._add_john()
        dicts = self.repo.get_contact_dicts(contact_ids=[])
        self.assertEqual(len(dicts), 0)

    # ── Get all VCF ───────────────────────────────────────────────────────

    def test_get_all_vcf_concatenates(self):
        self._add_john()
        self._add_jane()
        vcf = self.repo.get_all_vcf()
        self.assertIn("John Doe", vcf)
        self.assertIn("Jane Smith", vcf)
        self.assertIn("\r\n", vcf)

    def test_get_all_vcf_by_ids(self):
        cid = self._add_john()
        self._add_jane()
        vcf = self.repo.get_all_vcf(contact_ids=[cid])
        self.assertIn("John Doe", vcf)
        self.assertNotIn("Jane Smith", vcf)

    def test_get_all_vcf_no_vcf_content(self):
        self.repo.add_contact({"fullName": "NoVCF", "email": "novcf@test.com"})
        vcf = self.repo.get_all_vcf()
        self.assertEqual(vcf, "")

    def test_get_all_vcf_empty_repo(self):
        self.assertEqual(self.repo.get_all_vcf(), "")

    # ── Persistence (load from corrupt file) ──────────────────────────────

    def test_load_corrupt_json_falls_back_to_empty(self):
        # Write invalid JSON
        Path(self.repo.repo_path).write_text("{invalid json", encoding="utf-8")
        repo2 = ContactsRepository(repo_path=self.repo.repo_path)
        self.assertEqual(repo2.count(), 0)

    def test_load_non_list_json_falls_back_to_empty(self):
        Path(self.repo.repo_path).write_text('{"key": "not a list"}', encoding="utf-8")
        repo2 = ContactsRepository(repo_path=self.repo.repo_path)
        self.assertEqual(repo2.count(), 0)

    def test_load_missing_file_initializes_empty(self):
        repo2 = ContactsRepository(repo_path="/tmp/nonexistent_dir_xyz/test.json")
        self.assertEqual(repo2.count(), 0)


class TestDisplayName(unittest.TestCase):
    """Tests for the _display_name helper."""

    def test_display_name_full_name(self):
        entry = {"contact_data": {"fullName": "John Doe"}}
        self.assertEqual(_display_name(entry), "John Doe")

    def test_display_name_first_last(self):
        entry = {"contact_data": {"firstName": "John", "lastName": "Doe"}}
        self.assertEqual(_display_name(entry), "John Doe")

    def test_display_name_email_fallback(self):
        entry = {"contact_data": {"email": "john@example.com"}}
        self.assertEqual(_display_name(entry), "john@example.com")

    def test_display_name_unknown(self):
        entry = {"contact_data": {}}
        self.assertEqual(_display_name(entry), "(unknown)")

    def test_display_name_empty_entry(self):
        self.assertEqual(_display_name({}), "(unknown)")


if __name__ == "__main__":
    unittest.main()


class TestPersistenceSafety(unittest.TestCase):
    """Atomic writes + thread-safety of the JSON store."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = str(Path(self.temp_dir.name) / "contacts.json")
        self.repo = ContactsRepository(repo_path=self.repo_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_leaves_no_temp_litter(self):
        self.repo.add_contact({"fullName": "A", "email": "a@x.com"})
        leftovers = [p for p in Path(self.temp_dir.name).iterdir() if p.suffix == ".tmp"]
        self.assertEqual(leftovers, [])
        # And the real file is valid JSON with the contact in it.
        data = json.loads(Path(self.repo_path).read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)

    def test_save_is_atomic_replace(self):
        """A reader opening the path mid-save must never see partial JSON.
        We simulate by checking the file is parseable after every mutation."""
        for i in range(20):
            self.repo.add_contact({"fullName": f"P{i}", "email": f"p{i}@x.com"})
            json.loads(Path(self.repo_path).read_text(encoding="utf-8"))  # must not raise

    def test_concurrent_adds_are_consistent(self):
        import threading as _t

        def add_many(offset):
            for i in range(10):
                self.repo.add_contact(
                    {"fullName": f"T{offset}-{i}", "email": f"t{offset}.{i}@x.com"}
                )

        threads = [_t.Thread(target=add_many, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.repo.count(), 80)
        # Disk copy matches memory and is valid JSON.
        data = json.loads(Path(self.repo_path).read_text(encoding="utf-8"))
        self.assertEqual(len(data), 80)
        # No duplicate ids from racing uuid generation / list appends.
        ids = [c["id"] for c in data]
        self.assertEqual(len(ids), len(set(ids)))


class TestDuplicateDetection(unittest.TestCase):
    """Conservative near-duplicate detection + merge."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = ContactsRepository(repo_path=str(Path(self.temp_dir.name) / "contacts.json"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _add(self, **cd):
        return self.repo.add_contact(cd)["id"]

    def _inject(self, cid, **cd):
        """Append a raw contact, bypassing add_contact's same-email merge —
        used to simulate legacy/hand-edited data that already contains an
        email collision."""
        self.repo._contacts.append(
            {
                "id": cid,
                "contact_data": cd,
                "locked": False,
                "added_at": f"2020-01-01T00:00:{len(self.repo._contacts):02d}",
                "updated_at": "2020-01-01T00:00:00",
            }
        )

    def test_same_email_flagged(self):
        # add_contact merges same-email contacts, so this only occurs for
        # legacy/edited data — inject it directly.
        self._inject("id1", fullName="Ann Lee", email="a@x.com")
        self._inject("id2", fullName="Ann Lee", email="A@X.COM", company="Acme")
        groups = self.repo.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["reason"], "same email")

    def test_name_plus_company_flagged_different_email(self):
        # The real André Marra case: accent + different emails, same company.
        self._add(fullName="Andre Marra", email="marra@galapagos.com", company="Galapagos Capital")
        self._add(
            fullName="André Marra", email="andre.marra@galapagos.com", company="Galapagos Capital"
        )
        groups = self.repo.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["reason"], "same name + company")

    def test_name_plus_phone_flagged(self):
        self._add(fullName="Bob Smith", phone="+55 11 99999-1234")
        self._add(fullName="Bob Smith", mobile="11 99999 1234", company="Other")
        groups = self.repo.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertIn(groups[0]["reason"], ("same name + phone", "same name + company"))

    def test_same_name_no_corroboration_not_flagged(self):
        # Common name, nothing else in common — conservative: NOT a dup.
        self._add(fullName="John Silva", company="Alpha", email="j@alpha.com")
        self._add(fullName="John Silva", company="Beta", email="john@beta.com")
        self.assertEqual(self.repo.find_duplicates(), [])

    def test_single_first_name_not_enough(self):
        # Only one shared token (a first name) must not flag.
        self._add(fullName="Maria Santos", company="Acme", phone="111-22233")
        self._add(fullName="Maria Oliveira", company="Acme")
        self.assertEqual(self.repo.find_duplicates(), [])

    def test_transitive_grouping(self):
        # A~B (name+company) and B~C (name+phone) collapse into one group of 3.
        # Distinct emails so add_contact doesn't pre-merge any pair.
        self._add(fullName="Ann Lee", email="a1@x.com", company="Acme", phone="111-22233")
        self._add(fullName="Ann Lee", email="a2@x.com", company="Acme")
        self._add(fullName="Ann Lee", email="a3@x.com", company="Other", phone="111 22233")
        groups = self.repo.find_duplicates()
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["contacts"]), 3)

    # Distinct emails so add_contact doesn't pre-merge — these exercise
    # merge_contacts directly.
    def test_merge_fills_empty_fields_and_deletes_sources(self):
        tid = self._add(fullName="Ann Lee", email="a@x.com")
        sid = self._add(fullName="Ann Lee", email="b@x.com", company="Acme", phone="123-45678")
        merged = self.repo.merge_contacts(tid, [sid])
        self.assertEqual(merged["id"], tid)
        self.assertEqual(merged["contact_data"]["company"], "Acme")  # filled
        self.assertEqual(merged["contact_data"]["phone"], "123-45678")
        self.assertEqual(self.repo.count(), 1)  # source deleted

    def test_merge_never_overwrites_target_values(self):
        tid = self._add(fullName="Ann Lee", email="a@x.com", company="RealCo")
        sid = self._add(fullName="Ann Lee", email="b@x.com", company="WrongCo")
        merged = self.repo.merge_contacts(tid, [sid])
        self.assertEqual(merged["contact_data"]["company"], "RealCo")

    def test_merge_respects_locked_protected_fields(self):
        tid = self._add(fullName="Ann Lee", email="a@x.com")
        self.repo.set_locked(tid, True)
        sid = self._add(fullName="Ann Lee", email="b@x.com", company="Acme")
        # A locked target with an existing name/email must not have them
        # changed, but empty non-protected fields (company) still fill.
        merged = self.repo.merge_contacts(tid, [sid])
        self.assertEqual(merged["contact_data"]["fullName"], "Ann Lee")
        self.assertEqual(merged["contact_data"]["email"], "a@x.com")
        self.assertEqual(merged["contact_data"]["company"], "Acme")

    def test_merge_missing_target_returns_none(self):
        self.assertIsNone(self.repo.merge_contacts("nope", ["also-nope"]))
