import json
import tempfile
import unittest
from pathlib import Path

from utils.history_manager import HistoryManager


class HistoryManagerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = HistoryManager(base_dir=self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _sample_run(self):
        settings = {
            "vision_model": "llava:13b",
            "vision_timeout": 180,
            "detection_mode": "Automatic",
            "grid_rows": 1,
            "grid_cols": 1,
            "min_card_percent": 5,
            "max_card_percent": 40,
            "margins": {"top": 0, "bottom": 0, "left": 0, "right": 0},
        }
        original_files = [
            {
                "name": "card.png",
                "data": b"\x89PNG\r\n\x1a\n",
                "media_type": "image",
            }
        ]
        processed_cards = [
            {
                "filename": "john-doe",
                "contact_data": {"fullName": "John Doe", "email": "john@example.com"},
                "vcf_content": "BEGIN:VCARD\nFN:John Doe\nEMAIL:john@example.com\nEND:VCARD",
                "card_image": None,
                "source_file": "card.png",
                "locked": False,
            }
        ]
        return settings, original_files, processed_cards

    def test_create_run_persists_metadata(self):
        settings, original_files, processed_cards = self._sample_run()
        entry = self.manager.create_run(settings, original_files, processed_cards)

        run_path = Path(self.temp_dir.name) / entry.run_id
        metadata_path = run_path / "metadata.json"
        self.assertTrue(metadata_path.exists())

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["run_id"], entry.run_id)
        self.assertEqual(len(metadata["cards"]), 1)
        self.assertEqual(metadata["cards"][0]["contact_data"]["fullName"], "John Doe")

    def test_update_card_changes_lock_status(self):
        settings, original_files, processed_cards = self._sample_run()
        entry = self.manager.create_run(settings, original_files, processed_cards)

        self.manager.update_card(entry.run_id, 1, locked=True)
        refreshed = self.manager.get_run(entry.run_id)
        self.assertTrue(refreshed.cards[0].locked)

    def test_register_export_records_file(self):
        settings, original_files, processed_cards = self._sample_run()
        entry = self.manager.create_run(settings, original_files, processed_cards)

        export_bytes = b"name,email\nJohn Doe,john@example.com\n"
        export_file = self.manager.register_export(entry.run_id, "contacts.csv", export_bytes, media_type="csv")

        self.assertEqual(export_file.name, "contacts.csv")
        refreshed = self.manager.get_run(entry.run_id)
        self.assertEqual(len(refreshed.exports), 1)
        self.assertEqual(refreshed.exports[0].name, "contacts.csv")

    def test_build_run_package_creates_zip(self):
        settings, original_files, processed_cards = self._sample_run()
        entry = self.manager.create_run(settings, original_files, processed_cards)

        archive_bytes = self.manager.build_run_package(entry.run_id)
        self.assertGreater(len(archive_bytes), 0)


if __name__ == "__main__":
    unittest.main()


