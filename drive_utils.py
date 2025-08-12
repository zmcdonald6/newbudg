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
from settings import SHEET_ID, PARENT_FOLDER_ID, google_credentials

# Constants
SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.file"
]

# Load credentials from Streamlit secrets
creds = google_credentials(SCOPE), scopes=SCOPE
)

def upload_to_drive_and_log(file, file_type, uploader_email, custom_name):
    """
    Uploads a file to Google Drive, makes it public, and logs the upload in the UploadedFiles sheet.
    Appends a tag to the saved filename based on the file_type:
      - budget(opex)  -> ~opex
      - budget(capex) -> ~capex
      - expense       -> ~expense

    Prevents duplicate file names (tagged) from being uploaded.
    """
    # Decide suffix based on file_type (case-insensitive)
    suffix_map = {
        "budget(opex)": "~opex",
        "budget(capex)": "~capex",
        "expense": "~expense",
    }
    suffix = suffix_map.get(str(file_type).strip().lower(), "")
    tagged_name = f"{custom_name}{suffix}.xlsx"

    # Connect to Google Sheet
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
    existing_files = [row[0] for row in sheet.get_all_values()[1:]]  # Skip header row if any

    # Check for duplicate
    if tagged_name in existing_files:
        st.error(f"❌ A file named '{tagged_name}' already exists. Please choose a different name.")
        return None

    # Save uploaded file to temp path
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file.getvalue())
        temp_path = tmp.name

    # Initialize Drive service
    drive_service = build("drive", "v3", credentials=creds)

    # Prepare metadata
    mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    metadata = {
        "name": tagged_name,
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
        sheet.append_row([
            tagged_name,
            file_type,
            uploader_email,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            file_url
        ])
    except Exception as e:
        print("Failed to log file to sheet:", e)

    return file_url
