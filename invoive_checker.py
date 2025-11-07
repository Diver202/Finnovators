import pandas as pd
import numpy as np
import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os

# ---------- Normalization & Date Helpers ----------

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
        # Try ISO format as a fallback
        return datetime.fromisoformat(s)
    except:
        return None

def text_similarity(a, b):
    """Compute fuzzy text similarity ignoring case/punctuations (0..100)."""
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio() * 100

def compute_hash(inv):
    """Generate a hash key for invoice based on key identifiers."""
    concat = f"{inv.get('vendor_gstin','')}{inv.get('invoice_no','')}{inv.get('invoice_date','')}{inv.get('total_amount','')}"
    return hashlib.sha256(concat.encode()).hexdigest()

def lineitem_similarity(items1, items2):
    """Compare text content of line items (0..100)."""
    desc1 = " ".join([i.get("description", "") for i in items1])
    desc2 = " ".join([i.get("description", "") for i in items2])
    if not desc1 or not desc2:
        return 0.0
    vect = CountVectorizer().fit_transform([desc1, desc2])
    return float(cosine_similarity(vect)[0, 1] * 100)

def date_diff_days(d1, d2):
    """Return absolute difference in days between d1,d2 strings (try common formats)."""
    da = parse_date(d1)
    db = parse_date(d2)
    if da is None or db is None:
        return np.nan
    return abs((da - db).days)

# ---------- Price Anomaly Detection (NEW) ----------

def prepare_historical_items_db(df):
    """
    Flattens the historical invoice DataFrame into a per-item database
    for easier price comparison.
    """
    flat_items = []
    for _, row in df.iterrows():
        try:
            items_list = eval(row["items"]) if isinstance(row.get("items"), str) else []
            invoice_date = parse_date(row.get("invoice_date"))
            if not invoice_date or not items_list:
                continue
                
            for item in items_list:
                if not all(k in item for k in ('description', 'hsn', 'unit_price')):
                    continue
                
                flat_items.append({
                    "vendor_gstin": normalize_text(row.get("vendor_gstin")),
                    "invoice_date": invoice_date,
                    "item_description": item.get("description"),
                    "normalized_description": normalize_text(item.get("description")),
                    "item_hsn": str(item.get("hsn")),
                    "unit_price": float(item.get("unit_price"))
                })
        except Exception:
            continue # Skip rows with bad 'items' data
            
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
    Checks each line item's price against its historical price from the same
    vendor, adjusted for inflation and a margin of error.
    
    :param inflation_rate: Assumed annual inflation (e.g., 0.05 for 5%)
    :param margin: Acceptable variance above inflation (e.g., 0.20 for 20%)
    """
    anomalies = []
    if historical_items_df.empty:
        return anomalies

    new_vendor_gstin = normalize_text(new_invoice.get("vendor_gstin"))
    new_date = parse_date(new_invoice.get("invoice_date"))
    if not new_date:
        return [] # Cannot check without a valid new date

    for item in new_invoice.get("items", []):
        try:
            new_desc = item.get("description")
            new_norm_desc = normalize_text(new_desc)
            new_hsn = str(item.get("hsn"))
            new_price = float(item.get("unit_price"))
            
            # Find historical purchases of this *exact* item from this *exact* vendor
            df_hist = historical_items_df[
                (historical_items_df['vendor_gstin'] == new_vendor_gstin) &
                (historical_items_df['item_hsn'] == new_hsn) &
                (historical_items_df['normalized_description'] == new_norm_desc) &
                (historical_items_df['invoice_date'] < new_date) # Only look at past
            ]
            
            if df_hist.empty:
                # No history for this item from this vendor, cannot check.
                continue
                
            # Get the most recent historical purchase
            last_purchase = df_hist.iloc[0]
            last_price = last_purchase['unit_price']
            last_date = last_purchase['invoice_date']
            
            if last_price <= 0:
                continue # Cannot compare against a zero or negative price
                
            # Calculate time difference in years
            days_diff = (new_date - last_date).days
            if days_diff <= 30:
                # Too recent for inflation check, just check for large jump
                acceptable_limit = last_price * (1 + margin) 
            else:
                # Apply inflation calculation
                years_diff = days_diff / 365.25
                expected_price = last_price * ((1 + inflation_rate) ** years_diff)
                acceptable_limit = expected_price * (1 + margin)
            
            # Check if the new price exceeds the acceptable limit
            if new_price > acceptable_limit:
                pct_diff = ((new_price / acceptable_limit) - 1) * 100
                reason = (
                    f"Price Anomaly: Item '{new_desc}' (HSN: {new_hsn}) unit price {new_price:,.2f} "
                    f"is {pct_diff:.1f}% above the acceptable limit of {acceptable_limit:,.2f}. "
                    f"(Based on last price {last_price:,.2f} from {last_date.strftime('%Y-%m-%d')})."
                )
                anomalies.append(reason)
                
        except Exception:
            continue # Skip item if data is invalid (e.g., non-numeric price)
            
    return anomalies

# ---------- Ghost Invoice Detection (conservative) ----------

def detect_ghost_invoice(new_inv, historical_df):
    """
    Conservative ghost detection: require combination of signals before flagging:
    - unseen GSTIN OR vendor has different HSN history
    - AND abnormal price relative to vendor or market (if vendor history available)
    """
    reasons = []
    gstin = new_inv.get("vendor_gstin", "")

    # Prepare helper lists
    seen_gstins = set(historical_df["vendor_gstin"].astype(str).values)
    
    unseen_gstin = gstin not in seen_gstins

    # HSN inconsistency: new HSNs not observed in historical dataset for this vendor
    vendor_rows = historical_df[historical_df["vendor_gstin"] == gstin]
    vendor_hsns = set()
    for r in vendor_rows["items"]:
        try:
            its = eval(r) if isinstance(r, str) else []
            vendor_hsns.update([i.get("hsn", "") for i in its if i.get("hsn")])
        except:
            continue
    new_hsns = set([i.get("hsn", "") for i in new_inv.get("items", []) if i.get("hsn")])
    hsn_unseen_for_vendor = len(new_hsns - vendor_hsns) > 0 if vendor_rows.shape[0] > 0 else False

    # Price anomaly: compare new_inv total to vendor median (if vendor history exists)
    price_anomaly = False
    if vendor_rows.shape[0] >= 3: # Require at least 3 historical invoices for median
        try:
            med = vendor_rows["total_amount"].astype(float).median()
            if med > 0:
                # Flag if total is 10x higher or 90% lower
                if new_inv.get("total_amount", 0) > 10 * med or new_inv.get("total_amount", 0) < 0.1 * med:
                    price_anomaly = True
        except:
            price_anomaly = False # Fail safe

    # Conservative decision: require at least two strong signals to label ghost
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
        # do not return weak single-signal reasons (to avoid illogical flags)
        return []

# ---------- Core Checking Logic (priority: invoice_no -> date -> gstin -> items) ----------

def check_invoice(new_invoice, csv_path="invoice_data.csv", log_path="suspect_invoices_log.csv"):
    """
    Main function:
    - reads historical data from csv_path
    - applies exact/near-duplicate logic with invoice-number priority
    - conservative ghost detection
    - line-item price anomaly detection (NEW)
    - logs suspicious invoices to log_path
    - returns structured report dict for frontend
    """
    if not os.path.exists(csv_path):
        # If no history, we can't check. Log as "CLEAN" but maybe add note?
        # For this logic, we'll assume a missing file means we just append.
        print(f"Warning: {csv_path} not found. Appending new invoice as first entry.")
        append_to_master_csv(new_invoice, csv_path)
        return {
            "invoice_hash": compute_hash(new_invoice),
            "exact_duplicate": False, "exact_duplicate_match": None,
            "near_duplicates": [], "ghost_signals": [], 
            "line_item_price_anomalies": [],
            "overall_flag": "CLEAN",
            "reasons": ["No historical data to compare against."]
        }

    df = pd.read_csv(csv_path)
    # ensure numeric total_amount
    if "total_amount" in df.columns:
        df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce").fillna(0.0)
    
    # Prepare flattened item DB for price checks
    df_items = prepare_historical_items_db(df)
    
    new_hash = compute_hash(new_invoice)

    result = {
        "invoice_hash": new_hash,
        "exact_duplicate": False,
        "exact_duplicate_match": None,
        "near_duplicates": [],
        "ghost_signals": [],
        "line_item_price_anomalies": [], # NEW
        "overall_flag": "CLEAN",
        "reasons": []
    }

    # Helper function to safely build 'existing' dict from a DataFrame row
    def get_existing_from_row(row):
        try:
            return {
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "vendor_name": row["vendor_name"],
                "vendor_gstin": row["vendor_gstin"],
                "total_amount": float(row["total_amount"]),
                "items": eval(row["items"]) if isinstance(row.get("items"), str) else []
            }
        except Exception:
            return {
                "invoice_no": row.get("invoice_no", ""),
                "invoice_date": row.get("invoice_date", ""),
                "vendor_name": row.get("vendor_name", ""),
                "vendor_gstin": row.get("vendor_gstin", ""),
                "total_amount": float(row.get("total_amount") or 0),
                "items": []
            }

    # 1) Exact Duplicate by HASH (strict)
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)
        if compute_hash(existing) == new_hash:
            result["exact_duplicate"] = True
            result["exact_duplicate_match"] = int(idx)
            result["overall_flag"] = "EXACT_DUPLICATE"
            result["reasons"].append("Exact duplicate: identical vendor+invoice+date+amount")
            log_suspect_invoice(new_invoice, result, log_path)
            return result

    # 2) Invoice-number first priority checks (very strict thresholds)
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)

        invno_sim = text_similarity(new_invoice.get("invoice_no", ""), existing.get("invoice_no", ""))
        total_rel_diff = 0.0
        if existing["total_amount"] > 0:
            total_rel_diff = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        else:
             total_rel_diff = 0.0 if new_invoice.get("total_amount", 0.0) == 0.0 else 1.0

        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        # If invoice number is virtually identical and totals match -> immediate high risk
        if invno_sim >= 95 and total_rel_diff <= 0.05:
            date_diff = date_diff_days(new_invoice.get("invoice_date", ""), existing.get("invoice_date", ""))
            gstin_same = normalize_text(new_invoice.get("vendor_gstin", "")) == normalize_text(existing.get("vendor_gstin", ""))
            
            if (line_sim >= 50) or gstin_same or (not np.isnan(date_diff) and date_diff <= 3):
                near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special="Invoice number nearly identical and amounts match")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("Invoice number extremely similar + totals match -> high risk")
                log_suspect_invoice(new_invoice, result, log_path)
                return result
            else:
                continue # invoice number similar but items/vendor totally different -> do NOT flag

    # 3) Date-priority checks (secondary)
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)

        date_diff = date_diff_days(new_invoice.get("invoice_date", ""), existing.get("invoice_date", ""))
        total_rel = 0.0
        if existing["total_amount"] > 0:
            total_rel = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        else:
            total_rel = 0.0 if new_invoice.get("total_amount", 0.0) == 0.0 else 1.0

        vendor_sim = text_similarity(new_invoice.get("vendor_name", ""), existing.get("vendor_name", ""))
        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        if (not np.isnan(date_diff) and date_diff <= 1) and total_rel <= 0.05 and vendor_sim >= 75:
            if line_sim >= 40 or normalize_text(new_invoice.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin","")):
                invno_sim_val = text_similarity(new_invoice.get("invoice_no",""), existing.get("invoice_no",""))
                near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim_val, line_sim, total_rel, date_diff, reason_special="Dates and totals very close")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
                result["reasons"].append("Invoice date and totals close -> possible duplicate")
                # don't return — continue scanning to find higher-confidence matches
            else:
                continue # similar date/totals but line items divergent -> ignore (logical)

    # 4) GSTIN + item/amount checks (tertiary)
    for idx, row in df.iterrows():
        existing = get_existing_from_row(row)

        gstin_same = normalize_text(new_invoice.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin",""))
        total_rel = 0.0
        if existing["total_amount"] > 0:
            total_rel = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        else:
            total_rel = 0.0 if new_invoice.get("total_amount", 0.0) == 0.0 else 1.0
            
        invno_sim = text_similarity(new_invoice.get("invoice_no",""), existing.get("invoice_no",""))
        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        supporting = 0
        if total_rel <= 0.05: supporting += 1
        if invno_sim >= 80: supporting += 1
        if line_sim >= 60: supporting += 1

        if gstin_same and supporting >= 1:
            if line_sim < 30 and invno_sim < 90:
                continue # logical: same GSTIN but different items likely valid; do not flag
            
            date_diff_val = date_diff_days(new_invoice.get("invoice_date",""), existing.get("invoice_date",""))
            near_dup = _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel, date_diff_val, reason_special="GSTIN matches and supporting signals present")
            result["near_duplicates"].append(near_dup)
            
            if invno_sim >= 90 or total_rel <= 0.02:
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("GSTIN match with strong supporting signals -> high risk")
                log_suspect_invoice(new_invoice, result, log_path)
                return result
            else:
                if result["overall_flag"] == "CLEAN":
                    result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"

    # 5) Conservative ghost detection
    ghost_reasons = detect_ghost_invoice(new_invoice, df)
    if ghost_reasons:
        result["ghost_signals"] = ghost_reasons
        if result["overall_flag"] == "CLEAN":
            result["overall_flag"] = "POTENTIAL_GHOST_INVOICE"
        result["reasons"].extend(ghost_reasons)
        log_suspect_invoice(new_invoice, result, log_path)
        return result

    # 6) Line Item Price Anomaly Detection (NEW)
    price_anomalies = detect_line_item_price_anomalies(new_invoice, df_items)
    if price_anomalies:
        result["line_item_price_anomalies"] = price_anomalies
        result["reasons"].extend(price_anomalies)
        if result["overall_flag"] == "CLEAN":
            result["overall_flag"] = "PRICE_ANOMALY"
        log_suspect_invoice(new_invoice, result, log_path)
        return result

    # 7) If we collected near_duplicates but not returned earlier, choose the top match
    if result["near_duplicates"]:
        def score_key(x):
            f = x["features"]
            return (f["invoice_no_sim"], f["lineitems_sim"], -f["total_rel_diff"])
        
        result["near_duplicates"] = sorted(result["near_duplicates"], key=score_key, reverse=True)
        top = result["near_duplicates"][0]
        
        if result["overall_flag"] == "CLEAN":
            top_conf = top["features"]["final_confidence"]
            if top_conf >= 0.9:
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
            elif top_conf >= 0.75:
                result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
            else:
                result["overall_flag"] = "LOW_RISK_RECHECK"
            result["reasons"].append("Similarity-based match found; review required")
        
        log_suspect_invoice(new_invoice, result, log_path)
        return result # Return here, as it's not "CLEAN"

    # 8) If no flags raised, it's CLEAN. Append to master CSV.
    if result["overall_flag"] == "CLEAN":
        append_to_master_csv(new_invoice, csv_path)

    return result

# ---------- Helper to build near-dup entry (FIXED) ----------
def _build_near_dup_entry(new_invoice, idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special=None):
    
    new_hsns = set([i.get("hsn","") for i in new_invoice.get("items", []) if i.get("hsn")])
    old_hsns = set([i.get("hsn","") for i in existing.get("items", []) if i.get("hsn")])
    hsn_mismatch = 1.0 if new_hsns != old_hsns else 0.0

    features = {
        "invoice_no_sim": round(float(invno_sim), 3),
        "vendor_name_sim": round(float(text_similarity(new_invoice.get("vendor_name",""), existing.get("vendor_name",""))), 3),
        "gstin_match": 1.0 if normalize_text(new_invoice.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin","")) else 0.0,
        "total_rel_diff": round(float(total_rel_diff), 6),
        "date_diff_days": float(date_diff) if not np.isnan(date_diff) else np.nan,
        "lineitems_sim": round(float(line_sim), 3),
        "hsn_mismatch_norm": hsn_mismatch
    }
    
    # heuristic final confidence
    w_inv = 0.35
    w_date = 0.20
    w_gst = 0.15
    w_item = 0.20
    w_amount = 0.10
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
    if reason_special:
        reasons.append(reason_special)
    if features["invoice_no_sim"] >= 85:
        reasons.append("Invoice number similar")
    if features["lineitems_sim"] >= 50:
        reasons.append("Line items similar")
    if features["total_rel_diff"] <= 0.05:
        reasons.append("Totals nearly identical")
    if not np.isnan(features["date_diff_days"]) and features["date_diff_days"] <= 3:
        reasons.append("Dates close")
    if features["gstin_match"] == 1.0:
        reasons.append("GSTIN exact match")

    near_dup = {
        "db_row_index": int(idx),
        "existing_invoice_summary": {
            "invoice_no": existing.get("invoice_no"),
            "vendor_gstin": existing.get("vendor_gstin"),
            "invoice_date": existing.get("invoice_date"),
            "total_amount": existing.get("total_amount")
        },
        "features": features,
        "heuristic_confidence": features["final_confidence"],
        "model_confidence": features["final_confidence"], # Using heuristic as model
        "final_confidence": features["final_confidence"],
        "reasons": reasons,
        "existing_full": existing # For potential UI display
    }
    return near_dup

# ---------- Logging (FIXED) ----------
def log_suspect_invoice(new_invoice, result, log_path):
    log_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "invoice_no": new_invoice.get("invoice_no"),
        "vendor_gstin": new_invoice.get("vendor_gstin"),
        "invoice_date": new_invoice.get("invoice_date"),
        "total_amount": new_invoice.get("total_amount"),
        "flag": result.get("overall_flag"),
        "confidence": max([n["final_confidence"] for n in result.get("near_duplicates", [])], default=1.0 if result.get("exact_duplicate") else 0.0),
        "reasons": "; ".join(result.get("reasons", []))
    }

    df = pd.DataFrame([log_data])
    if not os.path.exists(log_path):
        df.to_csv(log_path, index=False)
    else:
        df.to_csv(log_path, mode='a', header=False, index=False)

def append_to_master_csv(new_invoice, csv_path="invoice_data.csv"):
    """Appends a clean (non-duplicate) invoice to the master CSV."""
    df_new = pd.DataFrame([{
        "invoice_no": new_invoice.get("invoice_no"),
        "invoice_date": new_invoice.get("invoice_date"),
        "vendor_name": new_invoice.get("vendor_name"),
        "vendor_gstin": new_invoice.get("vendor_gstin"),
        "total_amount": new_invoice.get("total_amount"),
        "items": str(new_invoice.get("items", [])) # Store list as string
    }])
    
    # Ensure all columns from the user's example are present, even if blank
    for col in ["item_description", "unit_price", "amount", "gst_rate"]:
        if col not in df_new.columns:
            df_new[col] = pd.NA
            
    if not os.path.exists(csv_path):
        df_new.to_csv(csv_path, index=False)
    else:
        # Append, ensuring column order matches if possible
        try:
            df_existing = pd.read_csv(csv_path)
            # Re-order new_df columns to match existing
            df_new = df_new[df_existing.columns]
            df_new.to_csv(csv_path, mode='a', header=False, index=False)
        except Exception:
             # Fallback if columns mismatch badly
            df_new.to_csv(csv_path, mode='a', header=False, index=False)
            
# ---------- Test Case (UNCOMMENTED) ----------

# This test invoice will be flagged for PRICE_ANOMALY
# It sells a 'Laptop' (HSN 8471) for 75000,
# while historical data shows a price of 48000 on 01-11-2025 (INV009).
# The time difference is small, so inflation won't account for this jump.
test_invoice = {
     "invoice_no": "INV-TEST-001",
     "invoice_date": "10-11-2025",
     "vendor_name": "TechMart",
     "vendor_gstin": "27AAACT1234F1Z9",
     "total_amount": 75000,
     "items": [
         {"description": "Laptop", "hsn": "8471", "quantity": 1, "unit_price": 75000, "amount": 75000, "gst_rate": 18}
     ]
}

# This test invoice should be flagged as an EXACT_DUPLICATE of INV001
# test_invoice = {
#      "invoice_no": "INV001",
#      "invoice_date": "12-10-2025",
#      "vendor_name": "TechMart",
#      "vendor_gstin": "27AAACT1234F1Z9",
#      "total_amount": 50000,
#      "items": "[{'description': 'Laptop', 'hsn': '8471', 'quantity': 1, 'unit_price': 50000}]"
# }

# This test invoice should be CLEAN
# test_invoice = {
#      "invoice_no": "INV-NEW-999",
#      "invoice_date": "10-11-2025",
#      "vendor_name": "New Vendor Inc",
#      "vendor_gstin": "99ZZZYY1234A1Z0",
#      "total_amount": 1000,
#      "items": [
#          {"description": "Stapler", "hsn": "8305", "quantity": 1, "unit_price": 1000, "amount": 1000, "gst_rate": 12}
#      ]
# }


print("--- Running Invoice Check ---")
result = check_invoice(test_invoice, csv_path="invoice_data.csv")
print("\n--- Check Result ---")
import json
print(json.dumps(result, indent=2, default=str))
print("--------------------")