import csv
import os
import json
import streamlit as st

# Define the headers for the CLEAN data
CLEAN_CSV_HEADERS = [
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
    "totalAmountFloat"
]

# Define the headers for the FLAGGED data (includes a reasons column)
FLAGGED_CSV_HEADERS = CLEAN_CSV_HEADERS + ["flag_reasons"]

def _get_row_data(data):
    """Helper function to convert parsedData dict into a CSV row dict."""
    return {
        "invoiceNumber": data.get("invoiceNumber"),
        "date": data.get("date"),
        "vendorName": data.get("vendorName"),
        "gstNumber": data.get("gstNumber"),
        "irn": data.get("irn"),
        "lineItems": json.dumps(data.get("lineItems", [])), # Serialize list
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

def save_to_clean_csv(data, filename="params_clean.csv"):
    """
    Appends a new row of clean data to the specified CSV file.
    Creates the file and writes headers if it doesn't exist.
    """
    try:
        fileExists = os.path.isfile(filename)
        row_data = _get_row_data(data)

        with open(filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CLEAN_CSV_HEADERS)
            if not fileExists:
                writer.writeheader()
            writer.writerow(row_data)
        
        st.success(f"Appended to {filename}")

    except Exception as e:
        st.error(f"Error saving to clean CSV: {e}")

def save_to_flagged_csv(data, reasons_list, filename="params_flagged.csv"):
    """
    Appends a new row of flagged data to the specified CSV file.
    Creates the file and writes headers if it doesn't exist.
    """
    try:
        fileExists = os.path.isfile(filename)
        row_data = _get_row_data(data)
        
        # Add the new column with all flag reasons
        row_data["flag_reasons"] = json.dumps(reasons_list)

        with open(filename, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=FLAGGED_CSV_HEADERS)
            if not fileExists:
                writer.writeheader()
            writer.writerow(row_data)
            
        st.warning(f"Saved to {filename} for review.")

    except Exception as e:
        st.error(f"Error saving to flagged CSV: {e}")