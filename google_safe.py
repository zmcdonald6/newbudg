import time, gspread, pandas as pd, streamlit as st
from gspread.exceptions import APIError
from google.oauth2 import service_account

SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource
def get_client():
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["GOOGLE"], scopes=SCOPE
    )
    return gspread.authorize(creds)

client = get_client()

def safe_get_records(ws_name: str, retries=2, delay=5, ttl=300):
    """Cached + retried fetch of sheet -> DataFrame"""
    @st.cache_data(ttl=ttl, show_spinner=False)
    def _inner(name):
        ws = client.open_by_key(SHEET_ID).worksheet(name)
        for attempt in range(retries):
            try:
                return ws.get_all_records()
            except APIError:
                time.sleep(delay)
        st.error(f"Failed to fetch {name}. Try again later.")
        return []
    rows = _inner(ws_name)
    return pd.DataFrame(rows)

def clear_cache():
    st.cache_data.clear()
    st.success("🔃 Cache cleared.")
