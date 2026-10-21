"""
Regression tests for the card-detection fallback rules (v2.1.38).

Background: an audit over 95 archived originals showed every single-card
phone photo being tiled into 4-8 junk regions by "infer a grid when fewer
than 4 contours are found" rules at three layers (card_processor,
ImprovedCardDetector gap-grid, ImprovedCardDetector uniform-grid), plus the
server's gap-overlay path emitting inter-card gutters as ~80px slivers.

Synthetic images are used so the tests are deterministic and shippable.
"""

import numpy as np
import pytest
from unittest.mock import MagicMock

from utils.improved_card_detector import ImprovedCardDetector
from utils.card_processor import CardProcessor


def _card(canvas, x, y, w, h):
    """Draw a white card with a dark border on the canvas (BGR)."""
    canvas[y : y + h, x : x + w] = 255
    import cv2

    cv2.rectangle(canvas, (x, y), (x + w - 1, y + h - 1), (20, 20, 20), 6)
    # A couple of "text" lines so the cell isn't flagged blank.
    cv2.rectangle(canvas, (x + 40, y + 40), (x + w - 40, y + 60), (60, 60, 60), -1)
    cv2.rectangle(canvas, (x + 40, y + h - 80), (x + w // 2, y + h - 60), (60, 60, 60), -1)


def _single_card_photo():
    """One landscape card centred on a grey background — a phone photo."""
    img = np.full((2000, 1500, 3), 140, dtype=np.uint8)
    _card(img, 250, 500, 1000, 600)
    return img


def _sheet_2x4():
    """Eight cards in a 2-column x 4-row grid with gutters — a scanned sheet."""
    img = np.full((2200, 1700, 3), 235, dtype=np.uint8)
    for r in range(4):
        for c in range(2):
            _card(img, 100 + c * 800, 100 + r * 500, 700, 420)
    return img


@pytest.fixture
def detector():
    return ImprovedCardDetector()


@pytest.fixture
def processor():
    return CardProcessor(provider_factory=MagicMock())


class TestSingleCardNotExploded:
    def test_detector_returns_one_region(self, detector):
        regions = detector.detect_cards(_single_card_photo())
        assert len(regions) == 1

    def test_processor_automatic_returns_one(self, processor):
        regions = processor.detect_cards(_single_card_photo(), "Automatic")
        assert len(regions) == 1

    def test_blank_image_is_whole_image_not_grid(self, processor):
        # Zero contours must NOT become an inferred 4x2 / 2x4 grid.
        blank = np.full((2000, 1500, 3), 140, dtype=np.uint8)
        regions = processor.detect_cards(blank, "Automatic")
        assert len(regions) == 1
        assert regions[0][0].shape[:2] == blank.shape[:2]


class TestSheetsStillDetected:
    def test_2x4_sheet_yields_eight(self, detector):
        regions = detector.detect_cards(_sheet_2x4())
        assert len(regions) == 8


class TestOverlayPath:
    """server._gap_detect_and_regularize + the >=4 override gate."""

    def test_two_stacked_cards_no_sliver_and_no_override(self):
        import server

        img = np.full((2400, 1500, 3), 140, dtype=np.uint8)
        _card(img, 250, 200, 1000, 600)
        _card(img, 250, 1400, 1000, 600)
        rects = server._gap_detect_and_regularize(img)
        if rects:
            heights = [h for _, _, _, h in rects]
            med = float(np.median(heights))
            # The relative sliver filter guarantees no tile under 30% of median.
            assert all(h >= 0.3 * med for h in heights)
        # A 2-3 tile gap result must never out-vote the detector.
        assert len(rects) < 4

    def test_preview_two_stacked_cards_draws_two_no_grid_banner(self):
        """The /api/preview path used to carry its OWN copy of the gap
        overlay logic, so server-side fixes never reached it: two stacked
        cards previewed as three (a ~20px gutter drawn as a card) plus a
        bogus 'Apply 3x1 grid' banner. It now calls the shared function."""
        import server

        img = np.full((2400, 1500, 3), 140, dtype=np.uint8)
        _card(img, 250, 200, 1000, 600)
        _card(img, 250, 1400, 1000, 600)
        _jpg, count, _lines, inferred_grid = server._annotate_image(img, "auto", 2, 2)
        assert count == 2
        assert inferred_grid is None  # 1-3 regions never trigger the banner


class TestContoursInOriginalCoordinates:
    def test_sheet_contours_span_full_resolution_frame(self, detector):
        """Contours used to come back in the 500px-high working frame, so the
        preview drew 7 correct cards as 7 tiny boxes in the top-left corner."""
        import cv2

        img = _sheet_2x4()  # 2200 x 1700
        regions = detector.detect_cards(img)
        polys = [c for _, c in regions if c is not None]
        assert len(polys) == 8
        xs = [cv2.boundingRect(c)[0] + cv2.boundingRect(c)[2] for c in polys]
        ys = [cv2.boundingRect(c)[1] + cv2.boundingRect(c)[3] for c in polys]
        assert max(xs) > 1500 and max(ys) > 1900  # bottom-right card lands where drawn
        assert min(cv2.boundingRect(c)[0] for c in polys) >= 90  # left column near x=100
