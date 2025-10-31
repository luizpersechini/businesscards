"""
LLM Processor Module
Uses Ollama API to structure and validate contact information from OCR text.
"""

import requests
import json
from typing import Dict, Optional, List
import re


class LLMProcessor:
    """Processes OCR text using Ollama LLM to extract structured contact information."""
    
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        """
        Initialize the LLM processor.
        
        Args:
            base_url: Ollama API base URL
            model: Model name to use (default: llama3.2)
        """
        self.base_url = base_url
        self.model = model
        self.api_endpoint = f"{base_url}/api/generate"
    
    def is_ollama_running(self) -> bool:
        """
        Check if Ollama is running and accessible.
        
        Returns:
            True if Ollama is accessible, False otherwise
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def extract_contact_info(self, ocr_text: str, qr_data: Optional[Dict] = None) -> Dict:
        """
        Extract structured contact information from OCR text using LLM.
        
        Args:
            ocr_text: Raw OCR text from business card
            qr_data: Optional QR code data to supplement
            
        Returns:
            Dictionary with structured contact fields
        """
        # Build the prompt
        prompt = self._build_extraction_prompt(ocr_text, qr_data)
        
        # Call Ollama
        try:
            response = self._call_ollama(prompt)
            
            # Parse JSON response
            contact_data = self._parse_llm_response(response)
            
            # Validate and clean data
            contact_data = self._validate_contact_data(contact_data)
            
            return contact_data
        
        except Exception as e:
            # Fallback to basic extraction if LLM fails
            print(f"LLM processing failed: {e}. Using fallback extraction.")
            return self._fallback_extraction(ocr_text, qr_data)
    
    def _build_extraction_prompt(self, ocr_text: str, qr_data: Optional[Dict] = None) -> str:
        """
        Build a prompt for the LLM to extract contact information.
        
        Args:
            ocr_text: Raw OCR text
            qr_data: Optional QR code data
            
        Returns:
            Formatted prompt string
        """
        prompt = """You are an expert at extracting contact information from business cards. The text below was extracted using OCR and may contain errors or be in Portuguese/English.

Business Card Text:
---
{ocr_text}
---
""".format(ocr_text=ocr_text)
        
        if qr_data:
            prompt += f"\nQR Code Data (prioritize this over OCR if available):\n{json.dumps(qr_data, indent=2)}\n"
        
        prompt += """
Extract and return ONLY a valid JSON object with these fields. Use null for missing information:

{
  "firstName": "first name only",
  "lastName": "last name only",
  "fullName": "complete name (use this if you can't split first/last)",
  "title": "job title (e.g., CEO, Manager, Director, Engineer)",
  "company": "company or organization name",
  "email": "email address",
  "phone": "primary phone with country code if present",
  "mobile": "mobile/cell phone if different from main phone",
  "address": "street address",
  "city": "city name",
  "state": "state or province",
  "zip": "postal/ZIP code",
  "country": "country (Brasil, Brazil, etc.)",
  "website": "website URL",
  "linkedin": "LinkedIn URL",
  "notes": "any other relevant info"
}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON - no explanations, no markdown, no extra text
2. Look for patterns: Names usually at top, emails have @, phones have numbers/+
3. Portuguese titles: "Presidente" = President, "Diretor" = Director, "Gerente" = Manager
4. Phone format: Keep country code (+55 for Brazil), format as +55 (XX) XXXXX-XXXX
5. Fix OCR errors: "O" → "0" in numbers, "l" → "1" in numbers, remove extra spaces
6. Email validation: must have @ and domain
7. Company names: Often have "Ltda", "S.A.", "Inc", ministry names, government entities
8. Addresses: Look for street types (Rua, Avenida, Av.), numbers, CEP codes
9. If QR code data exists, use it as the primary source and fill gaps with OCR
10. Names in Portuguese may have multiple parts (e.g., "João da Silva Santos")

Return ONLY the JSON object, starting with { and ending with }
"""
        
        return prompt
    
    def _call_ollama(self, prompt: str, temperature: float = 0.1) -> str:
        """
        Call Ollama API to generate a response.
        
        Args:
            prompt: Input prompt
            temperature: Sampling temperature (lower = more deterministic)
            
        Returns:
            Generated response text
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "temperature": temperature,
            "format": "json"  # Request JSON output
        }
        
        response = requests.post(self.api_endpoint, json=payload, timeout=60)
        response.raise_for_status()
        
        result = response.json()
        return result.get('response', '')
    
    def _parse_llm_response(self, response: str) -> Dict:
        """
        Parse LLM response to extract JSON contact data.
        
        Args:
            response: Raw LLM response
            
        Returns:
            Parsed contact dictionary
        """
        # Try to find JSON in the response
        try:
            # First, try to parse the entire response as JSON
            return json.loads(response)
        except json.JSONDecodeError:
            # If that fails, try to extract JSON from the response
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
        
        # If all parsing fails, return empty dict
        return {}
    
    def _validate_contact_data(self, data: Dict) -> Dict:
        """
        Validate and clean contact data.
        
        Args:
            data: Raw contact data dictionary
            
        Returns:
            Validated and cleaned contact data
        """
        validated = {}
        
        # Clean up each field
        for key, value in data.items():
            if value is None or value == "null" or value == "":
                continue
            
            # Clean string values
            if isinstance(value, str):
                value = value.strip()
                
                # Validate email
                if key == 'email':
                    if not self._is_valid_email(value):
                        continue
                
                # Clean phone numbers
                elif key in ['phone', 'mobile']:
                    value = self._clean_phone_number(value)
                
                # Validate URLs
                elif key in ['website', 'linkedin']:
                    if not value.startswith('http'):
                        value = 'https://' + value
            
            validated[key] = value
        
        return validated
    
    def _is_valid_email(self, email: str) -> bool:
        """Check if email format is valid."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def _clean_phone_number(self, phone: str) -> str:
        """
        Clean and format phone number.
        
        Args:
            phone: Raw phone number string
            
        Returns:
            Cleaned phone number
        """
        # Remove common non-digit characters but keep + for international
        cleaned = re.sub(r'[^\d+\-\(\)\s]', '', phone)
        return cleaned.strip()
    
    def _fallback_extraction(self, ocr_text: str, qr_data: Optional[Dict] = None) -> Dict:
        """
        Fallback extraction method using regex patterns when LLM is unavailable.
        
        Args:
            ocr_text: Raw OCR text
            qr_data: Optional QR code data
            
        Returns:
            Basic contact data dictionary
        """
        contact_data = {}
        
        # Extract email
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, ocr_text)
        if emails:
            contact_data['email'] = emails[0]
        
        # Extract phone (various formats)
        phone_pattern = r'[\+]?[(]?\d{1,4}[)]?[-\s\.]?\d{1,4}[-\s\.]?\d{1,4}[-\s\.]?\d{1,9}'
        phones = re.findall(phone_pattern, ocr_text)
        if phones:
            contact_data['phone'] = phones[0]
        
        # Extract URLs
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, ocr_text)
        if urls:
            contact_data['website'] = urls[0]
        
        # Try to extract name (first line often contains name)
        lines = [line.strip() for line in ocr_text.split('\n') if line.strip()]
        if lines:
            # First non-empty line is often the name
            potential_name = lines[0]
            # Check if it looks like a name (not an email, phone, or URL)
            if not re.search(r'[@\d]', potential_name):
                contact_data['fullName'] = potential_name
        
        # Supplement with QR data if available
        if qr_data:
            contact_data.update(qr_data)
        
        return contact_data
    
    def correct_ocr_errors(self, text: str, context: str = 'general') -> str:
        """
        Use LLM to correct common OCR errors.
        
        Args:
            text: Text with potential OCR errors
            context: Context hint (e.g., 'phone', 'email', 'address')
            
        Returns:
            Corrected text
        """
        if not self.is_ollama_running():
            return text
        
        prompt = f"""Correct OCR errors in the following {context} text. Return ONLY the corrected text, nothing else.

Text: {text}

Corrected text:"""
        
        try:
            response = self._call_ollama(prompt, temperature=0.1)
            return response.strip()
        except:
            return text
    
    def get_available_models(self) -> List[str]:
        """
        Get list of available models from Ollama.
        
        Returns:
            List of model names
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [model['name'] for model in data.get('models', [])]
        except:
            pass
        
        return []

