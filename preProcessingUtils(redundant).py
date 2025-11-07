import streamlit as st
import cv2
import numpy as np
from PIL import Image

def preProcessImage(pilImage):
    """
    Uses OpenCV to preprocess a PIL Image for better Tesseract accuracy.
    Converts to grayscale and then binarizes (pure black & white).
    """
    try:
        rgbImage = pilImage.convert('RGB')
        ocvImage = np.array(rgbImage)
        ocvImage = ocvImage[:, :, ::-1].copy() 

        grayImage = cv2.cvtColor(ocvImage, cv2.COLOR_BGR2GRAY)
        blurredImage = cv2.GaussianBlur(grayImage, (5, 5), 0)
        _, binaryImage = cv2.threshold(
            blurredImage, 
            0, 
            255, 
            cv2.THRESH_BINARY | cv2.THRESH_OTSU
        )

        # 4. Convert back to PIL Image format
        return Image.fromarray(binaryImage)

    except Exception as e:
        st.warning(f"Image preprocessing failed: {e}. Using original image.")
        return pilImage # Return the original image if something fails

# --- Standalone Test Script ---

# if __name__ == "__main__":
#     """
#     This is a test script to see the pre-processing in action.
#     To use it:
#     1. Uncomment this entire block of code (from `if __name__...` to the end).
#     2. Install PyMuPDF: pip install PyMuPDF
#     3. Run this from your terminal:
#        python preProcessingUtils.py "path/to/your/test_invoice.pdf"
    
#     It will create an 'output_preprocessed_page_0.png' file so you can see the result.
#     """
#     import sys
#     import fitz  # PyMuPDF
#     import io

#     print("Starting pre-processing test...")
    
#     if len(sys.argv) < 2:
#         print("Error: Please provide a path to a PDF file.")
#         print("Usage: python preprocessing_utils.py \"path/to/your/test.pdf\"")
#         sys.exit(1)

#     pdfPath = sys.argv[1]
    
#     try:
#         # 1. Open the PDF
#         doc = fitz.open(pdfPath)
        
#         # 2. Get the first page
#         page = doc.load_page(0)
        
#         # 3. Convert page to an image (as bytes)
#         pix = page.get_pixmap(dpi=300)
#         imgBytes = pix.tobytes("png")
        
#         # 4. Load image bytes into PIL
#         pilImg = Image.open(io.BytesIO(imgBytes))
        
#         print(f"Successfully loaded page 0 from {pdfPath}...")

#         # 5. Run the preprocessing function
#         preprocessedPilImg = preProcessImage(pilImg)
        
#         # 6. Save the output file
#         outputFilename = "output_preprocessed_page_0.png"
#         preprocessedPilImg.save(outputFilename)
        
#         print(f"SUCCESS: Pre-processing complete.")
#         print(f"Check the output file: {outputFilename}")

#     except Exception as e:
#         print(f"An error occurred: {e}")
#         print("Make sure you have PyMuPDF installed ('pip install PyMuPDF')")