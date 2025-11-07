import csv
import os
import json
import streamlit as st

# Define the headers based on ALL fields in parsedData
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
        # Check if file exists to determine if we need to write headers
        fileExists = os.path.isfile(filename)
        
        # Prepare the data row as a dictionary
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
            # Use DictWriter to map our dictionary to the CSV columns
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            
            if not fileExists:
                writer.writeheader() # Write headers only if file is new
                
            writer.writerow(row_data) # Append the new data row
        
        # This message is optional, you can comment it out
        st.success(f"Successfully appended data to {filename}")

    except Exception as e:
        st.error(f"Error saving to CSV: {e}")