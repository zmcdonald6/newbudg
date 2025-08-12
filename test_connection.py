import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Define API scope
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Load your service account credentials
creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
client = gspread.authorize(creds)

# Open the sheet by its ID
sheet = client.open_by_key("1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU")

# Access the 'Users' worksheet
worksheet = sheet.worksheet("Users")

# Read all records from the worksheet
records = worksheet.get_all_records()

# Display results
print("✅ Successfully connected to the sheet!")
print(f"📌 Found {len(records)} users:")
for user in records:
    print(user)
