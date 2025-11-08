import streamlit as st
import pandas as pd
import httpx
import asyncio
import json
import os

# --- 1. API Caller ---
# This is a copy of the fetcher from HSNSACValidate.py,
# as it's set up for text-only, non-schema calls.
async def _fetch_gemini_response(payload):
    """
    Handles the asynchronous API call to Gemini for text generation.
    """
    # We use the HSN key since it's already set up for text generation
    apiKey = st.secrets["GEMINI_API_KEY_HSN"]
    apiUrl = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={apiKey}"
    
    headers = {"Content-Type": "application/json"}
    maxRetries = 5
    delay = 1

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(maxRetries):
            try:
                response = await client.post(apiUrl, headers=headers, json=payload)
                response.raise_for_status()
                
                result = response.json()
                # Extract text from the correct part
                text = result.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return text
                
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                if attempt == maxRetries - 1:
                    st.error(f"Error calling Chatbot API: {e}")
                    return f"Sorry, I encountered an API error: {e}"
                await asyncio.sleep(delay)
                delay *= 2
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                st.error(f"Error parsing Chatbot API response: {e}")
                return f"Sorry, I couldn't understand the API's response: {e}"

# --- 2. The Main Chatbot Logic ---
async def get_chatbot_response(query: str, history: list):
    """
    Loads CSV data, formats a prompt, and gets a response from the LLM.
    """
    
    # --- Load Data ---
    try:
        clean_df = pd.read_csv("params_clean.csv")
        # Get last 10 rows
        clean_context = clean_df.tail(10).to_string(index=False)
    except FileNotFoundError:
        clean_context = "No clean invoices found."
    except pd.errors.EmptyDataError:
        clean_context = "The clean invoice file is empty."

    try:
        flagged_df = pd.read_csv("params_flagged.csv")
        # Get last 10 rows (most relevant for "last flagged")
        flagged_context = flagged_df.tail(10).to_string(index=False)
    except FileNotFoundError:
        flagged_context = "No flagged invoices found."
    except pd.errors.EmptyDataError:
        flagged_context = "The flagged invoice file is empty."

    # --- Create System Prompt ---
    system_prompt = f"""
    You are TrueBill, an expert AI assistant for invoice analysis.
    Your task is to answer questions based *only* on the data provided in the CONTEXT section.
    Do not make up information. If the answer is not in the context,
    say "I do not have that information in the provided data."

    CONTEXT:
    ---
    [LAST 10 FLAGGED INVOICES (from params_flagged.csv)]
    {flagged_context}
    ---
    [LAST 10 CLEAN INVOICES (from params_clean.csv)]
    {clean_context}
    ---
    """

    # --- Create API Payload ---
    # We add the system prompt and the recent history
    payload = {
        "contents": history + [{"role": "user", "parts": [{"text": query}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }

    # --- Get Response ---
    try:
        response_text = await _fetch_gemini_response(payload)
        return response_text
    except Exception as e:
        return f"An error occurred: {e}"