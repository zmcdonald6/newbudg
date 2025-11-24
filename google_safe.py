import time
import gspread
import pandas as pd
import streamlit as st
from gspread.exceptions import APIError
from google.auth.exceptions import TransportError
from google.oauth2 import service_account
from requests.exceptions import ReadTimeout, ConnectionError

SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


# ===============================================================
# 1. GLOBAL CACHED CLIENT
# ===============================================================
@st.cache_resource
def get_client():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["GOOGLE"], scopes=SCOPE
    )
    return gspread.authorize(creds)


# ===============================================================
# 2. RETRY HANDLER
# ===============================================================
def _retry_api(func, *args, retries=3, base_delay=2, **kwargs):
    for attempt in range(retries):
        try:
            return func(*args, **kwargs)

        except (APIError, ReadTimeout, ConnectionError, TransportError) as e:
            if attempt < retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            else:
                st.error(f"⚠️ Google Sheets error: {e}")
                return None

        except Exception as e:
            st.error(f"⚠️ Unexpected error: {e}")
            return None


# ===============================================================
# 3. SAFE READER WITH DETECTION FOR JSON-CHUNK SHEETS
# ===============================================================
@st.cache_data(ttl=300, show_spinner=False)
def safe_get_records(ws_name: str):
    """
    Auto-detects normal tables vs JSON-chunk storage.
    Prevents get_all_records() from corrupting JSON chunk data.
    """

    client = get_client()

    ss = _retry_api(client.open_by_key, SHEET_ID)
    if ss is None:
        return pd.DataFrame()

    ws = _retry_api(ss.worksheet, ws_name)
    if ws is None:
        return pd.DataFrame()

    # ----------------------------------------------------------
    # SPECIAL CASE: JSON CHUNK SHEETS (Classification storage)
    # ----------------------------------------------------------
    if ws_name == "BudgetStateMonthly":
        # Just return raw rows — classification_utils handles decoding
        raw_rows = _retry_api(ws.col_values, 1)  # column A chunks
        if raw_rows is None:
            return pd.DataFrame()
        return pd.DataFrame({"chunk": raw_rows})

    # ----------------------------------------------------------
    # NORMAL SHEETS
    # ----------------------------------------------------------
    rows = _retry_api(ws.get_all_records)
    if rows is None:
        return pd.DataFrame()

    return pd.DataFrame(rows)


# ===============================================================
# 4. CLEAR CACHE
# ===============================================================
def clear_cache():
    st.cache_data.clear()
    st.success("🔃 Cache cleared.")
