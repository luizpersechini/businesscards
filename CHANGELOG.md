# Changelog

All notable changes to the Business Card Scanner project will be documented in this file.

## [2.1.5] — 2026-05-27

### Added

- **Persistent per-contact lock** in the contacts repository. Lock a contact (click the padlock icon next to Edit/Delete in the Contacts tab, or in the scan-result card view) to mark it as "the version of truth". Locked contacts survive future scans intact — see the new merge-or-conflict rule below.
- **Merge-or-conflict on re-scan of locked contacts.** When a new scan extracts a card whose email matches an existing **locked** repo contact:
  - **Additive fields** — any field the existing contact didn't have (e.g. phone, mobile, address) is merged in silently, and the VCF is regenerated to include them.
  - **Conflicting fields** — any field where existing and incoming disagree is recorded as a conflict and reported back to the UI. The existing value is preserved; nothing is overwritten.
- **Conflict-resolution banner** in the scan results panel. If any scanned card touched a locked existing contact:
  - Shows "Added fields to N locked contact(s)" for purely additive merges.
  - Shows "N field conflicts on M locked contact(s) — review below" with a **Show details** toggle that lists each conflict (`field: existing X vs new Y`) and what was added. Includes instructions on how to resolve (edit the saved contact, or unlock to allow overwrite).
- **`PUT /api/contacts/{id}/lock`** endpoint. Body: `{"locked": true|false}`.

### Changed

- `ContactsRepository.add_contact()` now returns a dict `{id, status, additions, conflicts, locked}` instead of just the contact id. `status` is one of `added`, `updated` (unlocked overwrite), `merged` (locked, additive only), `conflict` (locked, some values disagree). All callers in `server.py` updated; the public API responses now include `status`, `additions`, and `conflicts` where relevant.
- Unlocked contacts still follow the legacy "rescan overwrites" behaviour, so you can deliberately refresh extracted data by leaving a card unlocked.

### Documented

- `_MERGEABLE_FIELDS` is the canonical list of fields that participate in the merge-or-conflict comparison: `firstName`, `lastName`, `fullName`, `title`, `company`, `email`, `phone`, `mobile`, `website`, `linkedin`, `address`, `city`, `state`, `zip`, `country`, `notes`. Comparison normalises whitespace and case, so `"Acme Corp"` and `"acme  corp"` don't trip a conflict.

---

## [2.1.4] — 2026-05-26

### Improved

- **Website extraction in the OCR-parser path.** Previous regex was too narrow:
  - Required 3+ domain labels (`label.label.tld`), so bare `acme.com` / `itaubba.com` were missed.
  - TLD whitelist was only `com|br|net|org|io|ca|co|app` — `.gov`, `.gouv`, `.edu`, `.fr`, `.de`, `.it`, `.uk`, `.es`, `.gov.br`, etc. all slipped through.
  - First-match-wins: if a card had both a bare domain and an `https://` URL, the bare one was taken.
  - No prefix stripping: `URL: www.x.com` and `(www.x.com)` captured the extra chars.

  New behaviour: collects all candidates, picks the strongest by score (explicit `https://` scheme > `www.` prefix > longest). Strips leading `URL:` / `Web:` / `Site:` / `Link:` / `Homepage:` prefixes and trailing punctuation. Supports the full common-TLD list including country TLDs and government/academic domains. **Priority order is preserved**: email/linkedin lines are still consumed first, name/company classification still runs after URL extraction, so a URL line can never be claimed as a company name.

### Documented

- The codebase-wide field priority is now: **Name → Company → Email → Phone → Website → others.** Higher-priority fields claim lines first; lower-priority extractors only see what's left. This invariant is encoded in the parser's run order and called out in `_parse_ocr_to_contact`.

---

## [2.1.3] — 2026-05-26

### Fixed

- **HEIC uploads rejected with "File content does not match a supported image/PDF format".** The upload validator's magic-byte sniff only accepted two specific ISOBMFF `ftyp` box lengths (`0x18` and `0x1c`). HEIC files from newer iOS versions use other box lengths (`0x14`, `0x20`, etc.) depending on the brand list, so they tripped the validator before even reaching the loader. Validator now checks the brand at bytes 8–11 against the full HEIF/HEIC/AVIF brand set (`heic, heix, hevc, hevx, heim, heis, hevm, hevs, mif1, msf1, heif, avif, avis`) and ignores box length, matching ISOBMFF spec. WEBP detection also tightened to require the `WEBP` fourCC at byte 8 (not just `RIFF` anywhere in the first 16 bytes).

---

## [2.1.2] — 2026-05-26

### Fixed

- **Silent dependency-missing regression on phone & name extraction.** `phonenumbers` and `probablepeople` were declared in `requirements.txt` but never `pip install`ed into the runtime Python 3.9. Both per-card try-imports in `utils/providers/ollama_provider.py` (lines 498 and 597 in 2.1.1) had `except ImportError: pass` with no log — so the OCR parser silently dropped every phone field and fell back to brittle regex name/company detection on every scan, for an unknown number of runs. On a single test image this surfaced as 3/18 phones (vs 17/18 once libs were installed) and the `company: "São Paulo, SP, Brazil"` (address misclassified as company) symptom.

### Changed

- Replaced both per-call try/import blocks with **module-level availability probes** (`PHONENUMBERS_AVAILABLE`, `PROBABLEPEOPLE_AVAILABLE`) that run once at import time. If either lib is missing, an actionable `logger.error(...)` fires immediately at server startup pointing at the pip command to fix it — so the next silent-dependency regression is visible in `/tmp/bcr_server.log` instead of hiding behind empty fields. Per-card overhead drops from 18 imports per scan to 1.

---

## [2.1.1] — 2026-05-25

Bug-fix follow-up to 2.1.0. All three issues surfaced on `IMG_1544.heic` (6×3 Portuguese-language card layout).

### Fixed

- **Empty `fullName` on every extracted card.** Root cause: the vision LLM returns camelCase keys (`firstName`, `lastName`, `fullName`) via `ContactInfo.to_legacy_dict()`, but the server's frontend-mapper in `_contact_data_to_frontend` and `_contact_to_api` was reading **snake_case** (`full_name`) and never falling back to `firstName + lastName` concatenation. Title/company/email survived because they're single-word keys. Mapper now tries (in order): `fullName`, `full_name`, `firstName + lastName`, `first_name + last_name`, `name`. Applied to all three sites in `server.py`.
- **CJK-character contamination in Portuguese text.** GLM-OCR (Chinese-origin model) was substituting accented Latin characters with visually-vaguely-similar CJK ideographs: `é → 矇` (U+77C7), `ç → 癟` (U+765F), `ã → 瓊` (U+74CA). Three-pronged fix:
  1. Added explicit prompt rule in `utils/providers/base.py`: _"Use ONLY Latin characters with proper Western European accents. NEVER substitute non-Latin characters (Chinese, Japanese, Korean, etc.) for accented Latin letters."_
  2. New `repair_cjk_substitutions()` post-processor with a confirmed-substitution table (`_CJK_TO_LATIN`) and a CJK-range regex (`_CJK_RE`). Unknown CJK chars in Latin-context fields fall through to `?` so corruption is visible rather than silent.
  3. Applied at **three sites** (the QR-only short-circuit at `extract_contact:185` was the gotcha — it bypasses every vision provider, so the base-class repair never ran for QR-sufficient cards): `card_processor.extract_contact` (both return points) + `providers.base._make_scan_result`. All paths through `extract_contact` now repair before returning.

### Added

- **`POST /api/scan/export/{fmt}`** — exports the just-completed scan's cards directly, separate from the persistent contacts repository. Supports `vcf` (concatenated, uses pre-generated `vcfContent`), `xlsx`, `csv` (Outlook format), and `zip` (bundles all three + per-card individual VCFs under `per_card/`).
- Wired up every export button in the Results panel — they were UI-only placeholders before. **Export All** and **Download ZIP** hit `/api/scan/export/zip`; the **VCF / Excel / Outlook CSV** pills hit their respective formats. Each button shows a spinner while in-flight and disables when no cards or another export is running. Errors surface via `alert()`. The **+ Outlook Push** button is visibly disabled with `(soon)` and a tooltip — MS Graph integration is not yet wired.

---

## [2.1.0] — 2026-05-25

Detection & extraction overhaul aimed at photographed multi-card images (phone-camera shots, not just flatbed scans). Auto mode now reliably extracts every card in a 6×3 layout where it previously got 7/18.

### Added

- **Interactive preview phase** — between Upload and Extract. `POST /api/preview` runs detection-only (no LLM), returns an annotated JPEG + tile count + inferred grid dims. Lets you confirm tiling before committing to slow vision inference.
- **Draggable grid editor** (Grid mode) — `GridOverlay` React component renders dashed internal dividers + solid outer crop rectangle + drag handles. Move row/column lines, drag the 4 outer edges to crop margins, dim mask shows excluded area. Lines clamp at 2 % min gap; debounced re-preview fires 350 ms after any drag.
- **"Apply N×N grid" suggestion** — when Auto mode falls back to a grid layout, the preview returns the inferred `(rows, cols)` and a one-click banner offers to switch to Grid mode with those dims.
- **Auto-deskew toggle** — opt-in pre-detection warp via `_deskew_to_card_cluster()`: finds the convex region containing all cards using edge density + morphological close, then applies four-point perspective transform so cards become axis-aligned before detection. Skipped automatically if cluster is < 25 % of the image or rotation < 1.5°.
- **Per-tile card refinement** — `_refine_tile_to_card()` runs CLAHE + 3 parallel edge strategies (Canny low, Canny high, adaptive threshold) inside every grid tile to find the actual card boundary, then four-point-warps or tight-crops to it. Drops inter-card gap pixels that confuse the vision model.
- **Gap-detection regularization** — `_gap_detect_and_regularize()`: drops outer bands < 50 % of median height (margins), splits oversized bands > 160 % of median, and re-runs `_find_gap_positions()` _inside_ each oversized band to find the real missed gap (not just an equal split).
- **HEIC / HEIF / WEBP upload support** — file picker `accept` + drag-drop filter accept these formats; server falls back to Pillow + `pillow-heif` when `cv2.imdecode` returns None.
- **Inline error & warning banners** in the Scanner — replaces silent `console.error` failures. Per-event SSE `error`/`warning` stages now surface visibly in the right pane.

### Changed

- `_scan_generator` no longer calls `CardProcessor.process_batch()` directly. Auto / Single / Single-card-from-PDF all route through `_process_with_refinement()`, which keeps contour-based detections as-is (already perspective-corrected by the detector) but runs `_refine_tile_to_card()` on every contour-less rectangular tile.
- When Auto detector returns few cells (gap detection failing on a real grid), `_process_with_refinement()` overrides with `_gap_detect_and_regularize()` and refines each cell — this is what restored 18/18 extraction on `IMG_1544.heic`.
- Preview annotation skipped in Grid mode — server returns the raw JPEG and the React overlay draws _everything_ (boundaries, dim mask, drag handles, tile numbers). Eliminates the previous "double-rendering" mess where server-baked thick green lines overlapped with React's dashed lines.
- Auto preview uses gap-detection bounds instead of re-inferring a uniform grid from sample dimensions — the inferred grid dims now match what the detector actually used, not a fictional uniform grid.

### Fixed

- HEIC uploads from iPhone no longer fail with `Could not decode image: IMG_*.heic`.
- Preview now matches scan card count for Auto mode (was off by 5+ on photographed layouts because uniform-grid inference re-introduced phantom cells the detector had already filtered).
- Bottom row of cards in photographed grids no longer gets merged with the row above; the regularizer re-runs gap detection inside oversized bands to find the real divider.
- Scan timer / progress interval now clears on `done` and `error` events (was leaking until the component unmounted).

---

## [2.0.0] — 2026-05

Major architectural change: **Streamlit removed; FastAPI + React is now the only frontend.**

### Added

- **`server.py`** — FastAPI backend with REST + SSE streaming for the scan pipeline.
- **React UI** under `frontend/index.html` (and `business-card-reader/project/` design source).
- **Stop button** on the scanner with `POST /api/scan/stop` + per-card cancellation checkpoints in `CardProcessor.process_batch`.
- **Edit contact** action in the Contacts tab — reuses the EditModal, optimistic update, `PUT /api/contacts/{id}`.
- **MECARD support** in the QR parser, with widened "QR-sufficient" rules so vision is skipped more often.
- **Optional LLM post-correction pass** in the OCR parser pipeline.
- **`phonenumbers`** (Google libphonenumber) for international phone parsing — replaces ~40 lines of brittle BR-only regex.
- **`probablepeople`** (CRF) for name vs corporation classification — solves the "Banco do Brasil" / "Acme Corp" misclassification class.
- **Pydantic-style JSON schema** enforced via Ollama `format` for LLM vision models (guaranteed valid JSON output).
- **`qwen2.5vl`** added as fallback Ollama vision model.
- **`PORT`** env var for choosing the FastAPI bind port (default 8501).
- **CI workflow** (`.github/workflows/ci.yml`) with pytest matrix on Python 3.10/3.11/3.12, system deps for libheif/tesseract/zbar, signal-mode timeout + 5-min OS-level kill switch.
- **`.env.example`** documenting `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.
- **216-test suite** covering FastAPI routes (`tests/test_server.py`), QR parser (`tests/test_qr_reader.py`), VCF round-trip (`tests/test_vcf_generator.py`), OCR parser (`tests/test_ocr_parser.py`), models, history, providers, contacts repository, export processor, card processor, UI helpers.
- **macOS launcher** (`BusinessCardScanner.app`) — double-clickable Dock icon that starts the server and opens the browser, with a paired `StopBusinessCardScanner.app` for clean shutdown.

### Changed

- `pyproject.toml` bumped to **2.0.0**, `requires-python>=3.10`, black/ruff/mypy targets bumped to py310.
- Provider package now uses relative imports (`from ..models import …`) instead of `sys.path.insert` hacks.
- Claude Opus model ID corrected (`claude-opus-4-6` → `claude-opus-4-7`).
- `pillow>=10.3,<12` (CVE-2023-50447), `opencv-python>=4.9` (NumPy 2.0 ABI), `numpy>=1.26,<3`.
- History list endpoint stops re-reversing the already-sorted result — newest runs now appear first.
- History persistence call signature corrected (was raising TypeError silently every scan).

### Removed

- `app.py` (Streamlit UI), `start_app.sh`, `tests/test_app.py`.
- `utils/ms_graph.py` (Outlook 365 sync — never wired into the React UI; recoverable from git history if needed).
- Dead utils: `ocr_processor.py`, `csv_validator.py`, `logging_config.py`, `pdf_processor.py`, `pdf_memory_optimizer.py`, `performance_monitor.py`.
- Stale docs: `IMPLEMENTATION_SUMMARY.md`, `SESSION_SUMMARY.md`, `IMPROVEMENTS.md`, `DESIGN_IMPLEMENTATION_SUMMARY.md`, `RELEASE_NOTES_v1.1.0.md`, `RELEASE_NOTES_v1.2.0.md`.
- `assets/custom.css` (Streamlit-era stylesheet, no longer referenced).

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
