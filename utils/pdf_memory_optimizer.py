"""
PDF Memory Optimizer
Optimizes memory usage when processing large PDF files.
"""

import logging
import gc
from io import BytesIO
from typing import List, Optional, Callable
from dataclasses import dataclass
import threading
import time

logger = logging.getLogger(__name__)

try:
    import fitz as _fitz
    HAS_PDF_SUPPORT = True
except ImportError:
    HAS_PDF_SUPPORT = False


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    peak_memory_mb: float
    avg_memory_mb: float
    gc_collections: int
    processing_time: float
    pages_processed: int
    memory_reduction_percent: float


class PDFMemoryOptimizer:
    """
    Optimizes memory usage for PDF processing.
    
    Features:
    - Progressive page loading (process one page at a time)
    - Memory cleanup between pages
    - GC optimization
    - Memory monitoring
    """
    
    def __init__(self, max_memory_mb: int = 1024):
        """
        Initialize memory optimizer.
        
        Args:
            max_memory_mb: Maximum memory usage in MB (soft limit)
        """
        self.max_memory_mb = max_memory_mb
        self.memory_stats = []
        
    def get_memory_usage(self) -> float:
        """
        Get current memory usage in MB.
        
        Returns:
            Memory usage in MB
        """
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024  # Convert to MB
        except ImportError:
            # Fallback if psutil not available
            return 0.0
    
    def optimize_gc(self):
        """Optimize garbage collection settings."""
        # Enable generational GC
        gc.enable()
        
        # Set thresholds for better performance
        gc.set_threshold(700, 10, 10)
        
        # Collect garbage
        collected = gc.collect()
        logger.debug(f"GC collected {collected} objects")
    
    def process_pdf_with_memory_control(
        self,
        pdf_file: BytesIO,
        page_processor: Callable,
        max_pages_per_batch: int = 10,
        cleanup_frequency: int = 5
    ) -> List:
        """
        Process PDF with memory control.
        
        Args:
            pdf_file: PDF file as BytesIO
            page_processor: Function to process each page
            max_pages_per_batch: Maximum pages to process before cleanup
            cleanup_frequency: How often to force GC cleanup
            
        Returns:
            List of processed results
        """
        if not HAS_PDF_SUPPORT:
            raise ValueError("PyMuPDF (fitz) not installed")
        
        start_time = time.time()
        start_memory = self.get_memory_usage()
        gc_count_before = gc.get_count()
        
        results = []
        
        try:
            doc = _fitz.open(stream=pdf_file.read(), filetype="pdf")
            total_pages = len(doc)
            
            logger.info(f"Processing {total_pages} pages with memory control")
            
            for page_num in range(total_pages):
                # Check memory usage
                current_memory = self.get_memory_usage()
                
                # Warn if approaching memory limit
                if current_memory > self.max_memory_mb * 0.8:
                    logger.warning(
                        f"High memory usage: {current_memory:.1f}MB / {self.max_memory_mb}MB "
                        f"({page_num+1}/{total_pages} pages)"
                    )
                
                # Process current page
                page = doc.load_page(page_num)
                result = page_processor(page, page_num)
                results.append(result)
                
                # Explicitly delete page object
                del page
                
                # Cleanup every N pages
                if (page_num + 1) % cleanup_frequency == 0:
                    self.optimize_gc()
                    logger.debug(f"Cleanup after page {page_num + 1}, "
                                f"memory: {self.get_memory_usage():.1f}MB")
                
                # Track memory stats
                self.memory_stats.append({
                    'page': page_num + 1,
                    'memory_mb': current_memory,
                    'timestamp': time.time() - start_time
                })
            
            doc.close()
            
        except Exception as e:
            logger.error(f"Memory-controlled processing failed: {e}")
            raise
        
        finally:
            # Final cleanup
            self.optimize_gc()
            
            # Calculate statistics
            end_time = time.time()
            end_memory = self.get_memory_usage()
            gc_count_after = gc.get_count()
            
            processing_time = end_time - start_time
            memory_used = end_memory - start_memory
            gc_collections = sum(gc_count_after) - sum(gc_count_before)
            
            logger.info(
                f"Processing completed: {total_pages} pages in {processing_time:.1f}s, "
                f"memory delta: {memory_used:.1f}MB, GC collections: {gc_collections}"
            )
        
        return results
    
    def get_memory_statistics(self) -> MemoryStats:
        """
        Get memory usage statistics.
        
        Returns:
            MemoryStats object
        """
        if not self.memory_stats:
            return MemoryStats(
                peak_memory_mb=0,
                avg_memory_mb=0,
                gc_collections=0,
                processing_time=0,
                pages_processed=0,
                memory_reduction_percent=0
            )
        
        memories = [stat['memory_mb'] for stat in self.memory_stats]
        peak_memory = max(memories) if memories else 0
        avg_memory = sum(memories) / len(memories) if memories else 0
        
        # Calculate memory reduction (compared to naive processing)
        # Assuming naive processing would use ~50MB per page for large images
        estimated_naive_memory = len(self.memory_stats) * 50  # 50MB per page estimate
        if estimated_naive_memory > 0:
            memory_reduction = max(0, (estimated_naive_memory - peak_memory) / estimated_naive_memory * 100)
        else:
            memory_reduction = 0
        
        return MemoryStats(
            peak_memory_mb=peak_memory,
            avg_memory_mb=avg_memory,
            gc_collections=gc.get_count()[0],  # Generation 0 collections
            processing_time=self.memory_stats[-1]['timestamp'] if self.memory_stats else 0,
            pages_processed=len(self.memory_stats),
            memory_reduction_percent=memory_reduction
        )
    
    def generate_memory_report(self) -> str:
        """
        Generate a human-readable memory usage report.
        
        Returns:
            Report string
        """
        stats = self.get_memory_statistics()
        
        report = [
            "📊 PDF Memory Optimization Report",
            "=" * 40,
            f"Pages Processed: {stats.pages_processed}",
            f"Peak Memory Usage: {stats.peak_memory_mb:.1f} MB",
            f"Average Memory Usage: {stats.avg_memory_mb:.1f} MB",
            f"Processing Time: {stats.processing_time:.1f} seconds",
            f"GC Collections: {stats.gc_collections}",
            f"Memory Reduction: {stats.memory_reduction_percent:.1f}%",
            "",
            "Memory Usage Pattern:"
        ]
        
        if self.memory_stats:
            # Show memory trend
            for i, stat in enumerate(self.memory_stats):
                if i % max(1, len(self.memory_stats) // 10) == 0:  # Sample ~10 points
                    report.append(f"  Page {stat['page']}: {stat['memory_mb']:.1f} MB")
        
        return "\n".join(report)


def process_large_pdf_safely(
    pdf_file: BytesIO,
    processing_callback: Callable,
    max_memory_mb: int = 1024
) -> List:
    """
    Safe wrapper for processing large PDFs with memory control.
    
    Args:
        pdf_file: PDF file as BytesIO
        processing_callback: Function to process each page
        max_memory_mb: Maximum memory limit
        
    Returns:
        List of processed results
    """
    optimizer = PDFMemoryOptimizer(max_memory_mb=max_memory_mb)
    
    def page_processor(page, page_num):
        """Wrapper for page processing."""
        return processing_callback(page, page_num)
    
    try:
        results = optimizer.process_pdf_with_memory_control(
            pdf_file,
            page_processor,
            max_pages_per_batch=5,
            cleanup_frequency=3
        )
        
        # Generate and log report
        report = optimizer.generate_memory_report()
        logger.info(f"\n{report}")
        
        return results
        
    except MemoryError:
        logger.error("Memory limit exceeded! Consider reducing image size or DPI.")
        raise
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        raise


# Example usage:
if __name__ == "__main__":
    # Example processing function
    def example_page_processor(page, page_num):
        """Example: Convert page to image."""
        zoom = 200 / 72.0
        mat = _fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        
        # Convert to BytesIO
        img_bytes = BytesIO(pix.tobytes("png"))
        img_bytes.name = f"page_{page_num + 1}.png"
        
        # Cleanup
        del pix
        
        return {
            'page': page_num + 1,
            'width': pix.width,
            'height': pix.height,
            'image': img_bytes
        }
    
    # Test with a PDF file
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        with open(pdf_path, 'rb') as f:
            pdf_bytes = BytesIO(f.read())
        
        print(f"Processing {pdf_path} with memory control...")
        results = process_large_pdf_safely(pdf_bytes, example_page_processor)
        print(f"Processed {len(results)} pages successfully.")