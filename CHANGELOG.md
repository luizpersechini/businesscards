# Changelog

All notable changes to the Business Card Scanner project will be documented in this file.

## [1.0.0] - 2025-10-31

### 🎉 Initial Release

#### Added
- **Core Features**
  - Web-based interface using Streamlit
  - Multiple card detection modes (Improved Auto, Automatic, Manual Grid, Manual Single)
  - OCR text extraction with EasyOCR (English + Portuguese support)
  - QR code detection and decoding with pyzbar
  - LLM-powered contact parsing using Ollama
  - VCF file generation for Outlook contacts
  - Bulk processing with ZIP download

- **Detection Modes**
  - Improved Auto: Document scanner algorithm with perspective correction
  - Automatic: Contour-based detection with fallback
  - Manual Grid: Split images by rows/columns with adjustable margins
  - Manual Single: Process entire image as one card

- **User Interface**
  - Visual grid preview with overlay
  - Adjustable detection parameters (area %, margins)
  - Language selector for OCR (6 languages supported)
  - High contrast contact information display
  - Real-time processing feedback

- **Smart Processing**
  - Brazilian/Portuguese business card support
  - Phone number formatting (+55 country code)
  - OCR error correction (O→0, l→1 in numbers)
  - Company name recognition (Ltda, S.A., government entities)
  - Address parsing (Rua, Avenida, CEP codes)
  - QR code data prioritization over OCR

- **Documentation**
  - README with installation and usage instructions
  - QUICKSTART guide for beginners
  - TESTING guide with examples
  - Setup scripts (setup.sh, start_app.sh)

#### Technical Details
- **Dependencies**: Streamlit, OpenCV, EasyOCR, pyzbar, vobject, Ollama
- **Python Version**: 3.8+
- **Platform**: macOS (tested), Linux (should work), Windows (may need adjustments)
- **LLM Models**: Supports any Ollama model (llama3.2, mistral, etc.)

#### Known Limitations
- QR code reading requires zbar library and proper DYLD_LIBRARY_PATH
- Grid layout margins need manual adjustment for best results
- LLM quality varies by model selection
- Processing speed depends on OCR/LLM model sizes

---

## Future Versions

See the `improvements` branch for planned enhancements:
- Automatic margin detection
- Contact editing interface
- CSV/Excel export
- Duplicate detection
- Contact merging
- Cloud storage integration

