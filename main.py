import streamlit as st
import bcrypt
import base64
from auth import get_user_credentials, log_activity
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

users = get_user_credentials()["usernames"]

# Constants
INACTIVITY_LIMIT_MINUTES = 10

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

# Login flow
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

# First login password change
elif st.session_state.authenticated:
    user = st.session_state.get("user_record")

    if user and user.get("first_login"):
        st.warning("🔐 This is your first login. Please change your password.")

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
                    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                    creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
                    client = gspread.authorize(creds)
                    sheet = client.open_by_key("1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU").worksheet("Users")

                    row = user["row_index"]
                    sheet.update_cell(row, 4, encoded)  # Update password
                    sheet.update_cell(row, 6, "FALSE")  # Mark first_login as false

                    st.success("✅ Password updated successfully.")
                    st.session_state.user_record["first_login"] = False
                    st.rerun()
    else:
        st.success(f"✅ Logged in as {st.session_state.name}")
        st.write("🎯 Your dashboard goes here...")

        if st.button("Logout"):
            log_activity(st.session_state.email, "Logout")
            st.session_state.authenticated = False
            st.session_state.email = ""
            st.session_state.name = ""
            st.session_state.pop("login_email", None)
            st.session_state.pop("login_password", None)
            st.session_state.user_record = {}
            st.rerun()
