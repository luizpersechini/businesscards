import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image


@dataclass
class HistoryFile:
    """Represents a stored file within a history run."""

    name: str
    path: str
    media_type: str = "binary"  # image, vcf, csv, json, zip, etc.


@dataclass
class HistoryCard:
    """Represents metadata for a processed business card."""

    index: int
    filename: Optional[str]
    source_file: Optional[str]
    locked: bool
    contact_data: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, HistoryFile] = field(default_factory=dict)


@dataclass
class HistoryEntry:
    """Combined metadata for a processing run."""

    run_id: str
    created_at: str
    settings: Dict[str, Any]
    original_files: List[HistoryFile]
    cards: List[HistoryCard]
    exports: List[HistoryFile]
    notes: Optional[str] = None


class HistoryManager:
    """
    Handles persistence and retrieval of processed runs.

    Each run is stored under `temp/history/<run_id>/` with the following structure:
        metadata.json        -> High-level metadata for quick listing.
        original/<files>     -> Copies of uploaded source images.
        cards/card_###/<...> -> Per-card artifacts (contact json, preview, vcf).
        exports/<files>      -> Generated export bundles (csv, xlsx, zip, etc.).
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        project_root = Path(__file__).resolve().parent.parent
        self.base_dir = Path(base_dir) if base_dir else project_root / "temp" / "history"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _generate_run_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = uuid.uuid4().hex[:6]
        return f"{timestamp}_{suffix}"

    def _run_path(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def _metadata_path(self, run_id: str) -> Path:
        return self._run_path(run_id) / "metadata.json"

    def _write_metadata(self, run_id: str, metadata: Dict[str, Any]) -> None:
        metadata_path = self._metadata_path(run_id)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_metadata(self, run_id: str) -> Dict[str, Any]:
        metadata_path = self._metadata_path(run_id)
        if not metadata_path.exists():
            raise FileNotFoundError(f"No history metadata for run_id='{run_id}'")
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def create_run(
        self,
        settings: Dict[str, Any],
        original_files: List[Dict[str, Any]],
        processed_cards: List[Dict[str, Any]],
        notes: Optional[str] = None,
    ) -> HistoryEntry:
        """
        Persist a new run to disk and return its metadata.

        Args:
            settings: Configuration used for processing (vision model, detection mode, etc.).
            original_files: List of dictionaries with `name` and `data` (bytes) keys.
            processed_cards: List of processed card dictionaries matching app session structure.
            notes: Optional free-form text.
        """
        run_id = self._generate_run_id()
        run_path = self._run_path(run_id)
        original_path = run_path / "original"
        cards_path = run_path / "cards"
        exports_path = run_path / "exports"

        for path in (run_path, original_path, cards_path, exports_path):
            path.mkdir(parents=True, exist_ok=True)

        stored_originals: List[HistoryFile] = []
        for file_info in original_files:
            name = file_info.get("name") or f"source_{len(stored_originals) + 1}.png"
            data = file_info.get("data")
            media_type = file_info.get("media_type", "image")

            if data is None:
                continue

            safe_name = sanitize_filename(name)
            destination = original_path / safe_name
            destination.write_bytes(data)
            stored_originals.append(
                HistoryFile(
                    name=safe_name,
                    path=str(destination.relative_to(run_path)),
                    media_type=media_type,
                )
            )

        stored_cards: List[HistoryCard] = []
        for idx, card in enumerate(processed_cards):
            card_dir = cards_path / f"card_{idx + 1:03d}"
            card_dir.mkdir(parents=True, exist_ok=True)

            filename = card.get("filename")
            contact_data = card.get("contact_data", {}) or {}
            source_file = card.get("source_file")
            locked = card.get("locked", False)

            artifacts: Dict[str, HistoryFile] = {}

            # Save contact data json
            contact_json_path = card_dir / "contact.json"
            contact_json_path.write_text(json.dumps(contact_data, ensure_ascii=False, indent=2), encoding="utf-8")
            artifacts["contact_json"] = HistoryFile(
                name="contact.json",
                path=str(contact_json_path.relative_to(run_path)),
                media_type="json",
            )

            # Save VCF content if present
            vcf_content = card.get("vcf_content")
            if vcf_content:
                vcf_name = f"{sanitize_filename(filename or f'card_{idx + 1:03d}')}.vcf"
                vcf_path = card_dir / vcf_name
                vcf_path.write_text(vcf_content, encoding="utf-8")
                artifacts["vcf"] = HistoryFile(
                    name=vcf_name,
                    path=str(vcf_path.relative_to(run_path)),
                    media_type="vcf",
                )

            # Save card preview image if available (expects RGB numpy array)
            card_image = card.get("card_image")
            if card_image is not None:
                try:
                    preview_path = card_dir / "preview.png"
                    Image.fromarray(card_image).save(preview_path)
                    artifacts["preview_image"] = HistoryFile(
                        name="preview.png",
                        path=str(preview_path.relative_to(run_path)),
                        media_type="image",
                    )
                except Exception:
                    # Ignore preview failures; metadata still stored.
                    pass

            stored_cards.append(
                HistoryCard(
                    index=idx + 1,
                    filename=filename,
                    source_file=source_file,
                    locked=locked,
                    contact_data=contact_data,
                    artifacts=artifacts,
                )
            )

        entry = HistoryEntry(
            run_id=run_id,
            created_at=datetime.now().isoformat(),
            settings=settings,
            original_files=stored_originals,
            cards=stored_cards,
            exports=[],
            notes=notes,
        )

        metadata_dict = history_entry_to_dict(entry)
        self._write_metadata(run_id, metadata_dict)
        return entry

    def list_runs(self) -> List[HistoryEntry]:
        """Return all stored runs ordered from newest to oldest."""
        runs: List[HistoryEntry] = []
        for directory in sorted(self.base_dir.glob("*"), key=os.path.getmtime, reverse=True):
            if not directory.is_dir():
                continue
            metadata_path = directory / "metadata.json"
            if not metadata_path.exists():
                continue
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            runs.append(history_entry_from_dict(metadata))
        return runs

    def get_run(self, run_id: str) -> HistoryEntry:
        """Load a single run by id."""
        metadata = self._load_metadata(run_id)
        return history_entry_from_dict(metadata)

    def delete_run(self, run_id: str) -> None:
        """Remove a run and all associated files."""
        run_path = self._run_path(run_id)
        if run_path.exists():
            shutil.rmtree(run_path)

    def register_export(self, run_id: str, filename: str, data: bytes, media_type: str = "binary") -> HistoryFile:
        """
        Store an export artifact on disk and update metadata.

        Args:
            run_id: Target run identifier.
            filename: Desired file name.
            data: File content bytes.
            media_type: Optional media descriptor (csv, xlsx, zip).
        """
        sanitized_name = sanitize_filename(filename)
        run_path = self._run_path(run_id)
        exports_path = run_path / "exports"
        exports_path.mkdir(parents=True, exist_ok=True)

        destination = exports_path / sanitized_name
        destination.write_bytes(data)

        metadata = self._load_metadata(run_id)
        exports = metadata.setdefault("exports", [])
        exports.append(
            {
                "name": sanitized_name,
                "path": str(destination.relative_to(run_path)),
                "media_type": media_type,
            }
        )
        self._write_metadata(run_id, metadata)

        return HistoryFile(
            name=sanitized_name,
            path=str(destination.relative_to(run_path)),
            media_type=media_type,
        )

    def update_card(
        self,
        run_id: str,
        card_index: int,
        contact_data: Optional[Dict[str, Any]] = None,
        locked: Optional[bool] = None,
        vcf_content: Optional[str] = None,
        card_image: Optional[Any] = None,
        filename: Optional[str] = None,
    ) -> HistoryCard:
        """
        Update an existing card entry inside a run.

        Args:
            run_id: Identifier of the run to update.
            card_index: 1-based index of the card.
            contact_data: Updated contact dictionary.
            locked: Updated lock state.
            vcf_content: Optional new VCF content to persist.
            card_image: Optional numpy RGB array for preview overwrite.
            filename: Optional new filename hint for associated artifacts.
        """
        metadata = self._load_metadata(run_id)
        cards = metadata.get("cards", [])

        if card_index < 1 or card_index > len(cards):
            raise IndexError(f"Card index {card_index} out of range for run '{run_id}'")

        card_meta = cards[card_index - 1]
        run_path = self._run_path(run_id)
        card_dir = run_path / "cards" / f"card_{card_index:03d}"
        card_dir.mkdir(parents=True, exist_ok=True)

        if contact_data is not None:
            card_meta["contact_data"] = contact_data
            contact_json_path = card_dir / "contact.json"
            contact_json_path.write_text(json.dumps(contact_data, ensure_ascii=False, indent=2), encoding="utf-8")
            _update_artifact_path(card_meta, "contact_json", contact_json_path, run_path, "json")

        if locked is not None:
            card_meta["locked"] = locked

        if filename is not None:
            card_meta["filename"] = filename

        if vcf_content is not None:
            vcf_name = f"{sanitize_filename(card_meta.get('filename') or f'card_{card_index:03d}')}.vcf"
            vcf_path = card_dir / vcf_name
            vcf_path.write_text(vcf_content, encoding="utf-8")
            _update_artifact_path(card_meta, "vcf", vcf_path, run_path, "vcf")

        if card_image is not None:
            try:
                preview_path = card_dir / "preview.png"
                Image.fromarray(card_image).save(preview_path)
                _update_artifact_path(card_meta, "preview_image", preview_path, run_path, "image")
            except Exception:
                pass

        cards[card_index - 1] = card_meta
        metadata["cards"] = cards
        self._write_metadata(run_id, metadata)
        return history_card_from_dict(card_meta)

    def build_run_package(self, run_id: str) -> bytes:
        """
        Bundle an entire run directory into a ZIP archive and return the bytes.
        Useful for \"Download history entry\" actions in the UI.
        """
        run_path = self._run_path(run_id)
        if not run_path.exists():
            raise FileNotFoundError(f"Run '{run_id}' not found")

        archive_path = run_path.with_suffix(".zip")
        if archive_path.exists():
            archive_path.unlink()

        shutil.make_archive(str(run_path), "zip", root_dir=run_path)
        data = archive_path.read_bytes()
        archive_path.unlink(missing_ok=True)
        return data


def sanitize_filename(filename: str) -> str:
    """Basic filename sanitization for cross-platform compatibility."""
    safe_chars = "-_.() "
    sanitized = "".join(c for c in filename if c.isalnum() or c in safe_chars)
    return sanitized or "file"


def history_entry_to_dict(entry: HistoryEntry) -> Dict[str, Any]:
    """Serialize HistoryEntry dataclass into a JSON-compatible dict."""
    return {
        "run_id": entry.run_id,
        "created_at": entry.created_at,
        "settings": entry.settings,
        "original_files": [history_file_to_dict(f) for f in entry.original_files],
        "cards": [history_card_to_dict(card) for card in entry.cards],
        "exports": [history_file_to_dict(f) for f in entry.exports],
        "notes": entry.notes,
    }


def history_entry_from_dict(data: Dict[str, Any]) -> HistoryEntry:
    """Deserialize dict metadata into HistoryEntry dataclass."""
    return HistoryEntry(
        run_id=data["run_id"],
        created_at=data["created_at"],
        settings=data.get("settings", {}),
        original_files=[history_file_from_dict(d) for d in data.get("original_files", [])],
        cards=[history_card_from_dict(d) for d in data.get("cards", [])],
        exports=[history_file_from_dict(d) for d in data.get("exports", [])],
        notes=data.get("notes"),
    )


def history_file_to_dict(file: HistoryFile) -> Dict[str, Any]:
    return {
        "name": file.name,
        "path": file.path,
        "media_type": file.media_type,
    }


def history_file_from_dict(data: Dict[str, Any]) -> HistoryFile:
    return HistoryFile(
        name=data["name"],
        path=data["path"],
        media_type=data.get("media_type", "binary"),
    )


def history_card_to_dict(card: HistoryCard) -> Dict[str, Any]:
    return {
        "index": card.index,
        "filename": card.filename,
        "source_file": card.source_file,
        "locked": card.locked,
        "contact_data": card.contact_data,
        "artifacts": {key: history_file_to_dict(value) for key, value in card.artifacts.items()},
    }


def history_card_from_dict(data: Dict[str, Any]) -> HistoryCard:
    artifacts_dict = data.get("artifacts", {})
    artifacts = {key: history_file_from_dict(value) for key, value in artifacts_dict.items()}
    return HistoryCard(
        index=data["index"],
        filename=data.get("filename"),
        source_file=data.get("source_file"),
        locked=data.get("locked", False),
        contact_data=data.get("contact_data", {}),
        artifacts=artifacts,
    )


def _update_artifact_path(
    card_meta: Dict[str, Any],
    artifact_key: str,
    file_path: Path,
    run_path: Path,
    media_type: str,
) -> None:
    artifacts = card_meta.setdefault("artifacts", {})
    artifacts[artifact_key] = {
        "name": file_path.name,
        "path": str(file_path.relative_to(run_path)),
        "media_type": media_type,
    }


