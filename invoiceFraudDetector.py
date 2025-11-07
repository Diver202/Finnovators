import streamlit as st
import asyncio
import io 
from PIL import Image

# Import all the functions from our utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile
from HSNSACValidate import validateHSNRates
from csvUtils import saveToCSV  # <-- 1. IMPORT THE NEW FUNCTION


async def main():
    st.set_page_config(layout="wide", page_title="Invoice Fraud Detector")
    st.title("Invoice Fraud & Discrepancy Detector")
    st.write("Upload a tax invoice (PDF or Image) to extract data and check for potential issues.")

    uploadedFile = st.file_uploader(
        "Choose an invoice file", 
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"]
    )

    if uploadedFile is not None:
        fileBytes = uploadedFile.getvalue()
        fileType = uploadedFile.type
        
        if fileType.startswith("image/"):
            try:
                if fileType != "image/tiff":
                    st.image(fileBytes, caption="Uploaded Image", use_column_width=True)
                else:
                    with io.BytesIO(fileBytes) as f:
                        img = Image.open(f)
                        with io.BytesIO() as output:
                            if getattr(img, "n_frames", 1) > 1:
                                img.seek(0)
                            
                            img.save(output, format="PNG")
                            st.image(
                                output.getvalue(), 
                                caption="Uploaded Image (Converted from TIFF)", 
                                use_column_width=True
                            )
            except Exception as e:
                st.error(f"Could not display image: {e}")

        st.divider()
        col1, col2 = st.columns(2)
        
        parsedData = {}
        
        with col1:
            st.subheader("Extracted Data (from AI)")
            with st.spinner(f"Analyzing {uploadedFile.name}... (Step 1: AI Vision)"):
                parsedData = await parseInvoiceMultimodal(fileBytes, fileType)
            
            if parsedData:
                saveJaisonToFile(parsedData, uploadedFile.name)
                saveToCSV(parsedData) # <-- 2. CALL THE NEW FUNCTION
            st.json(parsedData)
            
        with col2:
            st.subheader("Validation & Discrepancy Report")
            if parsedData:
                st.write("**(Step 2: Validation)**")
                with st.spinner("Running math checks & verifying GSTIN online..."):
                    findings = await performDiscrepancyChecks(parsedData)
                    
                    for i in range(0, len(findings), 2):
                        messageTypeFunc = findings[i]
                        message = findings[i+1]
                        messageTypeFunc(message)
                
                st.divider() 

                st.write("**(Step 3: HSN/SAC Rate Verification)**")
                with st.spinner("Cross-referencing HSN rates with live web data..."):
                    hsn_findings = await validateHSNRates(parsedData)
                    
                    if not hsn_findings:
                        st.info("No HSN/SAC codes were found to validate online.")
                    
                    for i in range(0, len(hsn_findings), 2):
                        messageTypeFunc = hsn_findings[i]
                        message = hsn_findings[i+1]
                        messageTypeFunc(message)
                        
            else:
                st.error("Could not extract any data from the uploaded file.")

if __name__ == "__main__":
    asyncio.run(main())