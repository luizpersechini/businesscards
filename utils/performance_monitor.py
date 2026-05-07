"""
Performance Monitoring and Metrics
Tracks performance metrics for PDF processing, OCR, and overall application.
"""

import time
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single operation."""
    operation: str
    start_time: float
    end_time: float
    duration: float
    memory_usage_mb: float = 0.0
    success: bool = True
    error_message: str = ""
    metadata: Dict[str, Any] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = asdict(self)
        if self.metadata:
            result['metadata'] = self.metadata
        return result


@dataclass
class PDFProcessingMetrics:
    """Metrics specific to PDF processing."""
    pdf_name: str
    total_pages: int
    total_size_mb: float
    processing_time: float
    avg_page_time: float
    memory_peak_mb: float
    memory_avg_mb: float
    images_resized: int
    images_compressed: int
    ocr_pages_processed: int = 0
    ocr_success_rate: float = 0.0
    contacts_found: int = 0


class PerformanceMonitor:
    """
    Monitors and logs performance metrics.
    """
    
    def __init__(self, enable_logging: bool = True):
        self.enable_logging = enable_logging
        self.metrics: List[PerformanceMetrics] = []
        self.pdf_metrics: List[PDFProcessingMetrics] = []
        self._lock = threading.Lock()
        
        # Initialize counters
        self.counters = defaultdict(int)
        self.timers = {}
    
    def start_timer(self, operation: str) -> str:
        """
        Start a timer for an operation.
        
        Args:
            operation: Operation name
            
        Returns:
            Timer ID
        """
        timer_id = f"{operation}_{int(time.time() * 1000)}"
        self.timers[timer_id] = {
            'operation': operation,
            'start_time': time.time(),
            'memory_start': self._get_memory_usage()
        }
        return timer_id
    
    def stop_timer(self, timer_id: str, success: bool = True, 
                   error_message: str = "", metadata: Dict = None) -> PerformanceMetrics:
        """
        Stop a timer and record metrics.
        
        Args:
            timer_id: Timer ID from start_timer
            success: Whether operation succeeded
            error_message: Error message if failed
            metadata: Additional metadata
            
        Returns:
            PerformanceMetrics object
        """
        if timer_id not in self.timers:
            logger.warning(f"Timer {timer_id} not found")
            return None
        
        timer_data = self.timers[timer_id]
        end_time = time.time()
        memory_end = self._get_memory_usage()
        
        metrics = PerformanceMetrics(
            operation=timer_data['operation'],
            start_time=timer_data['start_time'],
            end_time=end_time,
            duration=end_time - timer_data['start_time'],
            memory_usage_mb=memory_end - timer_data['memory_start'],
            success=success,
            error_message=error_message,
            metadata=metadata or {}
        )
        
        with self._lock:
            self.metrics.append(metrics)
            self.counters[f"{timer_data['operation']}_{'success' if success else 'failure'}"] += 1
            
            # Remove timer
            del self.timers[timer_id]
        
        if self.enable_logging:
            self._log_metrics(metrics)
        
        return metrics
    
    def record_pdf_metrics(self, metrics: PDFProcessingMetrics):
        """
        Record PDF-specific metrics.
        
        Args:
            metrics: PDFProcessingMetrics object
        """
        with self._lock:
            self.pdf_metrics.append(metrics)
        
        if self.enable_logging:
            logger.info(f"PDF Processing: {metrics.pdf_name}, "
                       f"{metrics.total_pages} pages, "
                       f"{metrics.processing_time:.2f}s, "
                       f"{metrics.memory_peak_mb:.1f}MB peak")
    
    def increment_counter(self, counter_name: str, amount: int = 1):
        """
        Increment a counter.
        
        Args:
            counter_name: Counter name
            amount: Amount to increment
        """
        with self._lock:
            self.counters[counter_name] += amount
    
    def _get_memory_usage(self) -> float:
        """
        Get current memory usage in MB.
        
        Returns:
            Memory usage in MB
        """
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0
    
    def _log_metrics(self, metrics: PerformanceMetrics):
        """Log performance metrics."""
        level = logging.INFO if metrics.success else logging.WARNING
        
        log_message = (f"Performance: {metrics.operation} - "
                      f"{metrics.duration:.3f}s, "
                      f"memory: {metrics.memory_usage_mb:.1f}MB")
        
        if not metrics.success:
            log_message += f", error: {metrics.error_message}"
        
        if metrics.metadata:
            log_message += f", metadata: {json.dumps(metrics.metadata, default=str)}"
        
        logger.log(level, log_message)
    
    def get_summary(self) -> Dict:
        """
        Get performance summary.
        
        Returns:
            Dictionary with performance summary
        """
        with self._lock:
            if not self.metrics:
                return {"error": "No metrics recorded"}
            
            # Calculate overall statistics
            total_operations = len(self.metrics)
            successful_ops = sum(1 for m in self.metrics if m.success)
            failed_ops = total_operations - successful_ops
            
            avg_duration = sum(m.duration for m in self.metrics) / total_operations
            max_duration = max(m.duration for m in self.metrics)
            min_duration = min(m.duration for m in self.metrics)
            
            # Group by operation
            operations = {}
            for metric in self.metrics:
                op = metric.operation
                if op not in operations:
                    operations[op] = {
                        'count': 0,
                        'success': 0,
                        'failures': 0,
                        'total_duration': 0,
                        'avg_duration': 0,
                        'max_duration': 0,
                        'min_duration': float('inf')
                    }
                
                ops = operations[op]
                ops['count'] += 1
                ops['success'] += 1 if metric.success else 0
                ops['failures'] += 0 if metric.success else 1
                ops['total_duration'] += metric.duration
                ops['avg_duration'] = ops['total_duration'] / ops['count']
                ops['max_duration'] = max(ops['max_duration'], metric.duration)
                ops['min_duration'] = min(ops['min_duration'], metric.duration)
            
            # PDF-specific stats
            pdf_stats = {}
            if self.pdf_metrics:
                total_pdf_pages = sum(m.total_pages for m in self.pdf_metrics)
                total_pdf_time = sum(m.processing_time for m in self.pdf_metrics)
                avg_pdf_time_per_page = total_pdf_time / total_pdf_pages if total_pdf_pages > 0 else 0
                
                pdf_stats = {
                    'total_pdfs': len(self.pdf_metrics),
                    'total_pages': total_pdf_pages,
                    'total_processing_time': total_pdf_time,
                    'avg_time_per_page': avg_pdf_time_per_page,
                    'total_contacts_found': sum(m.contacts_found for m in self.pdf_metrics),
                    'total_ocr_pages': sum(m.ocr_pages_processed for m in self.pdf_metrics)
                }
            
            return {
                'timestamp': datetime.now().isoformat(),
                'total_operations': total_operations,
                'successful_operations': successful_ops,
                'failed_operations': failed_ops,
                'success_rate': (successful_ops / total_operations * 100) if total_operations > 0 else 0,
                'avg_duration_seconds': avg_duration,
                'max_duration_seconds': max_duration,
                'min_duration_seconds': min_duration,
                'operations': operations,
                'counters': dict(self.counters),
                'pdf_stats': pdf_stats,
                'total_metrics': len(self.metrics)
            }
    
    def generate_report(self) -> str:
        """
        Generate a human-readable performance report.
        
        Returns:
            Report string
        """
        summary = self.get_summary()
        
        report = [
            "📊 Performance Report",
            "=" * 50,
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Total Operations: {summary.get('total_operations', 0)}",
            f"Successful: {summary.get('successful_operations', 0)}",
            f"Failed: {summary.get('failed_operations', 0)}",
            f"Success Rate: {summary.get('success_rate', 0):.1f}%",
            f"Average Duration: {summary.get('avg_duration_seconds', 0):.3f}s",
            f"Max Duration: {summary.get('max_duration_seconds', 0):.3f}s",
            "",
            "Operations Breakdown:"
        ]
        
        for op_name, op_stats in summary.get('operations', {}).items():
            report.append(f"  {op_name}:")
            report.append(f"    Count: {op_stats['count']}")
            report.append(f"    Success: {op_stats['success']}")
            report.append(f"    Failures: {op_stats['failures']}")
            report.append(f"    Avg Time: {op_stats['avg_duration']:.3f}s")
            report.append(f"    Min/Max: {op_stats['min_duration']:.3f}s / {op_stats['max_duration']:.3f}s")
            report.append("")
        
        if summary.get('pdf_stats'):
            pdf_stats = summary['pdf_stats']
            report.extend([
                "PDF Processing:",
                f"  Total PDFs: {pdf_stats['total_pdfs']}",
                f"  Total Pages: {pdf_stats['total_pages']}",
                f"  Total Time: {pdf_stats['total_processing_time']:.1f}s",
                f"  Avg Time/Page: {pdf_stats['avg_time_per_page']:.3f}s",
                f"  Contacts Found: {pdf_stats['total_contacts_found']}",
                f"  OCR Pages: {pdf_stats['total_ocr_pages']}",
                ""
            ])
        
        report.append("Counters:")
        for counter_name, count in summary.get('counters', {}).items():
            report.append(f"  {counter_name}: {count}")
        
        return "\n".join(report)
    
    def save_report(self, filepath: str):
        """
        Save performance report to file.
        
        Args:
            filepath: Path to save report
        """
        report = self.generate_report()
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"Performance report saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save performance report: {e}")
    
    def save_metrics_json(self, filepath: str):
        """
        Save metrics as JSON.
        
        Args:
            filepath: Path to save JSON
        """
        summary = self.get_summary()
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, default=str)
            logger.info(f"Metrics JSON saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save metrics JSON: {e}")
    
    def clear(self):
        """Clear all metrics."""
        with self._lock:
            self.metrics.clear()
            self.pdf_metrics.clear()
            self.counters.clear()
            self.timers.clear()


# Global performance monitor instance
_performance_monitor = None

def get_performance_monitor() -> PerformanceMonitor:
    """Get global performance monitor instance."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor(enable_logging=True)
    return _performance_monitor


def measure_performance(operation_name: str):
    """
    Decorator to measure performance of a function.
    
    Args:
        operation_name: Name of the operation
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            monitor = get_performance_monitor()
            timer_id = monitor.start_timer(operation_name)
            
            try:
                result = func(*args, **kwargs)
                monitor.stop_timer(timer_id, success=True, metadata={
                    'args_count': len(args),
                    'kwargs_count': len(kwargs),
                    'function': func.__name__
                })
                return result
            except Exception as e:
                monitor.stop_timer(timer_id, success=False, error_message=str(e))
                raise
        
        return wrapper
    return decorator