# 🚀 Improvements Roadmap

This branch is dedicated to future enhancements and experimental features.

## ✅ Completed Improvements

### Vision Mode (v1.1.0) ⭐
**Completed**: October 31, 2025

Major enhancement replacing traditional OCR pipeline with direct vision model analysis:

- ✅ **Vision Processor**: New module that sends card images directly to Ollama vision models
  - Supports: `llama3.2-vision`, `llava`, `bakllava`, and other vision-capable models
  - Base64 image encoding and API integration
  - Intelligent JSON parsing with fallback methods
  - Timeout handling and error recovery

- ✅ **Processing Mode Toggle**: Users can choose between two modes:
  - **Vision Mode (Recommended)**: Direct image analysis - more accurate for complex layouts
  - **OCR + LLM Mode**: Traditional pipeline for cases where vision models aren't available

- ✅ **Improved QR Detection**: 
  - OpenCV QR detector as fallback when pyzbar/zbar unavailable
  - Dual detection methods (pyzbar + OpenCV) for better reliability
  - Multiple preprocessing attempts for difficult QR codes
  - Detection method indicator (shows which method found the QR code)

**Benefits**:
- No more OCR errors on rotated or skewed text
- Better handling of complex card layouts
- Understands context better than OCR + text parsing
- Reduces processing steps (no OCR needed)
- More accurate extraction for handwritten notes
- Better language support (vision models handle any language)

**Requirements**:
- Vision model must be installed: `ollama pull llama3.2-vision`
- Longer processing time per card (30-60s vs 5-10s for OCR)
- Higher memory usage

---

## 🎯 Planned Improvements

### High Priority
- [ ] **Automatic Margin Detection**: Intelligent detection of card boundaries in grid layouts
- [ ] **Contact Data Editor**: Interface to review and edit extracted contact information before VCF generation
- [x] **Better QR Integration**: ✅ Added OpenCV fallback when zbar unavailable (v1.1.0)
- [ ] **Performance Optimization**: Faster processing for large batches (batch vision API calls)
- [ ] **Mobile Responsive Design**: Better experience on tablets and phones
- [ ] **Vision Model Benchmarking**: Compare accuracy across different vision models

### Medium Priority
- [ ] **Export Formats**: 
  - CSV export for spreadsheet analysis
  - Excel export with formatting
  - JSON export for API integration
- [ ] **Duplicate Detection**: Identify and flag potential duplicate contacts
- [ ] **Contact Merging**: Combine information from multiple cards of same person
- [ ] **Batch Editing**: Edit multiple contacts at once
- [ ] **Custom Field Mapping**: Let users define custom fields to extract

### Low Priority
- [ ] **Cloud Storage Integration**: 
  - Google Drive upload
  - Dropbox integration
  - OneDrive support
- [ ] **Advanced Image Processing**:
  - Auto-rotation correction
  - Perspective correction improvements
  - Shadow removal
- [ ] **Multi-language Expansion**: Add more languages (Chinese, Japanese, Arabic, etc.)
- [ ] **Database Storage**: Store processed cards in SQLite for history/search
- [ ] **Contact Search**: Search through previously processed contacts

### Experimental
- [x] **AI Model Options**: ✅ Support for vision models (llama3.2-vision, llava, bakllava) (v1.1.0)
- [ ] **Cloud AI APIs**: Support for OpenAI Vision, Anthropic Claude Vision, Google Gemini
- [ ] **OCR Model Selection**: Let users choose different OCR models (PaddleOCR, Tesseract)
- [ ] **Batch Learning**: Learn from user corrections to improve extraction
- [ ] **Template Recognition**: Detect card templates and use template-specific extraction
- [ ] **Business Card Design Tool**: Generate business cards from contact info
- [ ] **Confidence Scores**: Show confidence levels for extracted fields

## 🐛 Known Issues

### QR Code Reading
- Status: ✅ IMPROVED (v1.1.0)
- Solution: OpenCV fallback added, works without zbar in most cases
- Remaining: pyzbar still gives better detection, recommended to use `start_app.sh`

### Grid Layout
- Current: Manual margin adjustment needed
- Goal: Automatic edge detection and card spacing calculation

### Vision Mode Processing
- Current: Slow for large batches (60s per card)
- Goal: Batch API calls, parallel processing
- Current: JSON parsing sometimes fails if model doesn't follow instructions
- Goal: Better prompt engineering, retry logic

### Detection Accuracy
- Current: Some card layouts cause false positives/negatives
- Goal: Machine learning-based card detection
- Note: Vision mode helps by not relying on perfect card detection

## 💡 Ideas & Suggestions

Add your improvement ideas here:
- 
- 
- 

## 📝 Notes

- Each major feature should have its own feature branch off of `improvements`
- Test thoroughly before merging to `main`
- Update CHANGELOG.md with each release
- Maintain backward compatibility when possible

---

**To contribute**: Create a feature branch from `improvements`, implement the feature, test it, and merge back.

Example:
```bash
git checkout improvements
git checkout -b feature/contact-editor
# ... make changes ...
git commit -m "Add contact editor interface"
git checkout improvements
git merge feature/contact-editor
```

