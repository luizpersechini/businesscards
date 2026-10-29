"""
Tests for the configuration module (utils/config.py).
"""

import pytest
import os
from utils.config import AppConfig


class TestAppConfig:
    """Test AppConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = AppConfig()
        assert config.vision_model == "qwen2.5vl:7b"
        assert config.vision_timeout == 300
        assert config.min_card_percent == 2
        assert config.max_card_percent == 40
        assert config.grid_rows == 2
        assert config.grid_cols == 2
        assert config.ollama_url == "http://localhost:11434"
    
    def test_from_env_with_defaults(self):
        """Test loading config from environment with defaults."""
        config = AppConfig.from_env()
        assert config.vision_model == "qwen2.5vl:7b"  # Default value
        assert config.vision_timeout == 300
    
    def test_from_env_with_overrides(self, monkeypatch):
        """Test loading config from environment with overrides."""
        monkeypatch.setenv("VISION_MODEL", "llava:13b")
        monkeypatch.setenv("VISION_TIMEOUT", "120")
        monkeypatch.setenv("GRID_ROWS", "3")
        
        config = AppConfig.from_env()
        assert config.vision_model == "llava:13b"
        assert config.vision_timeout == 120
        assert config.grid_rows == 3
        assert config.grid_cols == 2  # Not overridden
    
    def test_from_env_boolean_parsing(self, monkeypatch):
        """Test parsing of boolean environment variables."""
        monkeypatch.setenv("OLLAMA_PRELOAD", "false")
        config = AppConfig.from_env()
        assert config.ollama_preload_enabled is False
        
        monkeypatch.setenv("OLLAMA_PRELOAD", "true")
        config = AppConfig.from_env()
        assert config.ollama_preload_enabled is True
    
    def test_validate_success(self):
        """Test validation with valid configuration."""
        config = AppConfig(
            vision_timeout=300,
            min_card_percent=5,
            max_card_percent=40,
            grid_rows=2,
            grid_cols=2,
        )
        errors = config.validate()
        assert errors == []
    
    def test_validate_invalid_timeout(self):
        """Test validation fails with invalid timeout."""
        config = AppConfig(vision_timeout=-1)
        errors = config.validate()
        assert len(errors) > 0
        assert any("timeout" in e.lower() for e in errors)
    
    def test_validate_invalid_card_percent(self):
        """Test validation fails with invalid card percentages."""
        config = AppConfig(min_card_percent=60, max_card_percent=40)
        errors = config.validate()
        assert len(errors) > 0
        assert any("card_percent" in e.lower() for e in errors)
    
    def test_validate_invalid_grid_dimensions(self):
        """Test validation fails with invalid grid dimensions."""
        config = AppConfig(grid_rows=0)
        errors = config.validate()
        assert len(errors) > 0
        assert any("grid" in e.lower() for e in errors)
    
    def test_validate_invalid_detection_mode(self):
        """Test validation fails with invalid detection mode."""
        config = AppConfig(detection_mode="Invalid Mode")
        errors = config.validate()
        assert len(errors) > 0
        assert any("detection_mode" in e.lower() for e in errors)
    
    def test_validate_invalid_log_level(self):
        """Test validation fails with invalid log level."""
        config = AppConfig(log_level="INVALID")
        errors = config.validate()
        assert len(errors) > 0
        assert any("log_level" in e.lower() for e in errors)
