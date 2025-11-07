import streamlit as st

# --- Validation Functions ---

def mockVerifyGstNumber(gstNumber):
    """
    Simulates a check against a GSTN portal database.
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

def performDiscrepancyChecks(data, text):
    """
    Generates a list of findings based on extracted data.
    """
    findings = []
    
    # 1. Check GST Number
    gstCheck = mockVerifyGstNumber(data.get("gstNumber"))
    
    if gstCheck["status"] == "Verified":
        findings.append(st.success)
    elif gstCheck["status"] in ["Fraudulent", "Missing"]:
        findings.append(st.error)
    else: # Unverified
        findings.append(st.warning)
    
    findings.append(gstCheck["message"])
    
    # 2. Check Total Amount
    if data.get("totalAmountFloat") is not None:
        if data["totalAmountFloat"] > 10000:
             findings.append(st.warning)
             findings.append(f"High Value Invoice: Total amount is {data['totalAmountFloat']}. Manual review suggested.")
        else:
             findings.append(st.success)
             findings.append(f"Invoice total of {data['totalAmountFloat']} recorded.")
    else:
        findings.append(st.error)
        findings.append("Could not extract a valid total amount from the invoice.")
    
    # 3. Check for IRN
    if data.get("irn"):
        findings.append(st.success)
        findings.append("IRN successfully extracted.")
    else:
        findings.append(st.warning)
        findings.append("IRN was not found on the invoice.")

    # 4. Check for HSN/SAC
    if data.get("hsnSacCodes"):
        findings.append(st.info)
        findings.append(f"Found {len(data['hsnSacCodes'])} HSN/SAC codes: {', '.join(data['hsnSacCodes'])}")
    else:
        findings.append(st.info)
        findings.append("No HSN/SAC codes were found.")

    return findings