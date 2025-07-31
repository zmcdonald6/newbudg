import gspread
import streamlit as st
from google.oauth2 import service_account
from datetime import datetime
import requests

# Set up credentials from Streamlit secrets
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = service_account.Credentials.from_service_account_info(
    dict(st.secrets["GOOGLE"]), scopes=SCOPE
)

def get_user_credentials():
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU")
    worksheet = sheet.worksheet("Users")
    records = worksheet.get_all_records()

    usernames = {}
    for idx, row in enumerate(records):
        usernames[row["email"]] = {
            "name": row["name"],
            "first_login": row.get("first_login", "FALSE").upper() == "TRUE",
            "password": row["hashed_password"],  # base64 string
            "row_index": idx + 2
        }

    return {"usernames": usernames}

def get_ip_address():
    try:
        response = requests.get("https://api.ipify.org?format=text")
        return response.text
    except:
        return "Unavailable"

def log_activity(email, activity_type):
    client = gspread.authorize(creds)
    sheet = client.open_by_key("1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU").worksheet("LoginLogs")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ip_address = get_ip_address()
    sheet.append_row([email, activity_type, timestamp, ip_address])
