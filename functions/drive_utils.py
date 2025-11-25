# Author: Zedaine McDonald

import os
import mimetypes
from datetime import datetime
import tempfile
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# NEW: Import db layer
from .db import add_uploaded_file, get_uploaded_files

# Constants
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
PARENT_FOLDER_ID = "10bL1POPWVyCcD7O1-Dokklq6wD2kG39-"

SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.file"
]

creds = service_account.Credentials.from_service_account_info(
    dict(st.secrets["GOOGLE"]), scopes=SCOPE
)


def upload_to_drive_and_log(file, file_type, uploader_email, custom_name):
    """
    Upload a file to Google Drive and log metadata in MySQL.
    The Google Sheets dependency is removed.
    """

    # Decide suffix based on file_type (case-insensitive)
    suffix_map = {
        "budget(opex)": "~opex",
        "budget(capex)": "~capex",
        "expense": "~expense",
    }
    suffix = suffix_map.get(str(file_type).strip().lower(), "")
    tagged_name = f"{custom_name}{suffix}.xlsx"

    # -------------------------------
    # ❗ NEW: Check duplicates in MySQL
    # -------------------------------
    existing = [row["file_name"] for row in get_uploaded_files()]
    if tagged_name in existing:
        st.error(f"❌ A file named '{tagged_name}' already exists. Choose a different name.")
        return None

    # Save file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file.getvalue())
        temp_path = tmp.name

    # Google Drive service
    drive_service = build("drive", "v3", credentials=creds)

    # Prepare metadata
    mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    metadata = {
        "name": tagged_name,
        "mimeType": mime_type,
        "parents": [PARENT_FOLDER_ID],
    }
    media = MediaFileUpload(temp_path, mimetype=mime_type, resumable=False)

    # Upload file to Drive
    uploaded_file = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True
    ).execute()

    file_id = uploaded_file.get("id")
    file_url = f"https://drive.google.com/uc?id={file_id}"

    # Make file publicly accessible
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print("⚠️ Permission setting failed:", e)

    # Remove temp file
    try:
        os.remove(temp_path)
    except Exception as e:
        print("⚠️ Failed to delete temp file:", e)

    # ----------------------------------------
    # ❗ NEW: Log metadata to MySQL instead of Sheets
    # ----------------------------------------
    try:
        add_uploaded_file(
            file_name=tagged_name,
            file_type=file_type,
            uploader_email=uploader_email,
            file_url=file_url
        )
    except Exception as e:
        st.error(f"⚠️ Failed to log file metadata to MySQL: {e}")
        return None

    return file_url
