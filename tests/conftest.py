"""
Shared test fixtures and configuration for Business Card Scanner tests.
"""

import sys
import pytest
import requests
import numpy as np
import cv2
from pathlib import Path
from unittest.mock import Mock, MagicMock
from typing import Dict, Any

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# ─────────────────────────────────────────────────────────────────────────────
# Disable probablepeople in tests
#
# probablepeople depends on python-crfsuite, a C extension. On Python 3.12
# manylinux GitHub-Actions runners, the wheel hangs in a tight C loop that
# never yields the GIL, so pytest-timeout's signal handler can't interrupt
# it. The hang manifests in tests/test_ocr_parser.py::test_extracts_simple_email
# (the first test to call OllamaVisionProvider._parse_ocr_to_contact, which
# internally tries to tag candidate lines with probablepeople).
#
# The OCR parser already has a graceful ImportError fallback to its
# pure-Python heuristics — and the existing tests in test_ocr_parser.py were
# written against those heuristics. Stubbing the modules out here makes
# `import probablepeople` raise ModuleNotFoundError immediately so the
# parser uses the fallback path. No test changes needed.
#
# Real fix would be to find a python-crfsuite version with a working cp312
# wheel; track that work separately.
# ─────────────────────────────────────────────────────────────────────────────
sys.modules.setdefault("probablepeople", None)
sys.modules.setdefault("probableparsing", None)

from utils.models import ContactInfo, Address, ScanResult, ProviderType, ProviderConfig
from utils.providers.factory import ProviderFactory


# ─────────────────────────────────────────────────────────────────────────────
# Block stray network calls to localhost
#
# Several tests (TestProviderFactory.test_statuses_return_all_providers, etc.)
# instantiate ProviderFactory and call get_all_statuses(), which triggers
# requests.get('http://localhost:11434/api/tags') and the vLLM equivalent.
# In CI those services don't exist; the calls *should* error out at connect
# time but on some sandboxed runners they hang past their 3s timeout and
# block the whole pytest run.
#
# This autouse session-scoped fixture monkeypatches requests.get / .post so
# that any call to a localhost URL raises ConnectionError immediately.
# Tests that explicitly want to mock a successful response can still do so
# by re-patching requests in their own monkeypatch — pytest's monkeypatch
# scope wins over this autouse one.
# ─────────────────────────────────────────────────────────────────────────────


def _is_local_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    u = url.lower()
    return ("://localhost" in u) or ("://127.0.0.1" in u) or ("://0.0.0.0" in u)


@pytest.fixture(autouse=True)
def _block_localhost_network(monkeypatch):
    """Fail fast on any localhost HTTP call so missing daemons don't hang CI.

    Two layers of defence:

    1. Patch ``requests.get`` / ``requests.post`` so any code that touches a
       localhost URL via the requests library raises ConnectionError
       immediately (no 3-second timeout, no socket connect attempt).
    2. Patch the local-provider availability checks
       (``OllamaVisionProvider.check_availability`` /
       ``VLLMVisionProvider.check_availability``) directly to return
       ``UNAVAILABLE`` without doing ANY network I/O. This is the surer fix
       because even if a future provider stops using the requests library
       (e.g. switches to httpx), the test suite will still be safe.

    Tests that explicitly want a positive response can still re-patch via
    their own ``monkeypatch`` (function-scope wins over this autouse one).
    """
    real_get = requests.get
    real_post = requests.post

    def _guarded(method_name, real_method):
        def _wrapper(url, *args, **kwargs):
            if _is_local_url(url):
                raise requests.exceptions.ConnectionError(
                    f"[conftest] Blocked {method_name.upper()} {url} — localhost "
                    "services are not started in tests. Mock requests in your "
                    "test if you need a fake response."
                )
            return real_method(url, *args, **kwargs)
        return _wrapper

    monkeypatch.setattr(requests, "get", _guarded("get", real_get))
    monkeypatch.setattr(requests, "post", _guarded("post", real_post))

    # Belt + braces: short-circuit local-provider availability checks so they
    # NEVER make a socket call. Importing here (lazily) so this conftest stays
    # cheap to import for tests that don't use ProviderFactory.
    from utils.models import ProviderStatus
    from utils.providers.ollama_provider import OllamaVisionProvider
    from utils.providers.vllm_provider import VLLMVisionProvider

    def _unavailable(self):
        self._last_error = "[conftest] Skipped network probe in tests"
        return ProviderStatus.UNAVAILABLE

    monkeypatch.setattr(OllamaVisionProvider, "check_availability", _unavailable)
    monkeypatch.setattr(VLLMVisionProvider, "check_availability", _unavailable)

    yield


@pytest.fixture
def tmp_test_dir(tmp_path):
    """Temporary directory for test files."""
    return tmp_path


@pytest.fixture
def sample_image_simple() -> np.ndarray:
    """Create a simple test image (solid color)."""
    return np.ones((400, 300, 3), dtype=np.uint8) * 200


@pytest.fixture
def sample_business_card_image() -> np.ndarray:
    """Create a mock business card image."""
    # Create a white background
    img = np.ones((600, 400, 3), dtype=np.uint8) * 255
    
    # Add some structure to simulate a business card
    # Blue header band
    cv2.rectangle(img, (0, 0), (400, 100), (200, 100, 50), -1)
    
    # Add text area
    cv2.rectangle(img, (20, 120), (380, 400), (255, 255, 255), -1)
    
    # Simulate borders
    cv2.rectangle(img, (10, 10), (390, 590), (0, 0, 0), 2)
    
    return img


@pytest.fixture
def sample_contact_dict() -> Dict[str, Any]:
    """Sample contact data in dictionary format."""
    return {
        'firstName': 'John',
        'lastName': 'Doe',
        'fullName': 'John Doe',
        'title': 'Software Engineer',
        'company': 'Tech Corp',
        'email': 'john@techcorp.com',
        'phone': '+1-555-0100',
        'mobile': '+1-555-0101',
        'address': '123 Main St\nNew York, NY 10001',
        'website': 'https://techcorp.com',
        'linkedin': 'https://linkedin.com/in/johndoe',
        'notes': 'Test contact',
    }


@pytest.fixture
def sample_contact_info() -> ContactInfo:
    """Sample ContactInfo dataclass."""
    return ContactInfo(
        first_name='Jane',
        last_name='Smith',
        full_name='Jane Smith',
        title='Product Manager',
        company='Design Studio',
        email='jane@designstudio.com',
        phone='+1-555-0200',
        mobile='+1-555-0201',
        address=Address(
            street='456 Oak Ave',
            city='San Francisco',
            state='CA',
            zip_code='94102',
            country='USA'
        ),
        website='https://designstudio.com',
        linkedin='https://linkedin.com/in/janesmith',
        notes='Senior PM',
    )


@pytest.fixture
def sample_qr_data() -> Dict[str, Any]:
    """Sample QR code extracted data."""
    return {
        'full_name': 'Alice Johnson',
        'first_name': 'Alice',
        'last_name': 'Johnson',
        'organization': 'Marketing Inc',
        'title': 'Marketing Director',
        'emails': ['alice@marketing.com'],
        'phones': ['+1-555-0300'],
        'url': 'https://marketing.com',
        'address': '789 Pine St; Chicago; IL; 60601; USA',
    }


@pytest.fixture
def mock_provider_factory() -> ProviderFactory:
    """Create a mock ProviderFactory for testing."""
    factory = Mock(spec=ProviderFactory)
    
    # Default: return successful scan result
    contact = ContactInfo(
        first_name='Test',
        last_name='User',
        email='test@example.com',
    )
    factory.extract_with_fallback.return_value = ScanResult(
        contact=contact,
        provider_used=ProviderType.OLLAMA,
        error=None,
    )
    
    factory.get_all_statuses.return_value = {
        ProviderType.OLLAMA: {
            'status': 'available',
            'is_local': True,
            'model': 'glm-ocr',
            'priority': 0,
            'error': None,
        }
    }
    
    factory.warmup_best_provider.return_value = (True, 'ollama')
    
    return factory


@pytest.fixture
def mock_qr_reader():
    """Create a mock QRReader for testing."""
    reader = Mock()
    reader.detect_and_decode.return_value = None
    reader.extract_contact_info.return_value = None
    return reader


@pytest.fixture
def mock_card_detector():
    """Create a mock ImprovedCardDetector for testing."""
    detector = Mock()
    # Return a single card by default
    detector.detect_cards.return_value = [(np.ones((400, 300, 3), dtype=np.uint8) * 255, None)]
    return detector


@pytest.fixture
def mock_vcf_generator():
    """Create a mock VCFGenerator for testing."""
    generator = Mock()
    generator.generate_vcf_string.return_value = "BEGIN:VCARD\nVERSION:3.0\nFN:Test User\nEND:VCARD"
    generator.contact_to_filename.return_value = "Test_User.vcf"
    generator.preview_vcard.return_value = "Test User\ntest@example.com"
    return generator
