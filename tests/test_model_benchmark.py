"""
Tests for utils/model_benchmark — scoring vision models against locked
(human-verified) contacts.
"""

import os

import pytest

from utils.model_benchmark import (
    BenchAccumulator,
    collect_items,
    field_matches,
    score_card,
)


class TestFieldMatching:
    def test_text_exact_normalized(self):
        assert field_matches("fullName", "Victor Becattini", {"fullName": "victor  becattini"})

    def test_text_accent_folded(self):
        assert field_matches("fullName", "João Gusmão", {"fullName": "Joao Gusmao"})

    def test_text_containment_counts(self):
        # "Sandvik" vs the full legal name is not a ranking-relevant error.
        assert field_matches("company", "Sandvik", {"company": "Sandvik Mining and Rock Solutions"})
        assert field_matches("company", "Sandvik Mining and Rock Solutions", {"company": "Sandvik"})

    def test_text_mismatch(self):
        assert not field_matches("fullName", "Victor Becattini", {"fullName": "Marcelo Dias"})

    def test_email_case_insensitive(self):
        assert field_matches("email", "A.B@Acme.COM", {"email": "a.b@acme.com"})

    def test_phone_suffix_tolerates_country_code(self):
        assert field_matches("phone", "+55 31 3555-7300", {"phone": "31 3555 7300"})

    def test_phone_pooled_with_mobile(self):
        # Truth phone found in the extracted MOBILE slot still counts.
        assert field_matches(
            "phone", "+55 31 3555-7300", {"phone": "", "mobile": "+55 31 3555 7300"}
        )

    def test_phone_too_short_never_matches(self):
        assert not field_matches("phone", "7300", {"phone": "7300"})

    def test_website_scheme_and_www_stripped(self):
        assert field_matches("website", "https://www.sandvik.com/", {"website": "sandvik.com"})

    def test_empty_extracted_no_match(self):
        assert not field_matches("fullName", "Victor", {})


class TestScoreCard:
    def test_only_truth_fields_scored(self):
        truth = {"fullName": "Ana Souza", "email": "ana@acme.com", "title": ""}
        out = score_card(truth, {"fullName": "Ana Souza", "email": "wrong@x.com"})
        assert out == {"fullName": True, "email": False}
        assert "title" not in out


class TestCollectItems:
    def _mk(self, tmp_path, contacts):
        thumb = tmp_path / "thumbs"
        thumb.mkdir()
        for c in contacts:
            cid = c.get("card_id")
            if cid and c.pop("_img", True):
                (thumb / f"{cid}.jpg").write_bytes(b"\xff\xd8fake")
        return str(thumb)

    def test_only_locked_with_image(self, tmp_path):
        contacts = [
            {
                "id": "a",
                "locked": True,
                "card_id": "r1_0",
                "contact_data": {"fullName": "A", "email": "a@x.com"},
            },
            {"id": "b", "locked": False, "card_id": "r1_1", "contact_data": {"fullName": "B"}},
            {"id": "c", "locked": True, "card_id": "", "contact_data": {"fullName": "C"}},
        ]
        thumb = self._mk(tmp_path, contacts)
        items = collect_items(contacts, thumb)
        assert [i["contact_id"] for i in items] == ["a"]
        assert items[0]["label"] == "A"
        assert os.path.exists(items[0]["image_path"])

    def test_limit_respected(self, tmp_path):
        contacts = [
            {
                "id": str(i),
                "locked": True,
                "card_id": f"r_{i}",
                "contact_data": {"fullName": f"P{i}", "email": f"p{i}@x.com"},
            }
            for i in range(5)
        ]
        thumb = self._mk(tmp_path, contacts)
        assert len(collect_items(contacts, thumb, limit=3)) == 3


class TestAccumulator:
    def test_summary_math(self):
        acc = BenchAccumulator("glm-ocr")
        acc.add({"fullName": True, "email": True}, 1000)
        acc.add({"fullName": False, "email": True}, 3000)
        s = acc.summary()
        assert s["model"] == "glm-ocr"
        assert s["fields"]["fullName"] == {"ok": 1, "total": 2, "pct": 50.0}
        assert s["fields"]["email"]["pct"] == 100.0
        assert s["overall"] == {"ok": 3, "total": 4, "pct": 75.0}
        assert s["avg_ms"] == 2000
        assert s["failures"] == 0

    def test_failure_counted(self):
        acc = BenchAccumulator("m")
        acc.add({"fullName": False}, 0, failed=True)
        assert acc.summary()["failures"] == 1


class TestModelRouting:
    """The factory must apply an explicitly-requested model to the matching
    provider config (regression: the UI's model choice used to be dropped,
    and extraction silently ran on whatever model Ollama had loaded)."""

    def test_model_provider_type_mapping(self):
        from utils.models import ProviderType
        from utils.providers.factory import ProviderFactory

        assert ProviderFactory._model_provider_type("glm-ocr") == ProviderType.OLLAMA
        assert ProviderFactory._model_provider_type("qwen2.5vl:7b") == ProviderType.OLLAMA
        assert ProviderFactory._model_provider_type("claude-3") == ProviderType.CLAUDE
        assert ProviderFactory._model_provider_type("gpt-4o") == ProviderType.OPENAI

    def test_requested_model_applied_to_ollama_config(self, monkeypatch):
        import numpy as np
        from unittest.mock import MagicMock

        from utils.models import ProviderStatus, ProviderType, ScanResult, ContactInfo
        from utils.providers.factory import ProviderFactory

        factory = ProviderFactory()
        ollama_cfg = next(c for c in factory.configs if c.provider_type == ProviderType.OLLAMA)

        seen = {}
        fake_provider = MagicMock()

        def _extract(image, qr):
            seen["model_at_call"] = ollama_cfg.model_name
            return ScanResult(
                contact=ContactInfo(full_name="X Y", email="x@y.com"),
                confidence=0.9,
                provider_used=ProviderType.OLLAMA,
                processing_time_ms=1,
            )

        fake_provider.extract_contact.side_effect = _extract
        monkeypatch.setattr(factory, "_get_or_create_provider", lambda cfg: fake_provider)

        # Simulate check_availability having switched to the loaded model.
        def _status(pt):
            if pt == ProviderType.OLLAMA:
                ollama_cfg.model_name = "some-loaded-model"
                return ProviderStatus.AVAILABLE
            return ProviderStatus.UNAVAILABLE

        monkeypatch.setattr(factory, "check_provider_status", _status)

        img = np.zeros((10, 10, 3), dtype=np.uint8)
        factory.extract_with_fallback(img, None, model="qwen2.5vl:7b")
        assert seen["model_at_call"] == "qwen2.5vl:7b"
