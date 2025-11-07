import streamlit as st
import asyncio

# Import all the functions from our new, separated utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile


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
                saveJaisonToFile(parsedData, uploadedFile.name)
            st.json(parsedData)
            
        with col2:
            st.subheader("Validation & Discrepancy Report (Step 2: Validation)")
            # Check if parsedData is not empty
            if parsedData:
                # This now only passes 'parsedData' as rawText no longer exists
                findings = await performDiscrepancyChecks(parsedData)
                
                for i in range(0, len(findings), 2):
                    messageTypeFunc = findings[i]
                    message = findings[i+1]
                    messageTypeFunc(message) 
            else:
                st.error("Could not extract any data from the uploaded file.")

if __name__ == "__main__":
    # This is the standard way to run an async main function
    asyncio.run(main())