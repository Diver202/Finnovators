import streamlit as st
import asyncio

# Import all the functions from our new, separated utility files
from ocrUtils import (
    extractTextFromPdf,
    extractTextFromImage
)
from aiUtils import parseInvoiceText
from validationUtils import performDiscrepancyChecks


# --- Streamlit App UI (Must be async) ---

async def main():
    st.set_page_config(layout="wide", page_title="Invoice Fraud Detector")
    st.title("Invoice Fraud & Discrepancy Detector")
    st.write("Upload a tax invoice (PDF or Image) to extract data and check for potential issues.")

    uploadedFile = st.file_uploader("Choose an invoice file", type=["pdf", "png", "jpg", "jpeg"])

    if uploadedFile is not None:
        fileBytes = uploadedFile.getvalue()
        fileType = uploadedFile.type
        
        rawText = ""
        
        with st.spinner(f"Processing {uploadedFile.name}... (Step 1: OCR)"):
            if fileType == "application/pdf":
                rawText = extractTextFromPdf(fileBytes)
            elif fileType.startswith("image/"):
                st.image(fileBytes, caption="Uploaded Image", use_column_width=True)
                rawText = extractTextFromImage(fileBytes)

        if rawText:
            st.divider()
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Extracted Data (from AI)")
                # This is now an async call, so we use 'await'
                with st.spinner("Calling AI model to parse text... (Step 2: AI Parsing)"):
                    parsedData = await parseInvoiceText(rawText)
                
                st.json(parsedData)
                
                with st.expander("Show Raw Extracted Text"):
                    st.text_area("Raw Text", rawText, height=300)

            with col2:
                st.subheader("Validation & Discrepancy Report (Step 3: Validation)")
                findings = performDiscrepancyChecks(parsedData, rawText)
                
                for i in range(0, len(findings), 2):
                    messageTypeFunc = findings[i]
                    message = findings[i+1]
                    messageTypeFunc(message) 
        else:
            st.error("Could not extract any text from the uploaded file.")

if __name__ == "__main__":
    # This is the standard way to run an async main function in Streamlit
    asyncio.run(main())