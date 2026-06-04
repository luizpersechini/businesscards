"""
Tests for the card processing pipeline (utils/card_processor.py).
"""

import pytest
import numpy as np
import cv2
from unittest.mock import Mock, MagicMock, patch

from utils.card_processor import CardProcessor
from utils.models import ContactInfo, ScanResult, ProviderType


class TestCardProcessor:
    """Test CardProcessor class."""

    @pytest.fixture
    def card_processor(self, mock_provider_factory):
        """Create CardProcessor instance with mocked dependencies."""
        processor = CardProcessor(
            provider_factory=mock_provider_factory,
            min_card_percent=5,
            max_card_percent=40,
        )
        return processor

    def test_init(self, mock_provider_factory):
        """Test CardProcessor initialization."""
        processor = CardProcessor(provider_factory=mock_provider_factory)
        assert processor.provider_factory == mock_provider_factory
        assert processor.qr_preprocessing_variants == 5

    # ─── Detect Cards Tests ───

    def test_detect_cards_single_card(self, card_processor, sample_business_card_image):
        """Test detecting single card mode."""
        cards = card_processor.detect_cards(
            sample_business_card_image, detection_mode="Manual - Single Card"
        )

        assert len(cards) == 1
        assert cards[0][0].shape == sample_business_card_image.shape

    @pytest.mark.parametrize(
        "mode", ["Single Card", "single", "manual - single card", "SINGLE CARD"]
    )
    def test_detect_cards_single_card_string_variants(
        self, card_processor, sample_business_card_image, mode
    ):
        """The server sends 'Single Card' (not 'Manual - Single Card'); all
        single-card spellings must yield exactly one region. Regression for
        the bug where 'Single Card' fell through to Automatic detection and
        split a card's QR code into a second spurious card."""
        cards = card_processor.detect_cards(sample_business_card_image, detection_mode=mode)
        assert len(cards) == 1
        assert cards[0][0].shape == sample_business_card_image.shape

    def test_detect_cards_grid_2x2(self, card_processor, sample_business_card_image):
        """Test detecting cards in 2x2 grid."""
        cards = card_processor.detect_cards(
            sample_business_card_image,
            detection_mode="Manual - Grid Layout",
            grid_rows=2,
            grid_cols=2,
        )

        assert len(cards) == 4

    def test_detect_cards_grid_with_margins(self, card_processor, sample_business_card_image):
        """Test grid detection with margins."""
        cards = card_processor.detect_cards(
            sample_business_card_image,
            detection_mode="Manual - Grid Layout",
            grid_rows=2,
            grid_cols=2,
            margin_top=10,
            margin_bottom=10,
        )

        assert len(cards) == 4

    def test_detect_cards_automatic(self, card_processor, sample_business_card_image):
        """Test automatic card detection."""
        # Test that automatic mode calls the detector
        cards = card_processor.detect_cards(sample_business_card_image, detection_mode="Automatic")

        # Should return a list of cards
        assert isinstance(cards, list)
        assert len(cards) > 0

    # ─── Extract Contact Tests ───

    def test_extract_contact_from_qr(
        self, card_processor, sample_business_card_image, sample_qr_data
    ):
        """Test contact extraction from QR code with sufficient data."""
        with patch.object(card_processor.qr_reader, "detect_and_decode") as mock_qr_detect:
            with patch.object(card_processor.qr_reader, "extract_contact_info") as mock_qr_extract:
                mock_qr_detect.return_value = [{"parsed": sample_qr_data}]
                mock_qr_extract.return_value = sample_qr_data

                contact, via_qr = card_processor.extract_contact(sample_business_card_image)

                assert contact is not None
                assert via_qr is True
                assert "email" in contact
                assert contact["email"] == "alice@marketing.com"

    def test_extract_contact_from_vision_fallback(self, card_processor, sample_business_card_image):
        """Test contact extraction falls back to vision when QR insufficient."""
        with patch.object(card_processor.qr_reader, "detect_and_decode") as mock_qr_detect:
            # Return QR data without email
            mock_qr_detect.return_value = None

            contact, via_qr = card_processor.extract_contact(sample_business_card_image)

            assert contact is not None
            assert via_qr is False
            assert "email" in contact  # Should have extracted via vision

    def test_extract_contact_no_data(self, card_processor, sample_business_card_image):
        """Test extraction failure with no detectable data."""
        with patch.object(card_processor.provider_factory, "extract_with_fallback") as mock_extract:
            with patch.object(card_processor.qr_reader, "detect_and_decode") as mock_qr:
                mock_qr.return_value = None
                mock_extract.return_value = ScanResult(
                    contact=None, provider_used=None, error="Vision failed"
                )

                contact, via_qr = card_processor.extract_contact(sample_business_card_image)

                assert contact is None
                assert via_qr is False

    # ─── Process Single Card Tests ───

    def test_process_single_card_success(
        self, card_processor, sample_business_card_image, sample_contact_info
    ):
        """Test successful single card processing."""
        contact_dict = {
            "firstName": "John",
            "lastName": "Doe",
            "email": "john@example.com",
        }

        with patch.object(card_processor, "extract_contact", return_value=(contact_dict, False)):
            result = card_processor.process_single_card(sample_business_card_image)

            assert result is not None
            assert "filename" in result
            assert "contact_data" in result
            assert "vcf_content" in result
            assert result["contact_data"]["email"] == "john@example.com"
            assert result["via_qr"] is False

    def test_process_single_card_failure(self, card_processor, sample_business_card_image):
        """Test single card processing failure."""
        with patch.object(card_processor, "extract_contact", return_value=(None, False)):
            result = card_processor.process_single_card(sample_business_card_image)

            assert result is None

    # ─── Process Batch Tests ───

    def test_process_batch_single_image(self, card_processor, sample_business_card_image):
        """Test batch processing with single image."""
        with patch.object(card_processor, "detect_cards") as mock_detect:
            with patch.object(card_processor, "process_single_card") as mock_process:
                mock_detect.return_value = [(sample_business_card_image, None)]
                mock_process.return_value = {
                    "filename": "test.vcf",
                    "contact_data": {"email": "test@example.com"},
                    "vcf_content": "VCF_CONTENT",
                }

                results = card_processor.process_batch(sample_business_card_image)

                assert len(results) == 1
                assert results[0]["filename"] == "test.vcf"

    def test_process_batch_multiple_cards(self, card_processor, sample_business_card_image):
        """Test batch processing with multiple cards."""
        with patch.object(card_processor, "detect_cards") as mock_detect:
            with patch.object(card_processor, "process_single_card") as mock_process:
                # Return 3 cards
                mock_detect.return_value = [
                    (sample_business_card_image, None),
                    (sample_business_card_image, None),
                    (sample_business_card_image, None),
                ]

                # Two succeed, one fails
                mock_process.side_effect = [
                    {
                        "filename": "card1.vcf",
                        "contact_data": {"email": "user1@example.com"},
                        "vcf_content": "",
                    },
                    None,  # Failure
                    {
                        "filename": "card3.vcf",
                        "contact_data": {"email": "user3@example.com"},
                        "vcf_content": "",
                    },
                ]

                results = card_processor.process_batch(sample_business_card_image)

                assert len(results) == 2  # Only successful cards
                assert results[0]["filename"] == "card1.vcf"
                assert results[1]["filename"] == "card3.vcf"

    def test_process_batch_grid_mode(self, card_processor, sample_business_card_image):
        """Test batch processing with grid layout mode."""
        # Test that grid mode works
        with patch.object(card_processor, "process_single_card") as mock_process:
            mock_process.return_value = {
                "filename": "test.vcf",
                "contact_data": {"email": "test@example.com"},
                "vcf_content": "",
            }

            results = card_processor.process_batch(
                sample_business_card_image,
                detection_mode="Manual - Grid Layout",
                grid_rows=2,
                grid_cols=2,
            )

            # Should have processed cards
            assert len(results) > 0
