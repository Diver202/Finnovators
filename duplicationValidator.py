import pandas as pd
import numpy as np
import hashlib
import re
import json
from datetime import datetime
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os
import streamlit as st # Added for st.error

# ---------- Normalization & Date Helpers (Unchanged) ----------

def normalize_text(s):
    """Remove punctuation, spaces, case differences, underscores, etc."""
    if not isinstance(s, str):
        s = str(s)
    s = s.lower()
    s = re.sub(r"[\s\-\_\,\.\'\/\\]+", "", s)
    return s.strip()

def parse_date(s):
    """Parse date strings from common formats."""
    if not isinstance(s, str):
        return None
    formats = ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except:
            continue
    try:
        return datetime.fromisoformat(s)
    except:
        return None

def text_similarity(a, b):
    """Compute fuzzy text similarity ignoring case/punctuations (0..100)."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio() * 100

def date_diff_days(d1, d2):
    """Return absolute difference in days between d1,d2 strings (try common formats)."""
    da = parse_date(d1)
    db = parse_date(d2)
    if da is None or db is None:
        return np.nan
    return abs((da - db).days)

# ---------- Data-Format-Aware Helpers (Refactored) ----------

def compute_hash(inv):
    """Generate a hash key for invoice based on key identifiers."""
    # --- REFACTORED to use new keys ---
    concat = (
        f"{inv.get('gstNumber','')}{inv.get('invoiceNumber','')}"
        f"{inv.get('date','')}{inv.get('totalAmountFloat','')}"
    )
    return hashlib.sha256(concat.encode()).hexdigest()

def lineitem_similarity(items1_str, items2_str):
    """Compare text content of line items (0..100)."""
    
    def load_items(items_str):
        if not isinstance(items_str, str):
            return items_str or [] # Already a list
        try:
            # Use json.loads as our CSV saver uses json.dumps
            return json.loads(items_str)
        except Exception:
            try:
                # Fallback for eval-style strings
                return eval(items_str) 
            except Exception:
                return [] # Fail safe

    items1 = load_items(items1_str)
    items2 = load_items(items2_str)

    desc1 = " ".join([i.get("description", "") for i in items1 if i])
    desc2 = " ".join([i.get("description", "") for i in items2 if i])
    
    if not desc1 or not desc2:
        return 0.0
    
    try:
        vect = CountVectorizer().fit_transform([desc1, desc2])
        return float(cosine_similarity(vect)[0, 1] * 100)
    except ValueError:
        return 0.0

def prepare_historical_items_db(df):
    """
    Flattens the historical invoice DataFrame into a per-item database
    for easier price comparison.
    --- REFACTORED to use new keys ---
    """
    flat_items = []
    for _, row in df.iterrows():
        try:
            # --- REFACTORED ---
            items_list_str = row.get("lineItems")
            items_list = json.loads(items_list_str) if isinstance(items_list_str, str) else items_list_str
            invoice_date = parse_date(row.get("date"))
            
            if not invoice_date or not items_list or not isinstance(items_list, list):
                continue
                
            for item in items_list:
                # --- REFACTORED ---
                if not isinstance(item, dict) or not all(k in item for k in ('description', 'hsnSac', 'unitPrice')):
                    continue
                
                flat_items.append({
                    "vendor_gstin": normalize_text(row.get("gstNumber")),
                    "invoice_date": invoice_date,
                    "item_description": item.get("description"),
                    "normalized_description": normalize_text(item.get("description")),
                    "item_hsn": str(item.get("hsnSac")), # REFACTORED
                    "unit_price": float(item.get("unitPrice"))
                })
        except Exception:
            continue
            
    if not flat_items:
        return pd.DataFrame()
        
    df_items = pd.DataFrame(flat_items)
    df_items = df_items.sort_values(by="invoice_date", ascending=False)
    return df_items

def detect_line_item_price_anomalies(
    new_invoice, 
    historical_items_df, 
    inflation_rate=0.05, 
    margin=0.20
):
    """
    Checks each line item's price against its historical price.
    --- REFACTORED to use new keys ---
    """
    anomalies = []
    if historical_items_df.empty:
        return anomalies

    # --- REFACTORED ---
    new_vendor_gstin = normalize_text(new_invoice.get("gstNumber"))
    new_date = parse_date(new_invoice.get("date"))
    if not new_date:
        return [] 

    new_items_list = new_invoice.get("lineItems", [])
    if isinstance(new_items_list, str):
        try:
            new_items_list = json.loads(new_items_list)
        except Exception:
            new_items_list = []
    
    if not isinstance(new_items_list, list):
        new_items_list = []

    for item in new_items_list:
        try:
            if not isinstance(item, dict): continue

            # --- REFACTORED ---
            new_desc = item.get("description")
            new_norm_desc = normalize_text(new_desc)
            new_hsn = str(item.get("hsnSac")) # REFACTORED
            new_price = float(item.get("unitPrice"))
            
            # Find historical purchases
            df_hist = historical_items_df[
                (historical_items_df['vendor_gstin'] == new_vendor_gstin) &
                (historical_items_df['item_hsn'] == new_hsn) &
                (historical_items_df['normalized_description'] == new_norm_desc) &
                (historical_items_df['invoice_date'] < new_date) # Only look at past
            ]
            
            if df_hist.empty:
                continue
                
            last_purchase = df_hist.iloc[0]
            last_price = last_purchase['unit_price']
            last_date = last_purchase['invoice_date']
            
            if last_price <= 0:
                continue
                
            days_diff = (new_date - last_date).days
            if days_diff <= 30:
                acceptable_limit = last_price * (1 + margin) 
            else:
                years_diff = days_diff / 365.25
                expected_price = last_price * ((1 + inflation_rate) ** years_diff)
                acceptable_limit = expected_price * (1 + margin)
            
            if new_price > acceptable_limit:
                pct_diff = ((new_price / acceptable_limit) - 1) * 100
                reason = (
                    f"Price Anomaly: Item '{new_desc}' (HSN: {new_hsn}) unit price {new_price:,.2f} "
                    f"is {pct_diff:.1f}% above the acceptable limit of {acceptable_limit:,.2f}. "
                    f"(Based on last price {last_price:,.2f} from {last_date.strftime('%Y-%m-%d')})."
                )
                anomalies.append(reason)
                
        except Exception:
            continue
            
    return anomalies

def detect_ghost_invoice(new_inv, historical_df):
    """
    Conservative ghost detection.
    --- REFACTORED to use new keys ---
    """
    reasons = []
    # --- REFACTORED ---
    gstin = normalize_text(new_inv.get("gstNumber", ""))
    seen_gstins = set(historical_df["gstNumber"].astype(str).apply(normalize_text).values)
    unseen_gstin = gstin not in seen_gstins

    # HSN inconsistency
    vendor_rows = historical_df[historical_df["gstNumber"].astype(str).apply(normalize_text) == gstin]
    vendor_hsns = set()
    
    # --- REFACTORED ---
    for r in vendor_rows["lineItems"]:
        try:
            its = json.loads(r) if isinstance(r, str) else r
            if isinstance(its, list):
                vendor_hsns.update([i.get("hsnSac", "") for i in its if isinstance(i, dict) and i.get("hsnSac")])
        except:
            continue
            
    # --- REFACTORED ---
    new_items_list = new_inv.get("lineItems", [])
    if isinstance(new_items_list, str):
        try: new_items_list = json.loads(new_items_list)
        except: new_items_list = []
    if not isinstance(new_items_list, list):
        new_items_list = []
        
    new_hsns = set([i.get("hsnSac", "") for i in new_items_list if isinstance(i, dict) and i.get("hsnSac")])
    hsn_unseen_for_vendor = len(new_hsns - vendor_hsns) > 0 if vendor_rows.shape[0] > 0 else False

    # Price anomaly
    price_anomaly = False
    if vendor_rows.shape[0] >= 3: 
        try:
            # --- REFACTORED ---
            med = vendor_rows["totalAmountFloat"].astype(float).median()
            if med > 0:
                if new_inv.get("totalAmountFloat", 0) > 10 * med or new_inv.get("totalAmountFloat", 0) < 0.1 * med:
                    price_anomaly = True
        except:
            price_anomaly = False 

    strong_signals = 0
    if unseen_gstin:
        strong_signals += 1
        reasons.append("GSTIN not previously seen in historical data")
    if hsn_unseen_for_vendor:
        strong_signals += 1
        reasons.append("HSN codes in invoice not matching vendor's historical HSNs")
    if price_anomaly:
        strong_signals += 1
        reasons.append("Invoice total is highly deviant from vendor's historical median")

    if strong_signals >= 2:
        return reasons
    else:
        return []

def _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special=None):
    
    # --- REFACTORED to use new keys ---
    def load_items(items_data):
        if not isinstance(items_data, (str, list)):
            return []
        if isinstance(items_data, str):
            try: return json.loads(items_data)
            except: return []
        return items_data

    new_items_list = load_items(new_invoice.get("lineItems"))
    existing_items_list = load_items(existing.get("lineItems"))

    new_hsns = set([i.get("hsnSac","") for i in new_items_list if isinstance(i, dict) and i.get("hsnSac")])
    old_hsns = set([i.get("hsnSac","") for i in existing_items_list if isinstance(i, dict) and i.get("hsnSac")])
    hsn_mismatch = 1.0 if new_hsns != old_hsns else 0.0

    features = {
        "invoice_no_sim": round(float(invno_sim), 3),
        "vendor_name_sim": round(float(text_similarity(new_invoice.get("vendorName",""), existing.get("vendorName",""))), 3),
        "gstin_match": 1.0 if normalize_text(new_invoice.get("gstNumber","")) == normalize_text(existing.get("gstNumber","")) else 0.0,
        "total_rel_diff": round(float(total_rel_diff), 6),
        "date_diff_days": float(date_diff) if not np.isnan(date_diff) else np.nan,
        "lineitems_sim": round(float(line_sim), 3),
        "hsn_mismatch_norm": hsn_mismatch
    }
    
    # heuristic final confidence (Unchanged)
    w_inv = 0.35; w_date = 0.20; w_gst = 0.15; w_item = 0.20; w_amount = 0.10
    amount_factor = 1.0 - min(1.0, features["total_rel_diff"])
    date_factor = 1.0
    if not np.isnan(features["date_diff_days"]):
        date_factor = 1.0 if features["date_diff_days"] <= 2 else max(0.0, 1 - (features["date_diff_days"]/30))
        
    final_score = (
        w_inv * (features["invoice_no_sim"] / 100.0) +
        w_date * date_factor +
        w_gst * features["gstin_match"] +
        w_item * (features["lineitems_sim"] / 100.0) +
        w_amount * amount_factor
    )
    features["final_confidence"] = round(max(0.0, min(1.0, final_score)), 4)

    reasons = []
    if reason_special: reasons.append(reason_special)
    if features["invoice_no_sim"] >= 85: reasons.append("Invoice number similar")
    if features["lineitems_sim"] >= 50: reasons.append("Line items similar")
    if features["total_rel_diff"] <= 0.05: reasons.append("Totals nearly identical")
    if not np.isnan(features["date_diff_days"]) and features["date_diff_days"] <= 3: reasons.append("Dates close")
    if features["gstin_match"] == 1.0: reasons.append("GSTIN exact match")

    near_dup = {
        "db_row_index": int(idx),
        "existing_invoice_summary": {
            "invoice_no": existing.get("invoiceNumber"), # REFACTORED
            "vendor_gstin": existing.get("gstNumber"), # REFACTORED
            "invoice_date": existing.get("date"), # REFACTORED
            "total_amount": existing.get("totalAmountFloat") # REFACTORED
        },
        "features": features,
        "final_confidence": features["final_confidence"],
        "reasons": reasons,
        "existing_full": existing
    }
    return near_dup

# ---------- Core Checking Logic (Refactored) ----------

# This is the new main function our Streamlit app will call
def run_historical_checks(parsedData, csv_path="params_clean.csv"):
    """
    Main function:
    - formats the new 'parsedData'
    - reads historical data from csv_path
    - applies all detection logic
    - returns a structured report dict
    --- REFACTORED to be called by Streamlit & NOT write files ---
    """
    
    # 1. Translate Streamlit's parsedData into the script's 'new_invoice' format
    new_invoice = {
        "invoiceNumber": parsedData.get("invoiceNumber"),
        "date": parsedData.get("date"),
        "vendorName": parsedData.get("vendorName"),
        "gstNumber": parsedData.get("gstNumber"),
        "irn": parsedData.get("irn"),
        "lineItems": parsedData.get("lineItems", []), # Pass the list directly
        "totalAmountFloat": parsedData.get("totalAmountFloat", 0.0)
    }

    if not os.path.exists(csv_path):
        return {
            "invoice_hash": compute_hash(new_invoice),
            "exact_duplicate": False, "exact_duplicate_match": None,
            "near_duplicates": [], "ghost_signals": [], 
            "line_item_price_anomalies": [],
            "overall_flag": "CLEAN",
            "reasons": ["No historical data to compare against. New invoice will be added to history."]
        }

    try:
        df = pd.read_csv(csv_path)
    except pd.errors.EmptyDataError:
        return {
            "invoice_hash": compute_hash(new_invoice),
            "exact_duplicate": False, "exact_duplicate_match": None,
            "near_duplicates": [], "ghost_signals": [], 
            "line_item_price_anomalies": [],
            "overall_flag": "CLEAN",
            "reasons": ["Historical data file is empty. New invoice will be added to history."]
        }
    except Exception as e:
        st.error(f"Failed to read historical data: {e}")
        return { "overall_flag": "ERROR", "reasons": [f"Failed to read historical data: {e}"] }

    
    if "totalAmountFloat" in df.columns:
        df["totalAmountFloat"] = pd.to_numeric(df["totalAmountFloat"], errors="coerce").fillna(0.0)
    
    df_items = prepare_historical_items_db(df)
    new_hash = compute_hash(new_invoice)

    result = {
        "invoice_hash": new_hash,
        "exact_duplicate": False,
        "exact_duplicate_match": None,
        "near_duplicates": [],
        "ghost_signals": [],
        "line_item_price_anomalies": [],
        "overall_flag": "CLEAN",
        "reasons": []
    }

    def get_existing_from_row(row):
        # --- REFACTORED to use new keys ---
        try:
            items_data_str = row.get("lineItems")
            items_data = json.loads(items_data_str) if isinstance(items_data_str, str) else items_data_str
            if not isinstance(items_data, list):
                items_data = []
        except Exception:
            items_data = []
            
        return {
            "invoiceNumber": row.get("invoiceNumber", ""),
            "date": row.get("date", ""),
            "vendorName": row.get("vendorName", ""),
            "gstNumber": row.get("gstNumber", ""),
            "totalAmountFloat": float(row.get("totalAmountFloat") or 0),
            "lineItems": items_data
        }

    # 1) Exact Duplicate by HASH
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)
        if compute_hash(existing) == new_hash:
            result["exact_duplicate"] = True
            result["exact_duplicate_match"] = int(idx)
            result["overall_flag"] = "EXACT_DUPLICATE"
            result["reasons"].append("Exact duplicate: identical vendor+invoice+date+amount")
            return result # Do not append to CSV, just return

    # 2) Invoice-number first priority checks
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)

        # --- REFACTORED ---
        invno_sim = text_similarity(new_invoice.get("invoiceNumber", ""), existing.get("invoiceNumber", ""))
        total_rel_diff = 0.0
        if existing["totalAmountFloat"] > 0:
            total_rel_diff = abs(new_invoice.get("totalAmountFloat", 0.0) - existing["totalAmountFloat"]) / existing["totalAmountFloat"]
        else:
             total_rel_diff = 0.0 if new_invoice.get("totalAmountFloat", 0.0) == 0.0 else 1.0

        line_sim = lineitem_similarity(new_invoice.get("lineItems", []), existing.get("lineItems", []))

        if invno_sim >= 95 and total_rel_diff <= 0.05:
            date_diff = date_diff_days(new_invoice.get("date", ""), existing.get("date", ""))
            gstin_same = normalize_text(new_invoice.get("gstNumber", "")) == normalize_text(existing.get("gstNumber", ""))
            
            if (line_sim >= 50) or gstin_same or (not np.isnan(date_diff) and date_diff <= 3):
                near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special="Invoice number nearly identical and amounts match")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("Invoice number extremely similar + totals match -> high risk")
                return result

    # 3) Date-priority checks
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)
        
        # --- REFACTORED ---
        date_diff = date_diff_days(new_invoice.get("date", ""), existing.get("date", ""))
        total_rel = 0.0
        if existing["totalAmountFloat"] > 0:
            total_rel = abs(new_invoice.get("totalAmountFloat", 0.0) - existing["totalAmountFloat"]) / existing["totalAmountFloat"]
        else:
            total_rel = 0.0 if new_invoice.get("totalAmountFloat", 0.0) == 0.0 else 1.0

        vendor_sim = text_similarity(new_invoice.get("vendorName", ""), existing.get("vendorName", ""))
        line_sim = lineitem_similarity(new_invoice.get("lineItems", []), existing.get("lineItems", []))

        if (not np.isnan(date_diff) and date_diff <= 1) and total_rel <= 0.05 and vendor_sim >= 75:
            if line_sim >= 40 or normalize_text(new_invoice.get("gstNumber","")) == normalize_text(existing.get("gstNumber","")):
                invno_sim_val = text_similarity(new_invoice.get("invoiceNumber",""), existing.get("invoiceNumber",""))
                near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim_val, line_sim, total_rel, date_diff, reason_special="Dates and totals very close")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
                result["reasons"].append("Invoice date and totals close -> possible duplicate")

    # 4) GSTIN + item/amount checks
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)
        
        # --- REFACTORED ---
        gstin_same = normalize_text(new_invoice.get("gstNumber","")) == normalize_text(existing.get("gstNumber",""))
        total_rel = 0.0
        if existing["totalAmountFloat"] > 0:
            total_rel = abs(new_invoice.get("totalAmountFloat", 0.0) - existing["totalAmountFloat"]) / existing["totalAmountFloat"]
        else:
            total_rel = 0.0 if new_invoice.get("totalAmountFloat", 0.0) == 0.0 else 1.0
            
        invno_sim = text_similarity(new_invoice.get("invoiceNumber",""), existing.get("invoiceNumber",""))
        line_sim = lineitem_similarity(new_invoice.get("lineItems", []), existing.get("lineItems", []))

        supporting = 0
        if total_rel <= 0.05: supporting += 1
        if invno_sim >= 80: supporting += 1
        if line_sim >= 60: supporting += 1

        if gstin_same and supporting >= 1:
            if line_sim < 30 and invno_sim < 90:
                continue 
            
            date_diff_val = date_diff_days(new_invoice.get("date",""), existing.get("date",""))
            near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel, date_diff_val, reason_special="GSTIN matches and supporting signals present")
            result["near_duplicates"].append(near_dup)
            
            if invno_sim >= 90 or total_rel <= 0.02:
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("GSTIN match with strong supporting signals -> high risk")
                return result

    # 5) Conservative ghost detection
    ghost_reasons = detect_ghost_invoice(new_invoice, df)
    if ghost_reasons:
        result["ghost_signals"] = ghost_reasons
        if result["overall_flag"] == "CLEAN":
            result["overall_flag"] = "POTENTIAL_GHOST_INVOICE"
        result["reasons"].extend(ghost_reasons)
        return result

    # 6) Line Item Price Anomaly Detection
    price_anomalies = detect_line_item_price_anomalies(new_invoice, df_items)
    if price_anomalies:
        result["line_item_price_anomalies"] = price_anomalies
        result["reasons"].extend(price_anomalies)
        if result["overall_flag"] == "CLEAN":
            result["overall_flag"] = "PRICE_ANOMALY"
        return result

    # 7) If we collected near_duplicates but not returned earlier, choose top match
    if result["near_duplicates"]:
        def score_key(x):
            f = x["features"]
            return (f.get("invoice_no_sim", 0), f.get("lineitems_sim", 0), -f.get("total_rel_diff", 1))
        
        result["near_duplicates"] = sorted(result["near_duplicates"], key=score_key, reverse=True)
        top = result["near_duplicates"][0]
        
        if result["overall_flag"] == "CLEAN":
            top_conf = top.get("features", {}).get("final_confidence", 0)
            if top_conf >= 0.9: result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
            elif top_conf >= 0.75: result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
            else: result["overall_flag"] = "LOW_RISK_RECHECK"
            result["reasons"].append("Similarity-based match found; review required")
        
        return result

    # 8) If no flags raised, it's CLEAN.
    if not result["reasons"]:
        result["reasons"].append("No duplicates, anomalies, or ghost signals found.")

    return result