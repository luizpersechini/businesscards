"""
Vision/LLM Provider abstraction layer.
Implements Strategy Pattern for swappable AI backends.
Priority: Local (Ollama, vLLM) > Cloud (Claude, OpenAI)
"""

from .base import VisionProvider
from .ollama_provider import OllamaVisionProvider
from .vllm_provider import VLLMVisionProvider
from .claude_provider import ClaudeVisionProvider
from .openai_provider import OpenAIVisionProvider
from .factory import ProviderFactory

__all__ = [
    "VisionProvider",
    "OllamaVisionProvider",
    "VLLMVisionProvider",
    "ClaudeVisionProvider",
    "OpenAIVisionProvider",
    "ProviderFactory",
]
