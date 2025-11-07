import streamlit as st
import asyncio

# Import all the functions from our utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile
# --- NEW: Import the HSN validator ---
from HSNSACValidate import validateHSNRates


# --- Streamlit App UI (Must be async) ---

async def main():
    st.set_page_config(layout="wide", page_title="Invoice Fraud Detector")
    st.title("Invoice Fraud & Discrepancy Detector")
    st.write("Upload a tax invoice (PDF or Image) to extract data and check for potential issues.")

    uploadedFile = st.file_uploader("Choose an invoice file", type=["pdf", "png", "jpg", "jpeg"])

    if uploadedFile is not None:
        fileBytes = uploadedFile.getvalue()
        fileType = uploadedFile.type
        
        # Display the image if it's an image file
        if fileType.startswith("image/"):
            st.image(fileBytes, caption="Uploaded Image", use_column_width=True)

        st.divider()
        col1, col2 = st.columns(2)
        
        parsedData = {}
        
        with col1:
            st.subheader("Extracted Data (from AI)")
            # This is now the main processing step
            with st.spinner(f"Analyzing {uploadedFile.name}... (Step 1: AI Vision)"):
                parsedData = await parseInvoiceMultimodal(fileBytes, fileType)
            
            if parsedData:
                # We can save this immediately
                saveJaisonToFile(parsedData, uploadedFile.name)
            st.json(parsedData)
            
        with col2:
            st.subheader("Validation & Discrepancy Report")
            # Check if parsedData is not empty
            if parsedData:
                # --- Step 2: Run internal and GSTIN checks ---
                st.write("**(Step 2: Validation)**")
                with st.spinner("Running math checks & verifying GSTIN online..."):
                    findings = await performDiscrepancyChecks(parsedData)
                    
                    for i in range(0, len(findings), 2):
                        messageTypeFunc = findings[i]
                        message = findings[i+1]
                        messageTypeFunc(message)
                
                st.divider() # Add a separator

                # --- Step 3: Run the new HSN web check ---
                st.write("**(Step 3: HSN/SAC Rate Verification)**")
                with st.spinner("Cross-referencing HSN rates with live web data..."):
                    hsn_findings = await validateHSNRates(parsedData)
                    
                    if not hsn_findings:
                        st.info("No HSN/SAC codes were found to validate online.")
                    
                    # Display the new findings
                    for i in range(0, len(hsn_findings), 2):
                        messageTypeFunc = hsn_findings[i]
                        message = hsn_findings[i+1]
                        messageTypeFunc(message)
                        
            else:
                st.error("Could not extract any data from the uploaded file.")

if __name__ == "__main__":
    # This is the standard way to run an async main function
    asyncio.run(main())