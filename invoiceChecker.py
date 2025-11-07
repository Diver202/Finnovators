import csv
import os
from datetime import datetime

CSV_FILE = 'invoice_data.csv'

def is_duplicate(invoice_no, date, gstin):
    if not os.path.exists(CSV_FILE):
        return False

    with open(CSV_FILE, mode='r', newline='', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if (row['invoice_no'] == invoice_no and
                row['date'] == date and
                row['gstin'] == gstin):
                return True
    return False

def validate_date_format(date_str):
    try:
        datetime.strptime(date_str, "%d-%m-%Y")
        return True
    except ValueError:
        return False

def add_invoice(invoice_no, date, gstin):
    if not validate_date_format(date):
        print("❌ Invalid date format. Please use dd-mm-yyyy.")
        return False

    if is_duplicate(invoice_no, date, gstin):
        
        return False

    file_exists = os.path.exists(CSV_FILE)
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        fieldnames = ['invoice_no', 'date', 'gstin']
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerow({'invoice_no': invoice_no, 'date': date, 'gstin': gstin})
        print("✅ Invoice added successfully.")
        return True

if __name__ == "__main__":
    invoice_no = input("Enter invoice number: ").strip()
    date = input("Enter invoice date (dd-mm-yyyy): ").strip()
    gstin = input("Enter GSTIN: ").strip()

    add_invoice(invoice_no, date, gstin)