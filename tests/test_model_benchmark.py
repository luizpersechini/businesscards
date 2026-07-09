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


class TestNameMatching:
    """Names may land in fullName OR firstName+lastName (OCR models like
    glm-ocr use the latter). The benchmark must credit both, mirroring the
    app's own fullName derivation — otherwise glm-ocr scores a false 0%."""

    def test_name_in_first_last_when_fullname_empty(self):
        assert field_matches(
            "fullName",
            "Fabiola Souza",
            {"fullName": None, "firstName": "Fabiola", "lastName": "Souza"},
        )

    def test_truth_subset_of_fuller_extracted_name(self):
        # 'Gilberto Costa' (truth) vs 'Gilberto Moura Costa' (full legal name)
        assert field_matches(
            "fullName",
            "Gilberto Costa",
            {"firstName": "Gilberto", "lastName": "Moura Costa"},
        )

    def test_short_truth_matches_first_last_even_if_fullname_is_title(self):
        # glm-ocr scramble: fullName holds a title, name is in first/last.
        assert field_matches(
            "fullName",
            "Candida",
            {"fullName": "Commercial Manager", "firstName": "Cândida", "lastName": "Lucena"},
        )

    def test_accent_folded_name(self):
        assert field_matches("fullName", "Joao Gusmao", {"fullName": "João Gusmão"})

    def test_wrong_name_still_fails(self):
        assert not field_matches(
            "fullName",
            "Victor Becattini",
            {"firstName": "Marcelo", "lastName": "Dias"},
        )


class TestCompanySpacing:
    """Company names written with different word breaks are the same name;
    short acronyms are not. (Investigated from a real benchmark run.)"""

    def test_spaced_vs_concatenated_with_legal_suffix(self):
        # 'Inter Maritima' (user's short form) == the model's full legal name.
        assert field_matches(
            "company",
            "Inter Maritima",
            {"company": "Intermarítima Portos e Logística S.A."},
        )

    def test_one_char_ocr_error_stays_a_miss(self):
        # 'Maceló' misread as 'Maceió' is a real error, not a spacing quirk.
        assert not field_matches(
            "company",
            "Maceló Logística & Serviços Portuários",
            {"company": "Maceió Logística & Serviços Portuários"},
        )

    def test_short_truth_not_false_matched(self):
        # 'IT' must not match 'digital' via a substring fluke.
        assert not field_matches("company", "IT", {"company": "digital"})


class TestCompanyAcronymAndBrand:
    """Bucket 2: verified short-form vs the model's full legal name.
    Acronym-of-initials and brand-prefix matching close the derivable ones;
    truly ambiguous cases (missing letters, wrong division) stay misses."""

    def test_acronym_of_initials(self):
        assert field_matches("company", "MME", {"company": "Ministério de Minas e Energia"})

    def test_acronym_stopwords_skipped(self):
        assert field_matches("company", "PUC", {"company": "Pontifícia Universidade Católica"})

    def test_brand_prefix(self):
        assert field_matches(
            "company", "Citibank", {"company": "Citi Treasury and Trade Solutions"}
        )
        assert field_matches(
            "company", "Citibank", {"company": "Citi Markets and Securities Services"}
        )

    def test_acronym_missing_letter_stays_miss_without_alias(self):
        # BNB = Banco do Nordeste *do Brasil*; the model dropped 'do Brasil',
        # so STRING LOGIC can't yield the third letter. (An explicit alias
        # group closes it — see TestCompanyAliases.) aliases=[] isolates the
        # string-logic behaviour from the on-disk alias file.
        assert not field_matches("company", "BNB", {"company": "Banco do Nordeste"}, aliases=[])

    def test_wrong_acronym_stays_miss(self):
        assert not field_matches("company", "ABC", {"company": "Apple Inc"}, aliases=[])

    def test_short_first_word_guarded(self):
        assert not field_matches("company", "San", {"company": "Sandvik Mining"}, aliases=[])

    def test_acronym_only_applies_to_company_not_title(self):
        # A 3-letter title must not fuzzy-match an unrelated expansion.
        assert not field_matches("title", "CEO", {"title": "Chief Executive of Operations Board"})


class TestCompanyAliases:
    """User-editable alias groups close org short-forms that string logic
    can't derive (e.g. BNB == Banco do Nordeste)."""

    GROUPS = [
        ["BNB", "Banco do Nordeste", "Banco do Nordeste do Brasil"],
        ["Petrobras", "Petróleo Brasileiro S.A."],
    ]

    def test_alias_closes_acronym(self):
        assert field_matches(
            "company", "BNB", {"company": "Banco do Nordeste"}, aliases=self.GROUPS
        )

    def test_alias_reverse_direction(self):
        assert field_matches(
            "company", "Banco do Nordeste do Brasil", {"company": "BNB"}, aliases=self.GROUPS
        )

    def test_alias_containment_within_group(self):
        # 'Banco do Nordeste' (extracted) matches the fuller alias entry.
        assert field_matches(
            "company",
            "BNB",
            {"company": "Banco do Nordeste do Brasil S.A."},
            aliases=self.GROUPS,
        )

    def test_alias_no_cross_group_leak(self):
        assert not field_matches(
            "company", "BNB", {"company": "Petróleo Brasileiro S.A."}, aliases=self.GROUPS
        )

    def test_alias_unrelated_still_miss(self):
        assert not field_matches("company", "BNB", {"company": "Bradesco"}, aliases=self.GROUPS)

    def test_aliases_only_for_company(self):
        # Alias groups must not bleed into other fields.
        assert not field_matches(
            "title", "BNB", {"title": "Banco do Nordeste"}, aliases=self.GROUPS
        )

    def test_load_missing_file_returns_empty(self):
        from utils.model_benchmark import load_company_aliases

        assert load_company_aliases("/nonexistent/path/aliases.json") == []

    def test_load_malformed_file_returns_empty(self, tmp_path):
        from utils.model_benchmark import load_company_aliases

        bad = tmp_path / "aliases.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert load_company_aliases(str(bad)) == []

    def test_load_valid_file(self, tmp_path):
        from utils.model_benchmark import load_company_aliases

        good = tmp_path / "aliases.json"
        good.write_text('[["A", "Alpha"], ["B", "Beta"]]', encoding="utf-8")
        groups = load_company_aliases(str(good))
        assert groups == [["A", "Alpha"], ["B", "Beta"]]
