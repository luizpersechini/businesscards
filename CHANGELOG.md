# Changelog

All notable changes to the Business Card Scanner project will be documented in this file.

## [2.0.0] — 2026-05

Major architectural change: **Streamlit removed; FastAPI + React is now the only frontend.**

### Added
- **`server.py`** — FastAPI backend with REST + SSE streaming for the scan pipeline.
- **React UI** under `frontend/index.html` (and `business-card-reader/project/`).
- **Stop button** on the scanner with `POST /api/scan/stop` + per-card cancellation checkpoints in `CardProcessor.process_batch`.
- **Edit contact** action in the Contacts tab — reuses the EditModal, optimistic update, `PUT /api/contacts/{id}`.
- **`PORT`** env var for choosing the FastAPI bind port (default 8501).
- **CI workflow** (`.github/workflows/ci.yml`) with pytest matrix on Python 3.10/3.11/3.12, system deps for libheif/tesseract/zbar.
- **`.env.example`** documenting `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MS_GRAPH_CLIENT_ID`, `MS_GRAPH_TENANT_ID`.
- **OCR parser tests** (`tests/test_ocr_parser.py`) covering CEP/phone disambiguation, name vs company swap, all-caps logos, etc.

### Changed
- `pyproject.toml` bumped to **2.0.0**.
- Provider package now uses relative imports (`from ..models import …`) instead of `sys.path.insert` hacks.
- Outlook OAuth token cache (`utils/ms_graph.py`) written with `0o600` permissions from creation.
- Claude Opus model ID corrected (`claude-opus-4-6` → `claude-opus-4-7`).
- `pillow>=10.3,<12` (CVE-2023-50447) and `numpy>=1.26,<3`.
- History list endpoint stops re-reversing the already-sorted result — newest runs now appear first.
- History persistence call signature corrected (was raising TypeError silently every scan).

### Removed
- `app.py` (Streamlit UI), `start_app.sh`, `tests/test_app.py`.
- Dead utils: `ocr_processor.py`, `csv_validator.py`, `logging_config.py`, `pdf_processor.py`, `pdf_memory_optimizer.py`, `performance_monitor.py`.
- Stale session/roadmap docs: `IMPLEMENTATION_SUMMARY.md`, `SESSION_SUMMARY.md`, `IMPROVEMENTS.md`, `DESIGN_IMPLEMENTATION_SUMMARY.md`.

# [Unreleased]

### 🗂️ Scan History & Persistence

#### Added
- **History Manager** (`utils/history_manager.py`): Persists each processing run with metadata, original uploads, per-card artifacts, and export files.
- **Scan History UI**: Filterable archive with summary view, ZIP download, reprocess, and delete actions.
- **Automated Tests** (`tests/test_history_manager.py`): Covers metadata persistence, card updates, export tracking, and ZIP packaging.

#### Changed
- Processing pipeline now saves every run automatically and keeps history entries in sync when cards are retried or locked.
- Streamlit interface exposes the archive with date/status filters and per-entry actions.

---

## [1.3.0] - 2025-11-03

### 🎨 UI Improvements & Code Cleanup

#### Added
- **CSV Validator Module** (`utils/csv_validator.py`): Diagnostic tool for Outlook CSV compatibility
  - Validates CSV format, encoding, line endings, and field names
  - Generates detailed diagnostic reports
  - Detects common import issues
- **Test CSV Generator** (`test_csv_generation.py`): Generate test CSV files for Outlook compatibility testing
- **Exact Outlook CSV Format**: CSV export now matches Outlook's native export format exactly
  - 61 columns in exact Outlook order
  - Field positions match Outlook expectations (E-mail Address at position 9, Business Phone at position 14)
  - Based on analysis of actual Outlook CSV exports

#### Changed
- **UI Cleanup**: Major interface reorganization
  - Removed regular CSV export option (kept only Outlook CSV)
  - Individual cards now displayed as compact list format with smaller icons
  - Better visual separation between Individual Cards Management and Bulk Downloads sections
  - Export format selection simplified (VCF, Excel, Outlook CSV only)
- **Vision Mode Only**: Removed OCR+LLM processing mode
  - Application now uses Vision mode exclusively for better accuracy
  - Simplified sidebar configuration
  - Removed all OCR and LLM processor dependencies
- **Default Vision Model**: Changed to `llava:13b` (most accurate)
  - Previously defaulted to `llama3.2-vision`
  - Better extraction quality out of the box
- **Detection Mode Renamed**: "Improved Auto (Recommended)" renamed to "Automatic"
  - More intuitive naming
  - Removed old "Automatic" detection mode (based on CardDetector)
  - Only uses ImprovedCardDetector for automatic detection
- **Outlook CSV Format Options**: Added configurable field names
  - Support for "E-mail Address", "Email Address", or "Email"
  - Support for "Business Phone", "Phone", or "Work Phone"
  - Simplified format option for maximum compatibility
  - Quote/no-quote options for troubleshooting

#### Removed
- **OCR+LLM Mode**: Completely removed OCR+LLM processing option
  - Removed `OCRProcessor` imports and initialization
  - Removed `LLMProcessor` imports and initialization
  - Removed OCR language selection UI
  - Removed LLM model selection for OCR mode
- **Old Automatic Detection**: Removed legacy `CardDetector` mode
  - Removed `CardDetector` imports
  - Only uses `ImprovedCardDetector` for automatic detection
- **Regular CSV Export**: Removed standard CSV option
  - Users can still export to Excel or use Outlook CSV
  - Outlook CSV is now the primary CSV format

#### Fixed
- **Outlook CSV Import**: Fixed email and phone field import issues
  - CSV format now matches Outlook export exactly (tested successfully)
  - Proper field ordering and naming ensures automatic mapping
  - Email and phone fields now import correctly to Outlook

#### Technical
- Simplified codebase by removing unused OCR/LLM processing paths
- Reduced dependencies (no longer need OCRProcessor/LLMProcessor for main flow)
- Better separation of concerns in export module
- CSV validator enables troubleshooting import issues

## [1.2.0] - 2025-10-31

### 🆕 Major Feature: Multiple Export Formats

#### Added - Export Formats
- **CSV Export**: Universal spreadsheet format for Excel/Google Sheets
  - Includes source file column
  - UTF-8 encoding for international characters
  - Compatible with all spreadsheet applications
- **Excel (XLSX) Export**: Professional formatted workbooks
  - Auto-sized columns for readability
  - Bold header row
  - Optimized column widths (max 50 chars)
  - Native Excel format with openpyxl
- **Outlook Import CSV**: Special format for direct Outlook import
  - Outlook-specific column names (Business Phone, Job Title, etc.)
  - UTF-8 with BOM for perfect Excel/Outlook compatibility
  - Pre-formatted for seamless import workflow
- **Complete Export Package**: One-click ZIP download
  - Combines all selected formats
  - Individual VCF files in dedicated folder
  - Timestamped bulk exports (CSV, XLSX, Outlook CSV)
  - User selects which formats to include

#### Added - Export UI Enhancements
- **Format Selection Checkboxes**: Choose VCF, CSV, Excel, or Outlook CSV
- **Export Statistics**: Summary showing contacts with email/phone/company
- **Helpful Tooltips**: Explains each export format's purpose
- **Organized Layout**: Individual files on left, bulk downloads on right
- **Smart Defaults**: VCF and CSV enabled by default

#### Added - New Module
- `utils/export_processor.py`: Unified export handling
  - `contacts_to_dataframe()`: Convert contacts to pandas DataFrame
  - `export_to_csv()`: Generate CSV with optional source column
  - `export_to_excel()`: Create formatted XLSX workbooks
  - `export_to_outlook_csv()`: Outlook-compatible CSV format
  - `create_export_package()`: Multi-format ZIP generator
  - `get_export_stats()`: Calculate contact statistics

#### Changed
- Download section reorganized for better UX
- Export options now customizable per user preference
- ZIP package now includes multiple formats, not just VCF

#### Dependencies
- Added `pandas==2.0.3` for data manipulation
- Added `openpyxl==3.1.2` for Excel file generation

#### Benefits
- ✅ Import contacts into CRM systems via CSV
- ✅ Share formatted contact lists in Excel
- ✅ Direct Outlook import without VCF hassles
- ✅ Choose only the formats you need
- ✅ One download for all formats

---

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

#### Configuration
- **Configurable Timeout**: 60-300 seconds (default: 180s/3 min)
- Timeout slider in sidebar for user customization
- Visible timeout feedback in processing spinner

#### Trade-offs
- ⚠️ Slower: 30-60s per card vs 5-10s for OCR mode
- ⚠️ Higher memory usage (~4-8GB VRAM recommended)
- ⚠️ Requires vision model: `ollama pull llama3.2-vision`

#### Production Ready
- ✅ Handles 7+ cards in batch processing
- ✅ QR code fallback for timeout errors
- ✅ Robust error handling with graceful degradation
- ✅ All None/null values sanitized for VCF generation
- ✅ PNG encoding eliminates image format issues

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
