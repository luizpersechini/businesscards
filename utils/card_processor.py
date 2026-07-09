"""
Core card processing pipeline for Business Card Scanner.
Orchestrates card detection, QR reading, and vision-based contact extraction.
"""

import cv2
import numpy as np
from typing import Callable, Dict, List, Optional, Tuple
import logging

from utils.improved_card_detector import ImprovedCardDetector
from utils.qr_reader import QRReader
from utils.providers.factory import ProviderFactory
from utils.vcf_generator import VCFGenerator
from utils.ui_components import (
    qr_data_is_sufficient,
    qr_to_contact_data,
    split_image_grid,
)

logger = logging.getLogger(__name__)


class CardProcessor:
    """
    Orchestrates the card processing pipeline:
    1. Image upload
    2. Card detection
    3. QR code reading
    4. Contact extraction (QR or vision)
    5. VCF generation
    """

    def __init__(
        self,
        provider_factory: ProviderFactory,
        min_card_percent: int = 5,
        max_card_percent: int = 40,
        qr_preprocessing_variants: int = 5,
    ):
        """
        Initialize card processor.

        Args:
            provider_factory: ProviderFactory instance
            min_card_percent: Minimum card area as percentage
            max_card_percent: Maximum card area as percentage
            qr_preprocessing_variants: Number of QR preprocessing attempts
        """
        self.provider_factory = provider_factory
        self.detector = ImprovedCardDetector(
            min_area_percent=min_card_percent,
            max_area_percent=max_card_percent,
        )
        self.qr_reader = QRReader()
        self.vcf_generator = VCFGenerator()
        self.qr_preprocessing_variants = qr_preprocessing_variants

    def detect_cards(
        self,
        image_bgr: np.ndarray,
        detection_mode: str = "Automatic",
        grid_rows: int = 2,
        grid_cols: int = 2,
        margin_top: int = 0,
        margin_bottom: int = 0,
        margin_left: int = 0,
        margin_right: int = 0,
    ) -> List[Tuple[np.ndarray, Optional[np.ndarray]]]:
        """
        Detect business cards in image using specified mode.

        Args:
            image_bgr: Input image in BGR format
            detection_mode: "Automatic", "Manual - Single Card", or "Manual - Grid Layout"
            grid_rows: Rows for grid mode
            grid_cols: Columns for grid mode
            margin_top: Top margin percentage for grid mode
            margin_bottom: Bottom margin percentage for grid mode
            margin_left: Left margin percentage for grid mode
            margin_right: Right margin percentage for grid mode

        Returns:
            List of (card_image, contour) tuples
        """
        logger.info(f"Detecting cards using mode: {detection_mode}")

        # Normalize the mode string. The server maps the frontend's "single"
        # to "Single Card" and "grid" to "Manual - Grid Layout", but older
        # code paths use "Manual - Single Card". Accept all spellings so a
        # mismatch can't silently fall through to Automatic — which would
        # split a single card (e.g. its QR code) into multiple regions.
        _mode = (detection_mode or "").strip().lower()

        if _mode in ("manual - single card", "single card", "single"):
            logger.info("Processing entire image as single card")
            return [(image_bgr, None)]

        elif _mode in (
            "manual - grid layout",
            "grid layout",
            "grid",
            "manual - grid",
        ):
            logger.info(f"Splitting into {grid_rows}x{grid_cols} grid")
            cards = split_image_grid(
                image_bgr,
                grid_rows,
                grid_cols,
                margin_top,
                margin_bottom,
                margin_left,
                margin_right,
            )
            logger.info(f"Split into {len(cards)} cards from grid")
            return cards

        elif _mode in ("automatic", "auto", ""):
            logger.info("Running automatic card detection")
            detected_cards = self.detector.detect_cards(image_bgr)

            # Grid-layout fallback: if auto-detection found very few cards
            if len(detected_cards) < 4:
                h_img, w_img = image_bgr.shape[:2]
                aspect = w_img / h_img if h_img > 0 else 1.0

                # Infer grid from aspect ratio
                if aspect < 1.4:
                    inferred_rows, inferred_cols = 4, 2
                else:
                    inferred_rows, inferred_cols = 2, 4

                grid_cards = split_image_grid(image_bgr, inferred_rows, inferred_cols)
                if len(grid_cards) > len(detected_cards):
                    logger.info(
                        f"Fallback to {inferred_rows}x{inferred_cols} grid layout "
                        f"(aspect ratio: {aspect:.2f})"
                    )
                    return grid_cards

            logger.info(f"Detected {len(detected_cards)} cards")
            return detected_cards

        else:
            logger.warning(f"Unknown detection mode: {detection_mode}, defaulting to Automatic")
            return self.detector.detect_cards(image_bgr)

    def extract_contact(
        self,
        card_image_bgr: np.ndarray,
        vision_model: str = "qwen2.5vl:7b",
        vision_timeout: int = 300,
    ) -> tuple:
        """
        Extract contact information from a single card image.
        Implements QR-first strategy: if QR has sufficient data, skip vision.

        Args:
            card_image_bgr: Card image in BGR format
            vision_model: Vision model name
            vision_timeout: Vision processing timeout in seconds

        Returns:
            Tuple of (contact_data_dict_or_None, via_qr: bool|str)
            via_qr values: True = QR-only, "hybrid" = QR+vision, False = vision-only
        """
        logger.info("Starting contact extraction")
        contact_data = {}
        via_qr = False

        # Step 1: QR Code detection
        logger.info("Attempting QR code detection")
        qr_data = None
        try:
            qr_results = self.qr_reader.detect_and_decode(card_image_bgr)
            if qr_results:
                logger.info(f"Found {len(qr_results)} QR code(s)")
                qr_data = self.qr_reader.extract_contact_info(qr_results)
                logger.debug(f"QR data fields: {list(qr_data.keys())}")
            else:
                logger.info("No QR codes detected")
        except Exception as e:
            logger.warning(f"QR code reading failed: {e}")

        # Capture any URL the QR encodes so the UI can offer to fetch the
        # linked contact page on demand. We deliberately do NOT fetch here —
        # resolution is user-initiated via POST /api/resolve-qr-url so no
        # network request is made during an unattended scan.
        qr_pending_url = None
        if qr_data:
            cand = qr_data.get("url")
            if isinstance(cand, str) and cand.strip().lower().startswith(("http://", "https://")):
                qr_pending_url = cand.strip()

        # Step 2: Check if QR data is sufficient
        if qr_data_is_sufficient(qr_data):
            logger.info(
                "QR code has sufficient data — skipping vision. "
                "Fields: name=%s, email=%s, phones=%s, org=%s",
                qr_data.get("full_name") or qr_data.get("first_name", ""),
                qr_data.get("email") or qr_data.get("emails", []),
                qr_data.get("phones", []),
                qr_data.get("organization", ""),
            )
            contact_data = qr_to_contact_data(qr_data)
            via_qr = True
            try:
                from utils.providers.base import (
                    demote_title_misplaced_as_name,
                    fix_field_permutations,
                    repair_cjk_substitutions,
                    strip_prompt_echoes,
                )

                contact_data = repair_cjk_substitutions(contact_data)
                contact_data = strip_prompt_echoes(contact_data)
                contact_data = fix_field_permutations(contact_data)
                contact_data = demote_title_misplaced_as_name(contact_data)
            except Exception as e:
                logger.warning(f"CJK repair failed (non-fatal): {e}")
            if qr_pending_url:
                contact_data["_qr_url"] = qr_pending_url
            return contact_data, via_qr

        if qr_data:
            logger.info(
                "QR data present but insufficient for skip — running vision. "
                "QR fields: name=%s, email=%s, phones=%s, org=%s",
                qr_data.get("full_name") or qr_data.get("first_name", ""),
                qr_data.get("email") or qr_data.get("emails", []),
                qr_data.get("phones", []),
                qr_data.get("organization", ""),
            )

        # Step 3: Vision analysis
        logger.info(f"Running vision analysis (model: {vision_model}, timeout: {vision_timeout}s)")
        try:
            scan_result = self.provider_factory.extract_with_fallback(
                card_image_bgr, qr_data, timeout=vision_timeout, model=vision_model
            )

            if scan_result.contact and scan_result.contact.has_minimum_data():
                contact_data = scan_result.contact.to_legacy_dict()
                via_qr = "hybrid" if qr_data else False
                logger.info(
                    "Vision analysis successful%s", " (QR hybrid)" if via_qr == "hybrid" else ""
                )
            else:
                error_msg = scan_result.error or "Unknown vision error"
                logger.error(f"Vision analysis failed: {error_msg}")

                # Fallback to QR data if available (even without email)
                if qr_data:
                    logger.info("Falling back to QR code data")
                    contact_data = qr_to_contact_data(qr_data)
                    via_qr = True
                else:
                    logger.error("No QR data available for fallback")
                    return None, False

        except Exception as e:
            logger.error(f"Vision processing exception: {e}")

            # Fallback to QR data
            if qr_data:
                logger.info("Falling back to QR code data due to exception")
                contact_data = qr_to_contact_data(qr_data)
                via_qr = True
            else:
                logger.error("No QR data available for fallback")
                return None, False

        if not contact_data or "error" in contact_data:
            logger.error("No valid contact data extracted")
            return None, False

        # CJK→Latin repair: covers all paths (QR-only, vision, hybrid).
        # Some vision models (GLM-OCR) substitute accented Latin chars
        # with visually-similar CJK ideographs; this repair maps them back.
        try:
            from utils.providers.base import (
                demote_title_misplaced_as_name,
                fix_field_permutations,
                repair_cjk_substitutions,
                strip_prompt_echoes,
            )

            contact_data = repair_cjk_substitutions(contact_data)
            contact_data = strip_prompt_echoes(contact_data)
            contact_data = fix_field_permutations(contact_data)
            contact_data = demote_title_misplaced_as_name(contact_data)
        except Exception as e:
            logger.warning(f"CJK repair failed (non-fatal): {e}")

        if qr_pending_url:
            contact_data["_qr_url"] = qr_pending_url

        return contact_data, via_qr

    def process_single_card(
        self,
        card_image_bgr: np.ndarray,
        card_image_rgb: Optional[np.ndarray] = None,
        vision_model: str = "qwen2.5vl:7b",
        vision_timeout: int = 300,
    ) -> Optional[Dict]:
        """
        Process a single card: extract contact and generate VCF.

        Args:
            card_image_bgr: Card image in BGR format
            card_image_rgb: Optional RGB version for storage
            vision_model: Vision model name
            vision_timeout: Vision processing timeout

        Returns:
            Dictionary with filename, contact_data, and vcf_content, or None if failed
        """
        logger.info("Processing single card")

        # Extract contact
        contact_data, via_qr = self.extract_contact(card_image_bgr, vision_model, vision_timeout)
        if not contact_data:
            logger.error("Failed to extract contact")
            return None

        # Generate VCF
        try:
            vcf_string = self.vcf_generator.generate_vcf_string(contact_data)
            filename = self.vcf_generator.contact_to_filename(contact_data)
            logger.info(f"Generated VCF: {filename}")

            return {
                "filename": filename,
                "contact_data": contact_data,
                "vcf_content": vcf_string,
                "card_image": card_image_rgb,
                "via_qr": via_qr,
            }
        except Exception as e:
            logger.error(f"VCF generation failed: {e}")
            return None

    def process_batch(
        self,
        image_bgr: np.ndarray,
        image_rgb: Optional[np.ndarray] = None,
        detection_mode: str = "Automatic",
        vision_model: str = "qwen2.5vl:7b",
        vision_timeout: int = 300,
        grid_rows: int = 2,
        grid_cols: int = 2,
        margin_top: int = 0,
        margin_bottom: int = 0,
        margin_left: int = 0,
        margin_right: int = 0,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[Dict]:
        """
        Process all cards in an image.

        Args:
            image_bgr: Input image in BGR format
            image_rgb: Optional RGB version for display
            detection_mode: Card detection mode
            vision_model: Vision model name
            vision_timeout: Vision processing timeout
            grid_rows: Grid rows for manual grid mode
            grid_cols: Grid columns for manual grid mode
            margin_top: Top margin percentage
            margin_bottom: Bottom margin percentage
            margin_left: Left margin percentage
            margin_right: Right margin percentage

        Returns:
            List of processed card dictionaries
        """
        logger.info("Starting batch processing")

        # Detect cards
        detected_cards = self.detect_cards(
            image_bgr,
            detection_mode,
            grid_rows,
            grid_cols,
            margin_top,
            margin_bottom,
            margin_left,
            margin_right,
        )
        logger.info(f"Detected {len(detected_cards)} cards to process")

        # Process each card
        processed_cards = []
        for card_idx, (card_image_bgr, contour) in enumerate(detected_cards):
            if cancel_check and cancel_check():
                logger.info(
                    f"Cancellation requested — stopping batch at card "
                    f"{card_idx + 1}/{len(detected_cards)}"
                )
                break
            logger.info(f"Processing card {card_idx + 1}/{len(detected_cards)}")

            # Convert to RGB for storage
            card_rgb = cv2.cvtColor(card_image_bgr, cv2.COLOR_BGR2RGB)

            # Process card
            result = self.process_single_card(
                card_image_bgr,
                card_rgb,
                vision_model,
                vision_timeout,
            )

            if result:
                processed_cards.append(result)
                logger.info(f"✓ Card {card_idx + 1} processed successfully")
            else:
                logger.warning(f"✗ Card {card_idx + 1} processing failed")

        logger.info(
            f"Batch processing complete: {len(processed_cards)}/{len(detected_cards)} succeeded"
        )
        return processed_cards
