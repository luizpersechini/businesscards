"""
Tests for the FastAPI routes in server.py.

Strategy:
  - Use fastapi.testclient.TestClient — synchronous, no event loop fuss.
  - Replace the module-level _provider_factory / _history / _contacts with
    mocks via monkeypatch so tests don't need Ollama/disk state.
  - Cover happy path + at least one error path per route.

Routes covered:
    GET    /api/status
    POST   /api/scan/stop
    GET    /api/contacts
    POST   /api/contacts
    PUT    /api/contacts/{id}
    DELETE /api/contacts/{id}
    GET    /api/contacts/export/vcf
    GET    /api/contacts/export/xlsx
    GET    /api/contacts/export/csv
    GET    /api/history
    DELETE /api/history/{id}
    GET    /
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(monkeypatch, tmp_path):
    """A TestClient with the heavy module-level singletons replaced by mocks."""
    # Mock contacts repository
    fake_contacts = MagicMock()
    fake_contacts.get_all.return_value = [
        {
            "id": "c1",
            "full_name": "João Silva",
            "email": "joao@acme.com",
            "phone": "+55 11 9999-1111",
            "company": "Acme",
            "added_at": "2026-05-07T10:00:00",
            "vcf_content": "BEGIN:VCARD\nVERSION:3.0\nFN:João Silva\nEND:VCARD\n",
        }
    ]
    fake_contacts.get_all_vcf.return_value = "BEGIN:VCARD\nVERSION:3.0\nFN:João Silva\nEND:VCARD\n"
    fake_contacts.export_to_xlsx.return_value = b"PK\x03\x04fake-xlsx"
    fake_contacts.export_to_csv.return_value = "Name,Email\nJoão Silva,joao@acme.com\n"
    fake_contacts.remove_contact.return_value = True
    # add_contact returns a result dict since the locked-contact merge feature.
    fake_contacts.add_contact.return_value = {
        "id": "c2",
        "status": "added",
        "additions": {},
        "conflicts": [],
        "locked": False,
    }
    fake_contacts.update_contact.return_value = {
        "id": "c1",
        "fullName": "João Silva Jr.",
        "email": "joao@acme.com",
        "added_at": "2026-05-07T10:00:00",
    }
    # PUT /api/contacts/{id} now does a partial merge via apply_field_updates.
    fake_contacts.apply_field_updates.return_value = {
        "id": "c1",
        "fullName": "João Silva Jr.",
        "email": "joao@acme.com",
        "added_at": "2026-05-07T10:00:00",
    }

    monkeypatch.setattr(server, "_contacts", fake_contacts)

    # Mock history manager
    fake_history = MagicMock()
    fake_history.list_runs.return_value = []
    monkeypatch.setattr(server, "_history", fake_history)

    return TestClient(server.app)


# ── /api/status ──────────────────────────────────────────────────────────────


def test_status_offline_when_ollama_unreachable(client, monkeypatch):
    def _fail(*_a, **_kw):
        raise ConnectionError("ollama down")

    monkeypatch.setattr(server._requests, "get", _fail)
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["ollama"] == "offline"
    assert body["model"] == "none"
    assert body["models"] == []


def test_status_ready_with_glm_model(client, monkeypatch):
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"models": [{"name": "glm-ocr:latest"}, {"name": "qwen2.5vl"}]}
    monkeypatch.setattr(server._requests, "get", lambda *a, **kw: fake)
    body = client.get("/api/status").json()
    assert body["ollama"] == "ready"
    assert body["model"] == "glm-ocr"
    assert "glm-ocr:latest" in body["models"]


# ── /api/scan/stop ───────────────────────────────────────────────────────────


def test_scan_stop_sets_cancel_flag(client):
    server._scan_cancel_event.clear()
    r = client.post("/api/scan/stop")
    assert r.status_code == 200
    assert r.json() == {"status": "stopping"}
    assert server._scan_cancel_event.is_set()
    server._scan_cancel_event.clear()  # cleanup


# ── /api/contacts ────────────────────────────────────────────────────────────


def test_list_contacts_returns_array(client):
    r = client.get("/api/contacts")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert body[0]["id"] == "c1"


def test_create_contact_rejects_missing_payload(client):
    r = client.post("/api/contacts", json={})
    assert r.status_code == 400


def test_create_contact_happy_path(client):
    # The fake repo's get_all returns an item with id 'c1'; we ask the repo
    # to create id 'c2', so we need to make get_all return that too.
    server._contacts.get_all.return_value = [
        {"id": "c2", "full_name": "Jane Doe", "email": "jane@x.com"}
    ]
    r = client.post(
        "/api/contacts",
        json={"contact": {"fullName": "Jane Doe", "email": "jane@x.com"}},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_update_contact_rejects_missing_payload(client):
    r = client.put("/api/contacts/c1", json={})
    assert r.status_code == 400


def test_update_contact_happy_path(client):
    r = client.put(
        "/api/contacts/c1",
        json={"contact": {"fullName": "João Silva Jr."}},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_update_contact_404_when_missing(client):
    server._contacts.apply_field_updates.return_value = None
    r = client.put(
        "/api/contacts/missing",
        json={"contact": {"fullName": "Nobody"}},
    )
    assert r.status_code == 404


def test_delete_contact_happy_path(client):
    r = client.delete("/api/contacts/c1")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_delete_contact_404_when_missing(client):
    server._contacts.remove_contact.return_value = False
    r = client.delete("/api/contacts/missing")
    assert r.status_code == 404


# ── /api/contacts/export/* ───────────────────────────────────────────────────


def test_export_vcf_returns_vcard_stream(client):
    r = client.get("/api/contacts/export/vcf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/vcard")
    assert b"BEGIN:VCARD" in r.content


def test_export_xlsx_returns_binary(client):
    r = client.get("/api/contacts/export/xlsx")
    assert r.status_code == 200
    assert "spreadsheet" in r.headers["content-type"]
    assert r.content.startswith(b"PK")  # xlsx is a zip


def test_export_csv_returns_csv(client):
    r = client.get("/api/contacts/export/csv")
    assert r.status_code == 200
    assert "csv" in r.headers["content-type"]
    assert b"Name" in r.content


# ── /api/history ─────────────────────────────────────────────────────────────


def test_history_empty(client):
    r = client.get("/api/history")
    assert r.status_code == 200
    assert r.json() == []


def test_history_delete_404_when_missing(client):
    server._history.delete_run.side_effect = FileNotFoundError("no such run")
    r = client.delete("/api/history/abc")
    assert r.status_code == 404


# ── / (frontend) ─────────────────────────────────────────────────────────────


def test_root_serves_html_frontend(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "html" in r.headers["content-type"].lower()
    body = r.text
    # Sanity: the React shell ships with these markers
    assert "<!DOCTYPE html>" in body or "<!doctype html>" in body
    assert "Business Card Reader" in body


# ── QR-only card consolidation ───────────────────────────────────────────────


def test_consolidate_merges_qr_only_into_single_rich_card():
    """A spurious QR-region card folds into the one real card; its _qr_url
    and website transfer over so the 'Fetch contact data' affordance is kept."""
    rich = {"contact_data": {"fullName": "Victor Becattini", "email": "v@s.com", "phone": "+55"}}
    qr = {
        "contact_data": {
            "website": "https://my.mobiz.pro/x",
            "notes": "Contact extracted from QR code",
            "_qr_url": "https://my.mobiz.pro/x",
        }
    }
    out = server._consolidate_qr_only_cards([rich, qr])
    assert len(out) == 1
    assert out[0]["contact_data"]["_qr_url"] == "https://my.mobiz.pro/x"
    assert out[0]["contact_data"]["website"] == "https://my.mobiz.pro/x"


def test_consolidate_leaves_batch_untouched():
    """With multiple rich cards we can't attribute a stray QR — leave all."""
    rich1 = {"contact_data": {"fullName": "A", "email": "a@x.com"}}
    rich2 = {"contact_data": {"fullName": "B", "email": "b@x.com"}}
    qr = {"contact_data": {"website": "https://q/x", "_qr_url": "https://q/x"}}
    out = server._consolidate_qr_only_cards([rich1, rich2, qr])
    assert len(out) == 3


def test_consolidate_keeps_lone_qr_card():
    """A QR-dominant card with no rich sibling is kept as-is."""
    qr = {"contact_data": {"website": "https://q/x", "_qr_url": "https://q/x"}}
    out = server._consolidate_qr_only_cards([qr])
    assert len(out) == 1


def test_consolidate_noop_without_qr_url():
    """Two rich cards, no QR — unchanged."""
    a = {"contact_data": {"fullName": "A", "email": "a@x.com"}}
    b = {"contact_data": {"company": "Acme", "phone": "+1"}}
    out = server._consolidate_qr_only_cards([a, b])
    assert len(out) == 2


# ── POST /api/contacts/{id}/rescan ──────────────────────────────────────────


def _rescan_setup(client, monkeypatch, tmp_path, locked=False, card=None):
    """Point THUMBNAIL_DIR at tmp, store a crop for contact c1, and replace
    CardProcessor with a fake whose process_single_card returns `card`."""
    import cv2
    import numpy as np

    thumb_dir = tmp_path / "thumbs"
    thumb_dir.mkdir()
    cv2.imwrite(str(thumb_dir / "card-abc.jpg"), np.full((40, 60, 3), 255, dtype=np.uint8))
    monkeypatch.setattr(server, "THUMBNAIL_DIR", str(thumb_dir))

    entry = {
        "id": "c1",
        "card_id": "card-abc",
        "locked": locked,
        "contact_data": {"fullName": "きみあき", "company": "????RtMジャパン????", "email": "k@x.jp"},
        "added_at": "2026-10-20T10:00:00",
    }
    server._contacts.get_all.return_value = [entry]
    rescan_result = {
        "status": "conflict" if locked else "updated",
        "additions": {"title": "Manager"} if locked else {},
        "conflicts": [{"field": "fullName", "existing": "きみあき", "incoming": "Kimiaki Tsuden"}] if locked else [],
        "locked": locked,
    }

    def _apply(cid, cd, vcf=""):
        # Mimic the real repository: an unlocked rescan replaces the data.
        if not locked:
            entry["contact_data"] = dict(cd)
        return rescan_result

    server._contacts.apply_rescan.side_effect = _apply

    calls = {}

    class FakeProcessor:
        def __init__(self, provider_factory=None):
            pass

        def process_single_card(self, img, rgb=None, vision_model=None, vision_timeout=None):
            calls["model"] = vision_model
            calls["shape"] = img.shape
            return card

    monkeypatch.setattr(server, "CardProcessor", FakeProcessor)
    return calls


def test_rescan_unlocked_replaces_data_and_strips_stashes(client, monkeypatch, tmp_path):
    card = {
        "contact_data": {
            "fullName": "Kimiaki Tsuden",
            "company": "Mitsubishi Corporation RtM Japan",
            "email": "k@x.jp",
            "notes": "原文: きみあき",
            "_model_used": "qwen2.5vl:7b",
            "_detected_lang": "ja",
            "_qr_url": "https://x",
        },
        "vcf_content": "BEGIN:VCARD\nEND:VCARD\n",
        "via_qr": False,
        "processing_time": 16.04,
    }
    calls = _rescan_setup(client, monkeypatch, tmp_path, card=card)
    r = client.post("/api/contacts/c1/rescan", json={"model": "qwen2.5vl:7b"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "updated"
    assert body["modelUsed"] == "qwen2.5vl:7b"
    assert body["detectedLang"] == "ja"
    assert body["time"] == 16.0
    assert calls["model"] == "qwen2.5vl:7b"
    assert calls["shape"] == (40, 60, 3)
    assert body["contact"]["contact"]["notes"] == "原文: きみあき"  # notes reach the UI
    stored = server._contacts.apply_rescan.call_args.args[1]
    assert stored["fullName"] == "Kimiaki Tsuden"
    assert not any(k.startswith("_") for k in stored)  # stashes never persisted
    assert server._contacts.apply_rescan.call_args.args[0] == "c1"


def test_rescan_locked_reports_conflicts(client, monkeypatch, tmp_path):
    card = {"contact_data": {"fullName": "Kimiaki Tsuden", "title": "Manager", "email": "k@x.jp"}}
    _rescan_setup(client, monkeypatch, tmp_path, locked=True, card=card)
    body = client.post("/api/contacts/c1/rescan", json={}).json()
    assert body["status"] == "conflict"
    assert body["additions"] == {"title": "Manager"}
    assert body["conflicts"][0]["field"] == "fullName"


def test_rescan_without_stored_crop_is_404(client, monkeypatch, tmp_path):
    _rescan_setup(client, monkeypatch, tmp_path, card={"contact_data": {"fullName": "X"}})
    server._contacts.get_all.return_value[0]["card_id"] = "missing"
    r = client.post("/api/contacts/c1/rescan", json={})
    assert r.status_code == 404
    r = client.post("/api/contacts/nope/rescan", json={})
    assert r.status_code == 404


def test_rescan_with_no_extraction_is_422(client, monkeypatch, tmp_path):
    _rescan_setup(client, monkeypatch, tmp_path, card=None)
    r = client.post("/api/contacts/c1/rescan", json={})
    assert r.status_code == 422


# ── duplicate flag on freshly-added cards ───────────────────────────────────


def test_frontend_mapper_emits_duplicates_for_new_entry():
    card = {
        "contact_data": {"fullName": "Henrik Kalbau", "company": "OLDENDORFF"},
        "_repo_status": "added",
        "_repo_id": "new1",
        "_duplicates": [
            {"id": "old1", "fullName": "Henrik Kalbau", "company": "Oldendorff Carriers",
             "email": "h@oldendorff.com", "reason": "same name + company", "addedAt": "2026-05-01", "locked": False}
        ],
    }
    out = server._contact_data_to_frontend(card, "x.heic", 0)
    assert out["repoStatus"] == "added"
    assert out["duplicates"][0]["id"] == "old1"
    assert out["duplicates"][0]["reason"] == "same name + company"
    # Cards without the stash get an empty list, never a missing key.
    assert server._contact_data_to_frontend({"contact_data": {"fullName": "X"}}, "y", 0)["duplicates"] == []
