"""
Vision-based contact extraction using Ollama's vision models.
This module sends card images directly to vision-capable LLMs for analysis.
"""

import base64
import json
import requests
from typing import Dict, Optional
import numpy as np
import cv2
from io import BytesIO
from PIL import Image


class VisionProcessor:
    """Process business card images using Ollama vision models."""
    
    def __init__(self, model: str = "llama3.2-vision", ollama_url: str = "http://localhost:11434"):
        """
        Initialize the vision processor.
        
        Args:
            model: Ollama vision model name (e.g., "llama3.2-vision", "llava")
            ollama_url: URL of the Ollama server
        """
        self.model = model
        self.ollama_url = ollama_url
        self.api_url = f"{ollama_url}/api/generate"
    
    def check_ollama_status(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return any(self.model in m.get('name', '') for m in models)
            return False
        except:
            return False
    
    def _image_to_base64(self, image: np.ndarray) -> str:
        """
        Convert OpenCV image (numpy array) to base64 string.
        
        Args:
            image: OpenCV image (BGR format)
            
        Returns:
            Base64 encoded image string
        """
        # Validate image
        if image is None or image.size == 0:
            raise ValueError("Invalid or empty image")
        
        # Ensure image is contiguous in memory
        if not image.flags['C_CONTIGUOUS']:
            image = np.ascontiguousarray(image)
        
        # Convert BGR to RGB (handle both BGR and grayscale)
        if len(image.shape) == 2:
            # Grayscale image
            rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        elif image.shape[2] == 3:
            # BGR image
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        elif image.shape[2] == 4:
            # BGRA image
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        else:
            raise ValueError(f"Unsupported image format with {image.shape[2]} channels")
        
        # Ensure proper data type
        if rgb_image.dtype != np.uint8:
            rgb_image = rgb_image.astype(np.uint8)
        
        # Convert to PIL Image
        pil_image = Image.fromarray(rgb_image)
        
        # Ensure reasonable size (max 4096 on either dimension)
        max_size = 4096
        if pil_image.width > max_size or pil_image.height > max_size:
            pil_image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        
        # Save to buffer with error handling
        buffer = BytesIO()
        try:
            pil_image.save(buffer, format="JPEG", quality=95, optimize=True)
        except Exception as e:
            # Try PNG as fallback
            buffer = BytesIO()
            pil_image.save(buffer, format="PNG", optimize=True)
        
        # Validate buffer
        img_bytes = buffer.getvalue()
        if len(img_bytes) == 0:
            raise ValueError("Failed to encode image: empty buffer")
        
        # Encode to base64
        return base64.b64encode(img_bytes).decode('utf-8')
    
    def _build_vision_prompt(self, qr_data: Optional[Dict] = None) -> str:
        """
        Build the prompt for vision model analysis.
        
        Args:
            qr_data: Optional QR code data to incorporate
            
        Returns:
            Prompt string for the vision model
        """
        prompt = """You are an expert at extracting contact information from business card images.

Analyze this business card image carefully and extract all visible contact information.

"""
        
        if qr_data:
            prompt += f"""QR CODE DATA FOUND (use this as primary source):
{json.dumps(qr_data, indent=2)}

"""
        
        prompt += """Extract and return ONLY a valid JSON object with these fields. Use null for missing information:

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
  "country": "country name",
  "website": "website URL",
  "linkedin": "LinkedIn URL",
  "notes": "any other relevant info"
}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON - no explanations, no markdown, no extra text
2. Look at the image carefully - read ALL visible text
3. Common patterns:
   - Names usually at top in larger/bold text
   - Emails have @ symbol
   - Phone numbers contain digits and may have +, (, ), -
   - Websites start with www. or http
4. Language support:
   - Portuguese titles: "Presidente" = President, "Diretor" = Director, "Gerente" = Manager
   - Phone format: Keep country code (+55 for Brazil), format as +55 (XX) XXXXX-XXXX
5. Address patterns:
   - Look for: Rua, Avenida, Av., Street, numbers, CEP, ZIP
6. Company identifiers:
   - Ltda, S.A., Inc, LLC, ministry names, government entities
7. If QR code data exists, use it as primary source and fill gaps from image
8. Handle rotated or skewed text as best as possible
9. Multiple names may indicate full name (e.g., "João da Silva Santos")
10. Look for social media icons and URLs (LinkedIn, Facebook, Twitter)

Return ONLY the JSON object, starting with { and ending with }. No markdown code blocks, no explanations.
"""
        
        return prompt
    
    def extract_contact_from_image(
        self,
        card_image: np.ndarray,
        qr_data: Optional[Dict] = None,
        timeout: int = 60
    ) -> Dict:
        """
        Extract contact information directly from card image using vision model.
        
        Args:
            card_image: OpenCV image of the business card
            qr_data: Optional QR code data
            timeout: Request timeout in seconds
            
        Returns:
            Dictionary containing extracted contact information
        """
        try:
            # Validate input
            if card_image is None:
                return {
                    "error": "Invalid input",
                    "message": "Card image is None"
                }
            
            # Convert image to base64
            try:
                image_b64 = self._image_to_base64(card_image)
            except Exception as e:
                return {
                    "error": "Image encoding failed",
                    "message": f"Could not convert image to JPEG/PNG: {str(e)}"
                }
            
            # Build prompt
            prompt = self._build_vision_prompt(qr_data)
            
            # Prepare request
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [image_b64],
                "stream": False,
                "options": {
                    "temperature": 0.1,  # Low temperature for consistent extraction
                    "top_p": 0.9
                }
            }
            
            # Make request to Ollama
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '').strip()
                
                # Try to parse JSON from response
                contact_data = self._parse_json_response(response_text)
                
                if contact_data:
                    return contact_data
                else:
                    return {
                        "error": "Failed to parse vision model response",
                        "raw_response": response_text[:500]
                    }
            else:
                return {
                    "error": f"Vision API error: {response.status_code}",
                    "message": response.text[:200]
                }
                
        except requests.exceptions.Timeout:
            return {
                "error": "Vision processing timeout",
                "message": "The vision model took too long to respond. Try a smaller/faster model."
            }
        except Exception as e:
            return {
                "error": "Vision processing failed",
                "message": str(e)
            }
    
    def _parse_json_response(self, response_text: str) -> Optional[Dict]:
        """
        Parse JSON from vision model response.
        Handles cases where model includes markdown or extra text.
        
        Args:
            response_text: Raw response from vision model
            
        Returns:
            Parsed JSON dict or None if parsing fails
        """
        # Try direct parse first
        try:
            return json.loads(response_text)
        except:
            pass
        
        # Try to extract JSON from markdown code blocks
        if "```json" in response_text:
            try:
                json_start = response_text.index("```json") + 7
                json_end = response_text.index("```", json_start)
                json_str = response_text[json_start:json_end].strip()
                return json.loads(json_str)
            except:
                pass
        
        # Try to find JSON object by looking for { }
        try:
            start = response_text.index('{')
            end = response_text.rindex('}') + 1
            json_str = response_text[start:end]
            return json.loads(json_str)
        except:
            pass
        
        return None
    
    def get_available_models(self) -> list:
        """Get list of available vision models from Ollama."""
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=2)
            if response.status_code == 200:
                models = response.json().get('models', [])
                # Filter for vision-capable models
                vision_keywords = ['vision', 'llava', 'bakllava', 'moondream']
                return [
                    m['name'] for m in models 
                    if any(keyword in m['name'].lower() for keyword in vision_keywords)
                ]
            return []
        except:
            return []

