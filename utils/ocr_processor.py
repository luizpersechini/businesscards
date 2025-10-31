"""
OCR Processor Module
Extracts text from business card images using EasyOCR.
"""

import easyocr
import numpy as np
from typing import List, Dict, Tuple
import cv2


class OCRProcessor:
    """Extracts text from images using EasyOCR."""
    
    def __init__(self, languages=['en', 'pt'], gpu=False):
        """
        Initialize the OCR processor.
        
        Args:
            languages: List of language codes (e.g., ['en', 'pt'])
                      'en' = English, 'pt' = Portuguese
            gpu: Whether to use GPU acceleration
        """
        self.reader = easyocr.Reader(languages, gpu=gpu)
        self.languages = languages
    
    def extract_text(self, image: np.ndarray, detail=1) -> Dict:
        """
        Extract text from an image.
        
        Args:
            image: Input image as numpy array (BGR format)
            detail: 0=simple text list, 1=bounding boxes and text, 2=detailed output
            
        Returns:
            Dictionary with:
                - 'raw_text': Full text extracted
                - 'structured_data': List of (bbox, text, confidence) tuples
                - 'text_blocks': List of text strings
        """
        # Convert BGR to RGB for EasyOCR
        if len(image.shape) == 3 and image.shape[2] == 3:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            rgb_image = image
        
        # Perform OCR
        results = self.reader.readtext(rgb_image, detail=1)
        
        # Process results
        text_blocks = []
        structured_data = []
        
        for bbox, text, confidence in results:
            text_blocks.append(text)
            structured_data.append({
                'bbox': bbox,
                'text': text,
                'confidence': confidence
            })
        
        # Combine all text
        raw_text = '\n'.join(text_blocks)
        
        return {
            'raw_text': raw_text,
            'structured_data': structured_data,
            'text_blocks': text_blocks
        }
    
    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image to improve OCR accuracy.
        
        Args:
            image: Input image
            
        Returns:
            Preprocessed image
        """
        # Convert to grayscale if not already
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
        
        # Apply adaptive thresholding to handle varying lighting
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        
        # Denoise
        processed = cv2.fastNlMeansDenoising(processed, None, 10, 7, 21)
        
        return processed
    
    def extract_with_preprocessing(self, image: np.ndarray) -> Dict:
        """
        Extract text with automatic preprocessing for better accuracy.
        
        Args:
            image: Input image
            
        Returns:
            OCR results dictionary
        """
        # Try with original image first
        results_original = self.extract_text(image)
        
        # If confidence is low, try with preprocessing
        avg_confidence = self._calculate_average_confidence(results_original['structured_data'])
        
        if avg_confidence < 0.7:  # If average confidence is below 70%
            preprocessed = self.preprocess_image(image)
            results_preprocessed = self.extract_text(preprocessed)
            
            # Return better results
            avg_confidence_preprocessed = self._calculate_average_confidence(
                results_preprocessed['structured_data']
            )
            
            if avg_confidence_preprocessed > avg_confidence:
                results_preprocessed['preprocessed'] = True
                return results_preprocessed
        
        results_original['preprocessed'] = False
        return results_original
    
    def _calculate_average_confidence(self, structured_data: List[Dict]) -> float:
        """Calculate average confidence from structured data."""
        if not structured_data:
            return 0.0
        
        total_confidence = sum(item['confidence'] for item in structured_data)
        return total_confidence / len(structured_data)
    
    def draw_text_boxes(self, image: np.ndarray, structured_data: List[Dict]) -> np.ndarray:
        """
        Draw bounding boxes around detected text for visualization.
        
        Args:
            image: Original image
            structured_data: OCR results with bounding boxes
            
        Returns:
            Image with text boxes drawn
        """
        result = image.copy()
        
        for item in structured_data:
            bbox = item['bbox']
            text = item['text']
            confidence = item['confidence']
            
            # Convert bbox to integer points
            points = np.array(bbox, dtype=np.int32)
            
            # Draw rectangle
            cv2.polylines(result, [points], True, (0, 255, 0), 2)
            
            # Put text label with confidence
            label = f"{text[:20]}... ({confidence:.2f})" if len(text) > 20 else f"{text} ({confidence:.2f})"
            cv2.putText(result, label, tuple(points[0]), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
        
        return result
    
    def detect_front_back(self, text1: str, text2: str) -> Dict:
        """
        Determine if two text extractions are from front/back of same card.
        This is a simple heuristic - LLM will do more sophisticated analysis.
        
        Args:
            text1: Text from first side
            text2: Text from second side
            
        Returns:
            Dictionary with analysis results
        """
        # Simple heuristic: front usually has name/title, back has additional info
        front_keywords = ['ceo', 'president', 'manager', 'director', 'founder', 
                         'engineer', 'designer', 'consultant', 'specialist']
        back_keywords = ['address', 'website', 'linkedin', 'twitter', 'facebook']
        
        text1_lower = text1.lower()
        text2_lower = text2.lower()
        
        front_score_1 = sum(1 for kw in front_keywords if kw in text1_lower)
        front_score_2 = sum(1 for kw in front_keywords if kw in text2_lower)
        
        back_score_1 = sum(1 for kw in back_keywords if kw in text1_lower)
        back_score_2 = sum(1 for kw in back_keywords if kw in text2_lower)
        
        # Simple determination
        if front_score_1 > back_score_1 and back_score_2 > front_score_2:
            return {'text1_is_front': True, 'text2_is_front': False, 'confidence': 'medium'}
        elif front_score_2 > back_score_2 and back_score_1 > front_score_1:
            return {'text1_is_front': False, 'text2_is_front': True, 'confidence': 'medium'}
        else:
            return {'text1_is_front': True, 'text2_is_front': None, 'confidence': 'low'}

