# 🚀 Improvements Roadmap

This branch is dedicated to future enhancements and experimental features.

## 🎯 Planned Improvements

### High Priority
- [ ] **Automatic Margin Detection**: Intelligent detection of card boundaries in grid layouts
- [ ] **Contact Data Editor**: Interface to review and edit extracted contact information before VCF generation
- [ ] **Better QR Integration**: Automatic fallback when zbar library is missing
- [ ] **Performance Optimization**: Faster processing for large batches
- [ ] **Mobile Responsive Design**: Better experience on tablets and phones

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
- [ ] **AI Model Options**: Support for different LLM backends (OpenAI, Anthropic, etc.)
- [ ] **OCR Model Selection**: Let users choose different OCR models
- [ ] **Batch Learning**: Learn from user corrections to improve extraction
- [ ] **Template Recognition**: Detect card templates and use template-specific extraction
- [ ] **Business Card Design Tool**: Generate business cards from contact info

## 🐛 Known Issues to Fix

### QR Code Reading
- Current: Requires `DYLD_LIBRARY_PATH` setup and `start_app.sh`
- Goal: Automatic library detection or better error handling

### Grid Layout
- Current: Manual margin adjustment needed
- Goal: Automatic edge detection and card spacing calculation

### LLM Processing
- Current: Quality varies by model
- Goal: Prompt optimization for specific models, fallback strategies

### Detection Accuracy
- Current: Some card layouts cause false positives/negatives
- Goal: Machine learning-based card detection

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

