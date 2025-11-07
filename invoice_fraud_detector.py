import streamlit as st
import pytesseract
from PIL import Image
import io
import re
import pdfplumber
import fitz  # PyMuPDF

tesseractPath = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
pytesseract.pytesseract.tesseract_cmd = tesseractPath

def extractTextFromImage(imageBytes):
    try:
        image = Image.open(io.BytesIO(imageBytes))
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        st.error(f"Error processing image with Tesseract: {e}")
        st.error("Please make sure you have Google's Tesseract-OCR engine installed on your system (not just the 'pip install pytesseract' library).")
        return ""

def extractTextFromPdf(pdfBytes):
    text = ""
    try:
        with io.BytesIO(pdfBytes) as f:
            with pdfplumber.open(f) as pdf:
                for page in pdf.pages:
                    pageText = page.extract_text()
                    if pageText:
                        text += pageText + "\n"
        
        if len(text.strip()) < 100: # Arbitrary threshold
            st.warning("Text-based extraction yielded little data. Attempting OCR on PDF pages...")
            text = "" 
            with fitz.open(stream=pdfBytes, filetype="pdf") as doc:
                for pageNum in range(len(doc)):
                    page = doc.load_page(pageNum)
                    pix = page.get_pixmap(dpi=300) 
                    imgBytes = pix.tobytes("png")
                    img = Image.open(io.BytesIO(imgBytes))
                    
                    pageText = pytesseract.image_to_string(img)
                    text += pageText + "\n"

        return text
    
    except Exception as e:
        st.error(f"Error processing PDF: {e}")
        return ""

def parseInvoiceText(text):
    gstPattern = re.compile(r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b', re.IGNORECASE)
    totalPattern = re.compile(r'(?:Total|Grand Total|Amount Due)\s*[:]?\s*[\$₹]?\s*([0-9,]+\.\d{2})', re.IGNORECASE)

    gstNumbers = gstPattern.findall(text)
    totalAmounts = totalPattern.findall(text)

    data = {
        "gstNumber": gstNumbers[0] if gstNumbers else None,
        "totalAmountStr": totalAmounts[-1] if totalAmounts else None,
    }
    
    if data["totalAmountStr"]:
        try:
            data["totalAmountFloat"] = float(data["totalAmountStr"].replace(',', ''))
        except ValueError:
            data["totalAmountFloat"] = None
    else:
        data["totalAmountFloat"] = None

    return data

#this needs to be changed

def mockVerifyGstNumber(gstNumber):
    if not gstNumber:
        return {"status": "Missing", "message": "No GST number found in invoice."}

    knownFraudulentGsts = ["27ABCDE1234F1Z5", "29AAAAA0000A1Z9"]
    validGstsDb = {
        "36AAIFP1234A1Z2": {"name": "Genuine Tech Solutions", "status": "Active"},
        "27AACCT5678F1Z6": {"name": "Reliable Goods Co.", "status": "Active"}
    }
    
    if gstNumber in knownFraudulentGsts:
        return {"status": "Fraudulent", "message": f"GSTIN {gstNumber} is on a known fraud list."}
    
    if gstNumber in validGstsDb:
        return {"status": "Verified", "message": f"GSTIN {gstNumber} is valid and belongs to '{validGstsDb[gstNumber]['name']}'."}
        
    return {"status": "Unverified", "message": f"GSTIN {gstNumber} could not be verified against the portal. (May be new or invalid)."}

#this needs to be changed
def performDiscrepancyChecks(data, text):
    findings = []
    
    gstCheck = mockVerifyGstNumber(data.get("gstNumber"))
    
    if gstCheck["status"] == "Verified":
        findings.append(st.success)
    elif gstCheck["status"] in ["Fraudulent", "Missing"]:
        findings.append(st.error)
    else: # Unverified
        findings.append(st.warning)
    
    findings.append(gstCheck["message"])
    
    if data.get("totalAmountFloat") is not None:
        if data["totalAmountFloat"] > 10000:
             findings.append(st.warning)
             findings.append(f"High Value Invoice: Total amount is {data['totalAmountFloat']}. Manual review suggested.")
        else:
             findings.append(st.success)
             findings.append(f"Invoice total of {data['totalAmountFloat']} recorded.")
    else:
        findings.append(st.error)
        findings.append("Could not extract a valid total amount from the invoice.")
    
    return findings

# --- Streamlit App UI ---

st.set_page_config(layout="wide", page_title="Invoice Fraud Detector")
st.title("📄 Invoice Fraud & Discrepancy Detector")
st.write("Upload a tax invoice (PDF or Image) to extract data and check for potential issues.")

uploadedFile = st.file_uploader("Choose an invoice file", type=["pdf", "png", "jpg", "jpeg"])

if uploadedFile is not None:
    fileBytes = uploadedFile.getvalue()
    fileType = uploadedFile.type
    
    rawText = ""
    
    with st.spinner(f"Processing {uploadedFile.name}..."):
        if fileType == "application/pdf":
            rawText = extractTextFromPdf(fileBytes)
        elif fileType.startswith("image/"):
            st.image(fileBytes, caption="Uploaded Image", use_column_width=True)
            rawText = extractTextFromImage(fileBytes)

    if rawText:
        st.divider()
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("🤖 Extracted Data")
            parsedData = parseInvoiceText(rawText)
            st.json(parsedData)
            
            with st.expander("Show Raw Extracted Text"):
                st.text_area("Raw Text", rawText, height=300)

        with col2:
            st.subheader("🔍 Validation & Discrepancy Report")
            findings = performDiscrepancyChecks(parsedData, rawText)
            
            for i in range(0, len(findings), 2):
                messageTypeFunc = findings[i]
                message = findings[i+1]
                messageTypeFunc(message) 
    else:
        st.error("Could not extract any text from the uploaded file.")