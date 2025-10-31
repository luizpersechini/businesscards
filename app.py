"""
Business Card Scanner Application
Main Streamlit interface for processing business cards and generating VCF files.
"""

import streamlit as st
import cv2
import numpy as np
from PIL import Image
import os
import sys
from io import BytesIO
import zipfile
from datetime import datetime
from typing import List, Tuple

# Add utils to path
sys.path.append(os.path.dirname(__file__))

from utils.card_detector import CardDetector
from utils.improved_card_detector import ImprovedCardDetector
from utils.ocr_processor import OCRProcessor
from utils.qr_reader import QRReader
from utils.llm_processor import LLMProcessor
from utils.vcf_generator import VCFGenerator


# Page configuration
st.set_page_config(
    page_title="Business Card Scanner",
    page_icon="📇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        margin-bottom: 2rem;
    }
    .step-header {
        font-size: 1.5rem;
        font-weight: bold;
        color: #2ca02c;
        margin-top: 1rem;
        margin-bottom: 0.5rem;
    }
    .status-success {
        color: #2ca02c;
        font-weight: bold;
    }
    .status-processing {
        color: #ff7f0e;
        font-weight: bold;
    }
    .status-warning {
        color: #d62728;
        font-weight: bold;
    }
    .contact-preview {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session_state():
    """Initialize session state variables."""
    if 'processed_cards' not in st.session_state:
        st.session_state.processed_cards = []
    if 'processing_complete' not in st.session_state:
        st.session_state.processing_complete = False


def load_image(uploaded_file):
    """Load an uploaded image file."""
    image = Image.open(uploaded_file)
    return np.array(image)


def draw_grid_overlay(image: np.ndarray, rows: int, cols: int,
                      margin_top: int = 0, margin_bottom: int = 0,
                      margin_left: int = 0, margin_right: int = 0) -> np.ndarray:
    """
    Draw grid lines on image for visualization.
    
    Args:
        image: Input image
        rows: Number of rows
        cols: Number of columns
        margin_top/bottom/left/right: Margins as percentages
        
    Returns:
        Image with grid overlay
    """
    overlay = image.copy()
    height, width = overlay.shape[:2]
    
    # Calculate margins
    top_skip = int(height * margin_top / 100)
    bottom_skip = int(height * margin_bottom / 100)
    left_skip = int(width * margin_left / 100)
    right_skip = int(width * margin_right / 100)
    
    # Working area
    working_height = height - top_skip - bottom_skip
    working_width = width - left_skip - right_skip
    
    card_height = working_height // rows
    card_width = working_width // cols
    
    # Draw margin boundaries (red dashed)
    if margin_top > 0:
        cv2.line(overlay, (0, top_skip), (width, top_skip), (0, 0, 255), 2)
    if margin_bottom > 0:
        cv2.line(overlay, (0, height - bottom_skip), (width, height - bottom_skip), (0, 0, 255), 2)
    if margin_left > 0:
        cv2.line(overlay, (left_skip, 0), (left_skip, height), (0, 0, 255), 2)
    if margin_right > 0:
        cv2.line(overlay, (width - right_skip, 0), (width - right_skip, height), (0, 0, 255), 2)
    
    # Draw grid lines (green)
    # Horizontal lines
    for row in range(1, rows):
        y = top_skip + (row * card_height)
        cv2.line(overlay, (left_skip, y), (width - right_skip, y), (0, 255, 0), 3)
    
    # Vertical lines
    for col in range(1, cols):
        x = left_skip + (col * card_width)
        cv2.line(overlay, (x, top_skip), (x, height - bottom_skip), (0, 255, 0), 3)
    
    # Draw outer box (yellow)
    cv2.rectangle(overlay, (left_skip, top_skip), 
                 (width - right_skip, height - bottom_skip), (0, 255, 255), 3)
    
    # Add labels
    card_num = 1
    for row in range(rows):
        for col in range(cols):
            y = top_skip + (row * card_height) + card_height // 2
            x = left_skip + (col * card_width) + card_width // 2
            cv2.putText(overlay, f'Card {card_num}', (x - 40, y),
                       cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 255), 3)
            card_num += 1
    
    return overlay


def split_image_grid(image: np.ndarray, rows: int, cols: int, 
                     margin_top: int = 0, margin_bottom: int = 0,
                     margin_left: int = 0, margin_right: int = 0) -> List[Tuple[np.ndarray, None]]:
    """
    Split an image into a grid of cards with margin support.
    
    Args:
        image: Input image
        rows: Number of rows
        cols: Number of columns
        margin_top: Top margin as percentage
        margin_bottom: Bottom margin as percentage
        margin_left: Left margin as percentage
        margin_right: Right margin as percentage
        
    Returns:
        List of (card_image, None) tuples
    """
    height, width = image.shape[:2]
    
    # Apply margins
    top_skip = int(height * margin_top / 100)
    bottom_skip = int(height * margin_bottom / 100)
    left_skip = int(width * margin_left / 100)
    right_skip = int(width * margin_right / 100)
    
    # Working area after margins
    working_height = height - top_skip - bottom_skip
    working_width = width - left_skip - right_skip
    
    card_height = working_height // rows
    card_width = working_width // cols
    
    cards = []
    
    for row in range(rows):
        for col in range(cols):
            y1 = top_skip + (row * card_height)
            y2 = top_skip + ((row + 1) * card_height) if row < rows - 1 else (height - bottom_skip)
            x1 = left_skip + (col * card_width)
            x2 = left_skip + ((col + 1) * card_width) if col < cols - 1 else (width - right_skip)
            
            card_image = image[y1:y2, x1:x2]
            cards.append((card_image, None))
    
    return cards


def process_business_cards(uploaded_files, use_llm, ollama_model, ocr_languages, detection_mode, grid_rows, grid_cols, min_percent, max_percent, margin_top, margin_bottom, margin_left, margin_right):
    """
    Main processing pipeline for business cards.
    
    Args:
        uploaded_files: List of uploaded image files
        use_llm: Whether to use LLM for processing
        ollama_model: Ollama model name
        ocr_languages: List of language codes for OCR
        detection_mode: Detection mode (Automatic/Manual)
        grid_rows: Number of rows for grid layout
        grid_cols: Number of columns for grid layout
        min_percent: Minimum card size percentage
        max_percent: Maximum card size percentage
    """
    # Initialize processors
    card_detector = CardDetector()
    improved_detector = ImprovedCardDetector(min_area_percent=min_percent, max_area_percent=max_percent)
    ocr_processor = OCRProcessor(languages=ocr_languages, gpu=False)
    qr_reader = QRReader()
    llm_processor = LLMProcessor(model=ollama_model) if use_llm else None
    vcf_generator = VCFGenerator()
    
    # Check Ollama status
    ollama_status = "Not used"
    if use_llm:
        if llm_processor.is_ollama_running():
            ollama_status = "✅ Connected"
        else:
            ollama_status = "⚠️ Not running (using fallback)"
            st.warning("Ollama is not running. Using fallback extraction method.")
    
    st.sidebar.info(f"**Ollama Status:** {ollama_status}")
    
    all_processed_cards = []
    
    # Process each uploaded file
    for file_idx, uploaded_file in enumerate(uploaded_files):
        st.markdown(f"### 📄 Processing: {uploaded_file.name}")
        
        # Create columns for progress display
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("#### Original Image")
            image = load_image(uploaded_file)
            st.image(image, use_column_width=True)
        
        # Convert to OpenCV format
        cv_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        
        # Step 1: Detect cards
        if detection_mode == "Manual - Single Card":
            with st.spinner("📋 Processing as single card..."):
                detected_cards = [(cv_image, None)]
                st.success(f"✅ Processing entire image as 1 card")
        
        elif detection_mode == "Manual - Grid Layout":
            with st.spinner(f"✂️ Splitting into {grid_rows}x{grid_cols} grid..."):
                detected_cards = split_image_grid(cv_image, grid_rows, grid_cols,
                                                 margin_top, margin_bottom, margin_left, margin_right)
                st.success(f"✅ Split into {len(detected_cards)} cards from grid")
        
        elif detection_mode == "Improved Auto (Recommended)":
            with st.spinner("✨ Detecting cards with document scanner algorithm..."):
                detected_cards = improved_detector.detect_cards(cv_image)
                st.success(f"✅ Detected {len(detected_cards)} card(s) with improved algorithm")
        
        else:  # Automatic (old method)
            with st.spinner("🔍 Detecting business cards..."):
                detected_cards = card_detector.detect_cards(cv_image)
                st.success(f"✅ Detected {len(detected_cards)} card(s)")
        
        # Process each detected card
        for card_idx, (card_image, contour) in enumerate(detected_cards):
            st.markdown(f"#### 📇 Card {card_idx + 1}")
            
            card_col1, card_col2 = st.columns([1, 1])
            
            with card_col1:
                st.markdown("**Detected Card Image**")
                card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
                st.image(card_rgb, use_column_width=True)
            
            with card_col2:
                # Step 2: OCR Processing
                with st.spinner("📝 Extracting text with OCR..."):
                    ocr_results = ocr_processor.extract_with_preprocessing(card_image)
                    raw_text = ocr_results['raw_text']
                    
                    st.markdown("**Extracted Text:**")
                    st.text_area(
                        "OCR Text",
                        raw_text,
                        height=150,
                        key=f"ocr_{file_idx}_{card_idx}",
                        label_visibility="collapsed"
                    )
                
                # Step 3: QR Code Detection - ALWAYS TRY
                with st.spinner("📱 Checking for QR codes..."):
                    qr_data = None
                    
                    try:
                        # FORCE QR CODE ATTEMPT
                        qr_results = qr_reader.detect_and_decode(card_image)
                        
                        if qr_results:
                            st.success(f"✅ Found {len(qr_results)} QR code(s)")
                            qr_data = qr_reader.extract_contact_info(qr_results)
                            
                            with st.expander("View QR Code Data"):
                                for qr in qr_results:
                                    st.json(qr['parsed'])
                            
                            # Show what was extracted from QR
                            if qr_data:
                                st.info(f"📱 QR code provided: {', '.join(qr_data.keys())}")
                        else:
                            st.info("No QR codes found on this card")
                    
                    except RuntimeError as e:
                        st.error(f"❌ QR code reading failed: {str(e)}")
                        st.info("💡 Restart app with: ./start_app.sh")
                    except Exception as e:
                        st.warning(f"⚠️ QR scan error: {str(e)}")
            
            # Step 4: LLM Processing
            st.markdown("**🤖 Processing Contact Information**")
            
            with st.spinner("Structuring contact data..."):
                if use_llm and llm_processor.is_ollama_running():
                    contact_data = llm_processor.extract_contact_info(raw_text, qr_data)
                else:
                    contact_data = llm_processor._fallback_extraction(raw_text, qr_data) if llm_processor else {}
                
                if not contact_data:
                    st.warning("⚠️ Could not extract contact information")
                    continue
            
            # Step 5: Display Contact Preview
            st.markdown("**Contact Information:**")
            preview_col1, preview_col2 = st.columns([2, 1])
            
            with preview_col1:
                preview = vcf_generator.preview_vcard(contact_data)
                # Better styled preview with high contrast
                st.markdown(f'''
                <div style="
                    background-color: white;
                    color: black;
                    padding: 1.5rem;
                    border-radius: 0.5rem;
                    border: 2px solid #1f77b4;
                    font-family: monospace;
                    font-size: 14px;
                    line-height: 1.8;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                ">
                {preview.replace(chr(10), "<br>")}
                </div>
                ''', unsafe_allow_html=True)
            
            with preview_col2:
                # Option to edit contact data
                with st.expander("✏️ Edit Contact Data"):
                    st.json(contact_data)
                    st.info("Contact editing feature - click to view raw data")
            
            # Generate VCF
            vcf_string = vcf_generator.generate_vcf_string(contact_data)
            filename = vcf_generator.contact_to_filename(contact_data)
            
            # Store processed card
            all_processed_cards.append({
                'filename': filename,
                'contact_data': contact_data,
                'vcf_content': vcf_string,
                'card_image': card_rgb,
                'source_file': uploaded_file.name
            })
            
            st.success("✅ Card processed successfully!")
            st.markdown("---")
    
    return all_processed_cards


def main():
    """Main application function."""
    initialize_session_state()
    
    # Header
    st.markdown('<div class="main-header">📇 Business Card Scanner</div>', unsafe_allow_html=True)
    st.markdown("Upload business card images to extract contact information and generate VCF files for Outlook.")
    
    # Sidebar configuration
    st.sidebar.title("⚙️ Configuration")
    
    # LLM Settings
    st.sidebar.markdown("### LLM Settings")
    use_llm = st.sidebar.checkbox("Use Ollama LLM", value=True, 
                                   help="Use local LLM for better extraction (requires Ollama)")
    
    ollama_model = st.sidebar.selectbox(
        "Ollama Model",
        ["llama3.2", "llama3.1", "llama3", "mistral", "phi3"],
        help="Select the Ollama model to use"
    )
    
    # OCR Settings
    st.sidebar.markdown("### OCR Settings")
    ocr_languages = st.sidebar.multiselect(
        "OCR Languages",
        options=['en', 'pt', 'es', 'fr', 'de', 'it'],
        default=['en', 'pt'],
        help="Select languages for text recognition"
    )
    
    language_names = {
        'en': 'English',
        'pt': 'Portuguese',
        'es': 'Spanish', 
        'fr': 'French',
        'de': 'German',
        'it': 'Italian'
    }
    
    selected_lang_names = [language_names.get(lang, lang) for lang in ocr_languages]
    st.sidebar.info(f"Languages: {', '.join(selected_lang_names)}")
    
    # Card Detection Settings
    st.sidebar.markdown("### Detection Settings")
    
    detection_mode = st.sidebar.radio(
        "Detection Mode",
        ["Improved Auto (Recommended)", "Automatic", "Manual - Single Card", "Manual - Grid Layout"],
        help="Choose how to detect cards"
    )
    
    if detection_mode == "Improved Auto (Recommended)":
        st.sidebar.success("✨ Document scanner algorithm")
        st.sidebar.info("Filters out QR codes & logos")
    
    manual_grid_rows = 1
    manual_grid_cols = 1
    
    if detection_mode == "Manual - Grid Layout":
        st.sidebar.info("Specify how cards are arranged")
        manual_grid_cols = st.sidebar.number_input("Columns", min_value=1, max_value=5, value=2)
        manual_grid_rows = st.sidebar.number_input("Rows", min_value=1, max_value=5, value=4)
        st.sidebar.success(f"Will extract {manual_grid_cols * manual_grid_rows} cards")
        
        st.sidebar.markdown("#### Fine-tune Grid")
        margin_top = st.sidebar.slider("Top Margin (%)", 0, 30, 0, help="Skip % from top")
        margin_bottom = st.sidebar.slider("Bottom Margin (%)", 0, 30, 0, help="Skip % from bottom")
        margin_left = st.sidebar.slider("Left Margin (%)", 0, 30, 0, help="Skip % from left")
        margin_right = st.sidebar.slider("Right Margin (%)", 0, 30, 0, help="Skip % from right")
        
        if margin_top or margin_bottom or margin_left or margin_right:
            st.sidebar.info(f"Active area: {100-margin_top-margin_bottom}% × {100-margin_left-margin_right}%")
    else:
        margin_top = margin_bottom = margin_left = margin_right = 0
    
    # Better controls for automatic detection
    if detection_mode in ["Improved Auto (Recommended)", "Automatic"]:
        st.sidebar.markdown("#### Size Filters")
        min_card_percent = st.sidebar.slider(
            "Min Card Size (%)", 
            min_value=2, 
            max_value=20, 
            value=5,
            help="Minimum card size as % of total image (filters out small logos/QR codes)"
        )
        max_card_percent = st.sidebar.slider(
            "Max Card Size (%)", 
            min_value=20, 
            max_value=60, 
            value=40,
            help="Maximum card size as % of total image"
        )
        st.sidebar.info(f"Cards must be {min_card_percent}-{max_card_percent}% of image")
    else:
        min_card_percent = 5
        max_card_percent = 40
    
    # Upload section
    st.markdown("## 📤 Upload Business Cards")
    uploaded_files = st.file_uploader(
        "Choose business card image(s)",
        type=['png', 'jpg', 'jpeg', 'bmp'],
        accept_multiple_files=True,
        help="Upload one or more images containing business cards"
    )
    
    if uploaded_files:
        st.info(f"📊 {len(uploaded_files)} file(s) uploaded")
        
        # Show grid preview for Manual Grid Layout mode
        if detection_mode == "Manual - Grid Layout" and len(uploaded_files) > 0:
            st.markdown("### 🎯 Grid Preview")
            st.info("👁️ Preview shows where cards will be extracted (adjust margins to align with cards)")
            
            preview_file = uploaded_files[0]  # Show preview for first image
            preview_image = load_image(preview_file)
            preview_cv = cv2.cvtColor(preview_image, cv2.COLOR_RGB2BGR)
            
            # Draw grid overlay
            overlay = draw_grid_overlay(preview_cv, manual_grid_rows, manual_grid_cols,
                                       margin_top, margin_bottom, margin_left, margin_right)
            overlay_rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
            
            st.image(overlay_rgb, caption=f"Grid Preview: {manual_grid_cols}x{manual_grid_rows}", use_column_width=True)
            
            st.markdown("""
            **Legend:**
            - 🟢 **Green lines**: Grid splits between cards
            - 🟡 **Yellow box**: Active card area
            - 🔴 **Red lines**: Margins (excluded area)
            - 🟣 **Purple labels**: Card numbers
            """)
        
        # Process button
        if st.button("🚀 Process Business Cards", type="primary"):
            with st.spinner("Processing..."):
                processed_cards = process_business_cards(
                    uploaded_files, use_llm, ollama_model, ocr_languages,
                    detection_mode, manual_grid_rows, manual_grid_cols,
                    min_card_percent, max_card_percent,
                    margin_top, margin_bottom, margin_left, margin_right
                )
                st.session_state.processed_cards = processed_cards
                st.session_state.processing_complete = True
        
        # Download section
        if st.session_state.processing_complete and st.session_state.processed_cards:
            st.markdown("## 💾 Download Contacts")
            
            download_col1, download_col2 = st.columns(2)
            
            with download_col1:
                st.markdown("### Individual VCF Files")
                
                for card in st.session_state.processed_cards:
                    st.download_button(
                        label=f"📥 {card['filename']}.vcf",
                        data=card['vcf_content'],
                        file_name=f"{card['filename']}.vcf",
                        mime="text/vcard"
                    )
            
            with download_col2:
                st.markdown("### Bulk Download")
                
                # Create ZIP file with all VCF files
                zip_buffer = BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                    for card in st.session_state.processed_cards:
                        zip_file.writestr(
                            f"{card['filename']}.vcf",
                            card['vcf_content']
                        )
                
                zip_buffer.seek(0)
                
                st.download_button(
                    label="📦 Download All VCF Files (ZIP)",
                    data=zip_buffer,
                    file_name=f"business_cards_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                    mime="application/zip"
                )
                
                # Also offer combined VCF
                vcf_generator = VCFGenerator()
                combined_vcf = "\n".join(card['vcf_content'] for card in st.session_state.processed_cards)
                
                st.download_button(
                    label="📋 Download Combined VCF File",
                    data=combined_vcf,
                    file_name=f"all_contacts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.vcf",
                    mime="text/vcard"
                )
            
            # Summary
            st.markdown("### 📊 Processing Summary")
            st.success(f"Successfully processed {len(st.session_state.processed_cards)} business card(s)!")
            
            # Show summary table
            summary_data = []
            for card in st.session_state.processed_cards:
                contact = card['contact_data']
                name = contact.get('fullName') or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                company = contact.get('company', 'N/A')
                email = contact.get('email', 'N/A')
                
                summary_data.append({
                    'Name': name,
                    'Company': company,
                    'Email': email,
                    'Source': card['source_file']
                })
            
            st.table(summary_data)
            
            # Reset button
            if st.button("🔄 Process More Cards"):
                st.session_state.processed_cards = []
                st.session_state.processing_complete = False
                st.rerun()
    
    else:
        # Instructions when no files uploaded
        st.markdown("""
        ### 📋 Instructions
        
        1. **Upload Images**: Click the upload button above to select business card images
        2. **Configure Settings**: Adjust settings in the sidebar if needed
        3. **Process**: Click the "Process Business Cards" button
        4. **Review**: Check the extracted contact information
        5. **Download**: Get individual VCF files or download all at once
        
        ### ⚙️ Setup Requirements
        
        **For best results:**
        - Install Ollama and pull a model: `ollama pull llama3.2`
        - Start Ollama: `ollama serve`
        - Ensure clear, well-lit images of business cards
        
        **Without Ollama:**
        - The app will use regex-based fallback extraction
        - Results may be less accurate but still functional
        """)
        
        # System status
        st.sidebar.markdown("### 📊 System Status")
        
        # Check Ollama
        llm_processor = LLMProcessor(model=ollama_model)
        if llm_processor.is_ollama_running():
            st.sidebar.success("✅ Ollama: Running")
            models = llm_processor.get_available_models()
            if models:
                st.sidebar.info(f"Available models: {', '.join(models[:3])}")
        else:
            st.sidebar.warning("⚠️ Ollama: Not running")
            st.sidebar.info("App will use fallback extraction")
        
        # Check QR Reader - always attempt
        qr_test = QRReader()
        try:
            # Test if QR reading works
            test_img = np.zeros((100, 100), dtype=np.uint8)
            qr_test.detect_and_decode(test_img)
            st.sidebar.success("✅ QR Code Reader: Working")
        except RuntimeError as e:
            st.sidebar.error("❌ QR Reader: Not working")
            with st.sidebar.expander("Fix QR Reading"):
                st.code("./start_app.sh", language="bash")
                st.caption("Or restart with library path set")
                st.code("export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH\nstreamlit run app.py")
        except:
            st.sidebar.warning("⚠️ QR Reader: Status unknown")


if __name__ == "__main__":
    main()

