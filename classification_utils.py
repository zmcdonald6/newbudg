import json
import pandas as pd
from google_safe import get_client, SHEET_ID
from datetime import datetime
import pymysql
import streamlit as st

CHUNK_SIZE = 48000  # safely under Google Sheets 50k cell limit

host=st.secrets["MYSQL"]["host"],
user=st.secrets["MYSQL"]["user"],
password=st.secrets["MYSQL"]["password"],
database=st.secrets["MYSQL"]["database"]

def get_db():
    try:
        pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            cursorclass=pymysql.cursors.DictCursor
        )
        print (f"Connected to database name: {database}")
    except Exception as e:
        print ("Connection failed")




# ============================================================
# LOAD — read JSON stored across multiple rows
# ============================================================
def load_budget_state_monthly(file_name: str):
    """
    Safely loads JSON-chunked classification data from BudgetStateMonthly.
    - Reads all chunks from column A
    - Joins them into one JSON string
    - Validates JSON structure
    - Returns only the rows for the requested budget
    - Never crashes on malformed data
    """

    client = get_client()

    try:
        ws = client.open_by_key(SHEET_ID).worksheet("BudgetStateMonthly")
    except Exception:
        # Worst case fallback → empty DF
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Read all rows in column A (each row = 1 JSON chunk)
    try:
        chunks = ws.col_values(1)
    except Exception:
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # EMPTY sheet
    if not chunks or all(c.strip() == "" for c in chunks):
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Build JSON string (safe join)
    json_str = "".join(c for c in chunks if c and c.strip() != "")

    if not json_str.strip():
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Parse JSON safely
    try:
        store = json.loads(json_str)
    except Exception:
        # Corrupted JSON → return safe empty DF
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Extract records for requested budget file
    rows = store.get(file_name, [])

    # Ensure valid structure
    if not isinstance(rows, list):
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Convert to DataFrame
    try:
        df = pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=[
            "Category", "Sub-Category", "Month", "Amount", "Status Category"
        ])

    # Guarantee required columns exist
    required = ["Category", "Sub-Category", "Month", "Amount", "Status Category"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    return df[required]


# ============================================================
# SAVE — write chunked JSON (safe for big data)
# ============================================================
def save_budget_state_monthly(file_name, df_melted, user_email):
    client = get_client()
    ws = client.open_by_key(SHEET_ID).worksheet("BudgetStateMonthly")

    # First load existing JSON (chunks → stitched)
    chunks = ws.col_values(1)
    if chunks:
        try:
            store = json.loads("".join(chunks))
        except:
            store = {}
    else:
        store = {}

    # Convert df into list of dicts
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    records = df_melted.to_dict(orient="records")

    # Add metadata to each record
    for r in records:
        r["updated_by"] = user_email
        r["updated_at"] = now

    # Replace only this file entry
    store[file_name] = records

    # Convert entire DB → JSON string
    json_str = json.dumps(store)

    # Split into chunks to avoid Google’s 50k limit
    chunks = [json_str[i:i+CHUNK_SIZE] for i in range(0, len(json_str), CHUNK_SIZE)]

    # Clear worksheet and write each chunk in its own row
    ws.clear()
    ws.update("A1", [[chunk] for chunk in chunks])
