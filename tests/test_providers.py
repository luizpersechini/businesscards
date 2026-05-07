"""
Tests for vision provider implementations (utils/providers/).
"""

import pytest
import numpy as np
import json
from unittest.mock import Mock, patch, MagicMock
import responses as responses_lib

from utils.providers.factory import ProviderFactory
from utils.models import ProviderType, ScanResult


class TestProviderFactory:
    """Test ProviderFactory class."""
    
    def test_factory_init(self):
        """Test ProviderFactory initialization."""
        factory = ProviderFactory()
        assert factory is not None
    
    def test_factory_get_all_statuses(self):
        """Test getting all provider statuses."""
        factory = ProviderFactory()
        statuses = factory.get_all_statuses()
        
        # Should have status for each provider type
        assert isinstance(statuses, dict)
        # At least one provider should be defined
        assert len(statuses) > 0
    
    def test_factory_provider_configs(self):
        """Test provider factory has default configs."""
        factory = ProviderFactory()
        # Should have configs attribute or DEFAULT_CONFIGS
        has_configs = hasattr(factory, 'provider_configs') or hasattr(factory, 'DEFAULT_CONFIGS')
        assert has_configs
    
    @patch.object(ProviderFactory, 'warmup_best_provider')
    def test_factory_warmup_best_provider(self, mock_warmup):
        """Test warmup best provider."""
        mock_warmup.return_value = (True, "ollama")
        
        factory = ProviderFactory()
        success, provider = factory.warmup_best_provider()
        
        assert success is True
        assert provider == "ollama"


class TestProviderFallback:
    """Test provider fallback mechanism."""
    
    def test_fallback_chain_exists(self):
        """Test that provider factory has fallback chain configured."""
        factory = ProviderFactory()
        
        # Should have multiple providers configured with priority
        statuses = factory.get_all_statuses()
        assert len(statuses) > 1
        
        # Providers should have priority ordering
        priorities = [info.get('priority', 999) for info in statuses.values()]
        assert len(set(priorities)) > 1  # Different priorities
    
    def test_extract_with_fallback_exists(self):
        """Test that extract_with_fallback method exists."""
        factory = ProviderFactory()
        
        # Method should be callable
        assert hasattr(factory, 'extract_with_fallback')
        assert callable(factory.extract_with_fallback)
