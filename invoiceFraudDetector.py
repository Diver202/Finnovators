import streamlit as st
import asyncio
import io 
from PIL import Image
import re

# Import all the functions from our utility files
from aiUtils import parseInvoiceMultimodal
from validationUtils import performDiscrepancyChecks
from saveJaison import saveJaisonToFile
from HSNSACValidate import validateHSNRates
from csvUtils import save_to_clean_csv, save_to_flagged_csv
from duplicationValidator import run_historical_checks 
# --- 1. FIX 1: ADD THE MISSING IMPORT ---
from notificationManager import send_email_report 

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

# --- render_report function (Unchanged) ---
def render_report(file_name):
    
    report_data = st.session_state.processed_data[file_name]
    parsed_data = report_data["parsed_data"]
    all_flags = report_data["all_flags"]
    historical_findings = report_data["historical_findings"]
    
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
        
        if historical_findings.get("near_duplicates"):
            with st.expander("View Duplicate Details"):
                st.json(historical_findings["near_duplicates"])


# --- render_login_page function (Unchanged) ---
def render_login_page():
    st.set_page_config(
        layout="centered", 
        page_title="Invoice Detector Login",
        page_icon=":shield:"
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    st.title("TrueBill AI")
    
    with st.form("login_form"):
        st.write("Please enter your email to receive batch reports.")
        email = st.text_input("Your Email")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            if re.match(r"[^@]+@[^@]+\.[^@]+", email):
                st.session_state['logged_in'] = True
                st.session_state['user_email'] = email
                st.rerun()
            else:
                st.error("Please enter a valid email address.")

# --- Main App Function (FIXED) ---
async def main():
    
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['user_email'] = ""
    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = {}

    if not st.session_state['logged_in']:
        render_login_page()
        return

    st.set_page_config(
        layout="wide", 
        page_title="Invoice Fraud Detector",
        page_icon=":shield:",
        initial_sidebar_state="expanded"
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # --- Sidebar ---
    with st.sidebar:
        st.title("Processed Files")
        st.write(f"Logged in as: `{st.session_state['user_email']}`")
        if st.button("Logout"):
            st.session_state['logged_in'] = False
            st.session_state['user_email'] = ""
            st.session_state['processed_data'] = {}
            st.rerun()
            
        st.write("Select an invoice to view its detailed report.")
        
        file_names = list(st.session_state.processed_data.keys())
        
        selected_file = st.sidebar.radio(
            "Invoices:",
            file_names,
            label_visibility="collapsed"
        )
    
    # --- Main content area ---
    st.title("Invoice Fraud & Discrepancy Detector")

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
            # Clear state *before* processing
            st.session_state.processed_data.clear()
            
            total_files = len(uploaded_files)
            progress_bar = st.progress(0, text=f"Starting batch process... 0/{total_files}")
            
            flagged_files_for_email = []

            for i, file in enumerate(uploaded_files):
                current_file_name = file.name
                progress_text = f"Processing {current_file_name}... ({i + 1}/{total_files})"
                progress_bar.progress((i + 1) / total_files, text=progress_text)
                
                all_flags = []
                parsed_data = {}
                historical_findings = {} 
                file_bytes = b""
                file_type = "unknown"
                
                try:
                    file_bytes = file.getvalue()
                    file_type = file.type
                    
                    parsed_data = await parseInvoiceMultimodal(file_bytes, file_type)
                    
                    if not parsed_data or not (parsed_data.get("invoiceNumber") or parsed_data.get("gstNumber")):
                        all_flags.append("Failed to parse key data (Invoice # or GSTIN).")
                        historical_findings = {"overall_flag": "PARSE_ERROR", "reasons": all_flags}
                    
                    else:
                        validation_findings = await performDiscrepancyChecks(parsed_data)
                        for j in range(0, len(validation_findings), 2):
                            if validation_findings[j] != st.success: 
                                all_flags.append(validation_findings[j+1])

                        hsn_findings = await validateHSNRates(parsed_data)
                        for j in range(0, len(hsn_findings), 2):
                            if hsn_findings[j] != st.success:
                                all_flags.append(hsn_findings[j+1])

                        historical_findings = await asyncio.to_thread(
                            run_historical_checks, parsed_data, "params_clean.csv" 
                        )
                        
                        hist_flag = historical_findings.get("overall_flag")
                        if hist_flag != "CLEAN":
                            all_flags.extend(historical_findings.get("reasons", ["Historical check failed."]))
                    
                    if not all_flags:
                        save_to_clean_csv(parsed_data, "params_clean.csv")
                    else:
                        save_to_flagged_csv(parsed_data, all_flags, "params_flagged.csv")
                        flagged_files_for_email.append({
                            "file_name": current_file_name,
                            "reasons": all_flags
                        })
                    
                    saveJaisonToFile(parsed_data, current_file_name)
                    
                    # We save results for *all* files, even error ones
                    st.session_state.processed_data[current_file_name] = {
                        "parsed_data": parsed_data,
                        "all_flags": all_flags,
                        "historical_findings": historical_findings,
                        "file_bytes": file_bytes,
                        "file_type": file_type
                    }

                except Exception as e:
                    st.error(f"Critical error on {current_file_name}: {e}. Skipping.")
                    all_flags = [f"Critical error: {e}"]
                    
                    flagged_files_for_email.append({
                        "file_name": current_file_name,
                        "reasons": all_flags
                    })
                    
                    st.session_state.processed_data[current_file_name] = {
                        "parsed_data": {"error": str(e)},
                        "all_flags": all_flags,
                        "historical_findings": {"overall_flag": "CRITICAL_ERROR", "reasons": all_flags},
                        "file_bytes": file_bytes, # Use the bytes we have
                        "file_type": file_type # Use the type we have
                    }
            
            # --- End of loop ---
            progress_bar.empty()
            st.success(f"Batch processing complete! Processed {len(st.session_state.processed_data)} files.")
            
            if flagged_files_for_email:
                with st.spinner("Sending email report..."):
                    await asyncio.to_thread(
                        send_email_report,
                        st.session_state['user_email'],
                        flagged_files_for_email
                    )
            else:
                st.success("No flagged files found in this batch!")
            
            # --- 2. FIX 2: ADD THE RERUN CALL ---
            # This forces Streamlit to reload the script,
            # which makes the sidebar see the new session_state.
            st.rerun()

    # --- Main Content Area (Report Display) ---
    if st.session_state.processed_data:
        if selected_file:
            render_report(selected_file)
    else:
        st.info("Upload one or more invoice files and click 'Process All' to see the validation reports.")

if __name__ == "__main__":
    asyncio.run(main())