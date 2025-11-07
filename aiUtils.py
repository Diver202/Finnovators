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
    apiKey = "AIzaSyAdnKDhhSEmycIQXO7u6AA1CPlcESElJh0"
    apiUrl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={apiKey}"
    
    headers = {"Content-Type": "application/json"}
    maxRetries = 5
    delay = 1  # Initial delay in seconds

    # --- CHANGE: Increased timeout for larger multi-page files ---
    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(maxRetries):
            try:
                response = await client.post(apiUrl, headers=headers, json=payload)
                response.raise_for_status()  # Raises error for 4xx/5xx responses
                
                result = response.json()
                
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
                return "{}"

# --- This function is now internal and returns a LIST of image parts ---
def _convertFileToImageParts(fileBytes, fileType):
    """
    Converts an uploaded file (PDF or Image) into a list of
    Base64-encoded image parts for the multimodal AI prompt.
    """
    imageParts = []
    
    if fileType == "application/pdf":
        try:
            with fitz.open(stream=fileBytes, filetype="pdf") as doc:
                
                for pageNum in range(len(doc)):
                    page = doc.load_page(pageNum)
                    pix = page.get_pixmap(dpi=200) 
                    imgBytes = pix.tobytes("png")
                    imgBase64 = base64.b64encode(imgBytes).decode('utf-8')
                    imageParts.append({
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": imgBase64
                        }
                    })
                st.info(f"Processing {len(imageParts)} pages from the PDF...")
            return imageParts
        except Exception as e:
            st.error(f"Error processing PDF with PyMuPDF: {e}")
            return None
            
    elif fileType.startswith("image/"):
        try:
            with io.BytesIO(fileBytes) as f:
                img = Image.open(f)
                with io.BytesIO() as output:
                    img.save(output, format="PNG")
                    imgBytes = output.getvalue()
                    imgBase64 = base64.b64encode(imgBytes).decode('utf-8')
                    imageParts.append({
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": imgBase64
                        }
                    })
                    return imageParts
        except Exception as e:
            st.error(f"Error processing image with PIL: {e}")
            return None
            
    return None

async def parseInvoiceMultimodal(fileBytes, fileType):
    """
    Calls the Gemini API to parse the invoice *image(s)*
    using a multimodal prompt and a structured JSON schema.
    """
    
    imagePartsList = _convertFileToImageParts(fileBytes, fileType)
    
    if not imagePartsList:
        st.error("Could not convert file to a processable image.")
        return {} # Return empty dict on failure

    # --- Updated system prompt for new fields ---
    systemPrompt = """
    You are an expert AI assistant for processing Indian tax invoices.
    You are looking at *one or more images* that make up a single invoice document.
    Your task is to extract specific fields from the *entire document*.
    Line items may be on page 1 and totals on the last page. Please combine them.
    
    - Reconstruct the 64-character IRN. It might be split across lines.
    - Find the 15-digit GSTIN.
    - Find the INVOICE date in DD-MM-YYYY format
    - Find all line items (description, hsnSac, quantity, unitPrice, GST per item (total sum of CGST IGST etc.), Discount per item) from *all pages*.
    - Find the final total amount (e.g., 'Grand Total' or 'Amount Due').
    - Find the total amount (Not percentage) of SGST, CGST, IGST, UTGST and Cess.
    - Find the amount spent on freight or delivery.
    - Find the amount of total discount, separate from the discounts over each individual item. If no item has individual discount, but the whole order has discount, it goes here.
    - Return ONLY the JSON object as specified in the schema.
    If a value is not found, return null for that field.
    It is possible that some of these fields are fraudulent. For example, if you do not find GSTIN, do not make one up. Report as null.

    Additional tasks - 
    An irn code only has a-f (lowercase) and 0-9. If you recieve the following characters, convert them to their respective replacements.
    "B" - 8
    "E" - 3
    "I" - 1
    "S" - 5
    "H" - 8
    """

    userPromptParts = [
        {
            "text": "Please extract the required fields from this invoice document. The document consists of the following page(s):"
        }
    ]
    userPromptParts.extend(imagePartsList)

    # --- Updated responseSchema with new fields and TYPO FIX ---
    responseSchema = {
    "type": "OBJECT",
    "properties": {
        "gstNumber": {"type": "STRING", "description": "The 15-digit GSTIN."},
        "date": {"type": "STRING", "description": "Invoice date in DD-MM-YYYY format"},
        "irn": {"type": "STRING", "description": "The 64-character Invoice Reference Number (IRN)."},
        "lineItems": {
            "type": "ARRAY",
            "description": "A list of all items/services from the invoice.",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING", "description": "The item/service name or description."},
                    "hsnSac": {"type": "STRING", "description": "The HSN or SAC code for the item."},
                    "quantity": {"type": "NUMBER", "description": "The quantity of the item."},
                    "unitPrice": {"type": "NUMBER", "description": "The price per unit of the item."},
                    "GST":{"type": "NUMBER", "description": "Total GST per item, if given."},
                    # --- CRITICAL FIX: Changed "Discount" to "NUMBER" ---
                    "Discount": {"type": "NUMBER", "description": "Discount per item, if given."}
                },
                "propertyOrdering": ["description", "hsnSac", "quantity", "unitPrice", "GST", "Discount"]
            }
        },
        "sgstAmount": {"type": "STRING", "description": "The total *amount* (not percentage) of SGST. Return null if not present."},
        "cgstAmount": {"type": "STRING", "description": "The total *amount* (not percentage) of CGST. Return null if not present."},
        "igstAmount": {"type": "STRING", "description": "The total *amount* (not percentage) of IGST. Return null if not present."},
        "utgstAmount": {"type": "STRING","description": "The total *amount* (not percentage) of UTGST. Return null if not present."},
        "cessAmount": {"type": "STRING", "description": "The total *amount* (not percentage) of Cess. Return null if not present."},
        "freightAndDelivery": {"type": "STRING", "description": "The extra amount, usually given under freight or delivery charges. Return null if not present."},
        "totalDiscount": {"type": "STRING", "description": "Discount applied over the whole, separate from the individual discounts. Return null if not present."},
        "totalAmountStr": {"type": "STRING", "description": "The final total amount (e.g., 'Grand Total' or 'Amount Due')."}
    },
    # --- CRITICAL FIX: Added new fields to propertyOrdering ---
    "propertyOrdering": [
        "gstNumber", "irn", "date", "lineItems", 
        "sgstAmount", "cgstAmount", "igstAmount", "utgstAmount", "cessAmount", 
        "freightAndDelivery", "totalDiscount", "totalAmountStr"
        ]
    }
    
    payload = {
        "contents": [{"parts": userPromptParts}],
        "systemInstruction": {"parts": [{"text": systemPrompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": responseSchema
        }
    }

    try:
        jsonText = await fetchFromGemini(payload)
        data = json.loads(jsonText)
        
        # Post-processing
        if data.get("totalAmountStr"):
            try:
                cleanedStr = re.sub(r'[₹$,]', '', data["totalAmountStr"])
                data["totalAmountFloat"] = float(cleanedStr)
            except (ValueError, TypeError):
                data["totalAmountFloat"] = None
        else:
            data["totalAmountFloat"] = None

        return data

    except Exception as e:
        st.error(f"Failed to parse invoice with AI: {e}")
        # Return a more complete empty structure
        return {
            "gstNumber": None,
            "irn": None,
            "date": None,
            "lineItems": [],
            "sgstAmount": None,
            "cgstAmount": None,
            "igstAmount": None,
            "utgstAmount": None,
            "cessAmount": None,
            "freightAndDelivery": None,
            "totalDiscount": None,
            "totalAmountStr": None,
            "totalAmountFloat": None
        }