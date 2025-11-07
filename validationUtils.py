import streamlit as st
import re
import httpx  # Using httpx to match your async app
import json
import asyncio

# --- HELPER FUNCTION (Unchanged from your file) ---
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

# --- YOUR PARTNER'S FUNCTIONS (Rewritten as async) ---

async def fetch_gstin_details(gstin):
    """
    Your partner's function, rewritten to be async.
    Calls the RapidAPI to get GSTIN details.
    """
    try:
        headers = {
            'x-rapidapi-key': "af6a58c474msh65744a06169c380p137bc4jsn43d1dfed9fa0",
            'x-rapidapi-host': "gst-insights-api.p.rapidapi.com"
        }
        endpoint = f"https://gst-insights-api.p.rapidapi.com/getGSTDetailsUsingGST/{gstin}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(endpoint, headers=headers)
            res.raise_for_status()
            return res.json()

    except httpx.HTTPStatusError as e:
        try: return e.response.json()
        except: return {"success": False, "message": f"API Error: Status {e.response.status_code}"}
    except Exception as e:
        return {"success": False, "message": f"API call failed: {e}"}

async def is_valid_gstin(gstin):
    """
    Your partner's function, rewritten to be async.
    This is the direct replacement for the mock function.
    """
    # Call the other async function
    json_data = await fetch_gstin_details(gstin)
    
    # Handle the 'list' vs 'dict' bug
    if isinstance(json_data, list) and json_data:
        json_data = json_data[0] # Grab first item if it's a list
    elif not isinstance(json_data, dict):
        return {"success": False, "message": "Invalid API response format."}

    # This is your partner's original logic
    if json_data.get("success", False) is True:
        return {"success": True, "message": "GSTIN is valid."}
    else:
        return {"success": False, "message": json_data.get("message", "GSTIN is invalid or API failed.")}

# --- Main Validation Function (Modified to use your functions) ---

async def performDiscrepancyChecks(data):
    """
    Generates a list of findings based on extracted data.
    This now calls your partner's 'is_valid_gstin' function.
    """
    findings = []
    tolerance = 1.0  # Allow for a 1 Rupee rounding error
    
    # --- Check 1: REAL GST Number Verification ---
    gstNumber = data.get("gstNumber")
    
    if not gstNumber:
        findings.append(st.error)
        findings.append("No GST number found in invoice.")
    else:
        with st.spinner(f"Verifying GSTIN {gstNumber} online..."):
            # Call your partner's function
            gstCheck = await is_valid_gstin(gstNumber)
        
        # This is the simplified check you wanted
        if gstCheck.get("success") is True:
            findings.append(st.success)
            findings.append(f"GSTIN {gstNumber} is valid.")
        else:
            findings.append(st.error)
            findings.append(f"GSTIN Invalid: {gstCheck.get('message', 'Check failed.')}")

    
    # --- Check 2: Full Mathematical Validation (Unchanged) ---
    
    totalAmount = _cleanAndConvertToFloat(data.get("totalAmountStr"))
    lineItems = data.get("lineItems")
    calculatedSubtotal = 0.0
    itemsAreValid = True

    if lineItems and isinstance(lineItems, list):
        for item in lineItems:
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
    
    sgst = _cleanAndConvertToFloat(data.get("sgstAmount"))
    cgst = _cleanAndConvertToFloat(data.get("cgstAmount"))
    igst = _cleanAndConvertToFloat(data.get("igstAmount"))
    utgst = _cleanAndConvertToFloat(data.get("utgstAmount"))
    cess = _cleanAndConvertToFloat(data.get("cessAmount"))
    totalTaxes = sgst + cgst + igst + utgst + cess

    if totalAmount is not None and totalAmount > 0 and itemsAreValid:
        calculatedGrandTotal = calculatedSubtotal + totalTaxes
        discrepancy = abs(calculatedGrandTotal - totalAmount)

        if discrepancy > tolerance:
            findings.append(st.error)
            findings.append(f"Total Amount Mismatch (High Fraud Risk): Line Items (₹{calculatedSubtotal:.2f}) + Total Taxes (₹{totalTTaxes:.2f}) = ₹{calculatedGrandTotal:.2f}. This does not match the Grand Total (₹{totalAmount:.2f}). Discrepancy: ₹{discrepancy:.2f}")
        else:
            findings.append(st.success)
            findings.append(f"Grand Total Verified: Line Items (₹{calculatedSubtotal:.2f}) + Taxes (₹{totalTaxes:.2f}) = ₹{calculatedGrandTotal:.2f}, which matches the Grand Total.")
            
    elif totalAmount is None or totalAmount == 0:
        findings.append(st.error)
        findings.append("Total Amount could not be found. Cannot perform final math check.")
    elif not itemsAreValid:
        findings.append(st.warning)
        findings.append("Could not perform final math check because line item data was incomplete or missing.")
    
    # --- Check 3: IRN Presence (Unchanged) ---
    if data.get("irn"):
        findings.append(st.success)
        findings.append(f"IRN found: {data['irn'][:10]}...") # Show snippet
    else:
        findings.append(st.warning)
        findings.append("IRN was not found on the invoice.")

    # --- Check 4: HSN/SAC Presence (Unchanged) ---
    if lineItems and isinstance(lineItems, list):
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