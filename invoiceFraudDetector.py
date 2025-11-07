import streamlit as st
import asyncio
import io 
from PIL import Image

# Import all the functions from our utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile
from HSNSACValidate import validateHSNRates
# --- 1. IMPORT NEW CSV MANAGER AND DELETE OLD 'saveToCSV' ---
from csvUtils import save_to_clean_csv, save_to_flagged_csv
from duplicationValidator import run_historical_checks 

# --- CUSTOM CSS (Unchanged) ---
CUSTOM_CSS = """
<style>
    .main { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    h1 { color: #5D9CEC; }
    h3 { color: #AAAAAA; font-style: italic; font-weight: 300; font-size: 1.1em; }
    [data-testid="stSuccess"] { background-color: #1A3B2F; border: 1px solid #2ECC71; border-radius: 10px; box-shadow: 0 4px 15px rgba(46, 204, 113, 0.1); }
    [data-testid="stError"] { background-color: #4A2525; border: 1px solid #E74C3C; border-radius: 10px; box-shadow: 0 4px 15px rgba(231, 76, 60, 0.1); }
    [data-testid="stWarning"] { background-color: #4A3B25; border: 1px solid #F39C12; border-radius: 10px; box-shadow: 0 4px 15px rgba(243, 156, 18, 0.1); }
    [data-testid="stInfo"] { background-color: #253B4A; border: 1px solid #3498DB; border-radius: 10px; box-shadow: 0 4px 15px rgba(52, 152, 219, 0.1); }
    .st-expander { border: 1px solid #333; border-radius: 10px; }
    .st-expander header { background-color: #1E1E1E; border-radius: 10px 10px 0 0; }
</style>
"""

# --- 2. Helper function to render the report (UPDATED) ---
def render_report(file_name):
    
    report_data = st.session_state.processed_data[file_name]
    parsed_data = report_data["parsed_data"]
    
    # --- This is the new master list of all flags ---
    all_flags = report_data["all_flags"]
    
    file_bytes = report_data["file_bytes"]
    file_type = report_data["file_type"]

    # Display the image
    if file_type.startswith("image/"):
        try:
            if file_type != "image/tiff":
                st.image(file_bytes, caption=f"Uploaded Image: {file_name}", use_column_width=True)
            else:
                with io.BytesIO(file_bytes) as f:
                    img = Image.open(f)
                    with io.BytesIO() as output:
                        if getattr(img, "n_frames", 1) > 1: img.seek(0)
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
    
    with col1:
        st.subheader("Extracted Data (from AI)")
        with st.expander("View Extracted JSON Data", expanded=False):
            st.json(parsed_data)
        
        st.info(f"**Invoice Number:** `{parsed_data.get('invoiceNumber', 'N/A')}`")
        st.info(f"**Vendor:** `{parsed_data.get('vendorName', 'N/A')}`")
        st.info(f"**Total Amount:** `{parsed_data.get('totalAmountStr', 'N/A')}`")

    with col2:
        st.subheader("Final Validation Status")
        
        # --- 3. RENDER THE FINAL STATUS ---
        if not all_flags:
            st.success("**Status: CLEAN**")
            st.markdown("- No flags found.")
            st.markdown("- Invoice has been saved to `params_clean.csv`.")
        else:
            st.error(f"**Status: FLAGGED ({len(all_flags)} issues found)**")
            st.markdown("- This invoice has been saved to `params_flagged.csv` for review.")
            st.markdown("- **Reasons:**")
            for reason in all_flags:
                st.markdown(f"  - {reason}")
        
        # --- Optionally show details of historical duplicates ---
        historical_findings = report_data["historical_findings"]
        if historical_findings.get("near_duplicates"):
            with st.expander("View Duplicate Details"):
                st.json(historical_findings["near_duplicates"])


# --- Main App Function (UPDATED) ---
async def main():
    st.set_page_config(
        layout="wide", 
        page_title="Invoice Fraud Detector",
        page_icon=":shield:",
        initial_sidebar_state="expanded"
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("Invoice Fraud & Discrepancy Detector")

    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = {}

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
            st.session_state.processed_data = {}
            total_files = len(uploaded_files)
            progress_bar = st.progress(0, text=f"Starting batch process... 0/{total_files}")
            
            temp_results = {}

            for i, file in enumerate(uploaded_files):
                current_file_name = file.name
                progress_text = f"Processing {current_file_name}... ({i + 1}/{total_files})"
                progress_bar.progress((i + 1) / total_files, text=progress_text)
                
                # This list will store all error/warning messages
                all_flags = []
                
                try:
                    file_bytes = file.getvalue()
                    file_type = file.type
                    
                    # --- RUN THE FULL PIPELINE (UPDATED) ---
                    parsed_data = await parseInvoiceMultimodal(file_bytes, file_type)
                    
                    if not parsed_data or not (parsed_data.get("invoiceNumber") or parsed_data.get("gstNumber")):
                        all_flags.append("Failed to parse key data (Invoice # or GSTIN).")
                        # Store minimal results
                        temp_results[current_file_name] = {
                            "parsed_data": parsed_data or {"error": "Parse failed"},
                            "all_flags": all_flags,
                            "historical_findings": {},
                            "file_bytes": file_bytes,
                            "file_type": file_type
                        }
                        # Save to flagged CSV and continue
                        save_to_flagged_csv(parsed_data or {"file": current_file_name}, all_flags, "params_flagged.csv")
                        saveJaisonToFile(parsed_data, current_file_name)
                        st.session_state.processed_data = temp_results
                        continue # Move to the next file

                    # --- Step 2: Validation ---
                    validation_findings = await performDiscrepancyChecks(parsed_data)
                    for i in range(0, len(validation_findings), 2):
                        if validation_findings[i] != st.success: # If it's st.error or st.warning
                            all_flags.append(validation_findings[i+1])

                    # --- Step 3: HSN Check ---
                    hsn_findings = await validateHSNRates(parsed_data)
                    for i in range(0, len(hsn_findings), 2):
                        if hsn_findings[i] != st.success:
                            all_flags.append(hsn_findings[i+1])

                    # --- Step 4: Historical Check ---
                    # It now ONLY reads from 'params_clean.csv'
                    historical_findings = await asyncio.to_thread(
                        run_historical_checks, parsed_data, "params_clean.csv" 
                    )
                    
                    hist_flag = historical_findings.get("overall_flag")
                    if hist_flag != "CLEAN":
                        all_flags.extend(historical_findings.get("reasons", ["Historical check failed."]))
                    
                    # --- 5. FINAL DECISION & SAVE ---
                    if not all_flags:
                        # CLEAN
                        save_to_clean_csv(parsed_data, "params_clean.csv")
                    else:
                        # FLAGGED
                        save_to_flagged_csv(parsed_data, all_flags, "params_flagged.csv")
                    
                    # Always save the JSON artifact
                    saveJaisonToFile(parsed_data, current_file_name)
                    
                    # Store results for the UI
                    temp_results[current_file_name] = {
                        "parsed_data": parsed_data,
                        "all_flags": all_flags,
                        "historical_findings": historical_findings, # For duplicate details
                        "file_bytes": file_bytes,
                        "file_type": file_type
                    }
                    st.session_state.processed_data = temp_results

                except Exception as e:
                    st.error(f"Critical error on {current_file_name}: {e}. Skipping.")
            
            progress_bar.empty()
            st.success(f"Batch processing complete! Processed {len(st.session_state.processed_data)} files.")

    # --- Sidebar and Main Content Area (Unchanged) ---
    if st.session_state.processed_data:
        st.sidebar.title("Processed Files")
        st.sidebar.write("Select an invoice to view its detailed report.")
        
        file_names = list(st.session_state.processed_data.keys())
        
        selected_file = st.sidebar.radio(
            "Invoices:",
            file_names,
            label_visibility="collapsed"
        )
        
        if selected_file:
            render_report(selected_file)
    else:
        st.info("Upload one or more invoice files and click 'Process All' to see the validation reports.")

if __name__ == "__main__":
    asyncio.run(main())