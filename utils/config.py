"""
Centralized configuration for Business Card Scanner.
Loads settings from environment variables with sensible defaults.
"""

import os
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class AppConfig:
    """
    Application configuration with defaults.
    Load from environment: AppConfig.from_env()
    """
    # Vision model configuration
    vision_model: str = "qwen2.5vl:7b"
    vision_timeout: int = 300  # 5 minutes - first load can be slow
    
    # Card detection configuration
    detection_mode: str = "Automatic"  # "Automatic", "Manual - Single Card", "Manual - Grid Layout"
    min_card_percent: int = 5  # Minimum card area as % of image
    max_card_percent: int = 40  # Maximum card area as % of image
    
    # Grid layout defaults
    grid_rows: int = 2
    grid_cols: int = 2
    
    # Margins for grid layout (percentage of image dimensions)
    margin_top: int = 0
    margin_bottom: int = 0
    margin_left: int = 0
    margin_right: int = 0
    
    # QR preprocessing variants (number of different preprocessing attempts)
    qr_preprocessing_variants: int = 5
    
    # Ollama configuration
    ollama_url: str = "http://localhost:11434"
    ollama_preload_enabled: bool = True
    ollama_preload_model: str = "qwen2.5vl:7b"

    # API endpoints for cloud providers
    vllm_url: str = "http://localhost:8000"
    
    # History and persistence
    history_base_dir: str = "temp"
    
    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None
    
    @classmethod
    def from_env(cls) -> "AppConfig":
        """
        Load configuration from environment variables.
        Falls back to defaults if not set.
        """
        return cls(
            vision_model=os.getenv("VISION_MODEL", "qwen2.5vl:7b"),
            vision_timeout=int(os.getenv("VISION_TIMEOUT", "300")),
            detection_mode=os.getenv("DETECTION_MODE", "Automatic"),
            min_card_percent=int(os.getenv("MIN_CARD_PERCENT", "5")),
            max_card_percent=int(os.getenv("MAX_CARD_PERCENT", "40")),
            grid_rows=int(os.getenv("GRID_ROWS", "2")),
            grid_cols=int(os.getenv("GRID_COLS", "2")),
            margin_top=int(os.getenv("MARGIN_TOP", "0")),
            margin_bottom=int(os.getenv("MARGIN_BOTTOM", "0")),
            margin_left=int(os.getenv("MARGIN_LEFT", "0")),
            margin_right=int(os.getenv("MARGIN_RIGHT", "0")),
            qr_preprocessing_variants=int(os.getenv("QR_PREPROCESSING_VARIANTS", "5")),
            ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            ollama_preload_enabled=os.getenv("OLLAMA_PRELOAD", "true").lower() == "true",
            ollama_preload_model=os.getenv("OLLAMA_PRELOAD_MODEL", "qwen2.5vl:7b"),
            vllm_url=os.getenv("VLLM_URL", "http://localhost:8000"),
            history_base_dir=os.getenv("HISTORY_BASE_DIR", "temp"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_file=os.getenv("LOG_FILE"),
        )
    
    def validate(self) -> List[str]:
        """
        Validate configuration and return list of errors (empty if valid).
        """
        errors = []
        
        if self.vision_timeout <= 0:
            errors.append("vision_timeout must be > 0")
        
        if self.min_card_percent <= 0 or self.min_card_percent > 50:
            errors.append("min_card_percent must be between 1 and 50")
        
        if self.max_card_percent < self.min_card_percent or self.max_card_percent > 100:
            errors.append("max_card_percent must be >= min_card_percent and <= 100")
        
        if self.grid_rows <= 0 or self.grid_cols <= 0:
            errors.append("grid_rows and grid_cols must be > 0")
        
        if self.detection_mode not in ["Automatic", "Manual - Single Card", "Manual - Grid Layout"]:
            errors.append(f"Invalid detection_mode: {self.detection_mode}")
        
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            errors.append(f"Invalid log_level: {self.log_level}")
        
        return errors
