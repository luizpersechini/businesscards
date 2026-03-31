"""
VCF Generator Module
Creates VCF (vCard) files from contact information for import into Outlook and other contact managers.
"""

import vobject
from typing import Dict, List
from datetime import datetime
import os


class VCFGenerator:
    """Generates VCF files from structured contact data."""
    
    def __init__(self):
        """Initialize the VCF generator."""
        pass
    
    def _sanitize_contact_data(self, contact_data: Dict) -> Dict:
        """
        Sanitize contact data by replacing None values with empty strings.
        
        Args:
            contact_data: Raw contact data dictionary
            
        Returns:
            Sanitized contact data dictionary
        """
        sanitized = {}
        for key, value in contact_data.items():
            if value is None or value == 'null' or value == 'None':
                sanitized[key] = ''
            elif isinstance(value, str):
                sanitized[key] = value.strip()
            else:
                sanitized[key] = value
        return sanitized
    
    def create_vcard(self, contact_data: Dict) -> vobject.vCard:
        """
        Create a vCard object from contact data.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            vobject.vCard object
        """
        # Sanitize contact data first
        contact_data = self._sanitize_contact_data(contact_data)
        
        # Create new vCard
        vcard = vobject.vCard()
        
        # Version (required)
        vcard.add('version')
        vcard.version.value = '3.0'
        
        # Full name (required)
        vcard.add('fn')
        if 'fullName' in contact_data and contact_data['fullName']:
            vcard.fn.value = contact_data['fullName']
        elif 'firstName' in contact_data or 'lastName' in contact_data:
            first = contact_data.get('firstName', '')
            last = contact_data.get('lastName', '')
            vcard.fn.value = f"{first} {last}".strip()
        else:
            vcard.fn.value = "Unknown"
        
        # Structured name (N)
        vcard.add('n')
        last_name = contact_data.get('lastName', '') or ''
        first_name = contact_data.get('firstName', '') or ''
        vcard.n.value = vobject.vcard.Name(
            family=last_name,
            given=first_name
        )
        
        # Organization
        company = contact_data.get('company')
        if company and company.strip():
            vcard.add('org')
            vcard.org.value = [company.strip()]
        
        # Title
        title = contact_data.get('title')
        if title and title.strip():
            vcard.add('title')
            vcard.title.value = title.strip()
        
        # Email
        email_val = contact_data.get('email')
        if email_val and email_val.strip():
            email = vcard.add('email')
            email.value = email_val.strip()
            email.type_param = 'INTERNET'
        
        # Phone numbers
        phone_val = contact_data.get('phone')
        if phone_val and phone_val.strip():
            tel = vcard.add('tel')
            tel.value = phone_val.strip()
            tel.type_param = ['WORK', 'VOICE']
        
        mobile_val = contact_data.get('mobile')
        if mobile_val and mobile_val.strip():
            mobile = vcard.add('tel')
            mobile.value = mobile_val.strip()
            mobile.type_param = ['CELL', 'VOICE']
        
        # Address
        address_fields = {
            'address': contact_data.get('address', '') or '',
            'city': contact_data.get('city', '') or '',
            'state': contact_data.get('state', '') or '',
            'zip': contact_data.get('zip', '') or '',
            'country': contact_data.get('country', '') or ''
        }
        
        if any(v.strip() for v in address_fields.values()):
            adr = vcard.add('adr')
            adr.type_param = 'WORK'
            adr.value = vobject.vcard.Address(
                street=address_fields['address'],
                city=address_fields['city'],
                region=address_fields['state'],
                code=address_fields['zip'],
                country=address_fields['country']
            )
        
        # Website
        website_val = contact_data.get('website')
        if website_val and website_val.strip():
            url = vcard.add('url')
            url.value = website_val.strip()
            url.type_param = 'WORK'
        
        # LinkedIn (as another URL)
        linkedin_val = contact_data.get('linkedin')
        if linkedin_val and linkedin_val.strip():
            url = vcard.add('url')
            url.value = linkedin_val.strip()
            url.type_param = 'LinkedIn'
        
        # Notes
        notes_val = contact_data.get('notes')
        if notes_val and notes_val.strip():
            note = vcard.add('note')
            note.value = notes_val.strip()
        
        # Add revision timestamp
        vcard.add('rev')
        vcard.rev.value = datetime.now().strftime('%Y%m%dT%H%M%SZ')
        
        return vcard
    
    def generate_vcf_string(self, contact_data: Dict) -> str:
        """
        Generate VCF file content as a string.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            VCF file content as string
        """
        vcard = self.create_vcard(contact_data)
        return vcard.serialize()
    
    def generate_vcf_file(self, contact_data: Dict, filename: str) -> str:
        """
        Generate and save a VCF file.
        
        Args:
            contact_data: Dictionary with contact information
            filename: Output filename (without .vcf extension)
            
        Returns:
            Full path to the created file
        """
        vcf_content = self.generate_vcf_string(contact_data)
        
        # Ensure filename ends with .vcf
        if not filename.endswith('.vcf'):
            filename = f"{filename}.vcf"
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(vcf_content)
        
        return filename
    
    def generate_bulk_vcf(self, contacts: List[Dict], filename: str = "contacts.vcf") -> str:
        """
        Generate a single VCF file containing multiple contacts.
        
        Args:
            contacts: List of contact data dictionaries
            filename: Output filename
            
        Returns:
            Full path to the created file
        """
        vcf_content = ""
        
        for contact_data in contacts:
            vcard = self.create_vcard(contact_data)
            vcf_content += vcard.serialize() + "\n"
        
        # Ensure filename ends with .vcf
        if not filename.endswith('.vcf'):
            filename = f"{filename}.vcf"
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(vcf_content)
        
        return filename
    
    # Known placeholder strings returned by LLMs when extraction fails.
    # Any value matching these patterns is ignored for filename generation.
    _PLACEHOLDER_FRAGMENTS = [
        "use this if you can't",
        "complete name",
        "company or organization",
        "job title",
        "email address",
        "primary phone",
        "mobile/cell",
        "street address",
        "any other relevant",
    ]

    @classmethod
    def _is_placeholder(cls, value: str) -> bool:
        """Return True if value looks like an LLM schema placeholder, not real data."""
        if not value or not isinstance(value, str):
            return True
        v = value.lower()
        # Placeholder strings tend to be long and contain parentheses
        if any(frag in v for frag in cls._PLACEHOLDER_FRAGMENTS):
            return True
        # Real names are rarely longer than 60 chars
        if len(value) > 60:
            return True
        return False

    def contact_to_filename(self, contact_data: Dict) -> str:
        """
        Generate a safe filename from contact data.

        Args:
            contact_data: Dictionary with contact information

        Returns:
            Safe filename string (without extension)
        """
        # Try to use name — skip if it looks like a placeholder
        if contact_data.get('fullName') and not self._is_placeholder(contact_data['fullName']):
            name = contact_data['fullName']
        elif (contact_data.get('firstName') or contact_data.get('lastName')) and \
             not self._is_placeholder(contact_data.get('firstName', '') + contact_data.get('lastName', '')):
            first = contact_data.get('firstName', '')
            last = contact_data.get('lastName', '')
            name = f"{first}_{last}".strip('_')
        elif contact_data.get('email') and not self._is_placeholder(contact_data.get('email', '')):
            name = contact_data['email'].split('@')[0]
        else:
            name = f"contact_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Clean filename (remove special characters)
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_name = safe_name.replace(' ', '_')
        
        return safe_name
    
    def validate_contact_data(self, contact_data: Dict) -> bool:
        """
        Check if contact data has minimum required fields for a valid vCard.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            True if valid, False otherwise
        """
        # Must have at least a name or email
        has_name = (
            contact_data.get('fullName') or 
            contact_data.get('firstName') or 
            contact_data.get('lastName')
        )
        has_email = contact_data.get('email')
        
        return has_name or has_email
    
    def preview_vcard(self, contact_data: Dict) -> str:
        """
        Generate a human-readable preview of the contact data.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            Formatted string with contact information
        """
        lines = []
        
        # Name
        if contact_data.get('fullName'):
            lines.append(f"Name: {contact_data['fullName']}")
        elif contact_data.get('firstName') or contact_data.get('lastName'):
            first = contact_data.get('firstName', '')
            last = contact_data.get('lastName', '')
            lines.append(f"Name: {first} {last}".strip())
        
        # Title and Company
        if contact_data.get('title'):
            lines.append(f"Title: {contact_data['title']}")
        if contact_data.get('company'):
            lines.append(f"Company: {contact_data['company']}")
        
        # Contact info
        if contact_data.get('email'):
            lines.append(f"Email: {contact_data['email']}")
        if contact_data.get('phone'):
            lines.append(f"Phone: {contact_data['phone']}")
        if contact_data.get('mobile'):
            lines.append(f"Mobile: {contact_data['mobile']}")
        
        # Address
        address_parts = []
        if contact_data.get('address'):
            address_parts.append(contact_data['address'])
        if contact_data.get('city'):
            address_parts.append(contact_data['city'])
        if contact_data.get('state'):
            address_parts.append(contact_data['state'])
        if contact_data.get('zip'):
            address_parts.append(contact_data['zip'])
        if contact_data.get('country'):
            address_parts.append(contact_data['country'])
        
        if address_parts:
            lines.append(f"Address: {', '.join(address_parts)}")
        
        # URLs
        if contact_data.get('website'):
            lines.append(f"Website: {contact_data['website']}")
        if contact_data.get('linkedin'):
            lines.append(f"LinkedIn: {contact_data['linkedin']}")
        
        # Notes
        if contact_data.get('notes'):
            lines.append(f"Notes: {contact_data['notes']}")
        
        return "\n".join(lines) if lines else "No contact information available"

