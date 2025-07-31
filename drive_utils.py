# Author: Zedaine McDonald

import os
import mimetypes
from datetime import datetime
import tempfile
import gspread
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Constants
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
PARENT_FOLDER_ID = "10bL1POPWVyCcD7O1-Dokklq6wD2kG39-"

SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.file"
]

# Load credentials from Streamlit secrets
creds = service_account.Credentials.from_service_account_info(
    dict(st.secrets["GOOGLE"]), scopes=SCOPE
)

def upload_to_drive_and_log(file, file_type, uploader_email, custom_name):
    # Save uploaded file to temp path
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file.getvalue())
        temp_path = tmp.name

    # Initialize Drive service
    drive_service = build("drive", "v3", credentials=creds)

    # Prepare metadata
    mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    metadata = {
        "name": custom_name + ".xlsx",
        "mimeType": mime_type,
        "parents": [PARENT_FOLDER_ID],
    }

    media = MediaFileUpload(temp_path, mimetype=mime_type, resumable=False)

    # Upload to Drive
    uploaded_file = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True
    ).execute()

    file_id = uploaded_file.get("id")

    # Make it publicly accessible
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print("⚠️ Permission setting failed:", e)

    file_url = f"https://drive.google.com/uc?id={file_id}"

    # Delete temp file
    try:
        os.remove(temp_path)
    except Exception as e:
        print("⚠️ Failed to delete temp file:", e)

    # Log in Google Sheet
    try:
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
        sheet.append_row([
            custom_name + ".xlsx",
            file_type,
            uploader_email,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            file_url
        ])
    except Exception as e:
        print("Failed to log file to sheet:", e)

    return file_url
