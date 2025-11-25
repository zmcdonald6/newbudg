import streamlit as st
import bcrypt
import base64
from datetime import datetime, timedelta
#import gspread
#from google.oauth2 import service_account
import pandas as pd
import requests
from io import BytesIO
#import re

from uritemplate import expand

#from auth import get_user_credentials
from functions.db import *
from functions.drive_utils import upload_to_drive_and_log
from analysis import process_budget, process_expenses
from fxhelper import get_usd_rates, convert_row_amount_to_usd
#from google_safe import clear_cache, get_client, SHEET_ID
#from gspread.exceptions import APIError
#from classification_utils import load_budget_state_monthly, save_budget_state_monthly
from dashboard_classification import dashboard
from functions.report_generator import render_generate_report_section

# Constants
INACTIVITY_LIMIT_MINUTES = 10
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

## Helper functions for data caching to prevent read overloads.
# --- Cached Google client ---
#@st.cache_resource
#def get_gclient():
#    creds = service_account.Credentials.from_service_account_info(st.secrets["GOOGLE"], scopes=SCOPE)
#    return gspread.authorize(creds)

#client = get_client()

# --- Cached data loaders ---
#@st.cache_data(ttl=60)
#def load_users():
#    ws = client.open_by_key(SHEET_ID).worksheet("Users")
#    rows = ws.get_all_records()
#    return pd.DataFrame(rows)

#@st.cache_data(ttl=60)
#def load_logs():
#    ws = client.open_by_key(SHEET_ID).worksheet("LoginLogs")
#    rows = ws.get_all_records()
#    return pd.DataFrame(rows)

#@st.cache_data(ttl=60)
#def load_files():
#    ws = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
#    rows = ws.get_all_records()
#    return pd.DataFrame(rows)

@st.cache_data(ttl=1800)
def cached_fx_rates():
    return get_usd_rates()

@st.cache_data(ttl=600)
def cached_file_download(url: str):
    return requests.get(url).content


#Helper to colour code Variance column conditionally
##Rules:
# 1) if spent>budget, colour = green
# 2) if spent<budget and spent >= 70% of budget, colour = orange
# 3) else, colour =red 
def variance_color_style(row):
    try:
        budget = float(row["Amount Budgeted"])
    except:
        budget = 0.0

    try:
        spent = float(row["Amount Spent (USD)"])
    except:
        spent = 0.0

    try:
        variance = float(row["Variance (USD)"])
    except:
        variance = 0.0

    # default = no styling
    styles = [""] * len(row)

    # Apply to variance column only
    if variance < 0:
        colour = "background-color: #8B0000; color: white;" #red
    elif variance > 0 and spent >= 0.7 * budget:
        colour = "background-color: orange; color: black;"  #orange
    elif variance > 0:
        colour = "background-color: #4CAF50; color: white;" #green
    else:
        colour = ""  # variance == 0
    
    try:
        index = row.index.get_loc("Variance (USD)")
        styles[index] = colour
    except Exception as e:
        print (f"An error has occured: {e}")
    return styles

#Helper function to create a status column.
def get_variance_status(budget, spent, variance):
    if variance < 0:
        return "Overspent"
    elif variance > 0 and spent >= 0.70 * budget:
        return "Warning — ≥70% Spent"
    elif variance > 0:
        return "Within Budget"
    else:
        return "No Expenditure / OOB"


# Initialize session
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.email = ""
    st.session_state.name = ""
    st.session_state.login_email = ""
    st.session_state.login_password = ""
    st.session_state.last_active = datetime.now()
    st.session_state.user_record = {}
    st.session_state.force_pw_change = False  # ← added
if "force_pw_change" not in st.session_state:
    st.session_state.force_pw_change = False

# Timeout
if st.session_state.authenticated:
    if datetime.now() - st.session_state.last_active > timedelta(minutes=INACTIVITY_LIMIT_MINUTES):
        st.warning("⏱️ Session timed out due to inactivity.")
        ip = get_ip()
        log_login_activity(st.session_state.email, "Auto Logout (Inactivity)", ip)
        st.session_state.authenticated = False
        st.rerun()
    else:
        st.session_state.last_active = datetime.now()

# Login screen
if not st.session_state.authenticated and not st.session_state.force_pw_change:
    st.header("🔐 Login")
    with st.form("login_form"):
        email = st.text_input("Email (case sensitive)", key="login_email")
        password = st.text_input("Password (case sensitive)", type="password", key="login_password")
        submit = st.form_submit_button("Login")

        if submit:
            user = get_user_by_email(email)
            if user:
                try:
                    decoded_hash = base64.b64decode(user["hashed_password"])
                    if bcrypt.checkpw(password.encode(), decoded_hash):
                        # success -> check first_login flag
                        st.session_state.email = email
                        st.session_state.name = user["name"]
                        st.session_state.user_record = user
                        if user.get("first_login", False):
                            st.session_state.force_pw_change = True
                            st.rerun()
                        else:
                            st.session_state.authenticated = True
                            st.session_state.last_active = datetime.now()
                            st.rerun()
                    else:
                        st.error("❌ Incorrect password.")
                except Exception as e:
                    st.error(f"Hash decoding failed: {e}")
            else:
                st.error("❌ Email not found.")

# First-login password reset screen
elif st.session_state.force_pw_change:
    st.title("🔑 Set a New Password")
    st.info("It looks like this is your first login. Please set a new password to continue.")

    with st.form("pw_reset_form"):
        pw1 = st.text_input("New password", type="password")
        pw2 = st.text_input("Confirm new password", type="password")
        submit_pw = st.form_submit_button("Update Password")

        if submit_pw:
            if not pw1 or len(pw1) < 8:
                st.error("Password must be at least 8 characters.")
            elif pw1 != pw2:
                st.error("Passwords do not match.")
            else:
                try:
                    # hash + base64
                    new_hash = bcrypt.hashpw(pw1.encode(), bcrypt.gensalt())
                    encoded = base64.b64encode(new_hash).decode()

                    # Update Google Sheet
                    #creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
                    #client = gspread.authorize(creds)
                    #ws = client.open_by_key(SHEET_ID).worksheet("Users")

                    # Find row by email
                    #cell = ws.find(st.session_state.email)
                    #row = cell.row

                    # Update the row values in header order
                    #header = ws.row_values(1)
                    #row_vals = ws.row_values(row)

                    # pad if needed
                    #while len(row_vals) < len(header):
                    #    row_vals.append("")

                    ## set new values
                    #hp_idx = header.index("hashed_password")
                    #fl_idx = header.index("first_login")
                    #row_vals[hp_idx] = encoded
                    #row_vals[fl_idx] = "FALSE"

                    # write back (A..end_col for this row)
                    #def _col_letters(n: int) -> str:
                    #    s = ""
                    #    while n > 0:
                    #        n, r = divmod(n - 1, 26)
                    #        s = chr(65 + r) + s
                    #    return s
                    #end_col_letter = _col_letters(len(header))

                    #ws.update(f"A{row}:{end_col_letter}{row}", [row_vals])

                    #Update Password
                    update_password(st.session_state.email, encoded)

                    # update session
                    st.session_state.user_record["first_login"] = False
                    st.session_state.user_record["password"] = encoded
                    st.session_state.force_pw_change = False
                    st.session_state.authenticated = True
                    st.session_state.last_active = datetime.now()

                    st.success("Password updated successfully. Redirecting…")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update password: {e}")

# Main dashboard
elif st.session_state.authenticated:
    st.title("MSGIT Budget Reporter")
    # === Templates download (Budget & Expenses) ===
    # with st.container():
    #    st.markdown("### Download budget and expense templates below")
    #    try:
    #        from pathlib import Path as _Path
    #        _tpl_dir = _Path(__file__).parent / "templates"
    #        _bud_bytes = (_tpl_dir / "Budget_Template_BTA.xlsx").read_bytes()
    #        _exp_bytes = (_tpl_dir / "Expense_Template_BTA.xlsx").read_bytes()
    #        c1, c2 = st.columns(2)
    #        with c1:
    #            st.download_button("Download Budget Template", data=_bud_bytes, file_name="Budget_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_bud_tpl")
    #        with c2:
    #            st.download_button("Download Expenses Template", data=_exp_bytes, file_name="Expenses_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_exp_tpl")
    #    except Exception as _e:
    #        st.info("Templates will appear here when available.")
    ip = get_ip()
    log_login_activity(st.session_state.email, "Login", ip)

    if st.button("🚪 Logout"):
        ip = get_ip()
        log_login_activity(st.session_state.email, "Logout",ip)
        for key in list(st.session_state.keys()):
            st.session_state[key] = False if key == "authenticated" else ""
        st.rerun()

    st.success(f"✅ Logged in as {st.session_state.name}")
    st.caption(f"Role: {st.session_state.user_record.get('role','user')}")


    # --- Admin panel ---
    _is_admin = str(st.session_state.user_record.get("role", "user")).strip().lower() == "admin"
    if _is_admin:
        st.subheader("Admin Panel")

        #Global refresh for cached sheets
        if st.button("♻️ Data Refresh"):
                    #clear_cache()
                    st.success("Cache cleared.")
                    st.rerun()

        #CRUD on Users
        with st.expander("User Management", expanded=False):
            # --- Load cached sheet data (API-safe) ---
            user_records = get_all_users()
            df_users = pd.DataFrame(user_records)

            # Handle refresh manually (clear cache + rerun)
            if st.button("🔄 Refresh Users"):
                #clear_cache()
                st.rerun()

            # --- Display users ---
            if df_users.empty:
                st.info("No users found.")
            else:
                st.dataframe(df_users, width="stretch")

            st.divider()
            st.subheader("Add New User")

            # --- Add new user form ---
            with st.form("admin_add_user_form"):
                new_name = st.text_input("Name")
                new_username = st.text_input("Username")
                new_email = st.text_input("Email")
                new_role = st.selectbox("Role", ["user", "admin"])
                new_password_plain = st.text_input("Initial Password", type="password")
                add_submit = st.form_submit_button("➕ Add User")

                if add_submit:
                    if not new_email or not new_password_plain:
                        st.error("Email and password are required.")
                    elif not df_users.empty and new_email.lower() in df_users["email"].astype(str).str.lower().values:
                        st.error("A user with that email already exists.")
                    else:
                        try:
                            hashed = bcrypt.hashpw(new_password_plain.encode(), bcrypt.gensalt())
                            encoded = base64.b64encode(hashed).decode()
                            add_user(new_name, new_username, new_email, encoded, new_role)
                            st.success("✅ User added — they’ll be required to change password on first login.")
                            st.rerun()
                        #except APIError:
                        #    st.error("Google API temporarily unavailable. Please try again later.")
                        except Exception as e:
                            st.error(f"Failed to add user: {e}")

            # ============================================================
            # RESET PASSWORD / REMOVE USER
            # ============================================================
            st.divider()
            st.subheader("Reset Password / Remove User")

            if df_users.empty:
                st.info("No users available.")
            else:
                sel_email = st.selectbox("Select user by email", df_users["email"].dropna().tolist())

                with st.form("admin_reset_remove_form"):
                    new_pw_plain = st.text_input("New Password", type="password")
                    col1, col2 = st.columns(2)
                    do_reset = col1.form_submit_button("🔑 Reset Password")
                    confirm_delete = col2.checkbox("Yes, delete this user")
                    do_delete = col2.form_submit_button("🗑️ Remove User")

                    # --- Reset password ---
                    if do_reset:
                        if not new_pw_plain:
                            st.error("Enter a new password.")
                        else:
                            try:
                                #ws = client.open_by_key(SHEET_ID).worksheet("Users")

                                # Find row index (row 1 is header)
                                #email_col = ws.col_values(ws.row_values(1).index("email") + 1)
                                #row_no = next((i for i, v in enumerate(email_col, start=1)
                                #            if v.strip().lower() == sel_email.strip().lower()), None)
                                #if not row_no or row_no == 1:
                                #    st.error("Couldn't locate user row.")
                                #else:
                                #    header = ws.row_values(1)
                                #    row_vals = ws.row_values(row_no)
                                #    while len(row_vals) < len(header):
                                #        row_vals.append("")

                                    # Update hashed password + force first_login = TRUE
                                #    new_h = bcrypt.hashpw(new_pw_plain.encode(), bcrypt.gensalt())
                                #    row_vals[header.index("hashed_password")] = base64.b64encode(new_h).decode()
                                #    row_vals[header.index("first_login")] = "TRUE"

                                    # Write back
                                #    end_col_letter = chr(64 + len(header))
                                #    ws.update(f"A{row_no}:{end_col_letter}{row_no}", [row_vals])
                                    reset_user_password(sel_email, base64.b64encode(
                                        bcrypt.hashpw(new_pw_plain.encode(), bcrypt.gensalt())
                                    ).decode())
                                    st.success("✅ Password reset — user must change it next login.")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Reset failed: {e}")

                    # --- Delete user ---
                    if do_delete:
                        if not confirm_delete:
                            st.error("Please confirm deletion first.")
                        else:
                            try:
                                #ws = client.open_by_key(SHEET_ID).worksheet("Users")
                                #email_col = ws.col_values(ws.row_values(1).index("email") + 1)
                                #row_no = next((i for i, v in enumerate(email_col, start=1)
                                #            if v.strip().lower() == sel_email.strip().lower()), None)
                                #if not row_no or row_no == 1:
                                #    st.error("Couldn't locate user row.")
                                #else:
                                #    ws.delete_rows(row_no)
                                #    get_user_credentials.clear()
                                #    clear_cache()
                                delete_user(sel_email)
                                st.success("✅ User removed.")
                                st.rerun()
                            #except APIError:
                            #    st.error("Google API write error. Try again later.")
                            except Exception as e:
                                st.error(f"Delete failed: {e}")

        # To View Logins
        with st.expander("Login Activity", expanded=False):
            # --- Load cached sheet data safely ---
            records = get_login_logs()
            df_logs = pd.DataFrame(records)

            # --- Manual refresh button (clear cache + rerun) ---
            if st.button("🔄 Refresh Logs"):
                #clear_cache()
                st.rerun()

            # --- Handle empty logs ---
            if df_logs.empty:
                st.info("No login activity found.")
                st.stop()

            # --- Display main log dataframe ---
            st.dataframe(df_logs, width="stretch")

            # --- Ensure timestamp column is proper datetime ---
            if "timestamp" in df_logs.columns:
                if not pd.api.types.is_datetime64_any_dtype(df_logs["timestamp"]):
                    df_logs["timestamp"] = pd.to_datetime(df_logs["timestamp"], errors="coerce")

            # =======================================================
            # FILTERS (Email + Date Range)
            # =======================================================
            if not df_logs.empty:
                # --- Email filter ---
                if "email" in df_logs.columns:
                    email_options = sorted(df_logs["email"].dropna().astype(str).unique().tolist())
                    selected_emails = st.multiselect(
                        "Filter by Email",
                        options=email_options,
                        default=email_options,
                    )
                else:
                    selected_emails = None

                # --- Date range filter (if timestamps exist) ---
                if "timestamp" in df_logs.columns and df_logs["timestamp"].notna().any():
                    ts_nonnull = df_logs["timestamp"].dropna()
                    default_start = ts_nonnull.min().date()
                    default_end = ts_nonnull.max().date()
                    start_date, end_date = st.date_input(
                        "Filter by Date Range",
                        value=(default_start, default_end),
                        min_value=default_start,
                        max_value=default_end,
                    )
                else:
                    start_date = end_date = None

                # --- Apply filters ---
                filtered = df_logs.copy()

                if selected_emails is not None and len(selected_emails) != len(email_options):
                    filtered = filtered[filtered["email"].isin(selected_emails)]

                if start_date and end_date and "timestamp" in filtered.columns:
                    mask = filtered["timestamp"].dt.date.between(start_date, end_date)
                    filtered = filtered[mask]

                # --- Show filtered data ---
                st.dataframe(filtered.sort_values("timestamp", ascending=False), width="stretch")
            else:
                st.info("No log entries available yet.")


        # --- CRUD on Files ---
        with st.expander("File Management", expanded=False):
            # --- Load cached sheet data safely ---
            file_records = get_uploaded_files()
            df_files = pd.DataFrame(file_records)

            # --- Manual refresh button (clear cache + rerun) ---
            if st.button("🔄 Refresh Files"):
                #clear_cache()
                st.rerun()

            # --- View files ---
            if df_files.empty:
                st.info("No uploaded files found.")
            else:
                st.dataframe(df_files, width="stretch")

            st.divider()

            # ===========================================================
            # ADD (UPLOAD) NEW FILE
            # ===========================================================
            st.subheader("Add File")
            with st.form("admin_upload_form"):
                uploaded_file = st.file_uploader("Choose a file (.xlsx)", type=["xlsx"], key="admin_file_uploader")
                custom_name = st.text_input("Enter file name (REQUIRED)", key="admin_custom_name")
                file_type = st.selectbox("Type of file", ["budget(opex)", "budget(capex)", "expense"], key="admin_file_type")
                submit_upload = st.form_submit_button("Upload File")

                if submit_upload:
                    if not uploaded_file:
                        st.error("Please choose a file.")
                    elif not custom_name.strip():
                        st.error("Please enter a file name.")
                    else:
                        try:
                            url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email, custom_name)
                            if url:
                                #clear_cache()
                                st.success("✅ Uploaded and logged successfully.")
                                st.write(f"[View File]({url})")
                                st.rerun()
                            else:
                                st.error("Upload or logging failed.")
                        except Exception as e:
                            st.error(f"Upload failed: {e}")

            st.divider()

            # ===========================================================
            # DELETE FILE RECORD
            # ===========================================================
            st.subheader("Delete File Record")

            if df_files.empty:
                st.info("No uploaded files found.")
            else:
                # --- Choose record to delete ---
                to_delete = st.selectbox(
                    "Select a file record to delete",
                    df_files["file_name"].dropna().tolist(),
                    key="admin_file_to_delete"
                )

                # --- Show quick details ---
                try:
                    sel_row = df_files[df_files["file_name"] == to_delete].iloc[0]
                    st.caption(
                        f"Type: {sel_row.get('file_type', '?')} • "
                        f"Uploaded by: {sel_row.get('uploader_email', '?')} • "
                        f"At: {sel_row.get('timestamp', '?')}"
                    )
                except Exception:
                    pass

                confirm = st.checkbox("Yes, delete this record")
                delete_clicked = st.button("🗑️ Delete File Record")

                # --- Delete action ---
                if delete_clicked:
                    if not confirm:
                        st.error("Please confirm deletion first.")
                    else:
                        try:
                            delete_uploaded_file(to_delete)
                            st.success("✅ File record removed successfully.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete record: {e}")


    
    # =========================================================
    # Upload interface (collapsed)
    # =========================================================
    with st.expander("Download Reporter Templates", expanded=False):
        st.markdown("### Download budget and expense templates below")
        try:
            from pathlib import Path as _Path
            _tpl_dir = _Path(__file__).parent / "templates"
            _bud_bytes = (_tpl_dir / "Budget_Template_BTA.xlsx").read_bytes()
            _exp_bytes = (_tpl_dir / "Expense_Template_BTA.xlsx").read_bytes()
            c1, c2 = st.columns(2)
            with c1:
                st.download_button("Download Budget Template", data=_bud_bytes, file_name="Budget_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_bud_tpl")
            with c2:
                st.download_button("Download Expenses Template", data=_exp_bytes, file_name="Expenses_Template.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="dl_exp_tpl")
        except Exception as _e:
            st.info("Templates will appear here when available.")

    with st.expander("⬆ Upload File (Budget or Expense)", expanded=False):
        with st.form("upload_form"):
            uploaded_file = st.file_uploader("Choose a file (.xlsx)", type=["xlsx"])
            custom_name = st.text_input("Enter file name (REQUIRED)")
            file_type = st.selectbox("Type of file", ["budget(opex)", "budget(capex)", "expense"])
            submit_upload = st.form_submit_button("Upload File")

            if submit_upload:
                if not uploaded_file:
                    st.error("Please choose a file.")
                elif not custom_name.strip():
                    st.error("Please enter a file name.")
                else:
                    try:
                        # ✅ Perform upload and log it
                        url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email, custom_name)

                        if url:
                            # ✅ Clear cache so admins see it instantly in their tables
                            st.success("✅ Uploaded and logged successfully.")
                            st.write(f"[View File]({url})")
                            st.experimental_rerun()
                        else:
                            st.error("Upload or logging failed. Please try again.")
                    except Exception as e:
                        st.error(f"Upload failed: {e}")

    #Report Generator
    render_generate_report_section(
        process_budget=process_budget,
        process_expenses=process_expenses,
        get_usd_rates=get_usd_rates,
        convert_row_amount_to_usd=convert_row_amount_to_usd,
        load_budget_state_monthly=load_budget_state_monthly,
        save_budget_state_monthly=save_budget_state_monthly,
        dashboard=dashboard,
        variance_color_style=variance_color_style,
        get_variance_status=get_variance_status    
    )
    
                   

