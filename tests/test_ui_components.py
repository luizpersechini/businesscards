"""
Tests for UI component functions (utils/ui_components.py).
"""

import pytest
import numpy as np
import cv2
from utils.ui_components import (
    draw_grid_overlay,
    qr_data_is_sufficient,
    qr_to_contact_data,
    split_image_grid,
    HistoryFileWrapper,
)


class TestDrawGridOverlay:
    """Test grid overlay drawing."""
    
    def test_draw_grid_overlay_basic(self, sample_image_simple):
        """Test drawing grid overlay on simple image."""
        result = draw_grid_overlay(sample_image_simple, rows=2, cols=2)
        
        # Should return image same size
        assert result.shape == sample_image_simple.shape
        assert result.dtype == sample_image_simple.dtype
    
    def test_draw_grid_overlay_with_margins(self, sample_image_simple):
        """Test drawing grid overlay with margins."""
        result = draw_grid_overlay(
            sample_image_simple,
            rows=2,
            cols=2,
            margin_top=10,
            margin_bottom=10,
            margin_left=5,
            margin_right=5,
        )
        
        assert result.shape == sample_image_simple.shape


class TestQRDataIsSufficient:
    """Test QR data sufficiency check."""
    
    def test_qr_data_is_sufficient_with_email_list(self, sample_qr_data):
        """Test QR data with email list is sufficient."""
        assert qr_data_is_sufficient(sample_qr_data) is True
    
    def test_qr_data_is_sufficient_with_single_email(self):
        """Test QR data with single email is sufficient."""
        qr_data = {'email': 'test@example.com'}
        assert qr_data_is_sufficient(qr_data) is True
    
    def test_qr_data_is_insufficient_no_email(self):
        """Test QR data without email is insufficient."""
        qr_data = {'full_name': 'John Doe', 'phone': '555-0100'}
        assert qr_data_is_sufficient(qr_data) is False
    
    def test_qr_data_is_insufficient_empty_email_list(self):
        """Test QR data with empty email list is insufficient."""
        qr_data = {'emails': [], 'full_name': 'John Doe'}
        assert qr_data_is_sufficient(qr_data) is False
    
    def test_qr_data_is_insufficient_none(self):
        """Test None QR data is insufficient."""
        assert qr_data_is_sufficient(None) is False
    
    def test_qr_data_is_insufficient_invalid_email(self):
        """Test QR data with invalid email is insufficient."""
        qr_data = {'email': 'not_an_email'}
        assert qr_data_is_sufficient(qr_data) is False


class TestQRToContactData:
    """Test QR data to contact data conversion."""
    
    def test_qr_to_contact_data_full(self, sample_qr_data):
        """Test conversion of full QR data."""
        result = qr_to_contact_data(sample_qr_data)
        
        assert result['fullName'] == 'Alice Johnson'
        assert result['firstName'] == 'Alice'
        assert result['lastName'] == 'Johnson'
        assert result['company'] == 'Marketing Inc'
        assert result['title'] == 'Marketing Director'
        assert result['email'] == 'alice@marketing.com'
        assert result['phone'] == '+1-555-0300'
        assert result['website'] == 'https://marketing.com'
        assert 'extracted from QR' in result['notes']
    
    def test_qr_to_contact_data_multiple_emails(self):
        """Test conversion with multiple emails."""
        qr_data = {'emails': ['primary@example.com', 'secondary@example.com']}
        result = qr_to_contact_data(qr_data)
        assert result['email'] == 'primary@example.com'  # Takes first
    
    def test_qr_to_contact_data_multiple_phones(self):
        """Test conversion with multiple phones."""
        qr_data = {'phones': ['+1-555-0400', '+1-555-0401']}
        result = qr_to_contact_data(qr_data)
        assert result['phone'] == '+1-555-0400'
        assert result['mobile'] == '+1-555-0401'
    
    def test_qr_to_contact_data_minimal(self):
        """Test conversion of minimal QR data."""
        qr_data = {'emails': ['user@example.com']}
        result = qr_to_contact_data(qr_data)
        assert result['email'] == 'user@example.com'
        assert 'notes' in result
        assert 'extracted from QR' in result['notes']


class TestSplitImageGrid:
    """Test image grid splitting."""
    
    def test_split_image_grid_2x2(self, sample_business_card_image):
        """Test splitting image into 2x2 grid."""
        cards = split_image_grid(sample_business_card_image, rows=2, cols=2)
        
        assert len(cards) == 4
        # Each card should be approximately 200x300
        for card, contour in cards:
            assert card is not None
            assert contour is None
            assert card.shape[0] > 0 and card.shape[1] > 0
    
    def test_split_image_grid_3x3(self, sample_business_card_image):
        """Test splitting image into 3x3 grid."""
        cards = split_image_grid(sample_business_card_image, rows=3, cols=3)
        assert len(cards) == 9
    
    def test_split_image_grid_with_margins(self, sample_business_card_image):
        """Test splitting with margins."""
        cards = split_image_grid(
            sample_business_card_image,
            rows=2,
            cols=2,
            margin_top=10,
            margin_bottom=10,
            margin_left=5,
            margin_right=5,
        )
        
        assert len(cards) == 4
        # Cards should be smaller due to margins
        h, w = sample_business_card_image.shape[:2]
        working_h = h - int(h * 0.1) - int(h * 0.1)  # 10% each side
        for card, _ in cards:
            assert card.shape[0] <= working_h
    
    def test_split_image_grid_single_row(self, sample_business_card_image):
        """Test splitting into single row."""
        cards = split_image_grid(sample_business_card_image, rows=1, cols=3)
        assert len(cards) == 3


class TestHistoryFileWrapper:
    """Test HistoryFileWrapper class."""
    
    def test_history_file_wrapper_from_bytes(self):
        """Test creating wrapper from bytes."""
        data = b"test data"
        wrapper = HistoryFileWrapper(data, "test.txt")
        
        assert wrapper.name == "test.txt"
        assert wrapper.getvalue() == data
    
    def test_history_file_wrapper_from_string(self):
        """Test creating wrapper from string."""
        data = "test string"
        wrapper = HistoryFileWrapper(data, "test.txt")
        
        assert wrapper.name == "test.txt"
        assert isinstance(wrapper.getvalue(), bytes)
        assert wrapper.getvalue() == b"test string"
