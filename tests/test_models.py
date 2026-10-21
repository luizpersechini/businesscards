"""
Tests for data models and provider abstraction.
Run with: python -m pytest tests/ -v
Or:       python tests/test_models.py
"""

import sys
import os
import unittest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.models import (
    ContactInfo, Address, ScanResult, BatchScanResult,
    ProviderType, ProviderConfig
)

# Compatibility: allow running with or without pytest
try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False


class TestAddress:
    """Test Address model."""

    def test_empty_address(self):
        addr = Address()
        assert addr.is_empty()
        assert addr.to_single_line() == ""

    def test_full_address(self):
        addr = Address(
            street="Rua Augusta, 1234",
            city="São Paulo",
            state="SP",
            zip_code="01304-001",
            country="Brasil"
        )
        assert not addr.is_empty()
        assert "São Paulo" in addr.to_single_line()
        assert "SP" in addr.to_single_line()

    def test_partial_address(self):
        addr = Address(city="Rio de Janeiro", state="RJ")
        assert not addr.is_empty()
        assert addr.to_single_line() == "Rio de Janeiro, RJ"


class TestContactInfo:
    """Test ContactInfo model."""

    def test_minimal_contact(self):
        contact = ContactInfo(first_name="Luiz")
        assert contact.has_minimum_data()
        assert contact.get_display_name() == "Luiz"

    def test_full_contact(self):
        contact = ContactInfo(
            first_name="João",
            last_name="Silva",
            title="Diretor",
            company="Empresa SA",
            email="joao@empresa.com",
            phone="+55 (11) 99999-0000",
            website="www.empresa.com",
        )
        assert contact.has_minimum_data()
        assert contact.get_display_name() == "João Silva"
        assert contact.website == "https://www.empresa.com"

    def test_email_validation(self):
        contact = ContactInfo(email="invalid-email")
        assert contact.email is None

    def test_valid_email(self):
        contact = ContactInfo(email="test@example.com")
        assert contact.email == "test@example.com"

    def test_phone_cleaning(self):
        contact = ContactInfo(phone="+55 (11) 99999-0000")
        assert contact.phone  # Should keep valid chars
        assert "+" in contact.phone

    def test_url_prefix(self):
        contact = ContactInfo(website="example.com")
        assert contact.website == "https://example.com"

    def test_full_name_fallback(self):
        contact = ContactInfo(full_name="Maria da Silva Santos")
        assert contact.get_display_name() == "Maria da Silva Santos"
        assert contact.has_minimum_data()

    def test_empty_contact(self):
        contact = ContactInfo()
        assert not contact.has_minimum_data()
        assert contact.get_display_name() == "Unknown"

    def test_corporate_card_counts_as_minimum_data(self):
        # Oldendorff case: company + phone + address, no person, no email.
        assert ContactInfo(company="Oldendorff Carriers GmbH & Co. KG", phone="+49 40 8000 88-0").has_minimum_data()
        assert ContactInfo(company="Acme", website="https://acme.com").has_minimum_data()
        assert not ContactInfo(company="Acme").has_minimum_data()  # company alone is not a contact
        assert not ContactInfo(phone="+49 40 8000 88-0").has_minimum_data()

    def test_legacy_dict_roundtrip(self):
        original = {
            "firstName": "João",
            "lastName": "Silva",
            "title": "CEO",
            "company": "Test Corp",
            "email": "joao@test.com",
            "phone": "+55 11 99999-0000",
            "address": "Rua Test, 123",
            "city": "São Paulo",
            "state": "SP",
            "zip": "01234-567",
            "country": "Brasil",
            "website": "https://test.com",
            "linkedin": "https://linkedin.com/in/joao",
            "notes": "Met at conference"
        }

        contact = ContactInfo.from_legacy_dict(original)
        result = contact.to_legacy_dict()

        assert result["firstName"] == "João"
        assert result["lastName"] == "Silva"
        assert result["email"] == "joao@test.com"
        assert result["city"] == "São Paulo"
        assert result["company"] == "Test Corp"

    def test_from_legacy_with_camelcase_aliases(self):
        data = {"firstName": "Test", "lastName": "User", "fullName": "Test User"}
        contact = ContactInfo.from_legacy_dict(data)
        assert contact.first_name == "Test"
        assert contact.last_name == "User"
        assert contact.full_name == "Test User"

    def test_null_handling(self):
        data = {
            "firstName": "Test",
            "lastName": None,
            "email": "",
            "phone": None,
        }
        contact = ContactInfo.from_legacy_dict(data)
        assert contact.first_name == "Test"
        assert contact.last_name is None


class TestScanResult:
    """Test ScanResult model."""

    def test_successful_scan(self):
        result = ScanResult(
            contact=ContactInfo(first_name="Test"),
            confidence=0.95,
            provider_used=ProviderType.OLLAMA,
            processing_time_ms=1500,
        )
        assert result.error is None
        assert result.confidence == 0.95
        assert result.provider_used == ProviderType.OLLAMA

    def test_failed_scan(self):
        result = ScanResult(
            contact=ContactInfo(),
            confidence=0.0,
            provider_used=ProviderType.OLLAMA,
            error="Timeout after 120s"
        )
        assert result.error is not None
        assert result.confidence == 0.0

    def test_batch_result(self):
        batch = BatchScanResult(
            results=[
                ScanResult(contact=ContactInfo(first_name="A"), confidence=0.9, provider_used=ProviderType.OLLAMA),
                ScanResult(contact=ContactInfo(), confidence=0.0, provider_used=ProviderType.OLLAMA, error="fail"),
            ],
            total_cards=2,
            successful=1,
            failed=1,
            total_time_ms=3000,
        )
        assert batch.total_cards == 2
        assert batch.successful == 1
        assert batch.failed == 1


class TestProviderConfig:
    """Test ProviderConfig model."""

    def test_default_config(self):
        config = ProviderConfig(
            provider_type=ProviderType.OLLAMA,
            model_name="llama3.2-vision",
        )
        assert config.timeout == 120
        assert config.temperature == 0.1
        assert config.enabled is True
        assert config.priority == 0

    def test_cloud_config(self):
        config = ProviderConfig(
            provider_type=ProviderType.CLAUDE,
            model_name="claude-sonnet-4-6",
            api_key="test-key",
            timeout=30,
            priority=10,
        )
        assert config.api_key == "test-key"
        assert config.priority == 10


class TestProviderType:
    """Test ProviderType enum."""

    def test_local_providers(self):
        assert ProviderType.OLLAMA.value == "ollama"
        assert ProviderType.VLLM.value == "vllm"

    def test_cloud_providers(self):
        assert ProviderType.CLAUDE.value == "claude"
        assert ProviderType.OPENAI.value == "openai"


class TestProviderFactory:
    """Test ProviderFactory without requiring actual providers."""

    def test_factory_initialization(self):
        from utils.providers.factory import ProviderFactory
        factory = ProviderFactory()

        # Should have default configs
        assert len(factory.configs) == 4

        # First should be Ollama (lowest priority number = highest priority)
        assert factory.configs[0].provider_type == ProviderType.OLLAMA
        assert factory.configs[0].priority == 0

    def test_local_first_ordering(self):
        from utils.providers.factory import ProviderFactory
        factory = ProviderFactory()

        # Local providers should come first
        local_types = {ProviderType.OLLAMA, ProviderType.VLLM}
        for i, config in enumerate(factory.configs):
            if config.provider_type in local_types:
                assert config.priority < 10, f"Local provider {config.provider_type} should have priority < 10"

    def test_statuses_return_all_providers(self):
        from utils.providers.factory import ProviderFactory
        factory = ProviderFactory()
        statuses = factory.get_all_statuses()

        assert len(statuses) == 4
        assert ProviderType.OLLAMA in statuses
        assert ProviderType.VLLM in statuses
        assert ProviderType.CLAUDE in statuses
        assert ProviderType.OPENAI in statuses

    def test_update_config(self):
        from utils.providers.factory import ProviderFactory
        factory = ProviderFactory()

        factory.update_config(ProviderType.OLLAMA, model_name="llava:13b", timeout=300)

        config = next(c for c in factory.configs if c.provider_type == ProviderType.OLLAMA)
        assert config.model_name == "llava:13b"
        assert config.timeout == 300


class TestVCFGeneratorWithPydantic:
    """Test that VCF generator works with Pydantic model output."""

    def test_vcf_from_pydantic_contact(self):
        from utils.vcf_generator import VCFGenerator

        contact = ContactInfo(
            first_name="Maria",
            last_name="Santos",
            title="Gerente",
            company="Empresa Ltda",
            email="maria@empresa.com",
            phone="+55 (11) 98765-4321",
        )

        legacy = contact.to_legacy_dict()
        generator = VCFGenerator()
        vcf_string = generator.generate_vcf_string(legacy)

        assert "BEGIN:VCARD" in vcf_string
        assert "Maria" in vcf_string
        assert "Santos" in vcf_string
        assert "maria@empresa.com" in vcf_string

    def test_vcf_validation_with_pydantic(self):
        from utils.vcf_generator import VCFGenerator

        contact = ContactInfo(first_name="Test")
        legacy = contact.to_legacy_dict()

        generator = VCFGenerator()
        assert generator.validate_contact_data(legacy)


class TestExportProcessorWithPydantic:
    """Test export processor with Pydantic model output."""

    def test_csv_export(self):
        from utils.export_processor import ExportProcessor

        contacts = [
            ContactInfo(
                first_name="João", last_name="Silva",
                email="joao@test.com", company="Test Corp"
            ).to_legacy_dict(),
            ContactInfo(
                first_name="Maria", last_name="Santos",
                email="maria@test.com", phone="+55 11 99999-0000"
            ).to_legacy_dict(),
        ]

        processor = ExportProcessor()
        csv_bytes = processor.export_to_csv(contacts, include_source=False)
        csv_text = csv_bytes.decode('utf-8-sig')

        assert "João" in csv_text
        assert "Maria" in csv_text
        assert "joao@test.com" in csv_text

    def test_outlook_csv_export(self):
        from utils.export_processor import ExportProcessor

        contacts = [
            ContactInfo(
                first_name="Test", last_name="User",
                email="test@example.com"
            ).to_legacy_dict(),
        ]

        processor = ExportProcessor()
        outlook_bytes = processor.export_to_outlook_csv(contacts)
        outlook_text = outlook_bytes.decode('utf-8-sig')

        assert "First Name" in outlook_text
        assert "test@example.com" in outlook_text


if __name__ == "__main__":
    if HAS_PYTEST:
        pytest.main([__file__, "-v", "--tb=short"])
    else:
        # Run with unittest as fallback
        # Convert pytest-style classes to unittest
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()

        test_classes = [
            TestAddress, TestContactInfo, TestScanResult,
            TestProviderConfig, TestProviderType, TestProviderFactory,
            TestVCFGeneratorWithPydantic, TestExportProcessorWithPydantic,
        ]

        for cls in test_classes:
            for name in dir(cls):
                if name.startswith('test_'):
                    method = getattr(cls, name)
                    if callable(method):
                        # Create a wrapper for unittest
                        tc = unittest.FunctionTestCase(lambda m=method, c=cls: m(c()))
                        suite.addTest(tc)

        runner = unittest.TextTestRunner(verbosity=2)
        runner.run(suite)


class TestCorporateCardVcf:
    def test_filename_and_validation_use_company(self):
        from utils.vcf_generator import VCFGenerator

        gen = VCFGenerator()
        cd = {"company": "OLDENDORFF CARRIERS GmbH & Co. KG", "phone": "+49 40 8000 88-0"}
        assert gen.contact_to_filename(cd) == "OLDENDORFF_CARRIERS_GmbH__Co_KG"
        assert gen.validate_contact_data(cd)
        assert not gen.validate_contact_data({"company": "Acme"})
