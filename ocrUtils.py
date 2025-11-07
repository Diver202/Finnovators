import streamlit as st
import pytesseract
from PIL import Image
import io
import pdfplumber
import fitz  # PyMuPDF

from preprocessing_utils import preprocessImage

# --- Tesseract Configuration ---
tesseractPath = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
try:
    pytesseract.pytesseract.tesseract_cmd = tesseractPath
except FileNotFoundError:
    st.error(f"Tesseract executable not found at {tesseractPath}. Please update the path in ocr_utils.py.")
    
# --- File Extraction Functions ---

def extractTextFromImage(imageBytes):
    """
    Extracts text from raw image bytes using Tesseract.
    """
    try:
        image = Image.open(io.BytesIO(imageBytes))
        preProcessedImage = preprocessImage(image)
        tesseractConfig = "--psm 6"
        text = pytesseract.image_to_string(preProcessedImage, config=tesseractConfig)
        return text
    except Exception as e:
        st.error(f"Error processing image with Tesseract: {e}")
        st.error("Please make sure you have Google's Tesseract-OCR engine installed on your system (not just the 'pip install pytesseract' library).")
        return ""

def extractTextFromPdf(pdfBytes):
    """
    Extracts text from PDF bytes.
    Tries text-based extraction first, then falls back to OCR if needed.
    """
    text = ""
    try:
        # 1. Try text-based extraction
        with io.BytesIO(pdfBytes) as f:
            with pdfplumber.open(f) as pdf:
                for page in pdf.pages:
                    pageText = page.extract_text()
                    if pageText:
                        text += pageText + "\n"
        
        # 2. If text is minimal, assume it's a scanned PDF and use OCR
        if len(text.strip()) < 100: # Arbitrary threshold
            st.warning("Text-based extraction yielded little data. Attempting OCR on PDF pages...")
            text = "" 
            with fitz.open(stream=pdfBytes, filetype="pdf") as doc:
                for pageNum in range(len(doc)):
                    page = doc.load_page(pageNum)
                    pix = page.get_pixmap(dpi=300) 
                    imgBytes = pix.tobytes("png")
                    img = Image.open(io.BytesIO(imgBytes))
                    preProcessedImage = preprocessImage(img)
                    tesseractConfig = "--psm 6"
                    pageText = pytesseract.image_to_string(preProcessedImage, config = tesseractConfig)
                    text += pageText + "\n"

        return text
    
    except Exception as e:
        st.error(f"Error processing PDF: {e}")
        return ""