# 🧪 Testing Guide

This guide will help you test the Business Card Scanner application to make sure everything is working correctly.

## Prerequisites

Before testing, make sure you've completed the setup:

```bash
./setup.sh
```

Or manually:
```bash
pip3 install -r requirements.txt
brew install zbar  # macOS
ollama pull llama3.2
```

## Quick Test Checklist

### 1. Start the Services

**Terminal 1 - Start Ollama (optional but recommended):**
```bash
ollama serve
```

**Terminal 2 - Start the App:**
```bash
streamlit run app.py
```

You should see a message like:
```
Local URL: http://localhost:8501
```

### 2. Open the Application

Open your web browser and go to `http://localhost:8501`

You should see:
- ✅ Title: "📇 Business Card Scanner"
- ✅ Upload button
- ✅ Sidebar with configuration options

### 3. Check System Status

In the sidebar, check the "System Status" section:
- ✅ If Ollama is running, you should see "✅ Ollama: Running"
- ✅ If you see available models listed, Ollama is properly configured

### 4. Test with Sample Images

#### Option A: Use Your Own Business Cards

1. Take photos of 1-3 business cards with your phone
2. Transfer them to your computer
3. Upload them to the app

**Tips for good test images:**
- Well-lit photos
- Card fills most of the frame
- Card is flat (not bent or curved)
- Text is clearly readable

#### Option B: Download Sample Business Cards

You can find free sample business card images online:
- Search "business card sample image" on Google Images
- Look for high-resolution, clear examples
- Download 2-3 different designs

### 5. Run a Test Processing

1. **Upload** an image using the file uploader
2. **Click** "🚀 Process Business Cards"
3. **Watch** the processing steps:
   - ✅ Original image displays
   - ✅ Cards are detected
   - ✅ OCR extracts text
   - ✅ QR codes are checked (if any)
   - ✅ Contact information is displayed
   - ✅ Download buttons appear

### 6. Test Download Functionality

After processing:
1. **Click** a "📥 Download" button for a single VCF file
2. **Verify** the file downloads (should be `Name.vcf`)
3. **Try** "Download All VCF Files (ZIP)"
4. **Extract** and check the ZIP contains all VCF files

### 7. Test Import to Contacts

**Test the VCF file works:**

**On macOS:**
```bash
open ContactName.vcf
```
This should open Contacts app and prompt to add the contact.

**On Windows:**
- Right-click the VCF file
- Select "Import to Outlook" or open with Contacts app

**Verify:**
- ✅ Contact name appears
- ✅ Email is correct
- ✅ Phone number is correct
- ✅ Company information is present

## Expected Results by Feature

### Card Detection
- **Single card in image**: Should detect 1 card
- **Multiple cards**: Should detect each separately
- **Card on cluttered background**: Should still isolate the card
- **Angled card**: Should apply perspective correction

### OCR Text Extraction
- **Clear text**: Should extract accurately (>90%)
- **Small text**: May have some errors but should be mostly readable
- **Colored backgrounds**: Should still extract text
- **Multiple fonts**: Should handle different fonts

### QR Code Detection
- **Card with QR code**: Should detect and decode
- **vCard QR code**: Should extract contact info
- **URL QR code**: Should show URL
- **No QR code**: Should show "No QR codes detected"

### LLM Processing (with Ollama)
- **Name extraction**: Should identify first and last name
- **Email**: Should extract and validate email format
- **Phone**: Should extract and format phone numbers
- **Company/Title**: Should identify organization and role
- **Address**: Should extract if present

### Fallback Mode (without Ollama)
- **Basic extraction**: Should still find email, phone, URLs
- **Less accurate**: May not perfectly separate fields
- **Still functional**: Should produce usable VCF files

## Troubleshooting Test Issues

### Issue: No Cards Detected

**Check:**
- Is the card clearly visible in the image?
- Is there enough contrast with the background?
- Try adjusting "Min/Max Card Area" in sidebar settings

**Fix:**
- Crop image to focus on the card
- Take photo with better lighting
- Lower the "Min Card Area" slider

### Issue: OCR Text is Gibberish

**Check:**
- Is the image in focus?
- Is the text readable to human eyes?
- Is the image resolution high enough?

**Fix:**
- Use higher resolution image
- Ensure good lighting
- Retake photo if blurry

### Issue: Wrong Contact Information

**Check:**
- Is Ollama running? (`ollama serve`)
- Is the OCR text accurate?
- Does the card have clear fields?

**Fix:**
- Start Ollama for better extraction
- Use fallback mode if LLM makes errors
- Manually edit extracted data before download

### Issue: VCF File Won't Import

**Check:**
- Did the file download completely?
- Is it a `.vcf` file?
- Does your contacts app support vCard 3.0?

**Fix:**
- Re-download the file
- Try "Combined VCF" instead of ZIP
- Open VCF in text editor to verify it's not corrupted

## Performance Benchmarks

**Typical processing times:**
- Single card: 5-15 seconds
- 5 cards: 25-60 seconds
- 10 cards: 50-120 seconds

**Factors affecting speed:**
- OCR is the slowest step (3-8 seconds per card)
- LLM processing adds 2-5 seconds per card
- Card detection is fast (<1 second)
- QR reading is fast (<1 second)

## Testing Scenarios

### Scenario 1: Conference Collection
1. Upload 10+ business card images
2. Process all at once
3. Download ZIP file
4. Import to Outlook
5. Verify all contacts appear

### Scenario 2: Single Card with QR Code
1. Find a card with QR code (or generate one)
2. Upload and process
3. Verify QR data is used
4. Check contact info matches QR content

### Scenario 3: Front and Back Cards
1. Take photos of both sides of a card
2. Upload both images
3. Process together
4. Verify information from both sides is captured

### Scenario 4: Without Ollama
1. Stop Ollama (`Ctrl+C` in terminal)
2. Process a card
3. Verify fallback extraction works
4. Check that basic fields (email, phone) are found

## Success Criteria

Your installation is working correctly if:

- ✅ App starts without errors
- ✅ Images upload successfully
- ✅ At least 1 card is detected
- ✅ OCR extracts readable text
- ✅ Contact information is shown
- ✅ VCF files download
- ✅ VCF files import to contacts app

## Next Steps

Once testing is complete:
1. ✅ Process your real business card collection!
2. ✅ Adjust settings for your specific needs
3. ✅ Set up a regular workflow for new cards
4. ✅ Share the tool with colleagues (if applicable)

## Getting Help

If tests fail or you encounter issues:
1. Check the troubleshooting section in README.md
2. Review error messages in the terminal
3. Verify all dependencies are installed
4. Try with different test images
5. Test with fallback mode (disable Ollama)

Happy testing! 🧪✨

