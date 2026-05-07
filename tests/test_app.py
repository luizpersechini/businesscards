"""
Tests for app.py module-level functions that don't require Streamlit runtime.

Tests utility functions, imports, compilation validity, and ContactsRepository integration.

Run with: python3 -m pytest tests/test_app.py -v
"""

import py_compile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import streamlit as st_mock

# Import app with streamlit side-effects patched out
with patch.object(st_mock, 'set_page_config'), \
     patch.object(st_mock, 'markdown'), \
     patch('utils.history_manager.HistoryManager'), \
     patch('utils.providers.factory.ProviderFactory'), \
     patch('utils.ms_graph.MSGraphContactManager'):
    import app


class TestAppCompilation(unittest.TestCase):
    """Verify app.py compiles without syntax errors."""

    def test_app_compiles(self):
        try:
            py_compile.compile(str(PROJECT_ROOT / "app.py"), doraise=True)
        except py_compile.PyCompileError as e:
            self.fail(f"app.py has a syntax error: {e}")


class TestAppImports(unittest.TestCase):
    """Verify all key top-level names exist after import."""

    def test_contacts_repo_exists(self):
        self.assertTrue(hasattr(app, 'contacts_repo'))

    def test_history_manager_exists(self):
        self.assertTrue(hasattr(app, 'history_manager'))

    def test_provider_factory_exists(self):
        self.assertTrue(hasattr(app, 'provider_factory'))

    def test_key_functions_exist(self):
        expected = [
            'initialize_session_state', 'load_image', 'draw_grid_overlay',
            'qr_data_is_sufficient', 'qr_to_contact_data', 'split_image_grid',
            'build_history_settings', 'save_history_run', 'update_history_card_entry',
            'archive_export', 'get_cached_history_runs', 'handle_history_delete_request',
            'schedule_history_relaunch', 'render_contacts_panel', 'render_history_panel',
            'handle_history_relaunch', 'process_single_card_retry',
            'process_business_cards', 'main',
            'pdf_pages_to_images', '_is_pdf', 'HAS_PDF_SUPPORT',
        ]
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue(hasattr(app, name), f"Missing: {name}")


class TestQRDataIsSufficient(unittest.TestCase):

    def test_none(self):
        self.assertFalse(app.qr_data_is_sufficient(None))

    def test_empty_dict(self):
        self.assertFalse(app.qr_data_is_sufficient({}))

    def test_email_list(self):
        self.assertTrue(app.qr_data_is_sufficient({"emails": ["t@t.com"]}))

    def test_plain_email_key(self):
        self.assertTrue(app.qr_data_is_sufficient({"email": "x@y.com"}))

    def test_no_email(self):
        self.assertFalse(app.qr_data_is_sufficient({"name": "John"}))


class TestQRToContactData(unittest.TestCase):

    def test_vcard_keys(self):
        r = app.qr_to_contact_data({
            "full_name": "John Doe", "organization": "Acme", "title": "CEO",
            "emails": ["j@a.com"], "phones": ["555-0100"], "url": "https://acme.com",
        })
        self.assertEqual(r.get("fullName"), "John Doe")
        self.assertEqual(r.get("company"), "Acme")
        self.assertEqual(r.get("title"), "CEO")
        self.assertEqual(r.get("email"), "j@a.com")
        self.assertEqual(r.get("phone"), "555-0100")
        self.assertEqual(r.get("website"), "https://acme.com")

    def test_multiple_phones_becomes_mobile(self):
        r = app.qr_to_contact_data({
            "full_name": "Jane", "phones": ["555-1000", "555-2000"],
        })
        self.assertEqual(r.get("phone"), "555-1000")
        self.assertEqual(r.get("mobile"), "555-2000")

    def test_first_last_name(self):
        r = app.qr_to_contact_data({"first_name": "Alice", "last_name": "Smith"})
        self.assertEqual(r.get("firstName"), "Alice")
        self.assertEqual(r.get("lastName"), "Smith")

    def test_notes_added(self):
        r = app.qr_to_contact_data({"full_name": "Test"})
        self.assertEqual(r.get("notes"), "Contact extracted from QR code")


class TestBuildHistorySettings(unittest.TestCase):

    def test_returns_correct_structure(self):
        s = app.build_history_settings(
            "llava", 180, "Auto", 2, 3, 5, 40, 1, 2, 3, 4)
        self.assertEqual(s["vision_model"], "llava")
        self.assertEqual(s["detection_mode"], "Auto")
        self.assertEqual(s["grid_rows"], 2)
        self.assertEqual(s["grid_cols"], 3)
        self.assertEqual(s["min_card_percent"], 5)
        self.assertEqual(s["max_card_percent"], 40)
        self.assertEqual(s["margins"], {"top": 1, "bottom": 2, "left": 3, "right": 4})


class TestDrawGridOverlay(unittest.TestCase):

    def test_shape_preserved(self):
        img = np.ones((400, 300, 3), dtype=np.uint8) * 255
        result = app.draw_grid_overlay(img, 2, 2)
        self.assertEqual(result.shape, img.shape)
        self.assertFalse(np.array_equal(result, img))


class TestSplitImageGrid(unittest.TestCase):

    def test_2x2(self):
        img = np.ones((400, 300, 3), dtype=np.uint8) * 255
        tiles = app.split_image_grid(img, 2, 2)
        self.assertEqual(len(tiles), 4)
        for t in tiles:
            tile_img, _ = t
            self.assertEqual(tile_img.shape, (200, 150, 3))

    def test_1x1(self):
        img = np.ones((400, 300, 3), dtype=np.uint8) * 255
        tiles = app.split_image_grid(img, 1, 1)
        self.assertEqual(len(tiles), 1)
        tile_img, _ = tiles[0]
        self.assertEqual(tile_img.shape, (400, 300, 3))


class TestLoadImage(unittest.TestCase):

    def test_png_to_numpy(self):
        from PIL import Image
        from io import BytesIO
        pil_img = Image.new('RGB', (100, 50), color='red')
        buf = BytesIO()
        pil_img.save(buf, format='PNG')
        buf.seek(0)
        arr = app.load_image(buf)
        self.assertEqual(arr.shape, (50, 100, 3))


class TestContactsRepositoryIntegration(unittest.TestCase):
    """End-to-end repository tests using app.contacts_repo singleton."""

    def setUp(self):
        app.contacts_repo.clear_all()

    def test_singleton_type(self):
        from utils.contacts_repository import ContactsRepository
        self.assertIsInstance(app.contacts_repo, ContactsRepository)

    def test_save_and_retrieve(self):
        cid = app.contacts_repo.add_contact(
            {"fullName": "Test User", "email": "test@repo.com", "company": "RepoCo"},
            source_file="card.png",
            vcf_content="BEGIN:VCARD\nFN:Test User\nEND:VCARD",
        )
        self.assertEqual(app.contacts_repo.count(), 1)
        entry = app.contacts_repo.get_all()[0]
        self.assertEqual(entry["contact_data"]["fullName"], "Test User")
        self.assertEqual(entry["source_file"], "card.png")

    def test_bulk_save_and_grouped(self):
        for c in [
            {"fullName": "A A", "company": "Alpha", "email": "a@a.com"},
            {"fullName": "B B", "company": "Alpha", "email": "b@b.com"},
            {"fullName": "C C", "company": "Beta", "email": "c@c.com"},
            {"fullName": "D D", "email": "d@d.com"},
        ]:
            app.contacts_repo.add_contact(contact_data=c)

        self.assertEqual(app.contacts_repo.count(), 4)
        groups = app.contacts_repo.get_grouped_by_company()
        self.assertIn("Alpha", groups)
        self.assertIn("Beta", groups)
        self.assertIn("(No company)", groups)
        self.assertEqual(len(groups["Alpha"]), 2)

    def test_duplicate_email_updates(self):
        app.contacts_repo.add_contact({"fullName": "First", "email": "dup@t.com"})
        app.contacts_repo.add_contact({"fullName": "Second", "email": "dup@t.com"})
        self.assertEqual(app.contacts_repo.count(), 1)
        self.assertEqual(app.contacts_repo.get_all()[0]["contact_data"]["fullName"], "Second")

    def test_search_and_vcf(self):
        app.contacts_repo.add_contact(
            {"fullName": "Alice J", "company": "BigData"},
            vcf_content="BEGIN:VCARD\nFN:Alice J\nEND:VCARD",
        )
        app.contacts_repo.add_contact({"fullName": "Bob S"})
        self.assertEqual(len(app.contacts_repo.search("Alice")), 1)
        self.assertEqual(len(app.contacts_repo.search("BigData")), 1)
        self.assertEqual(len(app.contacts_repo.search("Nobody")), 0)
        vcf = app.contacts_repo.get_all_vcf()
        self.assertIn("Alice J", vcf)
        self.assertNotIn("Bob S", vcf)  # no VCF content


class TestPDFSupport(unittest.TestCase):
    """Tests for PDF-to-image conversion and PDF detection."""

    def test_has_pdf_support_true(self):
        self.assertTrue(app.HAS_PDF_SUPPORT, "PyMuPDF should be installed")

    def test_is_pdf_by_extension(self):
        from io import BytesIO
        buf = BytesIO(b"dummy")
        buf.name = "test_document.pdf"
        self.assertTrue(app._is_pdf(buf))

    def test_is_pdf_by_content_sniffing(self):
        from io import BytesIO
        # Valid PDF header
        buf = BytesIO(b"%PDF-1.4\n%....")
        buf.name = "unknown.bin"
        self.assertTrue(app._is_pdf(buf))

    def test_is_pdf_false_for_image(self):
        from io import BytesIO
        from PIL import Image
        pil_img = Image.new('RGB', (100, 50), color='red')
        buf = BytesIO()
        pil_img.save(buf, format='PNG')
        buf.seek(0)
        buf.name = "card.png"
        self.assertFalse(app._is_pdf(buf))

    def test_pdf_pages_to_images_single_page(self):
        from io import BytesIO
        pdf_path = PROJECT_ROOT / "tests" / "fixtures" / "test_business_card.pdf"
        if not pdf_path.exists():
            self.skipTest("Test PDF fixture not found")
        with open(pdf_path, "rb") as f:
            pdf_buf = BytesIO(f.read())
        pdf_buf.name = "test_business_card.pdf"
        pages = app.pdf_pages_to_images(pdf_buf)
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].name.endswith("_page_1.png"))
        # Should be loadable as image
        img = app.load_image(pages[0])
        self.assertEqual(len(img.shape), 3)  # RGB image

    def test_pdf_pages_to_images_naming(self):
        from io import BytesIO
        pdf_path = PROJECT_ROOT / "tests" / "fixtures" / "test_business_card.pdf"
        if not pdf_path.exists():
            self.skipTest("Test PDF fixture not found")
        with open(pdf_path, "rb") as f:
            pdf_buf = BytesIO(f.read())
        pdf_buf.name = "test_business_card.pdf"
        pages = app.pdf_pages_to_images(pdf_buf)
        self.assertEqual(pages[0].name, "test_business_card_page_1.png")


if __name__ == "__main__":
    unittest.main()
