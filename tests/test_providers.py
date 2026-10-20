"""
Tests for vision provider implementations (utils/providers/).
"""

import pytest
import numpy as np
import json
from unittest.mock import Mock, patch, MagicMock
import responses as responses_lib

from utils.providers.factory import ProviderFactory
from utils.models import ProviderType, ScanResult


class TestProviderFactory:
    """Test ProviderFactory class."""
    
    def test_factory_init(self):
        """Test ProviderFactory initialization."""
        factory = ProviderFactory()
        assert factory is not None
    
    def test_factory_get_all_statuses(self):
        """Test getting all provider statuses."""
        factory = ProviderFactory()
        statuses = factory.get_all_statuses()
        
        # Should have status for each provider type
        assert isinstance(statuses, dict)
        # At least one provider should be defined
        assert len(statuses) > 0
    
    def test_factory_provider_configs(self):
        """Test provider factory has default configs."""
        factory = ProviderFactory()
        # Should have configs attribute or DEFAULT_CONFIGS
        has_configs = hasattr(factory, 'provider_configs') or hasattr(factory, 'DEFAULT_CONFIGS')
        assert has_configs
    
    @patch.object(ProviderFactory, 'warmup_best_provider')
    def test_factory_warmup_best_provider(self, mock_warmup):
        """Test warmup best provider."""
        mock_warmup.return_value = (True, "ollama")
        
        factory = ProviderFactory()
        success, provider = factory.warmup_best_provider()
        
        assert success is True
        assert provider == "ollama"


class TestProviderFallback:
    """Test provider fallback mechanism."""
    
    def test_fallback_chain_exists(self):
        """Test that provider factory has fallback chain configured."""
        factory = ProviderFactory()
        
        # Should have multiple providers configured with priority
        statuses = factory.get_all_statuses()
        assert len(statuses) > 1
        
        # Providers should have priority ordering
        priorities = [info.get('priority', 999) for info in statuses.values()]
        assert len(set(priorities)) > 1  # Different priorities
    
    def test_extract_with_fallback_exists(self):
        """Test that extract_with_fallback method exists."""
        factory = ProviderFactory()
        
        # Method should be callable
        assert hasattr(factory, 'extract_with_fallback')
        assert callable(factory.extract_with_fallback)


class TestTitleDemotion:
    """Tests for demote_title_misplaced_as_name / _looks_like_title.

    Guards the heuristic that catches vision models emitting a job title
    in the fullName field. The key invariant: never blank a real person's
    name, even when their surname collides with a role word.
    """

    @pytest.mark.parametrize(
        "value,expected",
        [
            # Unambiguous titles -> True
            ("CEO", True),
            ("Director", True),
            ("Diretor", True),
            ("Sales Manager", True),
            ("Vice President", True),
            ("VP of Sales", True),
            ("Diretor Comercial", True),
            ("Gerente de Vendas", True),
            ("Sales Director", True),
            ("Chief Technology Officer", True),
            # Real names -> False (must NOT demote)
            ("John Smith", False),
            ("Mike Director", False),  # surname collides w/ strong token
            ("Anna Presidente", False),
            ("Daniel Sales", False),  # single weak hit
            ("Maria Silva", False),
            ("Dr. John Smith", False),  # honorific veto
            ("Sra. Ana Costa", False),
            ("Robert Lead", False),
            ("Patricia Marketing", False),
            ("", False),
            (None, False),
        ],
    )
    def test_looks_like_title(self, value, expected):
        from utils.providers.base import _looks_like_title

        assert _looks_like_title(value) is expected

    def test_demote_moves_to_empty_title(self):
        from utils.providers.base import demote_title_misplaced_as_name

        cd = {"fullName": "Sales Manager", "title": "", "email": "a@b.com"}
        demote_title_misplaced_as_name(cd)
        assert cd["fullName"] is None
        assert cd["title"] == "Sales Manager"

    def test_demote_never_overwrites_existing_title(self):
        from utils.providers.base import demote_title_misplaced_as_name

        cd = {"fullName": "Sales Manager", "title": "Account Exec", "email": "a@b.com"}
        demote_title_misplaced_as_name(cd)
        assert cd["fullName"] is None
        assert cd["title"] == "Account Exec"  # preserved

    def test_demote_clears_first_last_when_concatenation_is_title(self):
        from utils.providers.base import demote_title_misplaced_as_name

        cd = {"firstName": "Sales", "lastName": "Manager", "fullName": None, "title": ""}
        demote_title_misplaced_as_name(cd)
        assert cd["firstName"] is None
        assert cd["lastName"] is None
        assert cd["title"] == "Sales Manager"

    def test_demote_leaves_real_name_untouched(self):
        from utils.providers.base import demote_title_misplaced_as_name

        cd = {"fullName": "Mike Director", "title": "", "email": "m@b.com"}
        demote_title_misplaced_as_name(cd)
        assert cd["fullName"] == "Mike Director"
        assert cd["title"] == ""

    def test_demote_safe_on_none(self):
        from utils.providers.base import demote_title_misplaced_as_name

        assert demote_title_misplaced_as_name(None) is None


class TestFieldPermutations:
    """Tests for fix_field_permutations — email-anchored repair of
    name/title/company scrambles produced by vision models.

    Canonical bug (real qwen2.5vl output): title held the person's name,
    company held the job title, email held the truth.
    """

    def _fix(self, cd):
        from utils.providers.base import fix_field_permutations

        return fix_field_permutations(dict(cd))

    def test_real_scan_scramble_fully_repaired(self):
        out = self._fix(
            {
                "title": "Victor Becattini",
                "company": "Vice Presidente Vendas Brasil",
                "email": "victor.becattini@sandvik.com",
            }
        )
        assert out["fullName"] == "Victor Becattini"
        assert out["firstName"] == "Victor"
        assert out["lastName"] == "Becattini"
        assert out["title"] == "Vice Presidente Vendas Brasil"
        assert out["company"] == "Sandvik"  # derived from email domain

    def test_pure_fullname_title_swap(self):
        out = self._fix(
            {
                "fullName": "Vice President Sales",
                "title": "Victor Becattini",
                "email": "victor.becattini@sandvik.com",
            }
        )
        assert out["fullName"] == "Victor Becattini"
        assert out["title"] == "Vice President Sales"  # displaced role re-homed

    def test_correct_extraction_untouched(self):
        cd = {
            "fullName": "Eric Kohtakangas",
            "title": "Senior Executive Vice President",
            "company": "Cementation Canada Inc.",
            "email": "eric.kohtakangas@cementation.com",
        }
        out = self._fix(cd)
        assert out == cd

    def test_freemail_domain_never_invents_company(self):
        out = self._fix({"fullName": "John Smith", "email": "john.smith@gmail.com"})
        assert not out.get("company")

    def test_accented_name_matches_plain_ascii_email(self):
        out = self._fix(
            {
                "title": "João Gusmão",
                "company": "Diretor Comercial",
                "email": "joao.gusmao@btgpactual.com",
            }
        )
        assert out["fullName"] == "João Gusmão"
        assert out["title"] == "Diretor Comercial"

    def test_single_token_email_local_no_rotation(self):
        # 'victor@' is too weak to anchor a rotation — leave fields alone.
        out = self._fix({"title": "Victor Becattini", "email": "victor@sandvik.com"})
        assert out["title"] == "Victor Becattini"
        assert not out.get("fullName")

    def test_no_email_is_noop(self):
        cd = {"title": "Victor Becattini", "company": "Vice Presidente"}
        assert self._fix(cd) == cd

    def test_role_like_company_moved_to_empty_title(self):
        # No name rotation needed; company still holds a job title.
        out = self._fix(
            {
                "fullName": "Ana Souza",
                "company": "Gerente de Vendas",
                "email": "ana.souza@acme.com",
            }
        )
        assert out["title"] == "Gerente de Vendas"
        assert out["company"] == "Acme"

    def test_company_mentioning_domain_not_demoted(self):
        # Company text is role-ish AND mentions the domain -> leave it.
        out = self._fix(
            {
                "fullName": "Ana Souza",
                "company": "Sandvik Sales Division",
                "email": "ana.souza@sandvik.com",
            }
        )
        assert out["company"] == "Sandvik Sales Division"

    def test_none_and_missing_safe(self):
        from utils.providers.base import fix_field_permutations

        assert fix_field_permutations(None) is None
        assert fix_field_permutations({}) == {}


class TestPromptEchoStrip:
    """strip_prompt_echoes — models copying our prompt's glossary line
    ('Gerente=Manager, Diretor=Director, Presidente=President') into fields."""

    def _strip(self, cd):
        from utils.providers.base import strip_prompt_echoes

        return strip_prompt_echoes(dict(cd))

    def test_exact_glossary_cleared(self):
        out = self._strip({"title": "Gerente=Manager, Diretor=Director, Presidente=President"})
        assert out["title"] is None

    def test_glossary_embedded_keeps_rest(self):
        out = self._strip({"title": "Diretor Comercial Gerente=Manager, Diretor=Director"})
        assert out["title"] == "Diretor Comercial"

    def test_single_pair_left_alone(self):
        # One '=' could be legitimate (e.g. notes); only runs of pairs are echoes.
        out = self._strip({"notes": "stand B12 = hall 3"})
        assert out["notes"] == "stand B12 = hall 3"

    def test_normal_fields_untouched(self):
        cd = {"title": "Vice Presidente Vendas Brasil", "company": "Sandvik"}
        assert self._strip(cd) == cd

    def test_none_safe(self):
        from utils.providers.base import strip_prompt_echoes

        assert strip_prompt_echoes(None) is None

    def test_prompt_no_longer_contains_glossary(self):
        from utils.providers.base import VisionProvider

        assert "Gerente=Manager" not in VisionProvider.build_extraction_prompt()


class TestCJKCards:
    """Japanese/Chinese/Korean cards keep their script, are detected, and get
    a Latin translation pass. Regression: before the sprinkle gate every
    kanji on a Tokyo card became '?' ("????RtMジャパン????")."""

    JA = {
        "firstName": "つう",
        "lastName": "でん",
        "fullName": "つうでん",
        "title": "営業部長",
        "company": "株式会社RtMジャパン",
        "address": "〒100-7027 東京都千代田区丸の内二丁目7番2号 JPタワー27階",
        "email": "kimiaki.tsuden@rtm.mitsubishicorp.com",
    }

    def test_japanese_fields_survive_repair(self):
        from utils.providers.base import repair_cjk_substitutions

        out = repair_cjk_substitutions(dict(self.JA))
        assert out["company"] == "株式会社RtMジャパン"
        assert out["address"].startswith("〒100-7027 東京都")
        assert "?" not in out["company"]

    def test_sprinkled_substitution_still_repaired(self):
        from utils.providers.base import repair_cjk_substitutions

        out = repair_cjk_substitutions({"fullName": "Andr矇 Rebou癟as", "company": "S瓊o Paulo Ltda"})
        assert out["fullName"] == "André Rebouças"
        assert out["company"] == "São Paulo Ltda"

    @pytest.mark.parametrize(
        "contact,expected",
        [
            ({"fullName": "つうでん", "company": "株式会社RtMジャパン"}, "ja"),
            ({"fullName": "王小明", "company": "北京科技有限公司"}, "zh"),
            ({"fullName": "김철수"}, "ko"),
            ({"fullName": "John Smith", "company": "Acme"}, None),
            ({"fullName": "Andr矇 Silva"}, None),  # substitution, not a CJK card
            (None, None),
        ],
    )
    def test_detect_cjk_script(self, contact, expected):
        from utils.providers.base import detect_cjk_script

        assert detect_cjk_script(contact) == expected

    def _provider(self):
        from utils.providers.ollama_provider import OllamaVisionProvider as OllamaProvider
        from utils.models import ProviderConfig

        return OllamaProvider(ProviderConfig(model_name="qwen2.5vl:7b", timeout=5))

    def test_translation_pass_latinizes_and_keeps_original(self):
        latin = {
            "firstName": "Kimiaki",
            "lastName": "Tsuden",
            "fullName": None,
            "company": "Mitsubishi Corporation RtM Japan Ltd.",
            "title": "General Manager, Sales",
        }
        resp = Mock(status_code=200)
        resp.json.return_value = {"response": json.dumps(latin, ensure_ascii=False)}
        with patch("utils.providers.ollama_provider.requests.post", return_value=resp) as post:
            out = self._provider()._translate_cjk_fields("b64", dict(self.JA), "ja")
        assert post.call_count == 1
        payload = post.call_args.kwargs["json"]
        assert payload["images"] == ["b64"]
        assert "Japanese" in payload["prompt"]
        assert "kimiaki.tsuden@" in payload["prompt"]
        assert out["fullName"] == "Kimiaki Tsuden"
        assert out["company"] == "Mitsubishi Corporation RtM Japan Ltd."
        assert out["title"] == "General Manager, Sales"
        assert out["notes"].startswith("原文: つうでん · 株式会社RtMジャパン · 営業部長")
        assert out["address"].startswith("〒100-7027")  # address keeps the script

    def test_translation_pass_rejects_cjk_answers_and_failures(self):
        # Model echoed Japanese back → fields untouched, no notes line.
        resp = Mock(status_code=200)
        resp.json.return_value = {"response": json.dumps({"fullName": "つうでん"}, ensure_ascii=False)}
        with patch("utils.providers.ollama_provider.requests.post", return_value=resp):
            out = self._provider()._translate_cjk_fields("b64", dict(self.JA), "ja")
        assert out["fullName"] == "つうでん" and "notes" not in out
        # HTTP failure → untouched.
        with patch("utils.providers.ollama_provider.requests.post", return_value=Mock(status_code=500)):
            out = self._provider()._translate_cjk_fields("b64", dict(self.JA), "ja")
        assert out["company"] == "株式会社RtMジャパン"

    def test_extract_runs_translation_only_for_cjk(self, monkeypatch):
        """End-to-end through extract_contact: a Japanese reply triggers the
        second call and sets _detected_lang; a Latin reply makes one call."""
        monkeypatch.delenv("OLLAMA_CJK_TRANSLATE", raising=False)
        img = np.full((300, 500, 3), 255, dtype=np.uint8)
        latin = {"firstName": "Kimiaki", "lastName": "Tsuden", "company": "RtM Japan", "title": "Manager"}
        replies = [json.dumps(self.JA, ensure_ascii=False), json.dumps(latin)]

        def fake_post(url, json=None, timeout=None):
            r = Mock(status_code=200)
            r.json.return_value = {"response": replies.pop(0)}
            return r

        with patch("utils.providers.ollama_provider.requests.post", side_effect=fake_post) as post:
            result = self._provider().extract_contact(img)
        assert post.call_count == 2
        assert result.detected_lang == "ja"
        assert result.contact.full_name == "Kimiaki Tsuden"
        assert result.contact.company == "RtM Japan"
        assert "原文: つうでん" in (result.contact.notes or "")

        replies[:] = [json.dumps({"fullName": "John Smith", "company": "Acme", "email": "j@acme.com"})]
        with patch("utils.providers.ollama_provider.requests.post", side_effect=fake_post) as post:
            result = self._provider().extract_contact(img)
        assert post.call_count == 1
        assert result.contact.full_name == "John Smith"

    @pytest.mark.parametrize(
        "name,email,expected",
        [
            ("Kimi Aki", "kimiaki.tsuden@rtm.example.com", "Kimiaki Tsuden"),  # furigana only
            ("Tsuden", "kimiaki_tsuden@example.com", "Kimiaki Tsuden"),  # family name only
            ("Kimiaki Tsuden", "kimiaki.tsuden@example.com", "Kimiaki Tsuden"),  # already right
            ("Taro Yamada", "info@example.com", "Taro Yamada"),  # no evidence → untouched
            ("Taro Yamada", "kimiaki.tsuden@example.com", "Taro Yamada"),  # unrelated → untouched
        ],
    )
    def test_reconcile_name_with_email(self, name, email, expected):
        from utils.providers.ollama_provider import OllamaVisionProvider

        c = {"fullName": name, "email": email}
        OllamaVisionProvider._reconcile_name_with_email(c)
        assert c["fullName"] == expected
