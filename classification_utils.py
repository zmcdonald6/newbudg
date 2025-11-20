from google_safe import safe_get_records, get_client, SHEET_ID
import pandas as pd
from datetime import datetime
import streamlit as st

# Loading specific budget file.
def load_budget_state_monthly(file_name: str):
    df = safe_get_records("BudgetStateMonthly")

    if df.empty:
        return pd.DataFrame(columns=[
            "file_name","Category","Sub-Category","Month","Amount","Status Category"
        ])

    df = df[df["file_name"] == file_name]
    return df

# SAVE — saves budget state, overrides previous rows for this budget file 
def save_budget_state_monthly(file_name: str, df_melted: pd.DataFrame, user_email: str):
    client = get_client()
    ws = client.open_by_key(SHEET_ID).worksheet("BudgetStateMonthly")

    # Read existing rows
    rows = ws.get_all_records()

    # Remove existing rows for this budget file
    retained = [r for r in rows if r.get("file_name") != file_name]

    # Clear sheet, rewrite header
    ws.clear()
    ws.append_row([
        "file_name","Category","Sub-Category","Month","Amount",
        "Status Category","updated_by","updated_at"
    ])

    # Write retained rows
    for r in retained:
        ws.append_row(list(r.values()))

    # Write new rows
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for _, r in df_melted.iterrows():
        ws.append_row([
            file_name,
            r["Category"],
            r["Sub-Category"],
            r["Month"],
            r["Amount"],
            r["Status Category"],
            user_email,
            now
        ])

    st.cache_data.clear()   #refreshing cache