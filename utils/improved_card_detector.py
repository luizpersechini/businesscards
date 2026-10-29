"""
Improved Card Detector Module
Uses document scanner techniques for better card detection.
Based on industry best practices from PyImageSearch and OpenCV documentation.
"""

import cv2
import numpy as np
from typing import List, Tuple
import imutils

# Strategy F (lattice completion) tunables — see _complete_lattice.
MIN_LATTICE_CARDS = 4  # need this many found cards to trust a lattice
LATTICE_TOL = 0.4  # row/col clustering tolerance, fraction of median card size
LATTICE_SNAP_FRACTION = 0.75  # a box under this fraction of median area hugged text
LATTICE_MIN_INK = 0.004  # absolute ink floor for an empty cell to count as a card
LATTICE_INK_RATIO = 0.4  # ...or this fraction of the least-inked found card
LATTICE_BRIGHTNESS_TOL = 60  # empty cell must be about as bright as the found cards


class ImprovedCardDetector:
    """
    Enhanced card detector using document scanner algorithms.
    """

    def __init__(self, min_area_percent=2, max_area_percent=40):
        """
        Initialize the improved card detector.

        Args:
            min_area_percent: Minimum area as percentage of image (default 2%)
            max_area_percent: Maximum area as percentage of image (default 40%)
        """
        self.min_area_percent = min_area_percent
        self.max_area_percent = max_area_percent

    def detect_cards(self, image: np.ndarray) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Detect business cards using advanced document scanning techniques.
        Filters out QR codes and logos.

        Uses multiple edge-detection strategies tried sequentially on the
        contrast-enhanced image so that clean PDF scans and noisy photos
        are both handled well.

        Args:
            image: Input image as numpy array (BGR format)

        Returns:
            List of tuples (card_image, contour) for each detected cards
        """
        original = image.copy()
        orig_height, orig_width = image.shape[:2]
        image_area = orig_height * orig_width

        # Calculate area thresholds based on percentage
        min_area = int(image_area * (self.min_area_percent / 100))
        max_area = int(image_area * (self.max_area_percent / 100))

        # Resize for better processing
        ratio = image.shape[0] / 500.0
        resized = imutils.resize(image, height=500)
        resized_area = resized.shape[0] * resized.shape[1]

        # Scale area thresholds for resized image
        min_area_resized = int(min_area / (ratio * ratio))
        max_area_resized = int(max_area / (ratio * ratio))

        # Convert to grayscale
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

        # ── Contrast enhancement (crucial for clean PDF / white-on-white scans) ──
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)

        # Apply Gaussian blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # ── Multi-strategy edge detection ──────────────────────────────────
        # Try each strategy independently and take the best result (most cards).
        # This is critical because combining them with bitwise_or produces
        # too much noise on clean scans while missing faint card edges.

        strategies = [
            # Strategy A: Canny with lower thresholds (good for faint edges on clean scans)
            ("canny_low", cv2.Canny(blurred, 20, 80)),
            # Strategy B: Canny with standard thresholds
            ("canny_mid", cv2.Canny(blurred, 40, 120)),
            # Strategy C: Canny with higher thresholds (fewer false positives)
            ("canny_high", cv2.Canny(blurred, 60, 150)),
            # Strategy D: Adaptive threshold (excellent for grid lines on clean scans)
            (
                "adaptive",
                cv2.adaptiveThreshold(
                    blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 3
                ),
            ),
        ]

        # Dilate/erode kernel — larger for clean scans to bridge thin gaps
        kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        kernel_med = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))

        best_cards: List[Tuple[np.ndarray, np.ndarray]] = []

        for _strat_name, edge_map in strategies:
            # Morphological close to bridge small gaps in edges
            closed = cv2.morphologyEx(edge_map, cv2.MORPH_CLOSE, kernel_med, iterations=1)
            # Dilate to thicken edges, then erode to reduce noise
            dilated = cv2.dilate(closed, kernel_small, iterations=1)
            eroded = cv2.erode(dilated, kernel_small, iterations=1)

            cards = self._contours_to_cards(
                eroded, original, resized, ratio, min_area_resized, max_area_resized
            )
            if len(cards) > len(best_cards):
                best_cards = cards

        # Strategy E: bright blobs. Light cards on a dark desk/table — the
        # commonest phone-photo setup — defeat every edge strategy above
        # (the desk texture drowns Canny; CLAHE amplifies it) yet are a
        # trivial brightness threshold: each card is one bright blob. On
        # a white scan the mask is one page-sized blob that fails the
        # max-area gate, so this never competes there. (IMG_4507: 0 edge
        # contours -> blind 4x2 split with 6 blank tiles; this finds 2/2.)
        blob_cards = self._bright_blob_cards(
            resized, original, ratio, min_area_resized, max_area_resized
        )
        # A filled bright blob with card aspect IS the card — unlike edge
        # contours it can't be a crease or a printed rule — so a blob
        # result is confident and the blind uniform split must not
        # out-vote it (it was turning IMG_4507's 2 cards into 8 tiles).
        blob_confident = False
        if blob_cards and len(blob_cards) >= len(best_cards):
            # Ties go to the blobs: their crops are the whole card, where
            # an edge contour may stop at a printed rule or shadow.
            best_cards = blob_cards
            blob_confident = True

        detected_cards = best_cards

        # Strategy F: lattice completion. On a sheet photo the cards that
        # WERE found reveal the layout (row/column centres + median card
        # size). A white card on a white desk has no edge at all, so no
        # strategy above can see it — but the lattice cell it sits in is
        # known, and ink in that cell means a card. (IMG_4675: 12 -> 15,
        # IMG_1544: 14 -> 18, IMG_8943: 13 -> 15.) Also snaps a box that
        # only hugged the text back to its full cell.
        if len(detected_cards) >= MIN_LATTICE_CARDS:
            detected_cards = self._complete_lattice(original, detected_cards)

        # ── Fallbacks ──────────────────────────────────────────────────────
        # If contour detection found fewer than 4 cards, try edge-density
        # grid detection.
        # A tiling may only replace contour results when it looks like a
        # real sheet (>= 4 tiles). Accepting any tiling that merely had
        # "more" pieces split every single-card phone photo into 2-8 junk
        # regions (audit over 95 archived originals: IMG_1658 -> 8,
        # IMG_2525 -> 4, IMG_2628 -> 7, all identical aspects). A 1-3
        # tile result is a crease/shadow false split, not a layout.
        MIN_SHEET_TILES = 4
        H, W = original.shape[:2]
        edge_confident_single = False

        def _plausible_sheet(tiles) -> bool:
            """A tiling is a real card sheet only if it has >= 4 tiles AND
            the tiles don't span the whole frame. Tiles that run the full
            image width (or height) are 1-D strips of ONE card cut along
            its printed rules/shadows — a real sheet photo always has
            margins/gutters, so its tiles never span the frame
            (IMG_2525: 4 strips 2302 wide on a 2302 px image; IMG_8943:
            5 strips at full width; IMG_2628: 7 full-height columns)."""
            if len(tiles) < MIN_SHEET_TILES:
                return False
            full_span = sum(1 for t, _ in tiles if t.shape[1] >= 0.97 * W or t.shape[0] >= 0.97 * H)
            return full_span < 0.5 * len(tiles)

        if len(detected_cards) < MIN_SHEET_TILES:
            grid_cards = self._detect_grid_by_gaps(original)
            # Gap detection is EDGE-derived, so a result of exactly 1 is a
            # confident "one card, here are its bounds" — on every
            # single-card photo in the audit it returned the correct crop
            # (IMG_2525 1944x1410, IMG_8943 2838x2102, IMG_2628 1719x999)
            # and must win. 2-3 tiles is the crease false-split; >= 4 must
            # pass the sheet check.
            # Also when contours found a lone (often spurious) region: gap
            # and contour agree it's one card, and the gap crop is the
            # real boundary (IMG_2525: 1 contour + gap 1944x1410).
            if len(grid_cards) == 1 and len(detected_cards) <= 1:
                detected_cards = grid_cards
                edge_confident_single = True
            elif _plausible_sheet(grid_cards) and len(grid_cards) > len(detected_cards):
                detected_cards = grid_cards

        # Last resort: uniform grid split, but filter blank cells. This is
        # BLIND (no edge evidence). It legitimately recovers scanned sheets
        # where contours under-find (Steinweg p1: 3 contours -> 8 cards),
        # so it still runs on low counts — but it must never out-vote a
        # confident edge-derived single card (it was chopping one card
        # into 4-7 half-width cells).
        if (
            len(detected_cards) < MIN_SHEET_TILES
            and not edge_confident_single
            and not blob_confident
        ):
            uniform_cards = self._uniform_grid_split(original)
            # Filter cells that are mostly blank (plain white/black background)
            filtered_uniform = [
                (cell, None) for cell, _ in uniform_cards if not _is_blank_cell(cell)
            ]
            if _plausible_sheet(filtered_uniform) and len(filtered_uniform) > len(detected_cards):
                detected_cards = filtered_uniform

        # If no cards found, try simpler bounding box fallback
        if len(detected_cards) == 0:
            detected_cards = self._fallback_detection(original)

        # If still nothing, return whole image
        if len(detected_cards) == 0:
            detected_cards.append((original, None))

        return detected_cards

    def _complete_lattice(
        self, original: np.ndarray, cards: List[Tuple[np.ndarray, np.ndarray]]
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Fill empty cells of the grid the detected cards form (Strategy F).

        Rows and columns are 1-D clusters of the card centres; the cell size
        is the median card. An empty cell is accepted as a card when it has
        ink (adaptive-threshold mask) above a floor derived from the least
        inked card already found — a blank patch of desk is not a card. A
        found card whose box is < LATTICE_SNAP_FRACTION of the median area
        hugged its text rather than its edge and is snapped to its cell.
        Cards outside any lattice logic (irregular layouts) are untouched;
        a lattice with more than twice as many cells as cards is not
        believed at all.
        """
        H, W = original.shape[:2]
        boxes = [cv2.boundingRect(cnt) for _, cnt in cards if cnt is not None]
        if len(boxes) < MIN_LATTICE_CARDS:
            return cards
        mw = float(np.median([b[2] for b in boxes]))
        mh = float(np.median([b[3] for b in boxes]))
        if mw <= 0 or mh <= 0:
            return cards

        def _cluster(vals: List[float], tol: float) -> List[float]:
            vals = sorted(vals)
            groups: List[List[float]] = [[vals[0]]]
            for v in vals[1:]:
                if v - float(np.mean(groups[-1])) <= tol:
                    groups[-1].append(v)
                else:
                    groups.append([v])
            return [float(np.mean(g)) for g in groups]

        cols = _cluster([b[0] + b[2] / 2 for b in boxes], LATTICE_TOL * mw)
        rows = _cluster([b[1] + b[3] / 2 for b in boxes], LATTICE_TOL * mh)
        if len(rows) * len(cols) > 2 * len(boxes):
            return cards

        gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
        ink = cv2.adaptiveThreshold(
            cv2.GaussianBlur(gray, (5, 5), 0),
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            31,
            15,
        )
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))

        def _ink_fraction(x: float, y: float, w: float, h: float) -> float:
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(W, int(x + w)), min(H, int(y + h))
            if x2 <= x1 or y2 <= y1:
                return 0.0
            return float(ink[y1:y2, x1:x2].mean()) / 255.0

        def _cell(cx: float, cy: float):
            x1, y1 = int(max(0, cx - mw / 2)), int(max(0, cy - mh / 2))
            x2, y2 = int(min(W, cx + mw / 2)), int(min(H, cy + mh / 2))
            quad = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=np.int32)
            return original[y1:y2, x1:x2].copy(), quad.reshape(-1, 1, 2)

        # Snap text-hugging boxes to their cell.
        out: List[Tuple[np.ndarray, np.ndarray]] = []
        for (crop, cnt), b in zip([c for c in cards if c[1] is not None], boxes):
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            if b[2] * b[3] < LATTICE_SNAP_FRACTION * mw * mh:
                r = min(rows, key=lambda v: abs(v - cy))
                c = min(cols, key=lambda v: abs(v - cx))
                out.append(_cell(c, r))
            else:
                out.append((crop, cnt))
        out.extend(c for c in cards if c[1] is None)

        found_ink = [_ink_fraction(*b) for b in boxes]
        threshold = max(LATTICE_MIN_INK, LATTICE_INK_RATIO * min(found_ink))

        def _mean_gray(x: float, y: float, w: float, h: float) -> float:
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(W, int(x + w)), min(H, int(y + h))
            return float(gray[y1:y2, x1:x2].mean()) if x2 > x1 and y2 > y1 else 0.0

        # A dark textured desk is full of "ink" to an adaptive threshold
        # (IMG_4506: an empty desk cell was accepted). A card cell must
        # also be about as bright as the cards that were found — the
        # whole point is white cards on a white desk.
        card_gray = float(np.median([_mean_gray(*b) for b in boxes]))
        for cy in rows:
            for cx in cols:
                if any(
                    abs(cx - (b[0] + b[2] / 2)) < LATTICE_TOL * mw
                    and abs(cy - (b[1] + b[3] / 2)) < LATTICE_TOL * mh
                    for b in boxes
                ):
                    continue
                x, y = cx - mw / 2, cy - mh / 2
                # A cell must lie (almost) inside the frame.
                if x < -0.1 * mw or y < -0.1 * mh or x + mw > W + 0.1 * mw or y + mh > H + 0.1 * mh:
                    continue
                if abs(_mean_gray(x, y, mw, mh) - card_gray) > LATTICE_BRIGHTNESS_TOL:
                    continue
                if _ink_fraction(x, y, mw, mh) >= threshold:
                    out.append(_cell(cx, cy))
        return out

    def _bright_blob_cards(
        self,
        resized: np.ndarray,
        original: np.ndarray,
        ratio: float,
        min_area_resized: int,
        max_area_resized: int,
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Light cards on a dark background as filled blobs (see Strategy E)."""
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        # Only meaningful when the background is darker than the cards:
        # require a genuinely bimodal frame (Otsu threshold not near white).
        thresh_val, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if thresh_val > 200 or mask.mean() > 0.6 * 255:
            return []
        # Desk glare sits between the dark desk and the white card, and a
        # single Otsu cut lumps it with the cards (IMG_4507: blobs grew
        # into tall glare-shaped lumps). A second Otsu over the bright
        # class alone separates "lit desk" from "paper" when they're
        # distinct; use it only when it moves the cut meaningfully.
        bright = blurred[blurred > thresh_val]
        if bright.size > 100:
            t2, _ = cv2.threshold(
                bright.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            if t2 - thresh_val > 25:
                _, mask = cv2.threshold(blurred, t2, 255, cv2.THRESH_BINARY)
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        kernel_small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        # Open: erase desk texture speckle. Close: fill printed text holes.
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_open, iterations=2)
        # Slight erosion separates cards that touch along an edge.
        mask = cv2.erode(mask, kernel_small, iterations=1)
        return self._contours_to_cards(
            mask, original, resized, ratio, min_area_resized, max_area_resized
        )

    def _contours_to_cards(
        self,
        edge_image: np.ndarray,
        original: np.ndarray,
        resized: np.ndarray,
        ratio: float,
        min_area_resized: int,
        max_area_resized: int,
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """Extract card regions from a preprocessed edge image via contour analysis."""
        contours = cv2.findContours(edge_image, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = imutils.grab_contours(contours)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        cards: List[Tuple[np.ndarray, np.ndarray]] = []
        used_regions: List[Tuple[int, int, int, int]] = []

        for c in contours[:80]:
            area = cv2.contourArea(c)
            if area < min_area_resized or area > max_area_resized:
                continue

            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)

            if len(approx) < 4 or len(approx) > 8:
                continue

            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = float(w) / h if h > 0 else 0

            if not (1.2 < aspect_ratio < 2.2 or 0.45 < aspect_ratio < 0.85):
                continue

            extent = area / (w * h) if (w * h) > 0 else 0
            if extent < 0.65:
                continue

            # Overlap check
            overlaps = False
            for ux, uy, uw, uh in used_regions:
                x_overlap = max(0, min(x + w, ux + uw) - max(x, ux))
                y_overlap = max(0, min(y + h, uy + uh) - max(y, uy))
                if x_overlap * y_overlap > (w * h * 0.2):
                    overlaps = True
                    break
            if overlaps:
                continue

            # Extract card. A business card is a rectangle, so the region
            # we keep is the contour's minimum-area rectangle, not the raw
            # polygon: an edge contour on a white-on-white photo often hugs
            # the printed text (concave, 5-8 vertices) and the preview drew
            # that as a jagged shape while the crop was a padded bounding
            # box. The min-area rect is the card itself, handles a slight
            # tilt, and is perspective-corrected like a clean 4-point hit.
            quad = cv2.boxPoints(cv2.minAreaRect(c)).astype(np.float32) * ratio
            card_warped = self.four_point_transform(original, quad)

            if card_warped is not None and card_warped.shape[0] > 80 and card_warped.shape[1] > 80:
                # Contours were found on the 500px-high working copy; return
                # the quad in ORIGINAL image coordinates so overlays
                # (preview) line up with the full-resolution crop.
                c_orig = np.rint(quad).astype(np.int32).reshape(-1, 1, 2)
                cards.append((card_warped, c_orig))
                used_regions.append((x, y, w, h))

        return cards

    # ... existing code for four_point_transform, _uniform_grid_split, etc. follows ...

    def _uniform_grid_split(self, image: np.ndarray) -> List[Tuple[np.ndarray, None]]:
        """
        Last-resort fallback: split the image into a uniform grid inferred
        from its aspect ratio.  Works reliably for flatbed scans and phone
        photos of card collections laid on a flat surface.

        Aspect heuristic (mirrors app.py logic):
          portrait  (w/h < 1.4) → 4 rows × 2 cols  (most common layout)
          landscape (w/h ≥ 1.4) → 2 rows × 4 cols
        """
        h, w = image.shape[:2]
        aspect = w / h if h > 0 else 1.0

        if aspect < 1.4:
            rows, cols = 4, 2
        else:
            rows, cols = 2, 4

        cell_h = h // rows
        cell_w = w // cols
        cards: List[Tuple[np.ndarray, None]] = []

        for r in range(rows):
            for c in range(cols):
                y1 = r * cell_h
                y2 = (r + 1) * cell_h if r < rows - 1 else h
                x1 = c * cell_w
                x2 = (c + 1) * cell_w if c < cols - 1 else w
                cell = image[y1:y2, x1:x2]
                if cell.shape[0] > 50 and cell.shape[1] > 50:
                    cards.append((cell, None))

        return cards

    def _fallback_detection(self, image: np.ndarray) -> List[Tuple[np.ndarray, None]]:
        """
        Fallback detection using thresholding.

        Args:
            image: Original image

        Returns:
            List of detected cards
        """
        orig_height, orig_width = image.shape[:2]
        image_area = orig_height * orig_width

        # Calculate area thresholds
        min_area = int(image_area * (self.min_area_percent / 100))
        max_area = int(image_area * (self.max_area_percent / 100))

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        # Use Otsu's thresholding
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        # Morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        detected_cards = []
        used_regions = []

        for contour in contours[:15]:
            area = cv2.contourArea(contour)

            if area < min_area or area > max_area:
                continue

            x, y, w, h = cv2.boundingRect(contour)

            # Check overlap
            overlaps = False
            for used_x, used_y, used_w, used_h in used_regions:
                x_overlap = max(0, min(x + w, used_x + used_w) - max(x, used_x))
                y_overlap = max(0, min(y + h, used_y + used_h) - max(y, used_y))
                overlap_area = x_overlap * y_overlap

                if overlap_area > (w * h * 0.3):
                    overlaps = True
                    break

            if overlaps:
                continue

            # Check aspect ratio - business card specific
            aspect_ratio = float(w) / h if h > 0 else 0
            if not (1.3 < aspect_ratio < 2.0 or 0.5 < aspect_ratio < 0.77):
                continue

            # Check extent (rectangularity)
            extent = area / (w * h) if (w * h) > 0 else 0
            if extent < 0.7:  # Business cards are very rectangular
                continue

            card_image = image[y : y + h, x : x + w]

            if card_image.shape[0] > 50 and card_image.shape[1] > 50:
                detected_cards.append((card_image, None))
                used_regions.append((x, y, w, h))

        return detected_cards

    # ------------------------------------------------------------------
    # Grid detection — designed for flatbed scans of multiple cards
    # ------------------------------------------------------------------

    def _detect_grid_by_gaps(self, image: np.ndarray) -> List[Tuple[np.ndarray, None]]:
        """
        Detect cards in grid layouts by finding horizontal and vertical
        gaps (separators) using edge-density projection.  Works well for
        flatbed scans where several cards are placed side by side.
        """
        h, w = image.shape[:2]

        # Image must be large enough to contain multiple cards
        if h < 400 or w < 400:
            return []

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)

        # --- Horizontal projection (find row separators) ---
        h_proj = np.sum(edges, axis=1).astype(float)
        # Very small smoothing kernel (3px) — just enough to remove
        # single-pixel noise without smearing card-border spikes into gaps.
        h_smooth = np.convolve(h_proj, np.ones(3) / 3, mode="same")
        row_splits = self._find_gap_positions(h_smooth, h, cross_length=w)

        # --- Vertical projection (find column separators) ---
        v_proj = np.sum(edges, axis=0).astype(float)
        v_smooth = np.convolve(v_proj, np.ones(3) / 3, mode="same")
        col_splits = self._find_gap_positions(v_smooth, w, cross_length=h)

        row_bounds = [0] + row_splits + [h]
        col_bounds = [0] + col_splits + [w]

        # Need at least a 2×1 or 1×2 grid
        if len(row_bounds) < 3 and len(col_bounds) < 3:
            return []

        cards: List[Tuple[np.ndarray, None]] = []
        image_area = h * w
        min_cell = image_area * (self.min_area_percent / 100)

        for r in range(len(row_bounds) - 1):
            for c in range(len(col_bounds) - 1):
                y1, y2 = row_bounds[r], row_bounds[r + 1]
                x1, x2 = col_bounds[c], col_bounds[c + 1]

                # Trim a small margin (gap residue / scanner artifacts)
                margin = 8
                y1, y2 = min(y1 + margin, y2), max(y2 - margin, y1 + 1)
                x1, x2 = min(x1 + margin, x2), max(x2 - margin, x1 + 1)

                cell = image[y1:y2, x1:x2]
                cell_h, cell_w = cell.shape[:2]

                if cell_h < 80 or cell_w < 80:
                    continue

                # Basic aspect-ratio sanity (very relaxed — grid cells
                # may be slightly off from standard card proportions)
                aspect = cell_w / cell_h
                if not (0.4 < aspect < 2.8):
                    continue

                # Skip tiny slivers that are clearly not cards
                if cell_h * cell_w < min_cell:
                    continue

                cards.append((cell, None))

        return cards

    @staticmethod
    def _find_gap_positions(
        profile: np.ndarray, total_length: int, cross_length: int, min_gap_frac: float = 0.01
    ) -> List[int]:
        """
        Walk an edge-density profile and return the centre position of
        every low-density gap (= separator between cards).

        Strategy: use a threshold that sits between the noise floor of
        a real scanner gap and the content density of any card row.
        """
        if len(profile) == 0:
            return []

        # --- Adaptive threshold ---
        # The 10th-percentile of the profile represents quiet regions
        # (gaps + blank card areas).  The 75th-percentile represents
        # content-rich rows.  A good threshold is halfway between them,
        # capped at 5 % of cross_length to stay far below card content.
        p10 = float(np.percentile(profile, 10))
        p75 = float(np.percentile(profile, 75))
        threshold = min((p10 + p75) / 2.0, cross_length * 0.05)
        # Hard floor: never go above 5 % of cross_length
        threshold = max(threshold, cross_length * 0.001)

        min_gap_px = max(8, int(total_length * min_gap_frac))
        edge_margin = int(total_length * 0.03)

        in_gap = profile < threshold
        gaps: List[int] = []
        gap_start = None

        for i, is_gap in enumerate(in_gap):
            if is_gap and gap_start is None:
                gap_start = i
            elif not is_gap and gap_start is not None:
                gap_end = i
                gap_size = gap_end - gap_start
                gap_center = (gap_start + gap_end) // 2

                if gap_size >= min_gap_px and edge_margin < gap_center < total_length - edge_margin:
                    gaps.append(gap_center)
                gap_start = None

        return gaps

    def four_point_transform(self, image: np.ndarray, pts: np.ndarray) -> np.ndarray:
        """
        Apply four point perspective transform to get top-down view.

        Args:
            image: Original image
            pts: Four corner points

        Returns:
            Warped image
        """
        # Order the points
        rect = self.order_points(pts)
        (tl, tr, br, bl) = rect

        # Compute width
        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))

        # Compute height
        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))

        # Construct destination points
        dst = np.array(
            [[0, 0], [maxWidth - 1, 0], [maxWidth - 1, maxHeight - 1], [0, maxHeight - 1]],
            dtype="float32",
        )

        # Compute perspective transform matrix
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))

        return warped

    def order_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Order points in consistent order: top-left, top-right, bottom-right, bottom-left.

        Args:
            pts: Array of 4 points

        Returns:
            Ordered array
        """
        rect = np.zeros((4, 2), dtype="float32")

        # Sum: top-left has smallest sum, bottom-right has largest
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]

        # Diff: top-right has smallest diff, bottom-left has largest
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]

        return rect


# ── Module-level helpers ────────────────────────────────────────────────────


def _is_blank_cell(
    image: np.ndarray, std_threshold: float = 25.0, white_threshold: float = 0.92
) -> bool:
    """
    Return True if the cell is mostly blank — uniform white, black, or
    nearly uniform colour.  Used to filter empty cells from uniform grid
    splits on PDF pages where only every Nth cell has a card.

    Checks:
      - Very low standard deviation (uniform colour)
      - AND very high fraction of white pixels (> 92%)
      → definitely blank
    """
    if image is None or image.size == 0:
        return True
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    h, w = gray.shape[:2]
    if h < 20 or w < 20:
        return True

    std_val = float(np.std(gray))
    if std_val < std_threshold:
        return True

    # Check white pixel fraction
    white_pixels = np.sum(gray > 230)
    total_pixels = gray.size
    if white_pixels / total_pixels > white_threshold:
        return True

    return False
