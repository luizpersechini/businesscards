"""
OCR Processor for scanned PDFs and images.
Provides text extraction from scanned documents using Tesseract OCR.
"""

import logging
from io import BytesIO
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

# Try to import OCR dependencies
try:
    import pytesseract
    from PIL import Image
    import cv2
    HAS_OCR_SUPPORT = True
except ImportError:
    HAS_OCR_SUPPORT = False


@dataclass
class OCRResult:
    """OCR processing result."""
    text: str
    confidence: float
    page_num: int
    language: str
    processing_time: float
    word_count: int
    has_contacts: bool = False
    extracted_contacts: List[Dict] = None


class OCRProcessor:
    """
    OCR processor for scanned documents.
    Uses Tesseract OCR with preprocessing for better text recognition.
    """
    
    def __init__(self, language: str = "por+eng", timeout: int = 30):
        """
        Initialize OCR processor.
        
        Args:
            language: Tesseract language codes (e.g., "por+eng" for Portuguese + English)
            timeout: Timeout in seconds for OCR processing
        """
        if not HAS_OCR_SUPPORT:
            raise ImportError("OCR dependencies not installed. Install: pip install pytesseract opencv-python")
        
        self.language = language
        self.timeout = timeout
        
        # Configure pytesseract path (if needed)
        # pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'  # Uncomment if needed
        
        logger.info(f"OCR Processor initialized with language: {language}")
    
    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image for better OCR results.
        
        Args:
            image: Input image as numpy array
            
        Returns:
            Preprocessed image
        """
        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image
        
        # Apply adaptive thresholding
        processed = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        
        # Denoise
        processed = cv2.medianBlur(processed, 3)
        
        # Sharpening kernel
        kernel = np.array([[-1, -1, -1],
                          [-1,  9, -1],
                          [-1, -1, -1]])
        processed = cv2.filter2D(processed, -1, kernel)
        
        return processed
    
    def extract_text_from_image(self, image_bytes: BytesIO, page_num: int = 1) -> OCRResult:
        """
        Extract text from an image using OCR.
        
        Args:
            image_bytes: Image as BytesIO
            page_num: Page number for tracking
            
        Returns:
            OCRResult object
        """
        import time
        start_time = time.time()
        
        try:
            # Open image
            img = Image.open(image_bytes)
            
            # Convert to numpy array for OpenCV processing
            img_array = np.array(img)
            
            # Preprocess image
            processed = self.preprocess_image(img_array)
            
            # Perform OCR
            custom_config = f'--oem 3 --psm 6 -l {self.language}'
            data = pytesseract.image_to_data(
                processed, 
                config=custom_config,
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout
            )
            
            # Extract text and confidence
            text = pytesseract.image_to_string(processed, config=custom_config)
            
            # Calculate average confidence
            confidences = [float(c) for c in data['conf'] if c != '-1']
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            # Count words
            word_count = len(text.split())
            
            # Check if text contains contact information patterns
            has_contacts = self._contains_contact_info(text)
            
            processing_time = time.time() - start_time
            
            return OCRResult(
                text=text.strip(),
                confidence=avg_confidence,
                page_num=page_num,
                language=self.language,
                processing_time=processing_time,
                word_count=word_count,
                has_contacts=has_contacts
            )
            
        except Exception as e:
            logger.error(f"OCR failed for page {page_num}: {e}")
            processing_time = time.time() - start_time
            
            return OCRResult(
                text="",
                confidence=0.0,
                page_num=page_num,
                language=self.language,
                processing_time=processing_time,
                word_count=0,
                has_contacts=False
            )
    
    def extract_text_from_pdf_images(self, pdf_images: List[BytesIO]) -> List[OCRResult]:
        """
        Extract text from multiple PDF page images.
        
        Args:
            pdf_images: List of BytesIO objects containing PDF page images
            
        Returns:
            List of OCRResult objects
        """
        results = []
        
        for i, image_bytes in enumerate(pdf_images):
            result = self.extract_text_from_image(image_bytes, page_num=i+1)
            results.append(result)
            
            logger.info(f"Page {i+1}: {result.word_count} words, "
                       f"confidence: {result.confidence:.1f}%, "
                       f"time: {result.processing_time:.2f}s")
        
        return results
    
    def _contains_contact_info(self, text: str) -> bool:
        """
        Check if text contains patterns indicative of contact information.
        
        Args:
            text: Extracted text
            
        Returns:
            True if contact info patterns found
        """
        text_lower = text.lower()
        
        # Common contact information patterns
        patterns = [
            r'\b@\b',  # Email
            r'\+\d{1,3}[-\s]?\d{1,14}',  # Phone numbers
            r'www\.',  # Websites
            r'\.com\b|\.org\b|\.net\b',  # Domain extensions
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email regex
            r'\b(?:mr|mrs|ms|dr|prof)\.?\s+[A-Z][a-z]+',  # Titles with names
            r'\b(?:ceo|cto|cfo|manager|director|president)\b',  # Job titles
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        
        return False
    
    def extract_structured_contacts(self, ocr_results: List[OCRResult]) -> List[Dict]:
        """
        Extract structured contact information from OCR results.
        
        Args:
            ocr_results: List of OCRResult objects
            
        Returns:
            List of structured contact dictionaries
        """
        contacts = []
        
        for result in ocr_results:
            if not result.text or result.word_count < 5:
                continue
            
            # Simple parsing for common contact patterns
            contact = {
                "name": self._extract_name(result.text),
                "email": self._extract_email(result.text),
                "phone": self._extract_phone(result.text),
                "company": self._extract_company(result.text),
                "title": self._extract_title(result.text),
                "source": f"OCR Page {result.page_num}",
                "confidence": result.confidence,
                "raw_text": result.text[:500] + "..." if len(result.text) > 500 else result.text
            }
            
            # Only add if we found at least some contact info
            if any(contact[key] for key in ["name", "email", "phone", "company"]):
                contacts.append(contact)
        
        return contacts
    
    def _extract_name(self, text: str) -> str:
        """Extract potential name from text."""
        import re
        # Look for title + name patterns
        patterns = [
            r'\b(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)',
            r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})',  # Start of line with capitalized words
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        
        return ""
    
    def _extract_email(self, text: str) -> str:
        """Extract email from text."""
        import re
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        match = re.search(email_pattern, text)
        return match.group(0) if match else ""
    
    def _extract_phone(self, text: str) -> str:
        """Extract phone number from text."""
        import re
        phone_patterns = [
            r'\+\d{1,3}[-\s]?\(?\d{1,4}\)?[-\s]?\d{1,4}[-\s]?\d{1,9}',  # International
            r'\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}',  # US-style
            r'\d{2}[-\s]?\d{4,5}[-\s]?\d{4}',  # Brazilian style
        ]
        
        for pattern in phone_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(0).strip()
        
        return ""
    
    def _extract_company(self, text: str) -> str:
        """Extract company name from text."""
        import re
        # Look for common company indicators
        patterns = [
            r'\b(?:Inc\.?|LLC|Ltd\.?|Corp\.?|GmbH)\b',
            r'\b[A-Z][A-Za-z&]+\s+(?:Company|Corporation|Solutions|Technologies|Group)\b',
        ]
        
        # Find line with company indicators
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
                return line
        
        return ""
    
    def _extract_title(self, text: str) -> str:
        """Extract job title from text."""
        import re
        titles = [
            'CEO', 'CTO', 'CFO', 'COO', 'President', 'Director', 'Manager',
            'Engineer', 'Developer', 'Analyst', 'Specialist', 'Consultant',
            'Head of', 'Lead', 'Senior', 'Junior', 'Associate'
        ]
        
        lines = text.split('\n')
        for line in lines:
            line_lower = line.lower()
            for title in titles:
                if title.lower() in line_lower:
                    return title
        
        return ""


def is_ocr_available() -> bool:
    """Check if OCR is available."""
    if not HAS_OCR_SUPPORT:
        return False
    
    # Test if tesseract is installed
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False