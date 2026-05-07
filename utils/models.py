"""
Data models for Business Card Scanner v2.0
Typed data models replacing raw dictionaries throughout the application.

Uses dataclasses (stdlib) for zero-dependency compatibility.
When pydantic is available, models gain automatic validation.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum


# ============================================================
# Enums
# ============================================================

class ProviderType(str, Enum):
    """Available vision/LLM providers."""
    OLLAMA = "ollama"
    VLLM = "vllm"
    CLAUDE = "claude"
    OPENAI = "openai"


class ProviderStatus(str, Enum):
    """Provider availability status."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


# ============================================================
# Data Models
# ============================================================

@dataclass
class Address:
    """Structured address model."""
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None

    def is_empty(self) -> bool:
        return not any([self.street, self.city, self.state, self.zip_code, self.country])

    def to_single_line(self) -> str:
        parts = [p for p in [self.street, self.city, self.state, self.zip_code, self.country] if p]
        return ", ".join(parts)


@dataclass
class ContactInfo:
    """
    Structured contact information extracted from a business card.
    This model is used as:
    - Schema reference for LLM structured outputs
    - Validation layer between modules
    - Data contract for providers and exporters
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[Address] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None
    notes: Optional[str] = None

    def __post_init__(self):
        """Validate and clean fields after initialization."""
        # Validate email
        if self.email and '@' not in self.email:
            self.email = None

        # Clean phone numbers
        if self.phone:
            cleaned = re.sub(r'[^\d+\-\(\)\s]', '', self.phone)
            self.phone = cleaned.strip() or None
        if self.mobile:
            cleaned = re.sub(r'[^\d+\-\(\)\s]', '', self.mobile)
            self.mobile = cleaned.strip() or None

        # Ensure URL prefix
        if self.website and not self.website.startswith('http'):
            self.website = 'https://' + self.website
        if self.linkedin and not self.linkedin.startswith('http'):
            self.linkedin = 'https://' + self.linkedin

    def get_display_name(self) -> str:
        if self.full_name:
            return self.full_name
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else "Unknown"

    def has_minimum_data(self) -> bool:
        return bool(self.full_name or self.first_name or self.last_name or self.email)

    def to_legacy_dict(self) -> dict:
        """Convert to legacy dictionary format for backward compatibility with existing modules."""
        d: Dict[str, str] = {}
        if self.first_name: d['firstName'] = self.first_name
        if self.last_name: d['lastName'] = self.last_name
        if self.full_name: d['fullName'] = self.full_name
        if self.title: d['title'] = self.title
        if self.company: d['company'] = self.company
        if self.email: d['email'] = self.email
        if self.phone: d['phone'] = self.phone
        if self.mobile: d['mobile'] = self.mobile
        if self.address and not self.address.is_empty():
            d['address'] = self.address.street or ''
            d['city'] = self.address.city or ''
            d['state'] = self.address.state or ''
            d['zip'] = self.address.zip_code or ''
            d['country'] = self.address.country or ''
        if self.website: d['website'] = self.website
        if self.linkedin: d['linkedin'] = self.linkedin
        if self.notes: d['notes'] = self.notes
        return d

    @classmethod
    def from_legacy_dict(cls, data: dict) -> "ContactInfo":
        """Create from legacy dictionary format."""
        address_obj = None
        if any(data.get(k) for k in ['address', 'city', 'state', 'zip', 'country']):
            address_obj = Address(
                street=data.get('address'),
                city=data.get('city'),
                state=data.get('state'),
                zip_code=data.get('zip'),
                country=data.get('country')
            )

        return cls(
            first_name=data.get('firstName'),
            last_name=data.get('lastName'),
            full_name=data.get('fullName'),
            title=data.get('title'),
            company=data.get('company'),
            email=data.get('email'),
            phone=data.get('phone'),
            mobile=data.get('mobile'),
            address=address_obj,
            website=data.get('website'),
            linkedin=data.get('linkedin'),
            notes=data.get('notes')
        )


@dataclass
class ScanResult:
    """Result of scanning a single business card."""
    contact: ContactInfo = field(default_factory=ContactInfo)
    confidence: float = 0.0
    provider_used: ProviderType = ProviderType.OLLAMA
    processing_time_ms: int = 0
    qr_data_used: bool = False
    source_file: Optional[str] = None
    error: Optional[str] = None


@dataclass
class BatchScanResult:
    """Result of scanning multiple business cards."""
    results: List[ScanResult] = field(default_factory=list)
    total_cards: int = 0
    successful: int = 0
    failed: int = 0
    total_time_ms: int = 0
    provider_used: ProviderType = ProviderType.OLLAMA


@dataclass
class ProviderConfig:
    """Configuration for a vision/LLM provider."""
    provider_type: ProviderType = ProviderType.OLLAMA
    model_name: str = "llama3.2-vision"
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: int = 120
    temperature: float = 0.1
    max_retries: int = 2
    priority: int = 0  # Lower = higher priority
    enabled: bool = True


@dataclass
class AppConfig:
    """Main application configuration."""
    providers: List[ProviderConfig] = field(default_factory=list)
    default_provider: ProviderType = ProviderType.OLLAMA
    detection_mode: str = "automatic"
    grid_rows: int = 1
    grid_cols: int = 1
    ms_graph_tenant_id: Optional[str] = None
    ms_graph_client_id: Optional[str] = None
    ms_graph_client_secret: Optional[str] = None
