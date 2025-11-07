import os
import json
import streamlit as st

def saveJaisonToFile(data, originalFilename, outputFolder="extractedJSON\parsed"):

    try:

        if not os.path.exists(outputFolder):
            os.makedirs(outputFolder)

        baseName = os.path.splitext(originalFilename)[0]
        jsonFilename = f"{baseName}json"

        filePath = os.path.join(outputFolder, jsonFilename)

        with open(filePath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        st.success(f"Successfully saved JSON to: {filePath}")
        
    except Exception as e:
        st.error(f"Error saving JSON file: {e}")