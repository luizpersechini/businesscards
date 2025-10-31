"""
Card Detector Module
Detects and extracts individual business cards from images using OpenCV.
"""

import cv2
import numpy as np
from typing import List, Tuple
from PIL import Image


class CardDetector:
    """Detects and extracts business cards from images."""
    
    def __init__(self, min_card_area=10000, max_card_area=500000):
        """
        Initialize the card detector.
        
        Args:
            min_card_area: Minimum area (in pixels) for a valid card
            max_card_area: Maximum area (in pixels) for a valid card
        """
        self.min_card_area = min_card_area
        self.max_card_area = max_card_area
    
    def detect_cards(self, image: np.ndarray) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Detect individual business cards in an image.
        
        Args:
            image: Input image as numpy array (BGR format from OpenCV)
            
        Returns:
            List of tuples (card_image, contour) for each detected card
        """
        # Make a copy of the original image
        original = image.copy()
        
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Use Otsu's thresholding for better separation
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # Invert if necessary (cards should be white on threshold)
        if cv2.countNonZero(thresh) > thresh.size / 2:
            thresh = cv2.bitwise_not(thresh)
        
        # Morphological operations to clean up and connect edges
        kernel_rect = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel_rect, iterations=2)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_rect, iterations=1)
        
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Sort contours by area (largest first)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        detected_cards = []
        used_regions = []  # Track regions to avoid duplicates
        
        for contour in contours:
            # Get the area
            area = cv2.contourArea(contour)
            
            # Filter by area
            if area < self.min_card_area or area > self.max_card_area:
                continue
            
            # Approximate the contour to reduce points
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(contour)
            
            # Check if this region overlaps significantly with already detected cards
            overlaps = False
            for used_x, used_y, used_w, used_h in used_regions:
                # Calculate overlap
                x_overlap = max(0, min(x + w, used_x + used_w) - max(x, used_x))
                y_overlap = max(0, min(y + h, used_y + used_h) - max(y, used_y))
                overlap_area = x_overlap * y_overlap
                
                # If more than 30% overlap, skip this contour
                if overlap_area > (w * h * 0.3):
                    overlaps = True
                    break
            
            if overlaps:
                continue
            
            # Check aspect ratio (business cards are typically rectangular)
            aspect_ratio = float(w) / h if h > 0 else 0
            
            # Business cards: 85.6mm x 53.98mm = 1.586 ratio (but can be vertical)
            # Allow range from 0.5 to 2.5 for both orientations
            if not (0.5 < aspect_ratio < 2.5):
                continue
            
            # Check if contour is roughly rectangular
            # Calculate extent (contour area / bounding box area)
            extent = area / (w * h) if (w * h) > 0 else 0
            
            # Cards should fill most of their bounding box (>65%)
            if extent < 0.65:
                continue
            
            # Check rectangularity using approximated polygon
            # Rectangles should have ~4 corners
            if len(approx) < 4 or len(approx) > 8:
                continue
            
            # Extract the card region with minimal padding
            padding = 3
            y1 = max(0, y - padding)
            y2 = min(original.shape[0], y + h + padding)
            x1 = max(0, x - padding)
            x2 = min(original.shape[1], x + w + padding)
            
            card_image = original[y1:y2, x1:x2]
            
            # Only add if the card is large enough
            if card_image.shape[0] > 80 and card_image.shape[1] > 80:
                detected_cards.append((card_image, contour))
                used_regions.append((x, y, w, h))
                
                # Limit to reasonable number of cards
                if len(detected_cards) >= 20:
                    break
        
        # If we didn't find many cards, try alternative method
        if len(detected_cards) < 2:
            edge_cards = self._detect_with_edges(original, gray)
            if len(edge_cards) > len(detected_cards):
                detected_cards = edge_cards
        
        # If still no cards detected, assume the whole image is a single card
        if len(detected_cards) == 0:
            detected_cards.append((original, None))
        
        return detected_cards
    
    def _detect_with_edges(self, original: np.ndarray, gray: np.ndarray) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Alternative detection method using edge detection.
        
        Args:
            original: Original color image
            gray: Grayscale version
            
        Returns:
            List of detected cards
        """
        # Strong edge detection with Canny
        edges = cv2.Canny(gray, 30, 100, apertureSize=3)
        
        # Use larger kernel to connect card edges
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=3)
        
        # Fill holes in the edges
        edges = cv2.dilate(edges, kernel, iterations=1)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Sort by area
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        detected_cards = []
        used_regions = []
        
        for contour in contours[:20]:  # Check top 20 contours
            area = cv2.contourArea(contour)
            
            if area < self.min_card_area or area > self.max_card_area:
                continue
            
            # Approximate contour
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            
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
            
            # Check aspect ratio
            aspect_ratio = float(w) / h if h > 0 else 0
            
            if not (0.5 < aspect_ratio < 2.5):
                continue
            
            # Check extent (how much of bounding box is filled)
            extent = area / (w * h) if (w * h) > 0 else 0
            if extent < 0.6:
                continue
            
            # Check rectangularity
            if len(approx) < 4 or len(approx) > 10:
                continue
            
            card_image = original[y:y+h, x:x+w]
            
            if card_image.shape[0] > 80 and card_image.shape[1] > 80:
                detected_cards.append((card_image, contour))
                used_regions.append((x, y, w, h))
                
                if len(detected_cards) >= 20:
                    break
        
        return detected_cards
    
    def _four_point_transform(self, image: np.ndarray, pts: np.ndarray) -> np.ndarray:
        """
        Apply perspective transformation to get a top-down view of the card.
        
        Args:
            image: Original image
            pts: Four corner points of the card
            
        Returns:
            Transformed (warped) image
        """
        # Order points: top-left, top-right, bottom-right, bottom-left
        rect = self._order_points(pts)
        (tl, tr, br, bl) = rect
        
        # Compute width of the new image
        widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
        widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
        maxWidth = max(int(widthA), int(widthB))
        
        # Compute height of the new image
        heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
        heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
        maxHeight = max(int(heightA), int(heightB))
        
        # Construct destination points for the transform
        dst = np.array([
            [0, 0],
            [maxWidth - 1, 0],
            [maxWidth - 1, maxHeight - 1],
            [0, maxHeight - 1]
        ], dtype="float32")
        
        # Calculate the perspective transform matrix and apply it
        M = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
        
        return warped
    
    def _order_points(self, pts: np.ndarray) -> np.ndarray:
        """
        Order points in clockwise order starting from top-left.
        
        Args:
            pts: Array of 4 points
            
        Returns:
            Ordered array: [top-left, top-right, bottom-right, bottom-left]
        """
        rect = np.zeros((4, 2), dtype="float32")
        
        # Sum: top-left will have smallest sum, bottom-right largest
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        
        # Diff: top-right will have smallest diff, bottom-left largest
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        
        return rect
    
    def draw_detections(self, image: np.ndarray, contours: List[np.ndarray]) -> np.ndarray:
        """
        Draw detected card contours on the image for visualization.
        
        Args:
            image: Original image
            contours: List of contours to draw
            
        Returns:
            Image with contours drawn
        """
        result = image.copy()
        
        for i, contour in enumerate(contours):
            if contour is not None:
                # Draw contour
                cv2.drawContours(result, [contour], -1, (0, 255, 0), 3)
                
                # Get bounding box to place label
                x, y, w, h = cv2.boundingRect(contour)
                cv2.putText(result, f'Card {i+1}', (x, y-10), 
                           cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        
        return result
    
    @staticmethod
    def pil_to_cv2(pil_image: Image.Image) -> np.ndarray:
        """Convert PIL Image to OpenCV format (BGR)."""
        return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    
    @staticmethod
    def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
        """Convert OpenCV image (BGR) to PIL Image."""
        return Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))

