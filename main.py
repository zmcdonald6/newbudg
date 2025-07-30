import streamlit as st
import bcrypt
import base64
from datetime import datetime, timedelta
import gspread
from google.oauth2 import service_account
import pandas as pd
import requests
from io import BytesIO

from auth import get_user_credentials, log_activity
from drive_utils import upload_to_drive_and_log
from analysis import process_budget, generate_summary, plot_budget_vs_spent, get_monthly_trend

# Constants
users = get_user_credentials()["usernames"]
INACTIVITY_LIMIT_MINUTES = 10
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Init session state
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.email = ""
    st.session_state.name = ""
    st.session_state.login_email = ""
    st.session_state.login_password = ""
    st.session_state.last_active = datetime.now()
    st.session_state.user_record = {}

# Inactivity timeout
if st.session_state.authenticated:
    if datetime.now() - st.session_state.last_active > timedelta(minutes=INACTIVITY_LIMIT_MINUTES):
        st.warning("⏱️ Session timed out due to inactivity.")
        log_activity(st.session_state.email, "Auto Logout (Inactivity)")
        st.session_state.authenticated = False
        st.rerun()
    else:
        st.session_state.last_active = datetime.now()

# Login screen
if not st.session_state.authenticated:
    st.header("🔐 Login")
    with st.form("login_form"):
        email = st.text_input("Email (case sensitive)", key="login_email")
        password = st.text_input("Password (case sensitive)", type="password", key="login_password")
        submit = st.form_submit_button("Login")

        if submit:
            user = users.get(email)
            if user:
                try:
                    decoded_hash = base64.b64decode(user["password"])
                    if bcrypt.checkpw(password.encode(), decoded_hash):
                        st.session_state.authenticated = True
                        st.session_state.email = email
                        st.session_state.name = user["name"]
                        st.session_state.user_record = user
                        st.session_state.last_active = datetime.now()
                        st.session_state.selected_budget = None
                        st.session_state.selected_expense = None
                        st.session_state.pop("login_email", None)
                        st.session_state.pop("login_password", None)
                        log_activity(email, "Login")
                        st.rerun()
                    else:
                        st.error("❌ Incorrect password.")
                        st.session_state.pop("login_password", None)
                        st.rerun()
                except Exception as e:
                    st.error(f"Hash decoding or check failed: {e}")
                    st.session_state.pop("login_password", None)
                    st.rerun()
            else:
                st.error("❌ Email not found.")
                st.session_state.pop("login_password", None)
                st.rerun()

# Post-login view
elif st.session_state.authenticated:
    user = st.session_state.get("user_record")

    # First login password change
    if user and user.get("first_login"):
        st.warning("🔐 First login: Please change your password.")
        with st.form("change_password"):
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            submit_change = st.form_submit_button("Update Password")

            if submit_change:
                if new_password != confirm_password:
                    st.error("❌ Passwords do not match.")
                elif len(new_password) < 6:
                    st.error("⚠️ Password must be at least 6 characters.")
                else:
                    hashed = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt())
                    encoded = base64.b64encode(hashed).decode()

                    creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPE)
                    client = gspread.authorize(creds)
                    sheet = client.open_by_key(SHEET_ID).worksheet("Users")
                    row = user["row_index"]
                    sheet.update_cell(row, 4, encoded)
                    sheet.update_cell(row, 6, "FALSE")

                    st.success("✅ Password updated successfully.")
                    st.session_state.user_record["first_login"] = False
                    st.rerun()

    else:
        st.success(f"✅ Logged in as {st.session_state.name}")

        # Upload UI
        st.header("⬆️ Upload New Budget or Expense File")
        with st.form("upload_form"):
            uploaded_file = st.file_uploader("Choose a file", type=["xlsx"])
            custom_name = st.text_input("Enter file name")
            file_type = st.selectbox("Type of file", ["budget", "expense"])
            submit_upload = st.form_submit_button("Upload File")

            if submit_upload and uploaded_file:
                if not custom_name.strip():
                    st.error("Please enter a file name")
                else:
                    url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email,custom_name)
                    st.success(f"✅ Uploaded and logged successfully.")
                    st.write(f"[View File]({url})")

        # File Selection
        st.header("📁 Select Budget and Expense Files")
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPE)
        client = gspread.authorize(creds)
        upload_log = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
        records = upload_log.get_all_records()

        if not records:
            st.info("📭 No uploaded files yet. Please upload at least one budget and one expense file.")
        else:
            df_files = pd.DataFrame(records)

            # Check for required column before filtering
            if "file_type" in df_files.columns:
                budget_files = df_files[df_files["file_type"] == "budget"]
                expense_files = df_files[df_files["file_type"] == "expense"]

                selected_budget = st.selectbox("📘 Select Budget File", budget_files["file_name"].tolist())
                selected_expense = st.selectbox("💸 Select Expense File", expense_files["file_name"].tolist())

                if selected_budget and selected_expense:
                    budget_url = budget_files[budget_files["file_name"] == selected_budget]["file_url"].values[0]
                    expense_url = expense_files[expense_files["file_name"] == selected_expense]["file_url"].values[0]

                    df_budget = process_budget(BytesIO(requests.get(budget_url).content))
                    df_expense = pd.read_excel(BytesIO(requests.get(expense_url).content))

                    st.markdown("### 📊 Budget vs Expense Summary")
                    summary_df = generate_summary(df_budget, df_expense)
                    st.dataframe(summary_df)

                    st.pyplot(plot_budget_vs_spent(summary_df))

                    st.markdown("### 📈 Monthly Expense Trend")
                    st.line_chart(get_monthly_trend(df_expense))

                    st.markdown("### 🔍 Filter by Category or Vendor")
                    categories = df_expense["Category"].dropna().unique().tolist()
                    vendors = df_expense["Vendor"].dropna().unique().tolist()

                    cat_filter = st.selectbox("Filter by Category", ["All"] + categories)
                    vend_filter = st.selectbox("Filter by Vendor", ["All"] + vendors)

                    filtered = df_expense.copy()
                    if cat_filter != "All":
                        filtered = filtered[filtered["Category"] == cat_filter]
                    if vend_filter != "All":
                        filtered = filtered[filtered["Vendor"] == vend_filter]

                    st.dataframe(filtered)
            else:
                st.error("❌ 'file_type' column missing in UploadedFiles sheet. Please check headers.")

        # Logout
        if st.button("Logout"):
            log_activity(st.session_state.email, "Logout")
            st.session_state.authenticated = False
            st.session_state.email = ""
            st.session_state.name = ""
            st.session_state.pop("login_email", None)
            st.session_state.pop("login_password", None)
            st.session_state.user_record = {}
            st.rerun()