"""
Shared test fixtures and configuration for Business Card Scanner tests.
"""

import sys
import pytest
import numpy as np
import cv2
from pathlib import Path
from unittest.mock import Mock, MagicMock
from typing import Dict, Any

# Add project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.models import ContactInfo, Address, ScanResult, ProviderType, ProviderConfig
from utils.providers.factory import ProviderFactory


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
