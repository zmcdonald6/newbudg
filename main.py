import streamlit as st
import bcrypt
import base64
from datetime import datetime, timedelta
import gspread
from google.oauth2 import service_account
import pandas as pd
import requests
import matplotlib.pyplot as plt
from io import BytesIO

from auth import get_user_credentials, log_activity
from drive_utils import upload_to_drive_and_log
from analysis import process_budget

# Constants
users = get_user_credentials()["usernames"]
INACTIVITY_LIMIT_MINUTES = 10
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# Initialize session
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.email = ""
    st.session_state.name = ""
    st.session_state.login_email = ""
    st.session_state.login_password = ""
    st.session_state.last_active = datetime.now()
    st.session_state.user_record = {}

# Timeout
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
                        st.rerun()
                    else:
                        st.error("❌ Incorrect password.")
                except Exception as e:
                    st.error(f"Hash decoding failed: {e}")
            else:
                st.error("❌ Email not found.")

# Main dashboard
elif st.session_state.authenticated:
    st.title("MSGIT Budget Reporter")
    log_activity(st.session_state.email, "Login")

    if st.button("🚪 Logout"):
        log_activity(st.session_state.email, "Logout")
        for key in st.session_state.keys():
            st.session_state[key] = False if key == "authenticated" else ""
        st.rerun()

    st.success(f"✅ Logged in as {st.session_state.name}")

    # Upload interface
    st.header("⬆️ Upload File (Budget or Expense)")
    with st.form("upload_form"):
        uploaded_file = st.file_uploader("Choose a file", type=["xlsx"])
        custom_name = st.text_input("Enter file name")
        file_type = st.selectbox("Type of file", ["budget", "expense"])
        submit_upload = st.form_submit_button("Upload File")

        if submit_upload and uploaded_file:
            if not custom_name.strip():
                st.error("Please enter a file name")
            else:
                url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email, custom_name)
                st.success(f"✅ Uploaded and logged successfully.")
                st.write(f"[View File]({url})")

    # Select files
    st.header("📁 Select Budget and Expense Files")
    creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
    client = gspread.authorize(creds)
    upload_log = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
    records = upload_log.get_all_records()

    if records:
        df_files = pd.DataFrame(records)
        budget_files = df_files[df_files["file_type"] == "budget"]
        expense_files = df_files[df_files["file_type"] == "expense"]

        selected_budget = st.selectbox("📘 Select Budget File", budget_files["file_name"].tolist())
        selected_expense = st.selectbox("💸 Select Expense File", expense_files["file_name"].tolist())

        if selected_budget and selected_expense:
            budget_url = budget_files[budget_files["file_name"] == selected_budget]["file_url"].values[0]
            expense_url = expense_files[expense_files["file_name"] == selected_expense]["file_url"].values[0]

            df_budget = process_budget(BytesIO(requests.get(budget_url).content))
            df_expense = pd.read_excel(BytesIO(requests.get(expense_url).content))

            # ✅ Normalize column names
            col_map = {
                "date": "Invoice Date", "invoice date": "Invoice Date",
                "vendorname": "Vendor", "vendor": "Vendor",
                "subcategory": "Sub-Category", "sub-category": "Sub-Category",
                "category": "Category",
                "amount": "Amount", "cost": "Amount", "totalcost": "Amount"
            }
            df_expense.rename(columns=lambda x: col_map.get(x.strip().lower(), x.strip()), inplace=True)

            # ✅ Validate required columns
            required = ["Category", "Sub-Category", "Invoice Date", "Vendor", "Amount"]
            missing = [c for c in required if c not in df_expense.columns]
            if missing:
                st.error(f"❌ Expense sheet is missing: {', '.join(missing)}")
                st.stop()

            # ✅ Parse mixed-format invoice dates
            def parse_date_safely(date_str):
                for fmt in ("%d/%m/%Y", "%m/%d/%Y"):
                    try:
                        return pd.to_datetime(date_str, format=fmt)
                    except:
                        continue
                return pd.NaT

            df_expense["Month"] = df_expense["Invoice Date"].apply(parse_date_safely).dt.strftime('%B')

            # Filter UI
            st.markdown("### 🔍 Filter Data")
            with st.expander("📂 Filter by Categories"):
                all_cats = sorted(df_expense["Category"].dropna().unique().tolist())
                select_all_cat = st.checkbox("Select All Categories", value=True, key="all_categories")
                selected_categories = st.multiselect("Choose Categories", options=all_cats, default=all_cats if select_all_cat else [])

            with st.expander("🏷️ Filter by Vendors"):
                all_vendors = sorted(df_expense["Vendor"].dropna().unique().tolist())
                select_all_ven = st.checkbox("Select All Vendors", value=True, key="all_vendors")
                selected_vendors = st.multiselect("Choose Vendors", options=all_vendors, default=all_vendors if select_all_ven else [])

            # Apply filters
            filtered_df = df_expense[
                df_expense["Category"].isin(selected_categories) &
                df_expense["Vendor"].isin(selected_vendors)
            ].copy()

            # Merge with budget
            merged = pd.merge(
                filtered_df,
                df_budget[df_budget["Subcategory"].notna()],
                how="left",
                left_on=["Category", "Sub-Category"],
                right_on=["Category", "Subcategory"]
            )

            # Final display table
            final_view = merged[["Category", "Sub-Category", "Vendor", "Total", "Amount", "Month"]]
            final_view.columns = ["Category", "Sub-category", "Vendor", "Amount Budgeted", "Amount Spent", "Month"]
            final_view["Variance"] = final_view["Amount Budgeted"] - final_view["Amount Spent"]

            st.markdown("### 📄 Expense vs Budget Table")
            st.dataframe(final_view)

            # Bar chart summary
            #category_summary = final_view.groupby("Category")["Amount Spent"].sum().reset_index()
            #fig, ax = plt.subplots(figsize=(8, 5))
            #ax.bar(category_summary["Category"], category_summary["Amount Spent"])
            #ax.set_xlabel("Category")
            #ax.set_ylabel("Total Spent")
            #ax.set_title("Total Spent by Category")
            #plt.xticks(rotation=45)
            #st.pyplot(fig)
    else:
        st.info("📭 No uploaded files yet. Please upload at least one budget and one expense file.")



