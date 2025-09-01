import pandas as pd
import re
from typing import Union, IO

# Months for budget template
MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

def _clean_text(series: pd.Series) -> pd.Series:
    """Strip and collapse whitespace in a Series of strings."""
    return (
        series.astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .replace("nan", pd.NA)
    )

def _extract_label(cat_str: str) -> str:
    """Extract leading label like 'A)', 'B)' → 'A','B'."""
    if pd.isna(cat_str):
        return None
    m = re.match(r"\s*([A-Za-z0-9])\)\s*", str(cat_str))
    return m.group(1).upper() if m else None

# ------------------- BUDGET -------------------
def process_budget(file_like: Union[str, IO[bytes]]) -> pd.DataFrame:
    """
    Reads the official Budget template:
    Category | Subcategory | Jan..Dec | Notes
    Returns: CatLabel, Category, Sub-Category, Total
    """
    try:
        df = pd.read_excel(file_like, sheet_name="Budget")
    except Exception:
        df = pd.read_excel(file_like, sheet_name=0)

    df.columns = [str(c).strip() for c in df.columns]

    required = ["Category","Subcategory"] + MONTHS + ["Notes"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Budget sheet missing required columns: {', '.join(missing)}")

    for m in MONTHS:
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0.0)

    df["Total"] = df[MONTHS].sum(axis=1)

    mask = df["Category"].astype(str).str.strip().ne("") & df["Subcategory"].astype(str).str.strip().ne("")
    out = df.loc[mask, ["Category","Subcategory","Total"]].copy()

    # Extract CatLabel directly from Category prefix
    out["CatLabel"] = out["Category"].apply(_extract_label)

    out = out.rename(columns={"Subcategory":"Sub-Category"})
    out["Total"] = pd.to_numeric(out["Total"], errors="coerce")

    return out[["CatLabel","Category","Sub-Category","Total"]]

# ------------------- EXPENSES -------------------
def process_expenses(file_like: Union[str, IO[bytes]]) -> pd.DataFrame:
    """
    Reads the official Expense template:
    Date | Category | Subcategory (compound "Category *** Subcategory")
    | Vendor | Amount | Currency | Classification | Notes

    Splits Subcategory into Category + Sub-Category,
    extracts CatLabel, forward-fills blanks,
    tags N/A/blank categories as "Out of Budget".
    """
    try:
        df = pd.read_excel(file_like, sheet_name="Expenses")
    except Exception:
        df = pd.read_excel(file_like, sheet_name=0)

    df.columns = [str(c).strip() for c in df.columns]

    required = ["Date","Category","Subcategory","Vendor","Amount","Currency","Classification","Notes"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Expenses sheet missing required columns: {', '.join(missing)}")

    # Parse Amount
    df["Amount"] = (
        df["Amount"]
        .astype(str)
        .str.replace(r"[^\d\.\-]", "", regex=True)
        .replace("", "0")
    )
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)

    # Parse Date
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date

    # Split "Category *** Sub-Category"
    split_cat = df["Subcategory"].astype(str).str.split("***", n=1, expand=True, regex=False)
    if split_cat.shape[1] == 2:
        df["Category"]     = _clean_text(split_cat[0])
        df["Sub-Category"] = _clean_text(split_cat[1])
    else:
        df["Sub-Category"] = _clean_text(df["Subcategory"])

    # Forward-fill continuation rows
    df[["Category","Sub-Category"]] = df[["Category","Sub-Category"]].ffill()

    # Tag N/A/blank categories
    df.loc[df["Category"].isna() | df["Category"].str.upper().eq("N/A"), "Category"] = "Out of Budget"

    # Extract CatLabel
    df["CatLabel"] = df["Category"].apply(_extract_label)

    # Clean classification
    df["Classification"] = _clean_text(df["Classification"]).str.upper()

    return df[["Date","CatLabel","Category","Sub-Category","Vendor","Amount","Currency","Classification","Notes"]]
