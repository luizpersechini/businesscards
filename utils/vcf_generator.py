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
    
    def create_vcard(self, contact_data: Dict) -> vobject.vCard:
        """
        Create a vCard object from contact data.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            vobject.vCard object
        """
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
        vcard.n.value = vobject.vcard.Name(
            family=contact_data.get('lastName', ''),
            given=contact_data.get('firstName', '')
        )
        
        # Organization
        if contact_data.get('company'):
            vcard.add('org')
            vcard.org.value = [contact_data['company']]
        
        # Title
        if contact_data.get('title'):
            vcard.add('title')
            vcard.title.value = contact_data['title']
        
        # Email
        if contact_data.get('email'):
            email = vcard.add('email')
            email.value = contact_data['email']
            email.type_param = 'INTERNET'
        
        # Phone numbers
        if contact_data.get('phone'):
            tel = vcard.add('tel')
            tel.value = contact_data['phone']
            tel.type_param = ['WORK', 'VOICE']
        
        if contact_data.get('mobile'):
            mobile = vcard.add('tel')
            mobile.value = contact_data['mobile']
            mobile.type_param = ['CELL', 'VOICE']
        
        # Address
        if any(contact_data.get(field) for field in ['address', 'city', 'state', 'zip', 'country']):
            adr = vcard.add('adr')
            adr.type_param = 'WORK'
            adr.value = vobject.vcard.Address(
                street=contact_data.get('address', ''),
                city=contact_data.get('city', ''),
                region=contact_data.get('state', ''),
                code=contact_data.get('zip', ''),
                country=contact_data.get('country', '')
            )
        
        # Website
        if contact_data.get('website'):
            url = vcard.add('url')
            url.value = contact_data['website']
            url.type_param = 'WORK'
        
        # LinkedIn (as another URL)
        if contact_data.get('linkedin'):
            url = vcard.add('url')
            url.value = contact_data['linkedin']
            url.type_param = 'LinkedIn'
        
        # Notes
        if contact_data.get('notes'):
            note = vcard.add('note')
            note.value = contact_data['notes']
        
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
    
    def contact_to_filename(self, contact_data: Dict) -> str:
        """
        Generate a safe filename from contact data.
        
        Args:
            contact_data: Dictionary with contact information
            
        Returns:
            Safe filename string (without extension)
        """
        # Try to use name
        if contact_data.get('fullName'):
            name = contact_data['fullName']
        elif contact_data.get('firstName') or contact_data.get('lastName'):
            first = contact_data.get('firstName', '')
            last = contact_data.get('lastName', '')
            name = f"{first}_{last}".strip('_')
        elif contact_data.get('email'):
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

