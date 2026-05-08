"""
Unit tests for QRReader's parser surface.

We test the pure-Python parsers (no real image input):
  - _parse_qr_data dispatch (vcard / mecard / url / mailto / tel / text)
  - _parse_vcard structured fields
  - _parse_mecard structured fields (added in #6)
  - extract_contact_info merge logic across multiple QR results

Image-detection paths (pyzbar / OpenCV) are intentionally NOT exercised
here — they require a real image fixture and a working zbar install.
"""

import pytest

from utils.qr_reader import QRReader


@pytest.fixture
def reader():
    return QRReader()


# ── _parse_qr_data dispatch ──────────────────────────────────────────────────


def test_dispatch_vcard(reader):
    p = reader._parse_qr_data("BEGIN:VCARD\nVERSION:3.0\nFN:Joel Silva\nEND:VCARD")
    assert p["type"] == "vcard"
    assert p["data"]["full_name"] == "Joel Silva"


def test_dispatch_mecard(reader):
    p = reader._parse_qr_data(
        "MECARD:N:Silva,João;ORG:Acme;TEL:+5511999999999;EMAIL:joao@acme.com;;"
    )
    assert p["type"] == "vcard"   # MECARD normalised to vcard shape
    d = p["data"]
    assert d["first_name"] == "João"
    assert d["last_name"] == "Silva"
    assert d["organization"] == "Acme"
    assert d["phones"] == ["+5511999999999"]
    assert d["emails"] == ["joao@acme.com"]


def test_dispatch_mecard_case_insensitive(reader):
    p = reader._parse_qr_data("mecard:N:Smith,Jane;TEL:+15551234;;")
    assert p["type"] == "vcard"
    assert p["data"]["first_name"] == "Jane"


def test_dispatch_url(reader):
    p = reader._parse_qr_data("https://example.com/profile")
    assert p["type"] == "url"
    assert p["data"]["url"] == "https://example.com/profile"


def test_dispatch_mailto(reader):
    p = reader._parse_qr_data("MAILTO:foo@bar.com")
    assert p["type"] == "email"
    assert p["data"]["email"] == "foo@bar.com"


def test_dispatch_tel(reader):
    p = reader._parse_qr_data("tel:+15551234")
    assert p["type"] == "phone"
    assert p["data"]["phone"] == "+15551234"


def test_dispatch_plain_text_fallback(reader):
    p = reader._parse_qr_data("hello world")
    assert p["type"] == "text"
    assert p["data"]["text"] == "hello world"


# ── _parse_vcard ─────────────────────────────────────────────────────────────


def test_vcard_full_record(reader):
    raw = "\n".join([
        "BEGIN:VCARD",
        "VERSION:3.0",
        "FN:Joel Silva",
        "N:Silva;Joel;;;",
        "ORG:Acme",
        "TITLE:Director",
        "TEL:+5511999999999",
        "TEL;TYPE=CELL:+5511988887777",
        "EMAIL:joel@acme.com",
        "EMAIL;TYPE=WORK:joel.work@acme.com",
        "URL:https://acme.com",
        "ADR:;;Rua Augusta 100;São Paulo;SP;01304-001;Brazil",
        "END:VCARD",
    ])
    d = reader._parse_vcard(raw)
    assert d["full_name"] == "Joel Silva"
    assert d["last_name"] == "Silva"
    assert d["first_name"] == "Joel"
    assert d["organization"] == "Acme"
    assert d["title"] == "Director"
    assert d["phones"] == ["+5511999999999", "+5511988887777"]
    assert d["emails"] == ["joel@acme.com", "joel.work@acme.com"]
    assert d["url"] == "https://acme.com"
    assert "Rua Augusta 100" in d["address"]


def test_vcard_minimal_record(reader):
    raw = "BEGIN:VCARD\nVERSION:3.0\nFN:Solo\nEND:VCARD"
    d = reader._parse_vcard(raw)
    assert d["full_name"] == "Solo"


def test_vcard_ignores_lines_without_colon(reader):
    raw = "BEGIN:VCARD\nVERSION:3.0\nbroken-line\nFN:OK\nEND:VCARD"
    d = reader._parse_vcard(raw)
    assert d["full_name"] == "OK"


# ── _parse_mecard ────────────────────────────────────────────────────────────


def test_mecard_compound_surname(reader):
    d = reader._parse_mecard("MECARD:N:da Silva,João;ORG:Acme;;")
    assert d["first_name"] == "João"
    assert d["last_name"] == "da Silva"


def test_mecard_role_alias(reader):
    # MECARD spec lets ROLE substitute for TITLE in some implementations.
    d = reader._parse_mecard("MECARD:N:Doe,Jane;ROLE:Engineer;;")
    assert d["title"] == "Engineer"


def test_mecard_empty_yields_empty_dict(reader):
    d = reader._parse_mecard("MECARD:")
    assert d == {}


def test_mecard_url_and_note(reader):
    d = reader._parse_mecard("MECARD:N:Doe,Jane;URL:janedoe.com;NOTE:VIP;;")
    assert d["url"] == "janedoe.com"
    assert d["notes"] == "VIP"


# ── extract_contact_info merge logic ─────────────────────────────────────────


def test_extract_merges_vcard_and_email_qr(reader):
    qr_results = [
        {"parsed": {"type": "vcard", "data": {"full_name": "Joel Silva", "phones": ["111"]}}},
        {"parsed": {"type": "email", "data": {"email": "joel@acme.com"}}},
    ]
    info = reader.extract_contact_info(qr_results)
    assert info["full_name"] == "Joel Silva"
    assert info["phones"] == ["111"]
    assert "joel@acme.com" in info["emails"]


def test_extract_appends_multiple_phone_qrs(reader):
    qr_results = [
        {"parsed": {"type": "phone", "data": {"phone": "+1"}}},
        {"parsed": {"type": "phone", "data": {"phone": "+2"}}},
    ]
    info = reader.extract_contact_info(qr_results)
    assert info["phones"] == ["+1", "+2"]


def test_extract_returns_none_for_empty_results(reader):
    # With no useful QR types the helper should return falsy / empty
    result = reader.extract_contact_info([])
    # Implementation may return None or {} — both are acceptable here.
    assert not result


# ── is_available / enhance_for_qr_detection smoke checks ─────────────────────


def test_is_available_returns_bool(reader):
    assert isinstance(reader.is_available(), bool)
