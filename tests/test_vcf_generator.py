"""
Tests for VCFGenerator.

Strategy: round-trip the generated VCF back through `vobject.readOne` and
assert that fields match. Catches RFC compliance bugs and escaping issues
that a string-equality test would miss.
"""

import pytest
import vobject

from utils.vcf_generator import VCFGenerator


@pytest.fixture
def gen():
    return VCFGenerator()


def _parse(vcf_text: str):
    return vobject.readOne(vcf_text)


# ── generate_vcf_string round-trip ───────────────────────────────────────────


def test_round_trip_full_record(gen):
    data = {
        "fullName": "Joel Silva",
        "firstName": "Joel",
        "lastName": "Silva",
        "title": "Director",
        "company": "Acme",
        "email": "joel@acme.com",
        "phone": "+55 11 9999-1111",
        "mobile": "+55 11 9999-2222",
        "website": "https://acme.com",
    }
    vcf = gen.generate_vcf_string(data)
    parsed = _parse(vcf)

    assert parsed.fn.value == "Joel Silva"
    assert parsed.n.value.given == "Joel"
    assert parsed.n.value.family == "Silva"
    assert parsed.org.value[0] == "Acme"
    assert parsed.title.value == "Director"
    # vobject exposes email/tel as a list of children
    emails = [e.value for e in parsed.contents.get("email", [])]
    assert "joel@acme.com" in emails
    tels = [t.value for t in parsed.contents.get("tel", [])]
    assert any("9999-1111" in t for t in tels)
    assert any("9999-2222" in t for t in tels)


def test_round_trip_minimal_record_uses_unknown_when_no_name(gen):
    """If no name fields are provided, the FN must still be present
    (RFC 6350 makes FN required) — generator falls back to 'Unknown'."""
    vcf = gen.generate_vcf_string({"email": "anon@example.com"})
    parsed = _parse(vcf)
    assert parsed.fn.value  # non-empty


def test_round_trip_only_first_last(gen):
    """When fullName is absent, FN must be assembled from firstName + lastName."""
    vcf = gen.generate_vcf_string({"firstName": "João", "lastName": "Silva"})
    parsed = _parse(vcf)
    assert parsed.fn.value == "João Silva"


def test_unicode_diacritics_preserved(gen):
    """Brazilian/Portuguese names with diacritics must survive serialise + parse."""
    data = {"fullName": "João Pereira", "company": "São Paulo Tecnologia"}
    vcf = gen.generate_vcf_string(data)
    parsed = _parse(vcf)
    assert parsed.fn.value == "João Pereira"
    assert parsed.org.value[0] == "São Paulo Tecnologia"


def test_none_values_dont_break_serialisation(gen):
    """None values should be sanitised, not crash the serialiser."""
    data = {
        "fullName": "Joel",
        "company": None,
        "email": None,
        "phone": None,
    }
    vcf = gen.generate_vcf_string(data)
    parsed = _parse(vcf)
    assert parsed.fn.value == "Joel"


def test_string_null_is_treated_as_missing(gen):
    """LLMs sometimes return the literal string 'null' — treat as empty."""
    data = {"fullName": "Joel", "company": "null", "email": "None"}
    vcf = gen.generate_vcf_string(data)
    # 'company' == "null" should not appear as a real ORG line
    assert "ORG:null" not in vcf


# ── generate_vcf_file ────────────────────────────────────────────────────────


def test_generate_vcf_file_writes_to_disk(gen, tmp_path):
    target = tmp_path / "joel"
    out_path = gen.generate_vcf_file({"fullName": "Joel"}, str(target))
    assert out_path.endswith(".vcf")
    content = open(out_path, "r", encoding="utf-8").read()
    parsed = _parse(content)
    assert parsed.fn.value == "Joel"


# ── generate_bulk_vcf concatenates separate vCards ───────────────────────────


def test_bulk_vcf_contains_one_vcard_per_contact(gen, tmp_path):
    contacts = [
        {"fullName": "A One"},
        {"fullName": "B Two"},
        {"fullName": "C Three"},
    ]
    out = gen.generate_bulk_vcf(contacts, filename=str(tmp_path / "bulk.vcf"))
    text = open(out, "r", encoding="utf-8").read()
    assert text.count("BEGIN:VCARD") == 3
    assert text.count("END:VCARD") == 3
    # First and last names should both appear
    assert "A One" in text
    assert "C Three" in text


# ── contact_to_filename helper ───────────────────────────────────────────────


def test_filename_prefers_full_name(gen):
    name = gen.contact_to_filename({"fullName": "Joel Silva", "email": "joel@acme.com"})
    assert "Joel" in name and "Silva" in name


def test_filename_falls_back_to_first_last(gen):
    name = gen.contact_to_filename({"firstName": "Joel", "lastName": "Silva"})
    assert "Joel" in name and "Silva" in name


def test_filename_falls_back_to_email_local_part(gen):
    name = gen.contact_to_filename({"email": "joel@acme.com"})
    assert "joel" in name.lower()


def test_filename_strips_unsafe_characters(gen):
    name = gen.contact_to_filename({"fullName": "Joel/Silva!?<>"})
    # Only alnum, space, dash, underscore allowed; spaces become underscores
    assert all(c.isalnum() or c in "-_" for c in name)


def test_filename_skips_llm_placeholder(gen):
    """If fullName is the schema placeholder text, fall back to email."""
    name = gen.contact_to_filename({
        "fullName": "Complete Name",   # known placeholder fragment
        "email": "real@x.com",
    })
    assert "real" in name.lower()


# ── validate_contact_data ────────────────────────────────────────────────────


def test_validate_requires_name_or_email(gen):
    # validate_contact_data returns truthy when a name or email is present.
    # It uses `has_name or has_email`, so the falsy result may be None or "",
    # not necessarily False.
    assert gen.validate_contact_data({"fullName": "X"})
    assert gen.validate_contact_data({"email": "x@x.com"})
    assert not gen.validate_contact_data({"phone": "555"})
    assert not gen.validate_contact_data({})
