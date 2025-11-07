import pandas as pd
import numpy as np
import hashlib
import re
from datetime import datetime
from difflib import SequenceMatcher
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import os

# ---------- Normalization Helpers ----------

def normalize_text(s):
    """Remove punctuation, spaces, case differences, underscores, etc."""
    if not isinstance(s, str):
        s = str(s)
    s = s.lower()
    s = re.sub(r"[\s\-\_\,\.\'\/\\]+", "", s)
    return s.strip()

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
    def parse_date(s):
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
    da = parse_date(d1)
    db = parse_date(d2)
    if da is None or db is None:
        return np.nan
    return abs((da - db).days)

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
    past_items_flat = []
    for row in historical_df["items"]:
        try:
            past = eval(row) if isinstance(row, str) else []
            past_items_flat.extend([i.get("hsn", "") for i in past])
        except:
            continue
    past_hsn_set = set([x for x in past_items_flat if x])

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
    if vendor_rows.shape[0] >= 3:
        try:
            med = vendor_rows["total_amount"].astype(float).median()
            if med > 0:
                if new_inv.get("total_amount", 0) > 10 * med or new_inv.get("total_amount", 0) < 0.1 * med:
                    price_anomaly = True
        except:
            price_anomaly = False

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
    - logs suspicious invoices to log_path
    - returns structured report dict for frontend
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"{csv_path} not found.")

    df = pd.read_csv(csv_path)
    # ensure numeric total_amount
    if "total_amount" in df.columns:
        df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce").fillna(0.0)
    new_hash = compute_hash(new_invoice)

    result = {
        "invoice_hash": new_hash,
        "exact_duplicate": False,
        "exact_duplicate_match": None,
        "near_duplicates": [],
        "ghost_signals": [],
        "overall_flag": "CLEAN",
        "reasons": []
    }

    # 1) Exact Duplicate by HASH (strict)
    for idx, row in df.iterrows():
        try:
            existing = {
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "vendor_name": row["vendor_name"],
                "vendor_gstin": row["vendor_gstin"],
                "total_amount": float(row["total_amount"]),
                "items": eval(row["items"]) if isinstance(row.get("items"), str) else []
            }
        except Exception:
            existing = {
                "invoice_no": row.get("invoice_no", ""),
                "invoice_date": row.get("invoice_date", ""),
                "vendor_name": row.get("vendor_name", ""),
                "vendor_gstin": row.get("vendor_gstin", ""),
                "total_amount": float(row.get("total_amount") or 0),
                "items": []
            }
        if compute_hash(existing) == new_hash:
            result["exact_duplicate"] = True
            result["exact_duplicate_match"] = int(idx)
            result["overall_flag"] = "EXACT_DUPLICATE"
            result["reasons"].append("Exact duplicate: identical vendor+invoice+date+amount")
            log_suspect_invoice(new_invoice, result, log_path)
            return result

    # 2) Invoice-number first priority checks (very strict thresholds)
    # if invoice number extremely similar (>=95) AND totals near-identical -> HIGH_RISK
    # but if invoice_no similar but lineitems differ strongly, suppress flag
    for idx, row in df.iterrows():
        try:
            existing = {
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "vendor_name": row["vendor_name"],
                "vendor_gstin": row["vendor_gstin"],
                "total_amount": float(row["total_amount"]),
                "items": eval(row["items"]) if isinstance(row.get("items"), str) else []
            }
        except Exception:
            existing = {
                "invoice_no": row.get("invoice_no", ""),
                "invoice_date": row.get("invoice_date", ""),
                "vendor_name": row.get("vendor_name", ""),
                "vendor_gstin": row.get("vendor_gstin", ""),
                "total_amount": float(row.get("total_amount") or 0),
                "items": []
            }

        invno_sim = text_similarity(new_invoice.get("invoice_no", ""), existing.get("invoice_no", ""))
        total_rel_diff = 0.0
        if existing["total_amount"] > 0:
            total_rel_diff = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        # If invoice number is virtually identical and totals match -> immediate high risk
        if invno_sim >= 95 and total_rel_diff <= 0.05:
            # but require some item similarity OR same GSTIN OR very close dates to avoid false positive
            date_diff = date_diff_days(new_invoice.get("invoice_date", ""), existing.get("invoice_date", ""))
            gstin_same = normalize_text(new_invoice.get("vendor_gstin", "")) == normalize_text(existing.get("vendor_gstin", ""))
            if (line_sim >= 50) or gstin_same or (not np.isnan(date_diff) and date_diff <= 3):
                near_dup = _build_near_dup_entry(idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special="Invoice number nearly identical and amounts match")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("Invoice number extremely similar + totals match -> high risk")
                log_suspect_invoice(new_invoice, result, log_path)
                return result
            else:
                # invoice number similar but items totally different and other signals absent -> do NOT flag
                continue

    # 3) Date-priority checks (secondary)
    # If invoice dates are identical or within 1 day and totals similar and vendor similar -> raise medium risk
    for idx, row in df.iterrows():
        try:
            existing = {
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "vendor_name": row["vendor_name"],
                "vendor_gstin": row["vendor_gstin"],
                "total_amount": float(row["total_amount"]),
                "items": eval(row["items"]) if isinstance(row.get("items"), str) else []
            }
        except Exception:
            existing = {
                "invoice_no": row.get("invoice_no", ""),
                "invoice_date": row.get("invoice_date", ""),
                "vendor_name": row.get("vendor_name", ""),
                "vendor_gstin": row.get("vendor_gstin", ""),
                "total_amount": float(row.get("total_amount") or 0),
                "items": []
            }

        date_diff = date_diff_days(new_invoice.get("invoice_date", ""), existing.get("invoice_date", ""))
        total_rel = 0.0
        if existing["total_amount"] > 0:
            total_rel = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        vendor_sim = text_similarity(new_invoice.get("vendor_name", ""), existing.get("vendor_name", ""))
        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        if (not np.isnan(date_diff) and date_diff <= 1) and total_rel <= 0.05 and vendor_sim >= 75:
            # ensure items are not entirely different
            if line_sim >= 40 or normalize_text(new_invoice.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin","")):
                near_dup = _build_near_dup_entry(idx, existing, text_similarity(new_invoice.get("invoice_no",""), existing.get("invoice_no","")), line_sim, total_rel, date_diff, reason_special="Dates and totals very close")
                result["near_duplicates"].append(near_dup)
                result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
                result["reasons"].append("Invoice date and totals close -> possible duplicate")
                # don't return — continue scanning to find higher-confidence matches
            else:
                # similar date/totals but line items divergent -> ignore (logical)
                continue

    # 4) GSTIN + item/amount checks (tertiary)
    # If GSTIN matches and totals very close and invoice_no somewhat similar → possible duplicate
    for idx, row in df.iterrows():
        try:
            existing = {
                "invoice_no": row["invoice_no"],
                "invoice_date": row["invoice_date"],
                "vendor_name": row["vendor_name"],
                "vendor_gstin": row["vendor_gstin"],
                "total_amount": float(row["total_amount"]),
                "items": eval(row["items"]) if isinstance(row.get("items"), str) else []
            }
        except Exception:
            existing = {
                "invoice_no": row.get("invoice_no", ""),
                "invoice_date": row.get("invoice_date", ""),
                "vendor_name": row.get("vendor_name", ""),
                "vendor_gstin": row.get("vendor_gstin", ""),
                "total_amount": float(row.get("total_amount") or 0),
                "items": []
            }

        gstin_same = normalize_text(new_invoice.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin",""))
        total_rel = 0.0
        if existing["total_amount"] > 0:
            total_rel = abs(new_invoice.get("total_amount", 0.0) - existing["total_amount"]) / existing["total_amount"]
        invno_sim = text_similarity(new_invoice.get("invoice_no",""), existing.get("invoice_no",""))
        line_sim = lineitem_similarity(new_invoice.get("items", []), existing.get("items", []))

        # require at least two supporting signals: gstin_same + (totals close OR invno similar OR line items similar)
        supporting = 0
        if total_rel <= 0.05:
            supporting += 1
        if invno_sim >= 80:
            supporting += 1
        if line_sim >= 60:
            supporting += 1

        if gstin_same and supporting >= 1:
            # avoid flagging when items are clearly different (line_sim < 30) unless invoice number is highly similar
            if line_sim < 30 and invno_sim < 90:
                # logical: same GSTIN but different items likely valid; do not flag
                continue
            near_dup = _build_near_dup_entry(idx, existing, invno_sim, line_sim, total_rel, date_diff_days(new_invoice.get("invoice_date",""), existing.get("invoice_date","")), reason_special="GSTIN matches and supporting signals present")
            result["near_duplicates"].append(near_dup)
            # escalate if strong
            if invno_sim >= 90 or total_rel <= 0.02:
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
                result["reasons"].append("GSTIN match with strong supporting signals -> high risk")
                log_suspect_invoice(new_invoice, result, log_path)
                return result
            else:
                if result["overall_flag"] == "CLEAN":
                    result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"

    # 5) Conservative ghost detection (requires >=2 strong signals)
    ghost_reasons = detect_ghost_invoice(new_invoice, df)
    if ghost_reasons:
        result["ghost_signals"] = ghost_reasons
        if result["overall_flag"] == "CLEAN":
            result["overall_flag"] = "POTENTIAL_GHOST_INVOICE"
        result["reasons"].extend(ghost_reasons)
        log_suspect_invoice(new_invoice, result, log_path)
        return result

    # 6) If we collected near_duplicates but not returned earlier, choose the top match to set final flag
    if result["near_duplicates"]:
        # sort by a combination: invoice_no_sim desc, lineitems_sim desc, total_rel_diff asc
        def score_key(x):
            f = x["features"]
            return (f["invoice_no_sim"], f["lineitems_sim"], -f["total_rel_diff"])
        result["near_duplicates"] = sorted(result["near_duplicates"], key=score_key, reverse=True)
        top = result["near_duplicates"][0]
        # set overall flag if not already set
        if result["overall_flag"] == "CLEAN":
            top_conf = top["features"]["final_confidence"]
                # ----------- Auto-update Master CSV -----------
    
            append_to_master_csv(new_invoice, csv_path)

            if top_conf >= 0.9:
                result["overall_flag"] = "HIGH_RISK_NEAR_DUPLICATE"
            elif top_conf >= 0.75:
                result["overall_flag"] = "MEDIUM_RISK_POSSIBLE_DUPLICATE"
            else:
                result["overall_flag"] = "LOW_RISK_RECHECK"
            result["reasons"].append("Similarity-based match found; review required")
            log_suspect_invoice(new_invoice, result, log_path)
            # ----------- Auto-update Master CSV -----------
    
        append_to_master_csv(new_invoice, csv_path)

    return result

# ---------- Helper to build near-dup entry ----------
def _build_near_dup_entry(idx, existing, invno_sim, line_sim, total_rel_diff, date_diff, reason_special=None):
    features = {
        "invoice_no_sim": round(float(invno_sim), 3),
        "vendor_name_sim": round(float(text_similarity(existing.get("vendor_name",""), existing.get("vendor_name",""))), 3),  # will be 100 for same record
        "gstin_match": 1.0 if normalize_text(existing.get("vendor_gstin","")) == normalize_text(existing.get("vendor_gstin","")) else 0.0,
        "total_rel_diff": round(float(total_rel_diff), 6),
        "date_diff_days": float(date_diff) if date_diff is not None else np.nan,
        "lineitems_sim": round(float(line_sim), 3),
        "hsn_mismatch_norm": 0 if set([i.get("hsn","") for i in (existing.get("items") or [])]) == set([i.get("hsn","") for i in (existing.get("items") or [])]) else 0
    }
    # heuristic final confidence (keeps invoice-number priority)
    # weights tuned to prioritize invoice_no and date then GSTIN and items
    w_inv = 0.35
    w_date = 0.20
    w_gst = 0.15
    w_item = 0.20
    w_amount = 0.10
    amount_factor = 1.0 - min(1.0, features["total_rel_diff"])
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
    if features["date_diff_days"] <= 3:
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
        "model_confidence": features["final_confidence"],
        "final_confidence": features["final_confidence"],
        "reasons": reasons,
        "existing_full": existing
    }
    return near_dup

# ---------- Logging ----------
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

# test_invoice = {
#     "invoice_no": "INV-002",
#     "invoice_date": "12-10-2025",
#     "vendor_name": "TechMart",
#     "vendor_gstin": "27AAACT1234F1Z9",
#     "total_amount": 5000,
#     "items": [
#         {"description": "Hydra Crane Hire", "hsn": "9985", "quantity": 1, "unit_price": 3000, "amount": 3000, "gst_rate": 18}
#     ]
# }

result = check_invoice(test_invoice, csv_path="invoice_data.csv")
print(result)

def append_to_master_csv(new_invoice, csv_path="invoice_data.csv"):
    """Appends a clean (non-duplicate) invoice to the master CSV."""
    df_new = pd.DataFrame([{
        "invoice_no": new_invoice["invoice_no"],
        "invoice_date": new_invoice["invoice_date"],
        "vendor_name": new_invoice["vendor_name"],
        "vendor_gstin": new_invoice["vendor_gstin"],
        "total_amount": new_invoice["total_amount"],
        "items": str(new_invoice["items"])  # Store list as string safely
    }])
    
    if not os.path.exists(csv_path):
        df_new.to_csv(csv_path, index=False)
    else:
        df_existing = pd.read_csv(csv_path)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.to_csv(csv_path, index=False)
    
    add_invoice(invoice_no, date, gstin)
