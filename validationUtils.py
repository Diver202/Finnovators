import streamlit as st
import re

# --- HELPER FUNCTION ---
def _cleanAndConvertToFloat(value):
    """
    Cleans and converts a currency string to a float.
    Returns 0.0 if the value is None or invalid.
    """
    if value is None:
        return 0.0
    try:
        # Remove currency symbols, commas, and whitespace
        cleanedStr = re.sub(r'[₹$,\s]', '', str(value))
        if not cleanedStr:
            return 0.0
        return float(cleanedStr)
    except (ValueError, TypeError):
        return 0.0

# --- Validation Functions ---

def mockVerifyGstNumber(gstNumber):
    """
    Simulates a check against a GST database.
    """
    if not gstNumber:
        return {"status": "Missing", "message": "No GST number found in invoice."}

    knownFraudulentGsts = ["27ABCDE1234F1Z5", "29AAAAA0000A1Z9"]
    validGstsDb = {
        "36AAIFP1234A1Z2": {"name": "Genuine Tech Solutions", "status": "Active"},
        "27AACCT5678F1Z6": {"name": "Reliable Goods Co.", "status": "Active"}
    }
    
    if gstNumber in knownFraudulentGsts:
        return {"status": "Fraudulent", "message": f"GSTIN {gstNumber} is on a known fraud list."}
    
    if gstNumber in validGstsDb:
        return {"status": "Verified", "message": f"GSTIN {gstNumber} is valid and belongs to '{validGstsDb[gstNumber]['name']}'."}
        
    return {"status": "Unverified", "message": f"GSTIN {gstNumber} could not be verified against the portal. (May be new or invalid)."}

def performDiscrepancyChecks(data):
    """
    Generates a list of findings based on extracted data,
    including mathematical validation as requested.
    """
    findings = []
    tolerance = 1.0  # Allow for a 1 Rupee rounding error
    
    # --- Check 1: GST Number Verification ---
    gstCheck = mockVerifyGstNumber(data.get("gstNumber"))
    
    if gstCheck["status"] == "Verified":
        findings.append(st.success)
    elif gstCheck["status"] in ["Fraudulent", "Missing"]:
        findings.append(st.error)
    else: # Unverified
        findings.append(st.warning)
    
    findings.append(gstCheck["message"])
    
    # --- Check 2: Full Mathematical Validation (Line Items + Taxes = Total) ---
    
    # --- FIX: Use the helper to get float from totalAmountStr ---
    totalAmount = _cleanAndConvertToFloat(data.get("totalAmountStr"))
    lineItems = data.get("lineItems")
    calculatedSubtotal = 0.0
    itemsAreValid = True

    # Step A: Calculate subtotal from line items
    if lineItems and isinstance(lineItems, list):
        for item in lineItems:
            # We can use the helper here too for robustness
            quantity = _cleanAndConvertToFloat(item.get("quantity"))
            unitPrice = _cleanAndConvertToFloat(item.get("unitPrice"))
            
            if quantity > 0 and unitPrice > 0:
                calculatedSubtotal += quantity * unitPrice
            else:
                findings.append(st.warning)
                findings.append(f"Could not validate math: Bad data for item '{item.get('description', 'Unknown')}' (quantity: {item.get('quantity')}, price: {item.get('unitPrice')})")
                itemsAreValid = False
    else:
        findings.append(st.info)
        findings.append("No line items found to calculate subtotal from.")
        itemsAreValid = False # Can't do the math check
    
    # --- FIX: Use helper to get floats from original string fields ---
    sgst = _cleanAndConvertToFloat(data.get("sgstAmount"))
    cgst = _cleanAndConvertToFloat(data.get("cgstAmount"))
    igst = _cleanAndConvertToFloat(data.get("igstAmount"))
    utgst = _cleanAndConvertToFloat(data.get("utgstAmount"))
    cess = _cleanAndConvertToFloat(data.get("cessAmount"))
    totalTaxes = sgst + cgst + igst + utgst + cess

    # Step C: Compare
    # Check if totalAmount is a valid number
    if totalAmount is not None and totalAmount > 0 and itemsAreValid:
        calculatedGrandTotal = calculatedSubtotal + totalTaxes
        discrepancy = abs(calculatedGrandTotal - totalAmount)

        if discrepancy > tolerance:
            findings.append(st.error)
            findings.append(f"Total Amount Mismatch (High Fraud Risk): Line Items (₹{calculatedSubtotal:.2f}) + Total Taxes (₹{totalTaxes:.2f}) = ₹{calculatedGrandTotal:.2f}. This does not match the Grand Total (₹{totalAmount:.2f}). Discrepancy: ₹{discrepancy:.2f}")
        else:
            findings.append(st.success)
            findings.append(f"Grand Total Verified: Line Items (₹{calculatedSubtotal:.2f}) + Taxes (₹{totalTaxes:.2f}) = ₹{calculatedGrandTotal:.2f}, which matches the Grand Total.")
            
    elif totalAmount is None or totalAmount == 0:
        findings.append(st.error)
        findings.append("Total Amount could not be found. Cannot perform final math check.")
    elif not itemsAreValid:
        findings.append(st.warning)
        findings.append("Could not perform final math check because line item data was incomplete or missing.")
    
    # --- Check 3: IRN Presence ---
    if data.get("irn"):
        findings.append(st.success)
        findings.append(f"IRN found: {data['irn'][:10]}...") # Show snippet
    else:
        findings.append(st.warning)
        findings.append("IRN was not found on the invoice.")

    # --- FIX: Check 4: HSN/SAC Presence (from line items) ---
    if lineItems and isinstance(lineItems, list):
        # Look inside lineItems for "hsnSac"
        all_hsn = [item.get("hsnSac") for item in lineItems if item.get("hsnSac")]
        if all_hsn:
            unique_hsn = set(all_hsn) # Get only unique codes
            findings.append(st.success)
            findings.append(f"Found {len(unique_hsn)} unique HSN/SAC codes: {', '.join(unique_hsn)}")
        else:
            findings.append(st.info)
            findings.append("Line items were found, but no HSN/SAC codes were extracted from them.")
    else:
        findings.append(st.info)
        findings.append("No HSN or SAC codes were found.")
    
    return findings