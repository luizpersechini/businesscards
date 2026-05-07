"""
Optimized PDF processing module for Business Card Scanner.
Provides advanced PDF reading and parsing optimizations.
"""

import hashlib
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Generator, Callable
import logging

try:
    import fitz as _fitz
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False

logger = logging.getLogger(__name__)


@dataclass
class PDFAnalysis:
    """Analysis results for PDF optimization."""
    total_pages: int
    page_sizes: List[Dict]
    has_text: bool
    has_images: bool
    estimated_cards_per_page: int
    recommended_dpi: int
    processing_strategy: str  # "full_render", "text_extract", "mixed"
    is_business_card_format: bool = False
    suggested_grid_layout: Optional[Tuple[int, int]] = None


class PDFProcessor:
    """
    Optimized PDF processor with:
    - Adaptive DPI selection
    - Direct text extraction for text-based PDFs
    - Parallel rendering
    - PDF caching
    - Smart processing strategies
    """
    
    def __init__(self, cache_dir: str = "temp/pdf_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def analyze_pdf_structure(self, pdf_file: BytesIO) -> PDFAnalysis:
        """
        Analyze PDF structure to optimize processing.
        
        Args:
            pdf_file: PDF file as BytesIO
            
        Returns:
            PDFAnalysis object with optimization recommendations
        """
        if not HAS_PDF_SUPPORT:
            raise ValueError("PyMuPDF (fitz) not installed")
        
        doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
        
        analysis = PDFAnalysis(
            total_pages=len(doc),
            page_sizes=[],
            has_text=False,
            has_images=False,
            estimated_cards_per_page=0,
            recommended_dpi=200,
            processing_strategy="full_render"
        )
        
        # Analyze first few pages (sample for efficiency)
        sample_pages = min(3, len(doc))
        for i in range(sample_pages):
            page = doc.load_page(i)
            
            # Check page size
            rect = page.rect
            analysis.page_sizes.append({
                "width": rect.width,
                "height": rect.height,
                "aspect_ratio": rect.width / rect.height
            })
            
            # Check content type
            text = page.get_text()
            if len(text) > 50:
                analysis.has_text = True
            
            # Check for images
            image_list = page.get_images()
            if image_list:
                analysis.has_images = True
        
        # Determine optimal strategy
        if analysis.has_text and not analysis.has_images:
            analysis.processing_strategy = "text_extract"
            analysis.recommended_dpi = 150
        elif analysis.has_images and not analysis.has_text:
            analysis.processing_strategy = "full_render"
            analysis.recommended_dpi = 300
        else:
            analysis.processing_strategy = "mixed"
            analysis.recommended_dpi = 200
        
        # Estimate cards based on page size (business card detection)
        for size in analysis.page_sizes:
            # Business cards are typically 3.5x2 inches ratio
            if 2.0 < size["aspect_ratio"] < 4.0:
                analysis.is_business_card_format = True
                analysis.recommended_dpi = 250  # Good balance for small text
            
            # Landscape pages likely contain multiple cards
            if size["aspect_ratio"] > 1.5:
                analysis.estimated_cards_per_page = max(
                    analysis.estimated_cards_per_page,
                    2 if size["width"] > 1000 else 1
                )
        
        # Suggest grid layout for business card PDFs
        if analysis.is_business_card_format and analysis.estimated_cards_per_page > 1:
            # Common layouts: 2x2, 3x2, 4x2
            if analysis.estimated_cards_per_page >= 4:
                analysis.suggested_grid_layout = (2, 2)
            elif analysis.estimated_cards_per_page >= 6:
                analysis.suggested_grid_layout = (3, 2)
        
        doc.close()
        return analysis
    
    def extract_text_from_pdf(self, pdf_file: BytesIO) -> Optional[List[Dict]]:
        """
        Extract text directly from PDF without rendering to images.
        
        Args:
            pdf_file: PDF file as BytesIO
            
        Returns:
            List of text blocks with coordinates, or None if extraction fails
        """
        if not HAS_PDF_SUPPORT:
            return None
        
        try:
            doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
            text_blocks = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                blocks = page.get_text("blocks")  # Get text blocks with coordinates
                
                for block in blocks:
                    x0, y0, x1, y1, text, block_no, block_type = block
                    if text.strip():  # Skip empty blocks
                        text_blocks.append({
                            "page": page_num + 1,
                            "x": x0, "y": y0,
                            "width": x1 - x0,
                            "height": y1 - y0,
                            "text": text.strip(),
                            "type": "text" if block_type == 0 else "image"
                        })
            
            doc.close()
            
            # Group text blocks into logical sections (potential cards)
            cards = self._group_text_blocks_into_cards(text_blocks)
            return cards
            
        except Exception as e:
            logger.warning(f"Direct text extraction failed: {e}")
            return None
    
    def _group_text_blocks_into_cards(self, text_blocks: List[Dict]) -> List[Dict]:
        """
        Group text blocks into logical business card sections.
        
        Args:
            text_blocks: List of text blocks with coordinates
            
        Returns:
            List of grouped cards
        """
        cards = []
        
        # Simple grouping: blocks close together vertically
        sorted_blocks = sorted(text_blocks, key=lambda b: b["y"])
        
        current_card = []
        for block in sorted_blocks:
            if not current_card:
                current_card.append(block)
            else:
                # Check if block is close to previous block (same card)
                last_block = current_card[-1]
                vertical_distance = block["y"] - (last_block["y"] + last_block["height"])
                
                if vertical_distance < 100:  # Close enough to be same card
                    current_card.append(block)
                else:
                    # New card
                    if current_card:
                        cards.append({
                            "page": current_card[0]["page"],
                            "blocks": current_card,
                            "text": "\n".join(b["text"] for b in current_card)
                        })
                    current_card = [block]
        
        # Add last card
        if current_card:
            cards.append({
                "page": current_card[0]["page"],
                "blocks": current_card,
                "text": "\n".join(b["text"] for b in current_card)
            })
        
        return cards
    
    def pdf_pages_to_images_optimized(
        self,
        pdf_file: BytesIO,
        dpi: int = 200,
        page_range: Optional[Tuple[int, int]] = None,
        adaptive_dpi: bool = True
    ) -> List[BytesIO]:
        """
        Optimized PDF rendering with:
        - Page range selection
        - Adaptive DPI based on content
        - Progressive rendering
        
        Args:
            pdf_file: PDF file as BytesIO
            dpi: Base DPI for rendering
            page_range: Optional (start_page, end_page) range
            adaptive_dpi: Whether to adjust DPI based on content
            
        Returns:
            List of BytesIO objects containing rendered images
        """
        if not HAS_PDF_SUPPORT:
            raise ValueError("PyMuPDF (fitz) not installed")
        
        # Get PDF fingerprint for caching
        pdf_fingerprint = self._get_pdf_fingerprint(pdf_file)
        
        # Check cache first
        if page_range:
            cached = self._get_cached_pages(pdf_fingerprint, page_range)
            if cached:
                logger.info(f"Using cached pages for {pdf_fingerprint}")
                return cached
        
        base_name = getattr(pdf_file, 'name', 'document')
        if base_name.lower().endswith('.pdf'):
            base_name = base_name[:-4]
        
        doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
        total_pages = len(doc)
        
        # Adaptive DPI adjustment
        if adaptive_dpi:
            # Sample first page to determine content type
            sample_page = doc.load_page(0)
            text = sample_page.get_text()
            images = sample_page.get_images()
            
            if len(text) > 100 and not images:
                dpi = 150  # Text doesn't need high DPI
            elif images and len(text) < 50:
                dpi = 300  # Images need higher DPI
        
        # Page range selection
        start_page, end_page = page_range or (0, total_pages)
        pages_to_render = range(start_page, min(end_page, total_pages))
        
        # Render pages
        pages = []
        zoom = dpi / 72.0
        mat = _fitz.Matrix(zoom, zoom)
        
        for page_num in pages_to_render:
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=mat)
            
            # Optimize compression based on content
            img_bytes = self._optimize_image_compression(pix, "mixed")
            img_bytes.name = f"{base_name}_page_{page_num + 1}.png"
            pages.append(img_bytes)
        
        doc.close()
        
        # Cache results
        if page_range:
            self._cache_pages(pdf_fingerprint, page_range, pages)
        
        return pages
    
    def pdf_pages_to_images_parallel(
        self,
        pdf_file: BytesIO,
        dpi: int = 200,
        max_workers: int = 4
    ) -> List[BytesIO]:
        """
        Render PDF pages in parallel for faster processing.
        
        Args:
            pdf_file: PDF file as BytesIO
            dpi: DPI for rendering
            max_workers: Maximum number of parallel workers
            
        Returns:
            List of BytesIO objects containing rendered images
        """
        if not HAS_PDF_SUPPORT:
            raise ValueError("PyMuPDF (fitz) not installed")
        
        doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
        total_pages = len(doc)
        
        base_name = getattr(pdf_file, 'name', 'document')
        if base_name.lower().endswith('.pdf'):
            base_name = base_name[:-4]
        
        zoom = dpi / 72.0
        mat = _fitz.Matrix(zoom, zoom)
        
        def render_page(page_num: int) -> BytesIO:
            """Render single page."""
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=mat)
            
            img_bytes = BytesIO(pix.tobytes("png"))
            img_bytes.name = f"{base_name}_page_{page_num + 1}.png"
            return img_bytes
        
        # Render pages in parallel
        pages = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(render_page, i): i for i in range(total_pages)}
            
            for future in as_completed(futures):
                try:
                    pages.append(future.result())
                except Exception as e:
                    logger.error(f"Failed to render page: {e}")
        
        # Sort by page number
        pages.sort(key=lambda x: int(x.name.split('_')[1].split('.')[0]))
        doc.close()
        return pages
    
    def process_pdf_in_chunks(
        self,
        pdf_file: BytesIO,
        chunk_size: int = 10,
        callback: Optional[Callable] = None
    ) -> Generator[List[BytesIO], None, None]:
        """
        Process PDF in chunks to reduce memory usage.
        
        Args:
            pdf_file: PDF file as BytesIO
            chunk_size: Number of pages per chunk
            callback: Optional callback for progress reporting
            
        Returns:
            Generator yielding lists of BytesIO objects
        """
        if not HAS_PDF_SUPPORT:
            raise ValueError("PyMuPDF (fitz) not installed")
        
        doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
        total_pages = len(doc)
        
        base_name = getattr(pdf_file, 'name', 'document')
        if base_name.lower().endswith('.pdf'):
            base_name = base_name[:-4]
        
        zoom = 200 / 72.0  # Default DPI
        mat = _fitz.Matrix(zoom, zoom)
        
        for chunk_start in range(0, total_pages, chunk_size):
            chunk_end = min(chunk_start + chunk_size, total_pages)
            chunk_pages = []
            
            for page_num in range(chunk_start, chunk_end):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=mat)
                
                img_bytes = BytesIO(pix.tobytes("png"))
                img_bytes.name = f"{base_name}_page_{page_num + 1}.png"
                chunk_pages.append(img_bytes)
                
                if callback:
                    callback(page_num + 1, total_pages)
            
            yield chunk_pages
        
        doc.close()
    
    def _get_pdf_fingerprint(self, pdf_file: BytesIO) -> str:
        """Generate fingerprint for PDF caching."""
        content = pdf_file.read()
        pdf_file.seek(0)
        return hashlib.md5(content).hexdigest()
    
    def _get_cached_pages(
        self,
        pdf_fingerprint: str,
        page_range: Tuple[int, int]
    ) -> Optional[List[BytesIO]]:
        """Get cached pages if available."""
        cache_file = self.cache_dir / f"{pdf_fingerprint}_{page_range[0]}_{page_range[1]}.pkl"
        
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    return pickle.load(f)
            except Exception:
                return None
        return None
    
    def _cache_pages(
        self,
        pdf_fingerprint: str,
        page_range: Tuple[int, int],
        pages: List[BytesIO]
    ):
        """Cache rendered pages."""
        cache_file = self.cache_dir / f"{pdf_fingerprint}_{page_range[0]}_{page_range[1]}.pkl"
        
        with open(cache_file, "wb") as f:
            pickle.dump(pages, f)
    
    def _optimize_image_compression(
        self,
        pix: _fitz.Pixmap,
        content_type: str = "mixed"
    ) -> BytesIO:
        """
        Optimize image compression based on content type.
        
        Args:
            pix: Fitz Pixmap object
            content_type: "text", "photo", or "mixed"
            
        Returns:
            BytesIO with optimized compressed image
        """
        img_bytes = BytesIO()
        
        if content_type == "text":
            # Text benefits from PNG with high compression
            # Note: compress_level parameter removed as it's not supported in current PyMuPDF
            pix.save(img_bytes, "png")
        elif content_type == "photo":
            # Photos can use JPEG with quality tradeoff
            # Note: Requires PIL for JPEG compression
            try:
                from PIL import Image
                img_pil = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                img_pil.save(img_bytes, "JPEG", quality=85, optimize=True)
            except ImportError:
                # Fallback to PNG if PIL not available
                pix.save(img_bytes, "png")
        else:
            # Mixed content - balanced approach
            pix.save(img_bytes, "png")
        
        return img_bytes
    
    def process_pdf_optimized(self, uploaded_file: BytesIO) -> List[BytesIO]:
        """
        Optimized PDF processing with smart strategies.
        
        Args:
            uploaded_file: PDF file as BytesIO
            
        Returns:
            List of BytesIO objects (images or text card representations)
        """
        # Step 1: Analyze PDF structure
        analysis = self.analyze_pdf_structure(uploaded_file)
        
        # Step 2: Choose processing strategy
        if analysis.processing_strategy == "text_extract":
            # Try direct text extraction first
            text_cards = self.extract_text_from_pdf(uploaded_file)
            if text_cards and len(text_cards) > 0:
                # Convert text cards to image-like format for compatibility
                return self._text_cards_to_images(text_cards)
        
        # Step 3: Render with optimized settings
        return self.pdf_pages_to_images_optimized(
            uploaded_file,
            dpi=analysis.recommended_dpi,
            adaptive_dpi=True
        )
    
    def _text_cards_to_images(self, text_cards: List[Dict]) -> List[BytesIO]:
        """
        Convert text cards to image-like BytesIO objects for compatibility.
        
        Args:
            text_cards: List of text card dictionaries
            
        Returns:
            List of BytesIO objects mimicking image files
        """
        images = []
        
        for card in text_cards:
            # Create a simple image representation of text card
            # This could be enhanced with actual text rendering
            text_bytes = BytesIO(card["text"].encode("utf-8"))
            text_bytes.name = f"text_card_page_{card['page']}.txt"
            images.append(text_bytes)
        
        return images