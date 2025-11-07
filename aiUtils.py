import streamlit as st
import asyncio
import httpx
import json
import re


async def fetchFromGemini(payload):
    """
    Handles the asynchronous API call to Gemini with exponential backoff.
    """
    apiKey = "AIzaSyAdnKDhhSEmycIQXO7u6AA1CPlcESElJh0"
    apiUrl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={apiKey}"
    
    headers = {"Content-Type": "application/json"}
    maxRetries = 5
    delay = 1  # Initial delay in seconds

    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(maxRetries):
            try:
                response = await client.post(apiUrl, headers=headers, json=payload)
                response.raise_for_status()  # Raises error for 4xx/5xx responses
                
                result = response.json()
                
                # Extract the raw JSON text from the model's response
                jsonText = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                return jsonText

            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt == maxRetries - 1:
                    st.error(f"Error calling Gemini API after {maxRetries} attempts: {e}")
                    raise e
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                st.error(f"Error parsing AI response: {e}")
                st.error(f"Raw response: {result}")
                return "{}" # Return empty JSON on parse failure

async def parseInvoiceText(text):
    """
    Calls the Gemini API to parse the invoice text
    using a structured JSON schema.
    """
    
    systemPrompt = """
    You are an expert AI assistant for processing Indian tax invoices.
    Your task is to extract specific fields from the raw, messy OCR text provided.
    - Reconstruct the 64-character IRN even if it is split across multiple lines or contains spaces.
    - Find the 15-digit GSTIN (e.g., 27ABCDE1234F1Z5).
    - Find all unique HSN or SAC codes (they are 4, 6, or 8 digits).
    - Find the final total amount (e.g., 'Grand Total' or 'Amount Due').
    - Return ONLY the JSON object as specified in the schema. Do not return any other text.
    If a value is not found, return null for that field.

    Additional tasks - 
    An irn code only has a-b (lowercase) and 0-9. If you recieve the following characters, convert them to their respective replacements.
    "B" - 8
    "E" - 3
    "I" - 1
    "S" - 5
    "H" - 8
    """

    userPrompt = f"""
    Please extract the required fields from the following invoice text:

    ---
    {text}
    ---
    """

    # Define the exact JSON structure we want the AI to return
    responseSchema = {
        "type": "OBJECT",
        "properties": {
            "gstNumber": {"type": "STRING", "description": "The 15-digit GSTIN."},
            "totalAmountStr": {"type": "STRING", "description": "The final total amount as a string (e..g, '5,123.50')."},
            "irn": {"type": "STRING", "description": "The 64-character Invoice Reference Number (IRN)."},
            "hsnSacCodes": {
                "type": "ARRAY",
                "items": {"type": "STRING"},
                "description": "A list of unique HSN or SAC codes."
            }
        },
        "propertyOrdering": ["gstNumber", "totalAmountStr", "irn", "hsnSacCodes"]
    }
    
    # This is the payload for the API call
    payload = {
        "contents": [{"parts": [{"text": userPrompt}]}],
        "systemInstruction": {"parts": [{"text": systemPrompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": responseSchema
        }
    }

    try:
        # Call the API helper function
        jsonText = await fetchFromGemini(payload)
        
        # Parse the JSON string into a Python dictionary
        data = json.loads(jsonText)
        
        # Post-processing: Convert the total string to a float for calculations
        if data.get("totalAmountStr"):
            try:
                # Clean up the string (remove commas, currency symbols)
                cleanedStr = re.sub(r'[₹$,]', '', data["totalAmountStr"])
                data["totalAmountFloat"] = float(cleanedStr)
            except (ValueError, TypeError):
                data["totalAmountFloat"] = None
        else:
            data["totalAmountFloat"] = None

        return data

    except Exception as e:
        st.error(f"Failed to parse invoice with AI: {e}")
        return {
            "gstNumber": None,
            "totalAmountStr": None,
            "irn": None,
            "hsnSacCodes": [],
            "totalAmountFloat": None
        }