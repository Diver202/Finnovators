import streamlit as st
import asyncio
import io 
from PIL import Image

# Import all the functions from our utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile
from HSNSACValidate import validateHSNRates
from csvUtils import saveToCSV # <-- Make sure this file is named saveToCSV.py

# --- 1. DEFINE OUR CUSTOM CSS (from our 'vanity' update) ---
CUSTOM_CSS = """
<style>
    /* --- Main Page & Font --- */
    .main {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }

    /* --- Title --- */
    h1 {
        color: #5D9CEC; 
    }

    /* --- "Step" Subheaders --- */
    h3 {
        color: #AAAAAA;
        font-style: italic;
        font-weight: 300;
        font-size: 1.1em;
    }

    /* --- Style the validation message boxes --- */
    [data-testid="stSuccess"] {
        background-color: #1A3B2F;
        border: 1px solid #2ECC71;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(46, 204, 113, 0.1);
    }

    [data-testid="stError"] {
        background-color: #4A2525;
        border: 1px solid #E74C3C;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(231, 76, 60, 0.1);
    }

    [data-testid="stWarning"] {
        background-color: #4A3B25;
        border: 1px solid #F39C12;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(243, 156, 18, 0.1);
    }

    [data-testid="stInfo"] {
        background-color: #253B4A;
        border: 1px solid #3498DB;
        border-radius: 10px;
        box-shadow: 0 4px 15px rgba(52, 152, 219, 0.1);
    }

    /* --- Style the JSON expander --- */
    .st-expander {
        border: 1px solid #333;
        border-radius: 10px;
    }
    .st-expander header {
        background-color: #1E1E1E;
        border-radius: 10px 10px 0 0;
    }
</style>
"""

# --- 2. Helper function to render the report for a selected file ---
# This contains all your old "column" logic
def render_report(file_name):
    
    # Get the data for the selected file from session state
    report_data = st.session_state.processed_data[file_name]
    parsed_data = report_data["parsed_data"]
    validation_findings = report_data["validation_findings"]
    hsn_findings = report_data["hsn_findings"]
    file_bytes = report_data["file_bytes"]
    file_type = report_data["file_type"]

    # Display the image (or convert TIFF)
    if file_type.startswith("image/"):
        try:
            if file_type != "image/tiff":
                st.image(file_bytes, caption=f"Uploaded Image: {file_name}", use_column_width=True)
            else:
                with io.BytesIO(file_bytes) as f:
                    img = Image.open(f)
                    with io.BytesIO() as output:
                        if getattr(img, "n_frames", 1) > 1:
                            img.seek(0)
                        img.save(output, format="PNG")
                        st.image(
                            output.getvalue(), 
                            caption=f"Uploaded Image: {file_name} (Converted from TIFF)", 
                            use_column_width=True
                        )
        except Exception as e:
            st.error(f"Could not display image: {e}")

    st.divider()
    
    col1, col2 = st.columns(2)
    
    # --- Column 1: Extracted Data ---
    with col1:
        st.subheader("Extracted Data (from AI)")
        with st.expander("View Extracted JSON Data", expanded=False):
            st.json(parsed_data)
        
        # Show key info at a glance
        st.info(f"**Invoice Number:** `{parsed_data.get('invoiceNumber', 'N/A')}`")
        st.info(f"**Vendor:** `{parsed_data.get('vendorName', 'N/A')}`")
        st.info(f"**Total Amount:** `{parsed_data.get('totalAmountStr', 'N/A')}`")

    # --- Column 2: Validation Report ---
    with col2:
        st.subheader("Validation & Discrepancy Report")
        
        st.markdown("<h3>(Step 2: Validation)</h3>", unsafe_allow_html=True)
        for i in range(0, len(validation_findings), 2):
            validation_findings[i](validation_findings[i+1]) # Call function with message
        
        st.divider() 

        st.markdown("<h3>(Step 3: HSN/SAC Rate Verification)</h3>", unsafe_allow_html=True)
        if not hsn_findings:
            st.info("No HSN/SAC codes were found to validate online.")
        for i in range(0, len(hsn_findings), 2):
            hsn_findings[i](hsn_findings[i+1]) # Call function with message


# --- Main App Function ---
async def main():
    # --- 3. Page Config & State Initialization ---
    st.set_page_config(
        layout="wide", 
        page_title="Invoice Fraud Detector",
        page_icon=":shield:",
        initial_sidebar_state="expanded" # Keep sidebar open
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("Invoice Fraud & Discrepancy Detector")

    # Initialize session state to store all our results
    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = {}

    # --- 4. The Main Uploader ---
    uploaded_files = st.file_uploader(
        "Drag and drop a folder or select multiple files",
        type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"],
        accept_multiple_files=True,
        key="batch_uploader"
    )

    if st.button("Process All Uploaded Files", key="batch_process", use_container_width=True):
        if not uploaded_files:
            st.warning("Please upload files first.")
        else:
            # Clear old data on a new run
            st.session_state.processed_data = {}
            
            total_files = len(uploaded_files)
            progress_bar = st.progress(0, text=f"Starting batch process... 0/{total_files}")
            
            temp_results = {} # Store results temporarily

            for i, file in enumerate(uploaded_files):
                current_file_name = file.name
                progress_bar.progress(
                    (i + 1) / total_files, 
                    text=f"Processing {current_file_name}... ({i + 1}/{total_files})"
                )
                
                try:
                    file_bytes = file.getvalue()
                    file_type = file.type
                    
                    # --- RUN THE FULL PIPELINE ---
                    parsed_data = await parseInvoiceMultimodal(file_bytes, file_type)
                    
                    if parsed_data and (parsed_data.get("invoiceNumber") or parsed_data.get("irn")):
                        validation_findings = await performDiscrepancyChecks(parsed_data)
                        hsn_findings = await validateHSNRates(parsed_data)
                        
                        # Save to files
                        saveJaisonToFile(parsed_data, current_file_name)
                        saveToCSV(parsed_data)
                        
                        # Store all results in our state
                        temp_results[current_file_name] = {
                            "parsed_data": parsed_data,
                            "validation_findings": validation_findings,
                            "hsn_findings": hsn_findings,
                            "file_bytes": file_bytes,
                            "file_type": file_type
                        }
                    else:
                        temp_results[current_file_name] = {
                            "parsed_data": parsed_data,
                            "validation_findings": [st.error, "Failed to parse any data from this file."],
                            "hsn_findings": [],
                            "file_bytes": file_bytes,
                            "file_type": file_type
                        }
                    
                    # Update state *inside the loop*
                    # This makes the sidebar populate as files are processed
                    st.session_state.processed_data = temp_results

                except Exception as e:
                    st.error(f"Critical error on {current_file_name}: {e}. Skipping.")
            
            progress_bar.empty()
            st.success(f"Batch processing complete! Processed {len(st.session_state.processed_data)} files.")

    # --- 5. The Sidebar Logic ---
    # This part runs every time the script reruns
    
    if st.session_state.processed_data:
        st.sidebar.title("Processed Files")
        st.sidebar.write("Select an invoice to view its detailed report.")
        
        file_names = list(st.session_state.processed_data.keys())
        
        # Use a radio button to select the file
        selected_file = st.sidebar.radio(
            "Invoices:",
            file_names,
            label_visibility="collapsed"
        )
        
        # --- 6. The Main Content Area ---
        # This will now show the report for the selected file
        if selected_file:
            render_report(selected_file)
    else:
        st.info("Upload one or more invoice files and click 'Process All' to see the validation reports.")


if __name__ == "__main__":
    asyncio.run(main())