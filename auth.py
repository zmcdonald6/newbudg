import gspread
from oauth2client.service_account import ServiceAccountCredentials

def get_user_credentials():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
    client = gspread.authorize(creds)

    sheet = client.open_by_key("1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU")
    worksheet = sheet.worksheet("Users")
    records = worksheet.get_all_records()

    usernames = {}
    for idx, row in enumerate(records):
        usernames[row["email"]] = {
            "name": row["name"],
            "first_login": row.get("first_login", "FALSE").upper()=="TRUE",
            "password": row["hashed_password"],  # Already base64-encoded string
            "row_index": idx + 2
        }

    return {"usernames": usernames}
