import streamlit as st
import json
import re
import httpx
import asyncio

from validationUtils import _cleanAndConvertToFloat

async def _fetchHSNData(payload):
    """
    Handles the asynchronous API call to Gemini with exponential backoff.
    This version uses the specific key for HSN validation.
    """
    apiKey = "AIzaSyANmHzDnMk5PcyC4lkTqQ0JIkxddzaRcH4"
    apiUrl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={apiKey}"
    
    headers = {"Content-Type": "application/json"}
    maxRetries = 5
    delay = 1  # Initial delay in seconds

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(maxRetries):
            try:
                response = await client.post(apiUrl, headers=headers, json=payload)
                response.raise_for_status()  # Raises error for 4xx/5xx responses
                
                result = response.json()
                part = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0]
                
                if "text" in part:
                    jsonText = part.get("text", "{}")
                    return jsonText
                
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt == maxRetries - 1:
                    st.error(f"Error calling HSN API (Key: ...zaRcH4) after {maxRetries} attempts: {e}")
                    raise e
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                st.error(f"Error parsing HSN AI response: {e}")
                st.error(f"Raw HSN response: {result}")
                return "{}"
            except Exception as e:
                st.error(f"An unexpected error occurred in _fetchHSNData: {e}")
                return "{}"

# --- UPDATED HSN Validation Logic ---

async def validateHSNRates(data: dict):
    """
    Validates HSN/SAC codes by checking their *item-specific* GST rate
    against the official rate found via a web-grounded AI call.
    """
    findings = []
    
    lineItems = data.get("lineItems", [])
    if not lineItems:
        findings.append(st.info)
        findings.append("No line items found to validate HSN rates.")
        return findings

    # --- Loop through each item and check its specific rate ---
    for i, item in enumerate(lineItems, start=1):
        desc = item.get("description", "N/A")
        hsn = str(item.get("hsnSac", "")).strip()
        
        # --- NEW: Calculate item-specific billed rate ---
        quantity = _cleanAndConvertToFloat(item.get("quantity"))
        unitPrice = _cleanAndConvertToFloat(item.get("unitPrice"))
        itemDiscount = _cleanAndConvertToFloat(item.get("Discount"))
        itemGST = _cleanAndConvertToFloat(item.get("GST"))

        item_base_amount = (quantity * unitPrice) - itemDiscount
        item_billed_rate = 0.0

        if item_base_amount > 0 and itemGST > 0:
            item_billed_rate = round((itemGST / item_base_amount) * 100, 2)
        
        # --- End of new calculation ---

        if not hsn:
            findings.append(st.info)
            findings.append(f"Skipping item '{desc}': Missing HSN/SAC code.")
            continue
        
        if item_billed_rate == 0.0:
            findings.append(st.info)
            findings.append(f"Skipping item '{desc}': No item-level GST found (or base price is zero).")
            continue
            
        # --- Prompt and Payload (Unchanged) ---
        rate_prompt = (
            f"Using Google Search, find the official total GST rate (e.g., 5, 12, 18, 28) "
            f"applicable in India for HSN/SAC code '{hsn}' (Description: {desc}). "
            f"Prioritize sources like ClearTax, CBIC, or official GST portals. "
            f"Return ONLY the numerical rate (e.g., '18' or '5.0'). Do not add any other text, JSON, or symbols."
        )

        payload = {
            "contents": [{"parts": [{"text": rate_prompt}]}],
            "generationConfig": {
                "responseMimeType": "text/plain" 
            },
            "tools": [{"google_search": {}}]
        }
        
        try:
            rate_text = await _fetchHSNData(payload)
            
            if not rate_text:
                raise ValueError("AI returned an empty response.")
                
            match = re.search(r'[\d\.]+', rate_text)
            
            if not match:
                raise ValueError(f"AI returned non-numeric text: '{rate_text}'")

            official_rate = float(match.group(0))

            if official_rate == 0:
                findings.append(st.warning)
                findings.append(f"Could not find a clear GST rate for HSN '{hsn}' ({desc}). AI response: '{rate_text}'")
                continue

            # --- CRITICAL CHANGE: Compare item rate to official rate ---
            if abs(official_rate - item_billed_rate) > 0.5:
                reason = (
                    f"HSN Rate Mismatch for '{desc}' (HSN: {hsn}): "
                    f"Item billed at {item_billed_rate}%, but the official rate found online is {official_rate}%."
                )
                findings.append(st.error)
                findings.append(reason)
            else:
                reason = (
                    f"HSN Rate Verified for '{desc}' (HSN: {hsn}): "
                    f"Item's billed rate ({item_billed_rate}%) matches official rate ({official_rate}%)."
                )
                findings.append(st.success)
                findings.append(reason)

        except (ValueError, TypeError) as e:
            st.warning(f"Could not parse rate for HSN '{hsn}'. Error: {e}")
            continue 
        except Exception as e:
            findings.append(st.error)
            findings.append(f"Failed to validate HSN {hsn}. (See API error above)")
            
    return findings