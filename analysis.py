import pandas as pd
import numpy as np
import re

def _extract_cat_label(text):
    """Return 'A','B','C',... from 'A) Something', else None."""
    if pd.isna(text):
        return None
    m = re.match(r"\s*([A-Za-z0-9])\)\s*", str(text))
    return m.group(1).upper() if m else None

def _strip_leading_label(s):
    if pd.isna(s):
        return None
    return re.sub(r"^\s*[A-Za-z0-9]+\)\s*", "", str(s).strip())

def _final_subcat(s):
    """From 'Thing *** Specific Name' keep the last part as the subcategory."""
    if pd.isna(s):
        return None
    parts = [p.strip() for p in str(s).split("***")]
    out = parts[-1] if parts else str(s)
    return re.sub(r"\s+", " ", out) or None

def process_budget(file_path_or_bytes):
    """
    Parse the Budget workbook into a tidy frame with:
      - CatLabel (A/B/C/...)
      - Category (budget category header text)
      - Sub-Category (cleaned, last *** chunk)
      - Total (numeric, already USD)
    """
    raw = pd.read_excel(file_path_or_bytes, sheet_name=0, header=None, engine="openpyxl")
    df = raw.dropna(how="all")
    df = df.dropna(axis=1, how="all").reset_index(drop=True)

    # Heuristic: choose the rightmost column with enough numerics as Total
    ncols = df.shape[1]
    numeric_counts = {c: pd.to_numeric(df.iloc[:, c], errors="coerce").notna().sum() for c in range(1, ncols)}
    candidates = [c for c, cnt in numeric_counts.items() if cnt >= 10]
    total_col = max(candidates) if candidates else (ncols - 1)

    def is_category_row(v):
        return isinstance(v, str) and re.match(r"^\s*[A-Z]\)\s+", v)

    def is_subsection_row(v):
        return isinstance(v, str) and re.match(r"^\s*[a-z0-9]\)\s+", v)

    records = []
    current_cat = None
    current_label = None

    for i in range(len(df)):
        desc = df.iloc[i, 0]

        if is_category_row(desc):
            current_label = _extract_cat_label(desc)     # 'A','B',...
            current_cat   = _strip_leading_label(desc)   # e.g., 'Email & Telephony'
            continue

        if is_subsection_row(desc):
            # Skip internal sub-sections like "a) ..."
            continue

        # Treat as a sub-item if any numeric appears in 1..total_col
        nums = pd.to_numeric(df.iloc[i, 1:total_col+1], errors="coerce")
        if nums.notna().any() and isinstance(desc, str) and desc.strip():
            sub = _final_subcat(_strip_leading_label(desc))
            tot = pd.to_numeric(df.iloc[i, total_col], errors="coerce")
            records.append({
                "CatLabel": current_label,              # 'A','B','C',...
                "Category": current_cat,                # full budget category name
                "Sub-Category": sub,                    # cleaned subcategory (after ***)
                "Total": float(tot) if pd.notna(tot) else np.nan  # USD already
            })

    out = pd.DataFrame(records).dropna(subset=["CatLabel","Category","Sub-Category"]).reset_index(drop=True)
    out["Total"] = pd.to_numeric(out["Total"], errors="coerce")
    return out

