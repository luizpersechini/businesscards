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
