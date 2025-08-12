import gspread
import streamlit as st
from google.oauth2 import service_account
from datetime import datetime
import requests

from settings import SHEET_ID, google_credentials

# API scopes
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_data(ttl=60, show_spinner=False)
def get_user_credentials():
    """
    Returns:
      {"usernames": {
          "<email>": {
            "name": str,
            "role": "admin"|"user",
            "first_login": bool,
            "password": base64_bcrypt,
            "row_index": int  # Google Sheet row number (2-based)
          }, ...
      }}
    """
    creds = google_credentials(SCOPE)
    client = gspread.authorize(creds)

    sheet = client.open_by_key(SHEET_ID)
    ws = sheet.worksheet("Users")
    records = ws.get_all_records()

    usernames = {}
    # Headers in your sheet: name | username | email | hashed_password | role | first_login
    for idx, row in enumerate(records):
        email = str(row.get("email", "")).strip()
        if not email:
            continue
        role_val = str(row.get("role", row.get("Role", "user"))).strip().lower()
        first_login = str(row.get("first_login", "FALSE")).strip().upper() == "TRUE"
        usernames[email] = {
            "name": row.get("name", ""),
            "role": role_val if role_val in ("admin", "user") else "user",
            "first_login": first_login,
            "password": row.get("hashed_password", ""),
            "row_index": idx + 2,  # add 1 for header + 1 for 1-based rows
        }

    return {"usernames": usernames}

def get_ip_address():
    try:
        resp = requests.get("https://api.ipify.org?format=text", timeout=10)
        return resp.text
    except Exception:
        return "Unavailable"

def log_activity(email: str, activity_type: str):
    """
    Append a row to the LoginLogs sheet: [email, activity_type, timestamp, ip_address]
    """
    try:
        creds = google_credentials(SCOPE)
        client = gspread.authorize(creds)
        ws = client.open_by_key(SHEET_ID).worksheet("LoginLogs")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ip_address = get_ip_address()
        ws.append_row([email, activity_type, timestamp, ip_address])
    except Exception as e:
        # Non-fatal: don't crash the app if logging fails
        st.warning(f"Login logging failed: {e}")
