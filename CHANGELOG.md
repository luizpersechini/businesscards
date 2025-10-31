# Changelog

All notable changes to the Business Card Scanner project will be documented in this file.

## [1.1.0] - 2025-10-31 (improvements branch)

### 🎯 Major Feature: Vision Mode

#### Added (Latest Updates)
- **Vision Processor Module** (`utils/vision_processor.py`)
  - Direct image analysis using Ollama vision models
  - Supports: llama3.2-vision, llava, llava:13b, bakllava
  - Base64 image encoding and API integration
  - Intelligent JSON parsing with multiple fallback methods
  - Timeout handling (90s default)
  - Better accuracy than OCR for complex layouts

- **Processing Mode Toggle**
  - "Vision (Recommended)" - Direct image analysis
  - "OCR + LLM" - Traditional pipeline (backward compatible)
  - Dynamic UI that shows relevant options per mode

- **Improved QR Code Detection**
  - OpenCV QR detector as fallback when pyzbar unavailable
  - Dual detection methods (pyzbar + OpenCV)
  - Multiple preprocessing attempts for difficult QR codes
  - Detection method indicator (shows which library found the code)
  - More reliable detection overall

#### Fixed (Bug Fixes)
- **PNG Encoding**: Switched from JPEG to PNG for better reliability (fixes "0xff00 sequence" errors)
- **VCF Generation**: Added `_sanitize_contact_data()` to handle None/null values from vision model
- **QR Fallback**: Auto-uses QR code data when vision processing times out or fails
- **Image Validation**: Comprehensive checks for empty, corrupted, or malformed images
- **Memory Handling**: Fixed non-contiguous array issues and multi-format support

#### Changed
- QR detection now always attempts to read codes (no more "disabled" state)
- Sidebar UI adapts based on processing mode selected
- Better error messages with actionable suggestions
- App initialization handles missing models gracefully
- Timeout errors now gracefully fallback to QR data if available

#### Benefits of Vision Mode
- ✅ No more OCR errors on rotated/skewed text
- ✅ Better handling of complex card layouts
- ✅ Understands context better than OCR + text parsing
- ✅ Reduces processing steps (no OCR needed)
- ✅ More accurate for handwritten notes
- ✅ Better multi-language support (vision models handle any language)

#### Trade-offs
- ⚠️ Slower: 30-60s per card vs 5-10s for OCR mode
- ⚠️ Higher memory usage (~4-8GB VRAM recommended)
- ⚠️ Requires vision model: `ollama pull llama3.2-vision`

---

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

See the `improvements` branch for ongoing enhancements and the `IMPROVEMENTS.md` file for the roadmap.
