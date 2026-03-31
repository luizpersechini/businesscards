"""
Improved Card Detector Module
Uses document scanner techniques for better card detection.
Based on industry best practices from PyImageSearch and OpenCV documentation.
"""

import cv2
import numpy as np
from typing import List, Tuple
from PIL import Image
import imutils


class ImprovedCardDetector:
    """
    Enhanced card detector using document scanner algorithms.
    """
    
    def __init__(self, min_area_percent=5, max_area_percent=40):
        """
        Initialize the improved card detector.
        
        Args:
            min_area_percent: Minimum area as percentage of image (default 5%)
            max_area_percent: Maximum area as percentage of image (default 40%)
        """
        self.min_area_percent = min_area_percent
        self.max_area_percent = max_area_percent
    
    def detect_cards(self, image: np.ndarray) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Detect business cards using advanced document scanning techniques.
        Filters out QR codes and logos.
        
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
        
        # Apply Gaussian blur
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Try multiple edge detection strategies for better grid detection
        # Strategy 1: Canny with lower threshold
        edged1 = cv2.Canny(blurred, 30, 100)
        
        # Strategy 2: Adaptive thresholding (better for grids)
        edged2 = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                       cv2.THRESH_BINARY_INV, 11, 2)
        
        # Combine both strategies
        edged = cv2.bitwise_or(edged1, edged2)
        
        # Dilate edges to close gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        edged = cv2.dilate(edged, kernel, iterations=1)
        edged = cv2.erode(edged, kernel, iterations=1)
        
        # Find contours
        contours = cv2.findContours(edged.copy(), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = imutils.grab_contours(contours)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        detected_cards = []
        used_regions = []
        
        # Loop through contours
        for c in contours[:50]:  # Check top 50 contours (increased for grids)
            # Get area first to filter early
            area = cv2.contourArea(c)
            
            # Filter by area (excludes small QR codes and logos)
            if area < min_area_resized or area > max_area_resized:
                continue
            
            # Approximate the contour
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            
            # Business cards should have 4-8 corners (more flexible for grids)
            if len(approx) < 4 or len(approx) > 8:
                continue
            
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(approx)
            
            # Check aspect ratio (business cards are typically 1.586:1)
            # Standard: 85.6mm x 53.98mm
            # More flexible range for grid layouts
            aspect_ratio = float(w) / h if h > 0 else 0
            
            # QR codes are square (1:1), logos vary but cards are specific
            # Relaxed constraints for better grid detection
            if not (1.2 < aspect_ratio < 2.2 or 0.45 < aspect_ratio < 0.85):
                continue
            
            # Check extent (how much of bounding box is filled)
            # Business cards fill their bounding box well
            # QR codes and logos may not
            extent = area / (w * h) if (w * h) > 0 else 0
            if extent < 0.70:  # Relaxed from 0.75 to 0.70
                continue
            
            # Check if this overlaps with already detected cards
            # Reduced overlap threshold for better grid detection
            overlaps = False
            for used_x, used_y, used_w, used_h in used_regions:
                x_overlap = max(0, min(x + w, used_x + used_w) - max(x, used_x))
                y_overlap = max(0, min(y + h, used_y + used_h) - max(y, used_y))
                overlap_area = x_overlap * y_overlap
                
                # Reduced from 0.3 to 0.2 (20% overlap allowed)
                if overlap_area > (w * h * 0.2):
                    overlaps = True
                    break
            
            if overlaps:
                continue
            
            # Apply perspective transform to get card
            # Scale points back to original image
            if len(approx) == 4:
                # Use 4-point transform for perfect rectangles
                pts = approx.reshape(4, 2) * ratio
                card_warped = self.four_point_transform(original, pts)
            else:
                # Use bounding box for non-perfect rectangles
                x_orig = int(x * ratio)
                y_orig = int(y * ratio)
                w_orig = int(w * ratio)
                h_orig = int(h * ratio)
                
                # Add small padding
                padding = 5
                y1 = max(0, y_orig - padding)
                y2 = min(original.shape[0], y_orig + h_orig + padding)
                x1 = max(0, x_orig - padding)
                x2 = min(original.shape[1], x_orig + w_orig + padding)
                
                card_warped = original[y1:y2, x1:x2]
            
            if card_warped is not None and card_warped.shape[0] > 100 and card_warped.shape[1] > 100:
                detected_cards.append((card_warped, c))
                used_regions.append((x, y, w, h))
        
        # If contour detection found fewer than 4 cards, try grid detection.
        # Scanned pages with cards laid side-by-side often defeat contour
        # methods because the gaps between cards are too thin or the
        # backgrounds merge.
        if len(detected_cards) < 4:
            grid_cards = self._detect_grid_by_gaps(original)
            if len(grid_cards) > len(detected_cards):
                detected_cards = grid_cards

        # If no cards found with either method, try simpler bounding box
        if len(detected_cards) == 0:
            detected_cards = self._fallback_detection(original)

        # If still nothing, return whole image
        if len(detected_cards) == 0:
            detected_cards.append((original, None))

        return detected_cards
    
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
            
            card_image = image[y:y+h, x:x+w]
            
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
        h_smooth = np.convolve(h_proj, np.ones(3) / 3, mode='same')
        row_splits = self._find_gap_positions(h_smooth, h, cross_length=w)

        # --- Vertical projection (find column separators) ---
        v_proj = np.sum(edges, axis=0).astype(float)
        v_smooth = np.convolve(v_proj, np.ones(3) / 3, mode='same')
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
    def _find_gap_positions(profile: np.ndarray, total_length: int,
                            cross_length: int,
                            min_gap_frac: float = 0.01) -> List[int]:
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

                if (gap_size >= min_gap_px
                        and edge_margin < gap_center < total_length - edge_margin):
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
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]
        ], dtype="float32")
        
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

