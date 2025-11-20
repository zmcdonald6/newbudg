import streamlit as st
import bcrypt
import base64
from datetime import datetime, timedelta
import gspread
from google.oauth2 import service_account
import pandas as pd
import requests
from io import BytesIO
import re

from uritemplate import expand

from auth import get_user_credentials, log_activity
from drive_utils import upload_to_drive_and_log
from analysis import process_budget, process_expenses
from fxhelper import get_usd_rates, convert_row_amount_to_usd
from google_safe import safe_get_records, clear_cache, client, SHEET_ID
from gspread.exceptions import APIError
from classification_utils import load_budget_state_monthly, save_budget_state_monthly
from dashboard_classification import dashboard

# Constants
INACTIVITY_LIMIT_MINUTES = 10
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

## Helper functions for data caching to prevent read overloads.
# --- Cached Google client ---
@st.cache_resource
def get_gclient():
    creds = service_account.Credentials.from_service_account_info(st.secrets["GOOGLE"], scopes=SCOPE)
    return gspread.authorize(creds)

client = get_gclient()

# --- Cached data loaders ---
@st.cache_data(ttl=60)
def load_users():
    ws = client.open_by_key(SHEET_ID).worksheet("Users")
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

@st.cache_data(ttl=60)
def load_logs():
    ws = client.open_by_key(SHEET_ID).worksheet("LoginLogs")
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

@st.cache_data(ttl=60)
def load_files():
    ws = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
    rows = ws.get_all_records()
    return pd.DataFrame(rows)

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
        log_activity(st.session_state.email, "Auto Logout (Inactivity)")
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
            users = get_user_credentials()["usernames"]
            user = users.get(email)
            if user:
                try:
                    decoded_hash = base64.b64decode(user["password"])
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
                    creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
                    client = gspread.authorize(creds)
                    ws = client.open_by_key(SHEET_ID).worksheet("Users")

                    # Find row by email
                    cell = ws.find(st.session_state.email)
                    row = cell.row

                    # Update the row values in header order
                    header = ws.row_values(1)
                    row_vals = ws.row_values(row)

                    # pad if needed
                    while len(row_vals) < len(header):
                        row_vals.append("")

                    # set new values
                    hp_idx = header.index("hashed_password")
                    fl_idx = header.index("first_login")
                    row_vals[hp_idx] = encoded
                    row_vals[fl_idx] = "FALSE"

                    # write back (A..end_col for this row)
                    def _col_letters(n: int) -> str:
                        s = ""
                        while n > 0:
                            n, r = divmod(n - 1, 26)
                            s = chr(65 + r) + s
                        return s
                    end_col_letter = _col_letters(len(header))

                    ws.update(f"A{row}:{end_col_letter}{row}", [row_vals])

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

    log_activity(st.session_state.email, "Login")

    if st.button("🚪 Logout"):
        log_activity(st.session_state.email, "Logout")
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
                    clear_cache()
                    st.success("Cache cleared.")
                    st.rerun()

        #CRUD on Users
        with st.expander("User Management", expanded=False):
            # --- Load cached sheet data (API-safe) ---
            df_users = safe_get_records("Users")

            # Handle refresh manually (clear cache + rerun)
            if st.button("🔄 Refresh Users"):
                clear_cache()
                st.rerun()

            # --- Display users ---
            if df_users.empty:
                st.info("No users found.")
            else:
                st.dataframe(df_users, use_container_width=True)

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
                            ws = client.open_by_key(SHEET_ID).worksheet("Users")
                            ws.append_row([new_name, new_username, new_email, encoded, new_role, "TRUE"])
                            get_user_credentials.clear()
                            clear_cache()
                            st.success("✅ User added — they’ll be required to change password on first login.")
                            st.rerun()
                        except APIError:
                            st.error("Google API temporarily unavailable. Please try again later.")
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
                                ws = client.open_by_key(SHEET_ID).worksheet("Users")

                                # Find row index (row 1 is header)
                                email_col = ws.col_values(ws.row_values(1).index("email") + 1)
                                row_no = next((i for i, v in enumerate(email_col, start=1)
                                            if v.strip().lower() == sel_email.strip().lower()), None)
                                if not row_no or row_no == 1:
                                    st.error("Couldn't locate user row.")
                                else:
                                    header = ws.row_values(1)
                                    row_vals = ws.row_values(row_no)
                                    while len(row_vals) < len(header):
                                        row_vals.append("")

                                    # Update hashed password + force first_login = TRUE
                                    new_h = bcrypt.hashpw(new_pw_plain.encode(), bcrypt.gensalt())
                                    row_vals[header.index("hashed_password")] = base64.b64encode(new_h).decode()
                                    row_vals[header.index("first_login")] = "TRUE"

                                    # Write back
                                    end_col_letter = chr(64 + len(header))
                                    ws.update(f"A{row_no}:{end_col_letter}{row_no}", [row_vals])
                                    get_user_credentials.clear()
                                    clear_cache()
                                    st.success("✅ Password reset — user must change it next login.")
                                    st.rerun()
                            except APIError:
                                st.error("Google API write error. Try again later.")
                            except Exception as e:
                                st.error(f"Reset failed: {e}")

                    # --- Delete user ---
                    if do_delete:
                        if not confirm_delete:
                            st.error("Please confirm deletion first.")
                        else:
                            try:
                                ws = client.open_by_key(SHEET_ID).worksheet("Users")
                                email_col = ws.col_values(ws.row_values(1).index("email") + 1)
                                row_no = next((i for i, v in enumerate(email_col, start=1)
                                            if v.strip().lower() == sel_email.strip().lower()), None)
                                if not row_no or row_no == 1:
                                    st.error("Couldn't locate user row.")
                                else:
                                    ws.delete_rows(row_no)
                                    get_user_credentials.clear()
                                    clear_cache()
                                    st.success("✅ User removed.")
                                    st.rerun()
                            except APIError:
                                st.error("Google API write error. Try again later.")
                            except Exception as e:
                                st.error(f"Delete failed: {e}")

        # To View Logins
        with st.expander("Login Activity", expanded=False):
            # --- Load cached sheet data safely ---
            df_logs = safe_get_records("LoginLogs")

            # --- Manual refresh button (clear cache + rerun) ---
            if st.button("🔄 Refresh Logs"):
                clear_cache()
                st.rerun()

            # --- Handle empty logs ---
            if df_logs.empty:
                st.info("No login activity found.")
                st.stop()

            # --- Display main log dataframe ---
            st.dataframe(df_logs, use_container_width=True)

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
                st.dataframe(filtered.sort_values("timestamp", ascending=False), use_container_width=True)
            else:
                st.info("No log entries available yet.")


        # --- CRUD on Files ---
        with st.expander("File Management", expanded=False):
            # --- Load cached sheet data safely ---
            df_files = safe_get_records("UploadedFiles")

            # --- Manual refresh button (clear cache + rerun) ---
            if st.button("🔄 Refresh Files"):
                clear_cache()
                st.rerun()

            # --- View files ---
            if df_files.empty:
                st.info("No uploaded files found.")
            else:
                st.dataframe(df_files, use_container_width=True)

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
                                clear_cache()
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
                            # ✅ Open the worksheet (only for the operation)
                            files_ws = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")

                            header = [h.strip().lower() for h in files_ws.row_values(1)]
                            if "file_name" not in header:
                                st.error("Header 'file_name' not found in UploadedFiles sheet.")
                            else:
                                col_idx = header.index("file_name") + 1
                                names = files_ws.col_values(col_idx)
                                row_no = next(
                                    (i for i, v in enumerate(names, start=1)
                                    if str(v).strip() == str(to_delete).strip()),
                                    None,
                                )

                                if not row_no or row_no == 1:
                                    st.error("Couldn't locate file row (or tried to delete header).")
                                else:
                                    files_ws.delete_rows(row_no)
                                    clear_cache()
                                    st.success("✅ File record removed successfully.")
                                    st.rerun()
                        except APIError:
                            st.error("Google API temporarily unavailable. Please try again later.")
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
                            clear_cache()
                            st.success("✅ Uploaded and logged successfully.")
                            st.write(f"[View File]({url})")
                            st.experimental_rerun()
                        else:
                            st.error("Upload or logging failed. Please try again.")
                    except Exception as e:
                        st.error(f"Upload failed: {e}")



    # =========================================================
    # Generate Report (collapsed, no auto-selection)
    # =========================================================
    with st.expander("🧾 Generate Report", expanded=False):
        creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
        client = gspread.authorize(creds)
        upload_log = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
        records = upload_log.get_all_records()

        if not records:
            st.info("📭 No uploaded files yet. Please upload at least one budget and one expense file.")
        else:
            df_files = pd.DataFrame(records)

            # budgets can be 'budget(opex)' or 'budget(capex)' (backward compat with plain 'budget')
            ft = df_files["file_type"].astype(str).str.lower()
            is_budget = ft.str.startswith("budget")
            budget_files = df_files[is_budget]
            expense_files = df_files[ft == "expense"]

            budget_options = ["— Select Budget File —"] + budget_files["file_name"].tolist()
            expense_options = ["— Select Expense File —"] + expense_files["file_name"].tolist()

            selected_budget = st.selectbox("📘 Budget File", budget_options, index=0)
            selected_expense = st.selectbox("💸 Expense File", expense_options, index=0)

            # Backward-compat type chooser for legacy 'budget' rows (only shown if needed)
            legacy_type_choice = None

            run_report = st.button("Generate Report")

            if run_report:
                if selected_budget == budget_options[0] or selected_expense == expense_options[0]:
                    st.error("Please select both a Budget and an Expense file.")
                    st.stop()

                # Resolve file URLs
                budget_row = budget_files[budget_files["file_name"] == selected_budget].iloc[0]
                expense_row = expense_files[expense_files["file_name"] == selected_expense].iloc[0]
                budget_url = budget_row["file_url"]
                expense_url = expense_row["file_url"]

                # Derive budget type from file_type, else prompt (OPEX/CAPEX)
                file_type_val = str(budget_row["file_type"]).lower()
                m = re.search(r"budget\((opex|capex)\)", file_type_val, flags=re.I)
                if m:
                    selected_budget_type = m.group(1).upper()  # 'OPEX' or 'CAPEX'
                else:
                    legacy_type_choice = st.selectbox(
                        "🏷️ This budget isn’t typed; choose how to treat expenses:",
                        ["OPEX", "CAPEX"], index=0
                    )
                    selected_budget_type = legacy_type_choice

                # --- Parse Budget (already USD)
                df_budget = process_budget(BytesIO(requests.get(budget_url).content))
                df_budget = df_budget[~df_budget["Sub-Category"].str.strip().str.lower().eq("total")]




                try:
                    df_expense = process_expenses(BytesIO(requests.get(expense_url).content))
                except Exception as e:
                    st.error(f"❌ Could not process Expenses file: {e}")
                    st.stop()

                # Normalize Classification and filter by selected budget type (OPEX/CAPEX)
                df_expense["Classification"] = df_expense["Classification"].astype(str).str.upper().str.strip()
                df_expense = df_expense[df_expense["Classification"] == selected_budget_type].copy()
                if df_expense.empty:
                    st.warning(f"No {selected_budget_type} expenses found for the selected files.")
                    st.stop()

                # ✅ Using CatLabel and Sub-Category directly from process_expenses
                df_expense = df_expense.copy()
                df_expense["Budget Category"] = df_expense["Category"]

                # ---- FX conversion (expenses only, to USD) ----
                try:
                    fx_rates = get_usd_rates()
                    provider = st.session_state.get("fx_provider", "unknown")
                    fetched = st.session_state.get("fx_fetched_at")
                    if fetched:
                        st.caption(f"FX provider: {provider} • fetched {fetched.strftime('%Y-%m-%d %H:%M:%S')}")
                except Exception as e:
                    st.error(f"Unable to fetch FX rates: {e}")
                    fx_rates = {}

                # Warn about unknown currencies (TTD, JMD, etc. all supported if code in rates)
                if isinstance(fx_rates, dict) and fx_rates:
                    known = set(fx_rates.keys())
                    expense_curs = set(df_expense["Currency"].dropna().astype(str).str.upper())
                    unknown_curs = sorted([c for c in expense_curs if c != "USD" and c not in known])
                    if unknown_curs:
                        st.warning(f"FX rate not found for: {', '.join(unknown_curs)} — those rows will show as NaN in USD.")

                # Convert amounts to USD ONLY if Currency != USD
                df_expense["Amount (USD)"] = df_expense.apply(
                    lambda r: convert_row_amount_to_usd(r, fx_rates, df_expense), axis=1
                )

                #st.markdown("""
                #### 📘 Variance Column Key
                #- <span style="background-color:#ff4d4d; padding:4px 10px; border-radius:4px; color:white;">Negative Variance</span> — Overspent  
                #- <span style="background-color:orange; padding:4px 10px; border-radius:4px; color:black;">Spent ≥ 70% of Budget</span> — Warning Zone  
                #- <span style="background-color:#4CAF50; padding:4px 10px; border-radius:4px; color:white;">Positive Variance</span> — Healthy / Under Budget  
                #""", unsafe_allow_html=True)

                #Generates interactive dashboard
                dashboard(df_budget=df_budget,
                          df_expense=df_expense,
                          selected_budget=selected_budget,
                          load_budget_state_monthly=load_budget_state_monthly,
                          save_budget_state_monthly=save_budget_state_monthly)

                # ===============================================================
                # Filters (Budget Category & Vendor)
                # ===============================================================
                st.markdown("Reports")
                with st.expander("📂 Filter by Categories"):
                    all_cats = sorted(df_expense["Budget Category"].dropna().unique().tolist())
                    select_all_cat = st.checkbox("Select All Categories", value=True, key="all_categories")
                    selected_categories = st.multiselect(
                        "Choose Categories", options=all_cats, default=all_cats if select_all_cat else []
                    )

                with st.expander("🏷️ Filter by Vendors"):
                    all_vendors = sorted(df_expense["Vendor"].dropna().unique().tolist())
                    select_all_ven = st.checkbox("Select All Vendors", value=True, key="all_vendors")
                    selected_vendors = st.multiselect(
                        "Choose Vendors", options=all_vendors, default=all_vendors if select_all_ven else []
                    )

                filtered_df = df_expense[
                    df_expense["Budget Category"].isin(selected_categories) &
                    df_expense["Vendor"].isin(selected_vendors)
                ].copy()

                # ===============================================================
                # Subcategory view (aggregated, no charts)
                # ===============================================================
                expenses_agg = (
                    filtered_df
                    .groupby(["Budget Category", "Sub-Category"], dropna=False, as_index=False)["Amount (USD)"]
                    .sum()
                )

                df_budget_for_merge = (
                    df_budget.rename(columns={"Category": "Budget Category"})[
                        ["Budget Category", "Sub-Category", "Total"]
                    ].drop_duplicates()
                )

                merged = expenses_agg.merge(
                    df_budget_for_merge,
                    how="left",
                    on=["Budget Category", "Sub-Category"]
                )

                final_view = merged.rename(columns={
                    "Budget Category": "Category",
                    "Total": "Amount Budgeted",
                    "Amount (USD)": "Amount Spent (USD)"
                }).copy()

                # Variance and rounding
                final_view["Variance (USD)"] = final_view["Amount Budgeted"].fillna(0) - final_view["Amount Spent (USD)"].fillna(0)
                for col in ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]:
                    final_view[col] = (final_view[col].astype(float).round(2)).fillna(0)
                final_view["Status"] = final_view.apply(
                lambda row: get_variance_status(
                    row["Amount Budgeted"],
                    row["Amount Spent (USD)"],
                    row["Variance (USD)"],
                ),
                axis=1
            )

                final_view = final_view[["Category", "Sub-Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)", "Status"]]
                final_view.sort_values(["Category", "Sub-Category"], inplace=True)

                # Show subcategory table (display "Out of Budget" where budget is NaN)
                def fmt_budget(x):
                    return "Out of Budget" if pd.isna(x) else f"{x:.2f}"

                with st.expander("📄 Expenditures (USD) — Subcategory", expanded=False):
                    #st.dataframe(
                    #    final_view.style
                    #        .format({"Amount Spent (USD)": "{:.2f}", "Variance (USD)": "{:.2f}"})
                    #        .format(fmt_budget, subset=["Amount Budgeted"]),
                    #    use_container_width=True
                    #)
                    styled_final = (
                        final_view.style
                            .apply(variance_color_style, axis=1)
                            .format({
                                "Amount Budgeted": "{:,.2f}",
                                "Amount Spent (USD)": "{:,.2f}",
                                "Variance (USD)": "{:,.2f}",
                            })
                    )
                    st.dataframe(styled_final, use_container_width=True)

                # ===============================================================
                # Category view (rolled-up, no charts)
                # ===============================================================
                # Budget per category = sum of subcategory totals
                budget_per_cat = (
                    df_budget.groupby("Category", as_index=False)["Total"].sum()
                    .rename(columns={"Total": "Amount Budgeted"})
                )

                # Spent per category = sum of expense USD by Budget Category
                spent_per_cat = (
                    filtered_df.groupby("Budget Category", as_index=False)["Amount (USD)"].sum()
                    .rename(columns={"Budget Category": "Category", "Amount (USD)": "Amount Spent (USD)"})
                )

                cat_view = budget_per_cat.merge(spent_per_cat, how="outer", on="Category")
                cat_view["Amount Budgeted"] = cat_view["Amount Budgeted"].fillna(0.0)
                cat_view["Amount Spent (USD)"] = cat_view["Amount Spent (USD)"].fillna(0.0)
                cat_view["Variance (USD)"] = cat_view["Amount Budgeted"] - cat_view["Amount Spent (USD)"]

                for col in ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]:
                    cat_view[col] = cat_view[col].astype(float).round(2)


                cat_view["Status"] = cat_view.apply(
                    lambda row: get_variance_status(
                        row["Amount Budgeted"],
                        row["Amount Spent (USD)"],
                        row["Variance (USD)"],
                    ),
                    axis=1
                )
                cat_view = cat_view[["Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)", "Status"]]
                cat_view.sort_values("Category", inplace=True)

                with st.expander("📊Expenditure Summary (USD) — Category", expanded=False):
                    #st.dataframe(
                    #    cat_view.style.format({
                    #        "Amount Budgeted": "{:.2f}",
                    #        "Amount Spent (USD)": "{:.2f}",
                    #        "Variance (USD)": "{:.2f}",
                    #    }),
                    #    use_container_width=True
                    #)
                    styled_cat = (
                        cat_view.style
                            .apply(variance_color_style, axis=1)
                            .format({
                                "Amount Budgeted": "{:,.2f}",
                                "Amount Spent (USD)": "{:,.2f}",
                                "Variance (USD)": "{:,.2f}",
                            })
                    )
                    st.dataframe(styled_cat, use_container_width=True)
                # ===============================================================
                # Full budget totals (overall summary)
                # ===============================================================
                full_view = final_view.copy()

                # Add category totals
                cat_totals = (
                    full_view.groupby("Category", as_index=False)[
                        ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]
                    ].sum()
                )
                cat_totals["Sub-Category"] = ""  # blank subcategory for totals

                # Mark totals for formatting
                cat_totals["is_total"] = True
                full_view["is_total"] = False

                # Combine totals + subcategories
                hierarchy_view = pd.concat([cat_totals, full_view], ignore_index=True)

                # Sort so totals appear first within each category
                hierarchy_view.sort_values(["Category", "is_total"], ascending=[True, False], inplace=True)

                # Display with formatting
                def fmt_budget(x):
                    return "Out of Budget" if pd.isna(x) else f"{x:,.2f}"

                # ===============================================================
                # Full Budget View (Category + Subcategories, including OOB)
                # ===============================================================

                # 1. Start with all budgeted subcategories (baseline structure)
                budget_full = (
                    df_budget.rename(columns={
                        "Category": "Category",
                        "Sub-Category": "Sub-Category",
                        "Total": "Amount Budgeted"
                    })[["Category", "Sub-Category", "Amount Budgeted"]].copy()
                )

                # Replace NaN budget values with 0
                budget_full["Amount Budgeted"] = pd.to_numeric(budget_full["Amount Budgeted"], errors="coerce").fillna(0)

                # 2. Aggregate expenses by Category/Subcategory
                expenses_agg = (
                    filtered_df.groupby(["Budget Category", "Sub-Category"], dropna=False, as_index=False)["Amount (USD)"]
                    .sum()
                    .rename(columns={"Budget Category": "Category", "Amount (USD)": "Amount Spent (USD)"})
                )

                # 3. Merge budget + expenses
                merged_full = budget_full.merge(
                    expenses_agg,
                    how="outer",
                    on=["Category", "Sub-Category"]
                )

                # 4. Compute variance
                merged_full["Amount Spent (USD)"] = merged_full["Amount Spent (USD)"].fillna(0)
                merged_full["Variance (USD)"] = merged_full["Amount Budgeted"] - merged_full["Amount Spent (USD)"]

                # 5. Identify Out-of-Budget (OOB) items
                budget_keys = set(budget_full.set_index(["Category", "Sub-Category"]).index)
                expense_keys = set(expenses_agg.set_index(["Category", "Sub-Category"]).index)

                # Subcategory pairs that exist in expenses but not in budget
                oob_keys = expense_keys - budget_keys

                # OOB items DataFrame
                if oob_keys:
                    oob_items = expenses_agg.set_index(["Category", "Sub-Category"]).loc[list(oob_keys)].reset_index()
                    oob_items["Category"] = "Out of Budget"        # force category override
                    oob_items["Amount Budgeted"] = 0.0
                    oob_items["Variance (USD)"] = -oob_items["Amount Spent (USD)"]
                    oob_items["is_oob"] = True              # ✅ NEW FLAG
                    merged_full = merged_full[~merged_full.set_index(["Category","Sub-Category"]).index.isin(oob_keys)]
                    merged_full = pd.concat([merged_full, oob_items], ignore_index=True)

                    # Remove them from merged_full if they leaked in with old category
                    merged_full = merged_full[~merged_full.set_index(["Category","Sub-Category"]).index.isin(oob_keys)]

                    # Add OOB rows back
                    merged_full = pd.concat([merged_full, oob_items], ignore_index=True)


                # 6. Category totals
                def total_budget(series):
                    # If category contains any OOB entries, set total budget = 0
                    if (series == "OOB").any():
                        return 0
                    return series.sum()

                cat_totals = (
                    merged_full.groupby("Category", as_index=False)
                    .agg({
                        "Amount Budgeted": total_budget,
                        "Amount Spent (USD)": "sum",
                        "Variance (USD)": "sum"
                    })
                )
                cat_totals["Sub-Category"] = ""
                cat_totals["is_total"] = True
                merged_full["is_total"] = False

                # 7. Combine totals + details
                hierarchy_view = pd.concat([cat_totals, merged_full], ignore_index=True)

                # Sort so totals come first, subcategories after, OOB last
                hierarchy_view["sort_key"] = hierarchy_view.apply(
                    lambda r: (1 if r["Category"] == "Out of Budget" else 0, 0 if r.get("is_total") else 1, str(r["Sub-Category"])),
                    axis=1
                )
                hierarchy_view.sort_values(["sort_key"], inplace=True)
                hierarchy_view.drop(columns=["sort_key"], inplace=True)

                # 8. Formatting helper
                def fmt_budget(val):
                    if isinstance(val, (int, float)) and val == 0:
                        return "OOB"
                    try:
                        return f"{val:,.2f}"
                    except Exception:
                        return val

                # 9. Display in Streamlit
                with st.expander("📘 Full Budget View (USD) — Category + Subcategories", expanded=False):
                    df_display = hierarchy_view.copy()

                    # ---- Sort categories in budget order, OOB last ----
                    budget_order = df_budget["Category"].drop_duplicates().tolist()
                    df_display["Category"] = pd.Categorical(
                        df_display["Category"],
                        categories=budget_order + ["Out of Budget"],
                        ordered=True
                    )
                    df_display.sort_values(["Category", "Sub-Category"], inplace=True)

                    #Adding indentation to subcategory items.
                    INDENT = "\u2003\u2003\u2003" 

                    # ---- Add arrow prefix to subcategories (not totals) ----
                    df_display.loc[df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""), "Sub-Category"] = (
                        INDENT + "→ " + df_display.loc[df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""), "Sub-Category"].astype(str)
                    )

                    # ---- Reset index so no row numbers show ----
                    df_display.reset_index(drop=True, inplace=True)

                    df_display["Status"] = df_display.apply(
                        lambda row: get_variance_status(
                            row["Amount Budgeted"],
                            row["Amount Spent (USD)"],
                            row["Variance (USD)"],
                        ),
                        axis=1
                    )


                    # ---- Columns to show ----
                    display_cols = ["Category", "Sub-Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)", "Status"]

                    #st.markdown("""
                    # 📘 Variance Column Key
                    #- <span style="background-color:#ff4d4d; padding:4px 10px; border-radius:4px; color:white;">Negative Variance</span> — Overspent  
                    #- <span style="background-color:orange; padding:4px 10px; border-radius:4px; color:black;">Spent ≥ 70% of Budget</span> — Warning Zone  
                    #- <span style="background-color:#4CAF50; padding:4px 10px; border-radius:4px; color:white;">Positive Variance</span> — Healthy / Under Budget  
                    #""", unsafe_allow_html=True)

                   


                    # ---- Style: bold category total rows (where Sub-Category is blank) ----
                    st.dataframe(
                        df_display[display_cols].style
                            .apply(lambda row: ["font-weight: bold" if not row["Sub-Category"] or row["Sub-Category"] == "→ " else "" for _ in row], axis=1)
                            .apply(variance_color_style,axis=1)
                            .format({
                                "Amount Budgeted": lambda v, is_oob=None: "OOB" if is_oob else f"{v:,.2f}",
                                "Amount Spent (USD)": "{:,.2f}",
                                "Variance (USD)": "{:,.2f}",
                            }),
                        use_container_width=True
                    )

                   

