import streamlit as st
import asyncio
import httpx
import json
import re
import base64
import fitz  # PyMuPDF
import io
from PIL import Image

async def fetchFromGemini(payload):
    """
    Handles the asynchronous API call to Gemini with exponential backoff.
    """
    # --- I have preserved your API key ---
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

def convertFileToImageBytes(fileBytes, fileType):
    """
    Converts the uploaded file (PDF or Image) into PNG image bytes.
    Processes ONLY the first page of a PDF.
    """
    if fileType == "application/pdf":
        try:
            with fitz.open(stream=fileBytes, filetype="pdf") as doc:
                page = doc.load_page(0)  # Load only the first page
                pix = page.get_pixmap(dpi=300)
                imgBytes = pix.tobytes("png")
                return imgBytes, "image/png"
        except Exception as e:
            st.error(f"Error processing PDF with PyMuPDF: {e}")
            return None, None
            
    elif fileType.startswith("image/"):
        try:
            # Convert to PNG to ensure consistency
            with io.BytesIO(fileBytes) as f:
                img = Image.open(f)
                with io.BytesIO() as output:
                    img.save(output, format="PNG")
                    return output.getvalue(), "image/png"
        except Exception as e:
            st.error(f"Error processing image with PIL: {e}")
            return None, None
            
    return None, None

async def parseInvoiceMultimodal(fileBytes, fileType):
    """
    Calls the Gemini API to parse the invoice *image*
    using a multimodal prompt and a structured JSON schema.
    """
    
    # Convert PDF or Image to a single PNG byte stream
    imageBytes, imageMimeType = convertFileToImageBytes(fileBytes, fileType)
    
    if not imageBytes:
        st.error("Could not convert file to a processable image.")
        return {}

    # 1. Base64-encode the image
    imageBase64 = base64.b64encode(imageBytes).decode('utf-8')

    # 2. Update the system prompt to reflect we are looking at an image
    systemPrompt = """
    You are an expert AI assistant for processing Indian tax invoices.
    You are looking at an *image* of an invoice.
    Your task is to extract specific fields from the image.
    - Reconstruct the 64-character IRN. It might be split across lines.
    - Find the 15-digit GSTIN (e.g., 27ABCDE1234F1Z5).
    - Find all unique HSN or SAC codes (they are 4, 6, or 8 digits).
    - Find the final total amount (e.g., 'Grand Total' or 'Amount Due').
    - Return ONLY the JSON object as specified in the schema.
    If a value is not found, return null for that field.

    Additional tasks - 
    An irn code only has a-f (lowercase) and 0-9. If you recieve the following characters, convert them to their respective replacements.
    "B" - 8
    "E" - 3
    "I" - 1
    "S" - 5
    "H" - 8
    """

    # 3. Create the user prompt (now with an image)
    userPromptParts = [
        {
            "text": "Please extract the required fields from this invoice image."
        },
        {
            "inlineData": {
                "mimeType": imageMimeType,
                "data": imageBase64
            }
        }
    ]

    # 4. Define the exact JSON structure we want the AI to return
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
    
    # 5. This is the payload for the API call
    payload = {
        "contents": [{"parts": userPromptParts}],
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