"""
Provider Factory - Implements LOCAL-FIRST provider selection.
Tries providers in priority order: Ollama > vLLM > Claude > OpenAI
Supports automatic fallback when a provider fails.
"""

import time
import numpy as np
from typing import Optional, Dict, List, Tuple
import logging

from .base import VisionProvider
from .ollama_provider import OllamaVisionProvider
from .vllm_provider import VLLMVisionProvider
from .claude_provider import ClaudeVisionProvider
from .openai_provider import OpenAIVisionProvider

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import (
    ProviderType, ProviderStatus, ProviderConfig,
    ScanResult, BatchScanResult, ContactInfo
)


logger = logging.getLogger(__name__)


class ProviderFactory:
    """
    Factory for creating and managing vision providers.
    Implements LOCAL-FIRST strategy with automatic fallback.

    Priority order (configurable):
    1. Ollama (local, free, requires GPU)
    2. vLLM (local, free, requires GPU)
    3. Claude API (cloud, paid, no GPU needed)
    4. OpenAI API (cloud, paid, no GPU needed)
    """

    # Default provider configurations with LOCAL FIRST priority
    DEFAULT_CONFIGS = [
        ProviderConfig(
            provider_type=ProviderType.OLLAMA,
            model_name="glm-ocr",
            api_url="http://localhost:11434",
            timeout=300,  # 5 min — first load can be slow on CPU/low VRAM
            priority=0,
            enabled=True,
        ),
        ProviderConfig(
            provider_type=ProviderType.VLLM,
            model_name="llava-hf/llava-v1.6-mistral-7b-hf",
            api_url="http://localhost:8000",
            timeout=300,
            priority=1,
            enabled=True,
        ),
        ProviderConfig(
            provider_type=ProviderType.CLAUDE,
            model_name="claude-sonnet-4-6",
            timeout=30,
            priority=10,
            enabled=True,
        ),
        ProviderConfig(
            provider_type=ProviderType.OPENAI,
            model_name="gpt-4o",
            timeout=30,
            priority=20,
            enabled=True,
        ),
    ]

    PROVIDER_CLASSES = {
        ProviderType.OLLAMA: OllamaVisionProvider,
        ProviderType.VLLM: VLLMVisionProvider,
        ProviderType.CLAUDE: ClaudeVisionProvider,
        ProviderType.OPENAI: OpenAIVisionProvider,
    }

    def __init__(self, configs: Optional[List[ProviderConfig]] = None):
        """
        Initialize with optional custom configs.
        If None, uses DEFAULT_CONFIGS with local-first priority.
        """
        self.configs = configs or self.DEFAULT_CONFIGS.copy()
        self.configs.sort(key=lambda c: c.priority)
        self._providers: Dict[ProviderType, VisionProvider] = {}
        self._availability_cache: Dict[ProviderType, Tuple[ProviderStatus, float]] = {}
        self._cache_ttl = 30  # seconds

    def _get_or_create_provider(self, config: ProviderConfig) -> VisionProvider:
        """Get or create a provider instance."""
        if config.provider_type not in self._providers:
            cls = self.PROVIDER_CLASSES.get(config.provider_type)
            if cls:
                self._providers[config.provider_type] = cls(config)
        return self._providers.get(config.provider_type)

    def check_provider_status(self, provider_type: ProviderType) -> ProviderStatus:
        """Check availability with caching."""
        now = time.time()
        cached = self._availability_cache.get(provider_type)
        if cached and (now - cached[1]) < self._cache_ttl:
            return cached[0]

        config = next((c for c in self.configs if c.provider_type == provider_type), None)
        if not config or not config.enabled:
            return ProviderStatus.UNAVAILABLE

        provider = self._get_or_create_provider(config)
        if not provider:
            return ProviderStatus.UNAVAILABLE

        status = provider.check_availability()
        self._availability_cache[provider_type] = (status, now)
        return status

    def get_all_statuses(self) -> Dict[ProviderType, Dict]:
        """Get status of all configured providers."""
        statuses = {}
        for config in self.configs:
            provider = self._get_or_create_provider(config)
            status = self.check_provider_status(config.provider_type)
            statuses[config.provider_type] = {
                "status": status.value,
                "model": config.model_name,
                "priority": config.priority,
                "enabled": config.enabled,
                "error": provider.last_error if provider else "Provider not created",
                "is_local": config.provider_type in (ProviderType.OLLAMA, ProviderType.VLLM),
            }
        return statuses

    def get_best_provider(self, preferred: Optional[ProviderType] = None) -> Optional[VisionProvider]:
        """
        Get the best available provider following LOCAL-FIRST priority.

        If preferred is specified and available, use it.
        Otherwise, try providers in priority order.
        """
        # Try preferred first
        if preferred:
            status = self.check_provider_status(preferred)
            if status == ProviderStatus.AVAILABLE:
                config = next((c for c in self.configs if c.provider_type == preferred), None)
                if config:
                    return self._get_or_create_provider(config)

        # Try in priority order (local first)
        for config in self.configs:
            if not config.enabled:
                continue
            status = self.check_provider_status(config.provider_type)
            if status == ProviderStatus.AVAILABLE:
                logger.info(f"Selected provider: {config.provider_type.value} (priority {config.priority})")
                return self._get_or_create_provider(config)

        return None

    def extract_with_fallback(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
        preferred: Optional[ProviderType] = None,
        timeout: Optional[int] = None,
    ) -> ScanResult:
        """
        Extract contact with automatic fallback through providers.
        Tries each provider in priority order until one succeeds.
        """
        errors = []

        # Build ordered list: preferred first, then by priority
        ordered_configs = sorted(self.configs, key=lambda c: c.priority)
        if preferred:
            ordered_configs = sorted(
                ordered_configs,
                key=lambda c: (0 if c.provider_type == preferred else 1, c.priority)
            )

        LOCAL_PROVIDERS = (ProviderType.OLLAMA, ProviderType.VLLM)

        for config in ordered_configs:
            if not config.enabled:
                continue

            status = self.check_provider_status(config.provider_type)
            if status != ProviderStatus.AVAILABLE:
                provider = self._providers.get(config.provider_type)
                err = provider.last_error if provider else "unavailable"
                errors.append(f"{config.provider_type.value}: {err}")
                continue

            provider = self._get_or_create_provider(config)
            if not provider:
                continue

            # Only apply UI timeout override to cloud providers.
            # Local providers (Ollama, vLLM) need their own (longer) timeouts.
            if timeout is not None and config.provider_type not in LOCAL_PROVIDERS:
                config.timeout = timeout

            logger.info(f"Trying provider: {config.provider_type.value} ({config.model_name})")
            result = provider.extract_contact(card_image, qr_data)

            if result.error is None and result.contact.has_minimum_data():
                return result

            errors.append(f"{config.provider_type.value}: {result.error}")
            logger.warning(f"Provider {config.provider_type.value} failed: {result.error}")

        # All providers failed
        return ScanResult(
            contact=ContactInfo(),
            confidence=0.0,
            provider_used=ProviderType.OLLAMA,
            processing_time_ms=0,
            error=f"All providers failed. Errors: {'; '.join(errors)}"
        )

    def batch_extract(
        self,
        card_images: List[np.ndarray],
        qr_data_list: Optional[List[Optional[Dict]]] = None,
        preferred: Optional[ProviderType] = None,
        progress_callback=None,
    ) -> BatchScanResult:
        """
        Extract contacts from multiple card images.
        Uses fallback strategy for each card independently.
        """
        start_time = time.time()

        if qr_data_list is None:
            qr_data_list = [None] * len(card_images)

        results = []
        successful = 0
        failed = 0
        provider_used = ProviderType.OLLAMA

        for i, (image, qr_data) in enumerate(zip(card_images, qr_data_list)):
            result = self.extract_with_fallback(image, qr_data, preferred)
            results.append(result)

            if result.error is None and result.contact.has_minimum_data():
                successful += 1
                provider_used = result.provider_used
            else:
                failed += 1

            if progress_callback:
                progress_callback(i + 1, len(card_images), result)

        total_ms = int((time.time() - start_time) * 1000)

        return BatchScanResult(
            results=results,
            total_cards=len(card_images),
            successful=successful,
            failed=failed,
            total_time_ms=total_ms,
            provider_used=provider_used,
        )

    def warmup_best_provider(self) -> Tuple[bool, str]:
        """
        Warm up the best available local provider so the model is loaded
        into RAM before the first real card is processed.
        Returns (success, provider_name).
        """
        for config in self.configs:
            if not config.enabled:
                continue
            if config.provider_type not in (ProviderType.OLLAMA, ProviderType.VLLM):
                continue
            status = self.check_provider_status(config.provider_type)
            if status != ProviderStatus.AVAILABLE:
                continue
            provider = self._get_or_create_provider(config)
            if provider and hasattr(provider, 'warmup'):
                ok = provider.warmup()
                return ok, config.provider_type.value
        return False, "none"

    def update_config(self, provider_type: ProviderType, **kwargs) -> None:
        """Update configuration for a specific provider."""
        for config in self.configs:
            if config.provider_type == provider_type:
                for key, value in kwargs.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
                # Clear cache
                self._availability_cache.pop(provider_type, None)
                self._providers.pop(provider_type, None)
                break
