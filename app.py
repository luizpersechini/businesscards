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

from utils.improved_card_detector import ImprovedCardDetector
from utils.qr_reader import QRReader
from utils.vision_processor import VisionProcessor
from utils.vcf_generator import VCFGenerator
from utils.export_processor import ExportProcessor


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


def qr_to_contact_data(qr_data: dict) -> dict:
    """
    Convert QR code data to contact data format.
    
    Args:
        qr_data: QR code extracted data
        
    Returns:
        Contact data dictionary
    """
    contact = {}
    
    # Extract from vCard format if present
    if 'full_name' in qr_data:
        contact['fullName'] = qr_data['full_name']
    if 'first_name' in qr_data:
        contact['firstName'] = qr_data['first_name']
    if 'last_name' in qr_data:
        contact['lastName'] = qr_data['last_name']
    if 'organization' in qr_data:
        contact['company'] = qr_data['organization']
    if 'title' in qr_data:
        contact['title'] = qr_data['title']
    
    # Handle emails (can be list)
    if 'emails' in qr_data and qr_data['emails']:
        if isinstance(qr_data['emails'], list):
            contact['email'] = qr_data['emails'][0]
        else:
            contact['email'] = qr_data['emails']
    
    # Handle phones (can be list)
    if 'phones' in qr_data and qr_data['phones']:
        if isinstance(qr_data['phones'], list):
            contact['phone'] = qr_data['phones'][0]
            if len(qr_data['phones']) > 1:
                contact['mobile'] = qr_data['phones'][1]
        else:
            contact['phone'] = qr_data['phones']
    
    # URL
    if 'url' in qr_data:
        contact['website'] = qr_data['url']
    
    # Address (usually semicolon separated in vCard)
    if 'address' in qr_data:
        addr = qr_data['address']
        if isinstance(addr, str):
            contact['address'] = addr.replace(', ', '\n')
        else:
            contact['address'] = str(addr)
    
    # Add note if QR data was used
    contact['notes'] = 'Contact extracted from QR code'
    
    return contact


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


def process_single_card_retry(card_image_rgb, vision_model, vision_timeout):
    """
    Retry processing a single card.
    
    Args:
        card_image_rgb: Card image in RGB format
        vision_model: Ollama vision model name
        vision_timeout: Timeout for vision processing
    
    Returns:
        Dictionary with reprocessed card data or None if failed
    """
    try:
        # Convert RGB to BGR for OpenCV
        card_image = cv2.cvtColor(card_image_rgb, cv2.COLOR_RGB2BGR)
        
        # Initialize processors
        qr_reader = QRReader()
        vcf_generator = VCFGenerator()
        vision_processor = VisionProcessor(model=vision_model)
        
        # QR Code Detection
        qr_data = None
        try:
            qr_results = qr_reader.detect_and_decode(card_image)
            if qr_results:
                qr_data = qr_reader.extract_contact_info(qr_results)
        except Exception as e:
            st.warning(f"⚠️ QR code reading failed: {str(e)}")
        
        # Extract contact information (Vision mode)
        contact_data = vision_processor.extract_contact_from_image(card_image, qr_data, timeout=vision_timeout)
        
        if 'error' in contact_data:
            if qr_data:
                st.warning("⚠️ Using QR code data as fallback...")
                contact_data = qr_to_contact_data(qr_data)
            else:
                st.error(f"❌ Vision processing error: {contact_data.get('message', 'Unknown')}")
                return None
        
        if not contact_data or 'error' in contact_data:
            return None
        
        # Generate VCF
        vcf_string = vcf_generator.generate_vcf_string(contact_data)
        filename = vcf_generator.contact_to_filename(contact_data)
        
        return {
            'filename': filename,
            'contact_data': contact_data,
            'vcf_content': vcf_string
        }
    
    except Exception as e:
        st.error(f"❌ Retry failed: {str(e)}")
        return None


def process_business_cards(uploaded_files, vision_model, vision_timeout, detection_mode, grid_rows, grid_cols, min_percent, max_percent, margin_top, margin_bottom, margin_left, margin_right):
    """
    Main processing pipeline for business cards.
    
    Args:
        uploaded_files: List of uploaded image files
        vision_model: Vision model name
        vision_timeout: Timeout for vision processing
        detection_mode: Detection mode (Automatic/Manual)
        grid_rows: Number of rows for grid layout
        grid_cols: Number of columns for grid layout
        min_percent: Minimum card size percentage
        max_percent: Maximum card size percentage
        margin_top/bottom/left/right: Margins for grid layout
    """
    # Initialize processors
    improved_detector = ImprovedCardDetector(min_area_percent=min_percent, max_area_percent=max_percent)
    qr_reader = QRReader()
    vcf_generator = VCFGenerator()
    
    # Initialize vision processor (always use Vision mode)
    vision_processor = VisionProcessor(model=vision_model)
    
    # Check Ollama status
    if vision_processor.check_ollama_status():
        ollama_status = f"✅ Connected ({vision_model})"
    else:
        ollama_status = "⚠️ Not running or model not available"
        st.error(f"Vision model '{vision_model}' not available. Install with: ollama pull {vision_model}")
    
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
        
        elif detection_mode == "Automatic":
            with st.spinner("✨ Detecting cards with document scanner algorithm..."):
                detected_cards = improved_detector.detect_cards(cv_image)
                st.success(f"✅ Detected {len(detected_cards)} card(s) with automatic detection")
        
        # Process each detected card
        for card_idx, (card_image, contour) in enumerate(detected_cards):
            st.markdown(f"#### 📇 Card {card_idx + 1}")
            
            card_col1, card_col2 = st.columns([1, 1])
            
            with card_col1:
                st.markdown("**Detected Card Image**")
                card_rgb = cv2.cvtColor(card_image, cv2.COLOR_BGR2RGB)
                st.image(card_rgb, use_column_width=True)
            
            with card_col2:
                qr_data = None
                contact_data = {}
                
                # Step 2: QR Code Detection - ALWAYS TRY FIRST
                with st.spinner("📱 Checking for QR codes..."):
                    try:
                        qr_results = qr_reader.detect_and_decode(card_image)
                        
                        if qr_results:
                            method_used = qr_results[0].get('method', 'unknown')
                            qr_data = qr_reader.extract_contact_info(qr_results)
                            
                            # Clean status display
                            st.markdown(f'''
                            <div style="
                                background-color: #d4edda;
                                color: #155724;
                                padding: 0.75rem;
                                border-radius: 0.25rem;
                                border-left: 4px solid #28a745;
                                margin: 0.5rem 0;
                            ">
                                ✅ <strong>Found {len(qr_results)} QR code(s)</strong> ({method_used})
                            </div>
                            ''', unsafe_allow_html=True)
                            
                            if qr_data:
                                # Show QR data fields in a clean way
                                with st.expander("📱 QR Code Data", expanded=False):
                                    qr_fields = ', '.join(qr_data.keys())
                                    st.markdown(f"**Available fields:** {qr_fields}")
                                    for qr in qr_results:
                                        st.json(qr['parsed'])
                        else:
                            st.markdown('''
                            <div style="
                                background-color: #f8f9fa;
                                color: #6c757d;
                                padding: 0.75rem;
                                border-radius: 0.25rem;
                                border-left: 4px solid #6c757d;
                                margin: 0.5rem 0;
                            ">
                                ℹ️ No QR codes detected
                            </div>
                            ''', unsafe_allow_html=True)
                    
                    except RuntimeError as e:
                        st.error(f"❌ QR code reading failed: {str(e)}")
                        st.markdown('''
                        <div style="
                            background-color: #fff3cd;
                            color: #856404;
                            padding: 0.75rem;
                            border-radius: 0.25rem;
                            border-left: 4px solid #ffc107;
                            margin: 0.5rem 0;
                        ">
                            💡 <strong>Fix:</strong> Restart with <code>./start_app.sh</code>
                        </div>
                        ''', unsafe_allow_html=True)
                    except Exception as e:
                        st.warning(f"⚠️ QR scan error: {str(e)}")
                
                # Step 3: Extract contact information (Vision mode)
                st.markdown("---")
                st.markdown("**👁️ Vision Analysis**")
                with st.spinner(f"🤖 Analyzing card image (timeout: {vision_timeout}s)..."):
                    contact_data = vision_processor.extract_contact_from_image(
                        card_image, qr_data, timeout=vision_timeout
                    )
                    
                    if 'error' in contact_data:
                        error_msg = contact_data.get('message', 'Unknown')
                        st.error(f"❌ Vision processing error: {error_msg}")
                        
                        # Try to use QR code data as fallback
                        if qr_data:
                            st.warning("⚠️ Using QR code data as fallback...")
                            contact_data = qr_to_contact_data(qr_data)
                            st.success("✅ Contact info extracted from QR code!")
                        else:
                            st.markdown(f'''
                            <div style="
                                background-color: #fff3cd;
                                color: #856404;
                                padding: 0.75rem;
                                border-radius: 0.25rem;
                                border-left: 4px solid #ffc107;
                                margin: 0.5rem 0;
                            ">
                                💡 <strong>Tip:</strong> Install vision model:<br>
                                <code>ollama pull {vision_model}</code>
                            </div>
                            ''', unsafe_allow_html=True)
                            continue
                    else:
                        st.success("✅ Vision analysis complete!")
                
                if not contact_data or 'error' in contact_data:
                    st.warning("⚠️ Could not extract contact information")
                    continue
            
            # Step 5: Display Contact Preview
            st.markdown("---")
            st.markdown("### 👤 **Extracted Contact Information**")
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
                # Option to view raw contact data
                with st.expander("✏️ **View Raw Data**", expanded=False):
                    st.caption("JSON representation of extracted data:")
                    st.json(contact_data)
            
            # Generate VCF
            vcf_string = vcf_generator.generate_vcf_string(contact_data)
            filename = vcf_generator.contact_to_filename(contact_data)
            
            # Store processed card
            all_processed_cards.append({
                'filename': filename,
                'contact_data': contact_data,
                'vcf_content': vcf_string,
                'card_image': card_rgb,
                'source_file': uploaded_file.name,
                'locked': False  # Unlocked by default, user can lock successful ones
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
    
    # Vision Settings (always use Vision mode now)
    st.sidebar.markdown("### 🔬 Vision Settings")
    
    vision_model = st.sidebar.selectbox(
        "Vision Model",
        ["llava:13b", "llama3.2-vision", "llava", "bakllava"],
        index=0,  # llava:13b is default
        help="Select the Ollama vision model (must support images)"
    )
    
    vision_timeout = st.sidebar.slider(
        "Vision Timeout (seconds)",
        min_value=60,
        max_value=300,
        value=180,
        step=30,
        help="Time to wait for vision model response. Increase for slower systems or complex cards."
    )
    
    st.sidebar.info("🎯 Vision models analyze images directly - more accurate!")
    st.sidebar.caption(f"⏱️ Current timeout: {vision_timeout}s (~{vision_timeout//60} min)")
    
    
    # Card Detection Settings
    st.sidebar.markdown("### Detection Settings")
    
    detection_mode = st.sidebar.radio(
        "Detection Mode",
        ["Automatic", "Manual - Single Card", "Manual - Grid Layout"],
        help="Choose how to detect cards"
    )
    
    if detection_mode == "Automatic":
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
                    uploaded_files, vision_model, vision_timeout,
                    detection_mode, manual_grid_rows, manual_grid_cols,
                    min_card_percent, max_card_percent,
                    margin_top, margin_bottom, margin_left, margin_right
                )
                st.session_state.processed_cards = processed_cards
                st.session_state.processing_complete = True
        
        # Download section
        if st.session_state.processing_complete and st.session_state.processed_cards:
            # Handle individual card retry requests (moved inside download section)
            for idx in range(len(st.session_state.processed_cards)):
                if st.session_state.get(f'retry_card_{idx}', False):
                    # Clear the retry flag
                    st.session_state[f'retry_card_{idx}'] = False
                    
                    card = st.session_state.processed_cards[idx]
                    st.info(f"🔄 Retrying card {idx+1}: {card['filename']}...")
                    
                    with st.spinner(f"Re-processing card {idx+1}..."):
                        # Get current settings from sidebar (they're already in scope)
                        retry_result = process_single_card_retry(
                            card['card_image'],
                            vision_model,
                            vision_timeout
                        )
                        
                        if retry_result:
                            # Update the card with new data
                            st.session_state.processed_cards[idx]['contact_data'] = retry_result['contact_data']
                            st.session_state.processed_cards[idx]['vcf_content'] = retry_result['vcf_content']
                            st.session_state.processed_cards[idx]['filename'] = retry_result['filename']
                            st.success(f"✅ Card {idx+1} reprocessed successfully!")
                        else:
                            st.error(f"❌ Failed to reprocess card {idx+1}")
                    
                    st.rerun()
            
            # Download section UI
            st.markdown("## 💾 Download Contacts")
            
            # Initialize export processor
            export_processor = ExportProcessor()
            
            # Export format selection
            st.markdown("### 📦 Choose Export Formats")
            export_col1, export_col2, export_col3 = st.columns(3)
            
            with export_col1:
                include_vcf = st.checkbox("VCF (Outlook/Contacts)", value=True, help="vCard format for contact managers")
            with export_col2:
                include_excel = st.checkbox("Excel (XLSX)", value=True, help="Microsoft Excel format")
            with export_col3:
                outlook_csv = st.checkbox("Outlook Import CSV", value=True, help="Special CSV format for Outlook import")
            
            # Set include_csv to False since we removed regular CSV option
            include_csv = False
            
            # Outlook CSV format options
            outlook_simplified = False
            outlook_email_field = 'E-mail Address'
            outlook_phone_field = 'Business Phone'
            outlook_use_quotes = True
            
            if outlook_csv:
                with st.expander("⚙️ Outlook CSV Options", expanded=False):
                    outlook_simplified = st.checkbox(
                        "Use Simplified Format", 
                        value=False,
                        help="Minimal fields only (First Name, Last Name, Company, Email, Phone) for maximum compatibility"
                    )
                    
                    outlook_email_field = st.selectbox(
                        "Email Field Name",
                        options=['E-mail Address', 'Email Address', 'Email'],
                        index=0,
                        help="Field name for email column. Try different options if import fails."
                    )
                    
                    outlook_phone_field = st.selectbox(
                        "Phone Field Name",
                        options=['Business Phone', 'Phone', 'Work Phone'],
                        index=0,
                        help="Field name for phone column. Try different options if import fails."
                    )
                    
                    outlook_use_quotes = st.checkbox(
                        "Quote Fields",
                        value=True,
                        help="Wrap all fields in quotes. Disable if Outlook has issues with quoted fields."
                    )
                    
                    # Show diagnostic info
                    st.caption("💡 **Tip:** If email/phone don't import, try different field names or simplified format.")
            
            # Prepare export data
            contacts = [card['contact_data'] for card in st.session_state.processed_cards]
            for i, card in enumerate(st.session_state.processed_cards):
                contacts[i]['source'] = card.get('source_file', 'Unknown')
            
            # Show stats
            stats = export_processor.get_export_stats(contacts)
            st.info(f"📊 **Export Summary:** {stats['total']} contacts | "
                   f"{stats['with_email']} with email | {stats['with_phone']} with phone | "
                   f"{stats['with_company']} with company")
            
            st.markdown("---")
            
            # Individual Cards Management Section
            st.markdown("### 📄 Individual Cards Management")
            st.caption("💡 **Lock cards with good results** to prevent re-processing. **Retry** failed extractions individually.")
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Individual card management - Compact list format
            for idx, card in enumerate(st.session_state.processed_cards):
                is_locked = card.get('locked', False)
                contact = card['contact_data']
                
                # Get contact info
                name = contact.get('fullName') or f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip() or "Unknown"
                company = contact.get('company', '') or ''
                email = contact.get('email', '') or ''
                phone = contact.get('phone', '') or ''
                
                # Truncate long values for compact display
                name_display = name[:30] + "..." if len(name) > 30 else name
                company_display = company[:25] + "..." if len(company) > 25 else company
                email_display = email[:25] + "..." if len(email) > 25 else email
                phone_display = phone[:18] + "..." if len(phone) > 18 else phone
                
                # Compact list row layout
                row_col1, row_col2, row_col3, row_col4, row_col5, row_col6 = st.columns([0.8, 2.5, 2, 2.5, 2, 3])
                
                with row_col1:
                    # Lock status icon (smaller)
                    lock_icon = "🔒" if is_locked else "🔓"
                    st.markdown(f'<div style="text-align: center; font-size: 16px;">{lock_icon}</div>', unsafe_allow_html=True)
                
                with row_col2:
                    # Name
                    st.markdown(f'<div style="font-weight: 600;">{name_display}</div>', unsafe_allow_html=True)
                
                with row_col3:
                    # Company
                    if company:
                        st.markdown(f'<div style="color: #666; font-size: 0.9em;">{company_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col4:
                    # Email
                    if email:
                        st.markdown(f'<div style="color: #666; font-size: 0.85em;">✉️ {email_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col5:
                    # Phone
                    if phone:
                        st.markdown(f'<div style="color: #666; font-size: 0.85em;">☎️ {phone_display}</div>', unsafe_allow_html=True)
                    else:
                        st.markdown('<div style="color: #ccc;">—</div>', unsafe_allow_html=True)
                
                with row_col6:
                    # Action buttons in compact row
                    action_col1, action_col2, action_col3, action_col4 = st.columns([1, 1, 1, 1])
                    
                    with action_col1:
                        # Lock/Unlock button (smaller)
                        btn_label = "🔓" if is_locked else "🔒"
                        if st.button(btn_label, key=f"lock_{idx}", 
                                   help="Lock/Unlock" if not is_locked else "Lock/Unlock",
                                   use_container_width=True):
                            st.session_state.processed_cards[idx]['locked'] = not is_locked
                            st.rerun()
                    
                    with action_col2:
                        # Retry button (smaller)
                        retry_disabled = is_locked
                        if st.button("🔄", key=f"retry_{idx}", 
                                   disabled=retry_disabled,
                                   help="Retry" if not retry_disabled else "Unlock first",
                                   use_container_width=True):
                            st.session_state[f'retry_card_{idx}'] = True
                            st.rerun()
                    
                    with action_col3:
                        # VCF download (smaller)
                        if include_vcf:
                            st.download_button(
                                label="📥",
                                data=card['vcf_content'],
                                file_name=f"{card['filename']}.vcf",
                                mime="text/vcard",
                                key=f"vcf_{idx}_{card['filename']}",
                                help="Download VCF",
                                use_container_width=True
                            )
                    
                    with action_col4:
                        # Outlook CSV download (smaller)
                        if outlook_csv:
                            if outlook_simplified:
                                single_outlook_csv = export_processor.export_to_outlook_csv_simple(
                                    [card['contact_data']],
                                    email_field_name=outlook_email_field,
                                    phone_field_name=outlook_phone_field,
                                    use_quotes=outlook_use_quotes
                                )
                            else:
                                single_outlook_csv = export_processor.export_to_outlook_csv(
                                    [card['contact_data']],
                                    email_field_name=outlook_email_field,
                                    phone_field_name=outlook_phone_field
                                )
                            st.download_button(
                                label="📧",
                                data=single_outlook_csv,
                                file_name=f"{card['filename']}.csv",
                                mime="text/csv",
                                key=f"outlook_csv_{idx}_{card['filename']}",
                                help="Download Outlook CSV",
                                use_container_width=True
                            )
                
                # Add subtle divider between items
                if idx < len(st.session_state.processed_cards) - 1:
                    st.markdown('<hr style="margin: 8px 0; border: none; border-top: 1px solid #e0e0e0;">', unsafe_allow_html=True)
            
            # Clear visual separation
            st.markdown("<br>", unsafe_allow_html=True)
            st.divider()
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Bulk Downloads Section
            st.markdown("### 📦 Bulk Downloads")
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            bulk_col1, bulk_col2 = st.columns(2)
            
            with bulk_col1:
                # Excel Export
                if include_excel:
                    excel_data = export_processor.export_to_excel(contacts)
                    st.download_button(
                        label="📗 Download Excel (XLSX)",
                        data=excel_data,
                        file_name=f"contacts_{timestamp}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="Microsoft Excel format with formatting",
                        use_container_width=True
                    )
                
                # Combined VCF
                if include_vcf:
                    combined_vcf = "\n".join(card['vcf_content'] for card in st.session_state.processed_cards)
                    st.download_button(
                        label="📋 Download Combined VCF",
                        data=combined_vcf,
                        file_name=f"all_contacts_{timestamp}.vcf",
                        mime="text/vcard",
                        help="All contacts in one VCF file",
                        use_container_width=True
                    )
            
            with bulk_col2:
                # Outlook CSV Export
                if outlook_csv:
                    if outlook_simplified:
                        outlook_csv_data = export_processor.export_to_outlook_csv_simple(
                            contacts,
                            email_field_name=outlook_email_field,
                            phone_field_name=outlook_phone_field,
                            use_quotes=outlook_use_quotes
                        )
                    else:
                        outlook_csv_data = export_processor.export_to_outlook_csv(
                            contacts,
                            email_field_name=outlook_email_field,
                            phone_field_name=outlook_phone_field
                        )
                    
                    st.download_button(
                        label="📧 Download Outlook CSV",
                        data=outlook_csv_data,
                        file_name=f"outlook_import_{timestamp}.csv",
                        mime="text/csv",
                        help="Import this CSV directly into Outlook",
                        use_container_width=True
                    )
                    
                    # Show diagnostic report if CSV validator is available
                    try:
                        from utils.csv_validator import CSVValidator
                        validator = CSVValidator()
                        diagnostic_report = validator.generate_diagnostic_report(outlook_csv_data)
                        
                        with st.expander("📋 CSV Diagnostic Report", expanded=False):
                            st.code(diagnostic_report, language='text')
                    except Exception as e:
                        pass  # Skip diagnostic if validator fails
                
                # Complete Package (ZIP)
                if include_vcf or include_excel or outlook_csv:
                    st.markdown("---")
                    st.markdown("**🎁 Complete Package:**")
                    vcf_files = [(f"{card['filename']}.vcf", card['vcf_content']) 
                                for card in st.session_state.processed_cards]
                    
                    package_data = export_processor.create_export_package(
                        contacts=contacts,
                        vcf_files=vcf_files if include_vcf else [],
                        include_csv=False,  # Regular CSV removed
                        include_excel=include_excel,
                        include_outlook_csv=outlook_csv
                    )
                    
                    st.download_button(
                        label="🎁 Download ZIP Package",
                        data=package_data,
                        file_name=f"contacts_package_{timestamp}.zip",
                        mime="application/zip",
                        help="ZIP file with all selected formats",
                        use_container_width=True
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
        
        # Check Ollama Vision Model
        vision_check = VisionProcessor(model=vision_model)
        if vision_check.check_ollama_status():
            st.sidebar.success(f"✅ Ollama: Running ({vision_model})")
        else:
            st.sidebar.warning(f"⚠️ Ollama: Model '{vision_model}' not available")
            st.sidebar.info(f"Install with: ollama pull {vision_model}")
        
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

