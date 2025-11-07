import csv
import os
import json
import streamlit as st

# --- UPDATED: Added invoiceNumber and vendorName to headers ---
CSV_HEADERS = [
    "invoiceNumber",
    "date",
    "vendorName",
    "gstNumber",
    "irn",
    "lineItems", # This will store the JSON string of the array
    "sgstAmount",
    "cgstAmount",
    "igstAmount",
    "utgstAmount",
    "cessAmount",
    "freightAndDelivery",
    "totalDiscount",
    "totalAmountStr",
    "totalAmountFloat" # Good to save the float value too
]

def saveToCSV(data, filename="params.csv"):
    """
    Appends a new row of extracted data to the specified CSV file.
    Creates the file and writes headers if it doesn't exist.
    """
    try:
        fileExists = os.path.isfile(filename)
        
        # --- UPDATED: Added invoiceNumber and vendorName to row_data ---
        row_data = {
            "invoiceNumber": data.get("invoiceNumber"),
            "date": data.get("date"),
            "vendorName": data.get("vendorName"),
            "gstNumber": data.get("gstNumber"),
            "irn": data.get("irn"),
            "lineItems": json.dumps(data.get("lineItems", [])), # Serialize list to JSON string
            "sgstAmount": data.get("sgstAmount"),
            "cgstAmount": data.get("cgstAmount"),
            "igstAmount": data.get("igstAmount"),
            "utgstAmount": data.get("utgstAmount"),
            "cessAmount": data.get("cessAmount"),
            "freightAndDelivery": data.get("freightAndDelivery"),
            "totalDiscount": data.get("totalDiscount"),
            "totalAmountStr": data.get("totalAmountStr"),
            "totalAmountFloat": data.get("totalAmountFloat")
        }

        with open(filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            
            if not fileExists:
                writer.writeheader() 
                
            writer.writerow(row_data) 
        
        # This message is optional, you can comment it out
        st.success(f"Successfully appended data to {filename}")

    except Exception as e:
        st.error(f"Error saving to CSV: {e}")