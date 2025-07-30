# Author: Zedaine McDonald

import gspread
import os
import mimetypes
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account
import tempfile

# Constants
SCOPE = [
    "https://www.googleapis.com/auth/drive",
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive.file"
]

SERVICE_ACCOUNT_FILE = "service_account.json"
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"  # Your actual Google Sheet ID
PARENT_FOLDER_ID = "10bL1POPWVyCcD7O1-Dokklq6wD2kG39-"  # 'Files' folder inside BudgApp shared drive

def upload_to_drive_and_log(file, file_type, uploader_email, custom_name):
    # ✅ Save file to a temp file and close handle immediately (Windows compatible)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(file.getvalue())
        temp_path = tmp.name

    # ✅ Auth
    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPE)
    drive_service = build("drive", "v3", credentials=creds)

    # ✅ Set metadata and upload
    mime_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    metadata = {
        "name": custom_name + ".xlsx",
        "mimeType": mime_type,
        "parents": [PARENT_FOLDER_ID],
    }

    media = MediaFileUpload(temp_path, mimetype=mime_type, resumable=False)

    uploaded_file = drive_service.files().create(
        body=metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True
    ).execute()

    file_id = uploaded_file.get("id")

    # ✅ Share the file publicly (optional)
    try:
        drive_service.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"},
            supportsAllDrives=True
        ).execute()
    except Exception as e:
        print("⚠️ Permission setting failed:", e)

    file_url = f"https://drive.google.com/uc?id={file_id}"

    # ✅ Safely delete temp file
    try:
        os.remove(temp_path)
    except Exception as e:
        print("⚠️ Failed to delete temp file:", e)

    # ✅ Log to Google Sheet
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
