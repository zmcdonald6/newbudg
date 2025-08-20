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
from analysis import process_budget
from fxhelper import get_usd_rates, convert_row_amount_to_usd

# Constants

INACTIVITY_LIMIT_MINUTES = 10
SHEET_ID = "1VxrFw6txf_XFf0cxzMbPGHnOn8N5JGeeS0ve5lfLqCU"
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# ========= Cached Google Sheets helpers =========
@st.cache_resource
def get_gs_client():
    creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
    return gspread.authorize(creds)

@st.cache_data(ttl=60)  # cache read data for 60 seconds
def ws_records(sheet_name: str):
    client = get_gs_client()
    ws = client.open_by_key(SHEET_ID).worksheet(sheet_name)
    return ws.get_all_records()

def clear_sheet_cache():
    ws_records.clear()
    get_user_credentials.clear()
# ================================================

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
                    clear_sheet_cache()
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to update password: {e}")

# Main dashboard
elif st.session_state.authenticated:
    st.title("MSGIT Budget Reporter")
    log_activity(st.session_state.email, "Login")

    if st.button("🚪 Logout"):
        log_activity(st.session_state.email, "Logout")
        for key in list(st.session_state.keys()):
            st.session_state[key] = False if key == "authenticated" else ""
        st.rerun()

    st.success(f"✅ Logged in as {st.session_state.name}")
    st.caption(f"Role: {st.session_state.user_record.get('role','user')}")
    # --- Admin panel skeleton (structure only) ---
    _is_admin = str(st.session_state.user_record.get("role", "user")).strip().lower() == "admin"
    if _is_admin:
        st.subheader("Admin Panel")

        #CRUD on Users
        with st.expander("User Management", expanded=False):
            st.caption("Data cached for 60s to prevent API 429s.")
            if st.button("🔄 Refresh Users", key="refresh_users"): clear_sheet_cache(); st.rerun()
            # --- Sheets setup (local to this expander) ---
            try:
                creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
                client = gspread.authorize(creds)
                users_ws = client.open_by_key(SHEET_ID).worksheet("Users")
            except Exception as e:
                st.error(f"Couldn't open Users sheet: {e}")
                st.stop()

            # --- Load & show users ---
            rows = ws_records('Users')
            df_users = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["name","username","email","hashed_password","role","first_login"]
            )
            st.dataframe(df_users, use_container_width=True)

            st.divider()
            st.subheader("Add New User")
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
                    elif any(str(r.get("email","")).strip().lower() == new_email.strip().lower() for r in rows):
                        st.error("A user with that email already exists.")
                    else:
                        try:
                            hashed = bcrypt.hashpw(new_password_plain.encode(), bcrypt.gensalt())
                            encoded = base64.b64encode(hashed).decode()
                            # Force password change on first login by default
                            users_ws.append_row([
                                new_name, new_username, new_email, encoded, new_role, "TRUE"
                            ])
                            st.success("User added. They will be required to change password on first login.")
                            get_user_credentials.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to add user: {e}")

            st.divider()
            st.subheader("Reset Password / Remove User")

            emails = [r.get("email","") for r in rows]
            if not emails:
                st.info("No users found.")
            else:
                sel_email = st.selectbox("Select user by email", emails)

                # helper: exact-match row by email (no substring false-positives)
                def _find_row_by_email(ws, email: str) -> int | None:
                    header = ws.row_values(1)
                    if "email" not in header:
                        return None
                    email_col = header.index("email") + 1
                    col_vals = ws.col_values(email_col)
                    for i, v in enumerate(col_vals, start=1):
                        if str(v).strip().lower() == email.strip().lower():
                            return i
                    return None

                with st.form("admin_reset_remove_form"):
                    new_pw_plain = st.text_input("New Password", type="password")
                    col1, col2 = st.columns(2)
                    do_reset = col1.form_submit_button("🔑 Reset Password")
                    confirm = col2.checkbox("Yes, delete this user")
                    do_delete = col2.form_submit_button("🗑️ Remove User")

                    if do_reset:
                        if not new_pw_plain:
                            st.error("Enter a new password.")
                        else:
                            try:
                                row_no = _find_row_by_email(users_ws, sel_email)
                                if not row_no:
                                    st.error("Couldn't locate user row.")
                                else:
                                    header = users_ws.row_values(1)
                                    row_vals = users_ws.row_values(row_no)
                                    # Pad to header length
                                    while len(row_vals) < len(header):
                                        row_vals.append("")
                                    # Map header -> index
                                    h2i = {h: i for i, h in enumerate(header)}

                                    # Set new password + force first_login to TRUE
                                    new_h = bcrypt.hashpw(new_pw_plain.encode(), bcrypt.gensalt())
                                    row_vals[h2i["hashed_password"]] = base64.b64encode(new_h).decode()
                                    row_vals[h2i["first_login"]] = "TRUE"

                                    # Compute range like A{row}:<end>{row}
                                    def _col_letters(n: int) -> str:
                                        s = ""
                                        while n > 0:
                                            n, r = divmod(n - 1, 26)
                                            s = chr(65 + r) + s
                                        return s
                                    end_col_letter = _col_letters(len(header))

                                    users_ws.update(f"A{row_no}:{end_col_letter}{row_no}", [row_vals])
                                    st.success("Password reset. User will be forced to change it on next login.")
                                    get_user_credentials.clear()
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Failed to reset password: {e}")

                    if do_delete:
                        if not confirm:
                            st.error("Please check “Yes, delete this user” to confirm.")
                        else:
                            try:
                                row_no = _find_row_by_email(users_ws, sel_email)
                                if not row_no or row_no == 1:
                                    st.error("Couldn't locate user row (or tried to delete the header).")
                                else:
                                    users_ws.delete_rows(row_no)
                                    st.success("User removed.")
                                    get_user_credentials.clear()
                                    st.rerun()
                            except Exception as e:
                                st.error(f"Failed to remove user: {e}")
        # To View Logins
        with st.expander("Login Activity", expanded=False):
            st.caption("Data cached for 60s to prevent API 429s.")
            if st.button("🔄 Refresh Logs", key="refresh_logs"): clear_sheet_cache(); st.rerun()
            # Sheets setup
            try:
                creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
                client = gspread.authorize(creds)
                logs_ws = client.open_by_key(SHEET_ID).worksheet("LoginLogs")
            except Exception as e:
                st.error(f"Couldn't open LoginLogs sheet: {e}")
                st.stop()

            # Load logs (view-only)
            rows = ws_records('LoginLogs')  # expected columns: email, activity_type, timestamp, ip_address
            df_logs = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["email", "activity_type", "timestamp", "ip_address"]
            )

            # Sort newest first if timestamp exists
            # --- Filters (Email + Date Range) ---
            if df_logs.empty:
                st.dataframe(df_logs, use_container_width=True)
            else:
                # Ensure timestamp is datetime (already done above, but guard anyway)
                if "timestamp" in df_logs.columns and not pd.api.types.is_datetime64_any_dtype(df_logs["timestamp"]):
                    df_logs["timestamp"] = pd.to_datetime(df_logs["timestamp"], errors="coerce")

                # Email filter
                if "email" in df_logs.columns:
                    email_options = sorted(df_logs["email"].dropna().astype(str).unique().tolist())
                    selected_emails = st.multiselect(
                        "Filter by email", options=email_options, default=email_options
                    )
                else:
                    selected_emails = None

                # Date range filter (only if we have timestamps)
                if "timestamp" in df_logs.columns:
                    ts_nonnull = df_logs["timestamp"].dropna()
                    if not ts_nonnull.empty:
                        default_start = ts_nonnull.min().date()
                        default_end   = ts_nonnull.max().date()
                        start_date, end_date = st.date_input(
                            "Filter by date range",
                            value=(default_start, default_end),
                            min_value=default_start,
                            max_value=default_end
                        )
                    else:
                        start_date = end_date = None
                else:
                    start_date = end_date = None

                # Apply filters
                filtered = df_logs.copy()

                if selected_emails is not None and len(selected_emails) != len(email_options):
                    filtered = filtered[filtered["email"].isin(selected_emails)]

                if start_date and end_date and "timestamp" in filtered.columns:
                    mask = filtered["timestamp"].dt.date.between(start_date, end_date)
                    filtered = filtered[mask]

                st.dataframe(filtered, use_container_width=True)

        #CRUD on Files
        with st.expander("File Management", expanded=False):
            st.caption("Data cached for 60s to prevent API 429s.")
            if st.button("🔄 Refresh Files", key="refresh_files"): clear_sheet_cache(); st.rerun()
             # Sheets setup
            try:
                creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
                client = gspread.authorize(creds)
                files_ws = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
            except Exception as e:
                st.error(f"Couldn't open UploadedFiles sheet: {e}")
                st.stop()

            # --- View files ---
            rows = ws_records('UploadedFiles')  # expects headers: file_name, file_type, uploader_email, timestamp, file_url
            df_files = pd.DataFrame(rows) if rows else pd.DataFrame(
                columns=["file_name", "file_type", "uploader_email", "timestamp", "file_url"]
            )
            st.dataframe(df_files, use_container_width=True)

            st.divider()

            # --- Add (upload) a new file ---
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
                        url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email, custom_name)
                        if url:
                            st.success("✅ Uploaded and logged successfully.")
                            st.write(f"[View File]({url})")
                            clear_sheet_cache()
                            st.rerun()
                        else:
                            st.error("Upload or logging failed.")

            st.divider()

            # --- Delete a file record (sheet only) ---
            st.subheader("Delete File Record")
            if df_files.empty:
                st.info("No uploaded files found.")
            else:
                to_delete = st.selectbox("Select a file to delete (record only)", df_files["file_name"].tolist(), key="admin_file_to_delete")
                # Show a little context
                try:
                    sel_row = df_files[df_files["file_name"] == to_delete].iloc[0]
                    st.caption(f"Type: {sel_row.get('file_type','?')} • Uploaded by: {sel_row.get('uploader_email','?')} • At: {sel_row.get('timestamp','?')}")
                except Exception:
                    pass

                confirm = st.checkbox("Yes, delete this record")
                delete_clicked = st.button("🗑️ Delete File Record")

                if delete_clicked:
                    if not confirm:
                        st.error("Please check “Yes, delete this record” to confirm.")
                    else:
                        try:
                            # Exact-match by file_name (header-agnostic)
                            header = [str(h).strip().lower() for h in files_ws.row_values(1)]
                            if "file_name" not in header:
                                st.error("Header 'file_name' not found in UploadedFiles.")
                            else:
                                col_idx = header.index("file_name") + 1
                                names = files_ws.col_values(col_idx)
                                row_no = next((i for i, v in enumerate(names, start=1) if str(v).strip() == str(to_delete).strip()), None)

                                if not row_no or row_no == 1:
                                    st.error("Couldn't locate file row (or tried to delete the header).")
                                else:
                                    files_ws.delete_rows(row_no)  # remove the log record
                                    st.success("File record removed.")
                                    clear_sheet_cache()
                                    st.rerun()
                        except Exception as e:
                            st.error(f"Failed to delete file record: {e}")
        #Report Generator
        #with st.expander("Report Generation", expanded=False):
        #st.info("Admins can generate reports here, or use the general 'Generate Report' section below. (Coming soon)")
    # =========================================================
    # Upload interface (collapsed)
    # =========================================================
    with st.expander("⬆Upload File (Budget or Expense)", expanded=False):
        with st.form("upload_form"):
            uploaded_file = st.file_uploader("Choose a file", type=["xlsx"])
            custom_name = st.text_input("Enter file name (REQUIRED)")
            file_type = st.selectbox("Type of file", ["budget(opex)", "budget(capex)", "expense"])
            submit_upload = st.form_submit_button("Upload File")

            if submit_upload and uploaded_file:
                if not custom_name.strip():
                    st.error("Please enter a file name")
                else:
                    url = upload_to_drive_and_log(uploaded_file, file_type, st.session_state.email, custom_name)
                    if url:
                        st.success("✅ Uploaded and logged successfully.")
                        st.write(f"[View File]({url})")
                        clear_sheet_cache()

    # =========================================================
    # Generate Report (collapsed, no auto-selection)
    # =========================================================
    with st.expander("🧾 Generate Report", expanded=False):
        st.caption("Data cached for 60s to prevent API 429s.")
        if st.button("🔄 Refresh Reports", key="refresh_reports"): clear_sheet_cache(); st.rerun()
        creds = service_account.Credentials.from_service_account_info(dict(st.secrets["GOOGLE"]), scopes=SCOPE)
        client = gspread.authorize(creds)
        upload_log = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
        records = ws_records('UploadedFiles')

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

                # --- Load Expense & Normalize
                df_expense_raw = pd.read_excel(BytesIO(requests.get(expense_url).content))

                # Normalize column names (include Classification)
                col_map = {
                    "date": "Invoice Date", "invoice date": "Invoice Date",
                    "vendorname": "Vendor", "vendor": "Vendor",
                    "subcategory": "Sub-Category", "sub-category": "Sub-Category",
                    "category": "Category",
                    "amount": "Amount", "cost": "Amount", "totalcost": "Amount",
                    "currency": "Currency",
                    "classification": "Classification"
                }
                df_expense = df_expense_raw.rename(columns=lambda x: col_map.get(str(x).strip().lower(), str(x).strip())).copy()

                # Validate required columns (Classification required for CAPEX/OPEX)
                required = ["Category", "Sub-Category", "Invoice Date", "Vendor", "Amount", "Currency", "Classification"]
                missing = [c for c in required if c not in df_expense.columns]
                if missing:
                    st.error(f"❌ Expense sheet is missing required columns: {', '.join(missing)}")
                    st.stop()

                # Normalize Classification and filter by selected budget type (OPEX/CAPEX)
                df_expense["Classification"] = df_expense["Classification"].astype(str).str.upper().str.strip()
                df_expense = df_expense[df_expense["Classification"] == selected_budget_type].copy()
                if df_expense.empty:
                    st.warning(f"No {selected_budget_type} expenses found for the selected files.")
                    st.stop()

                # Extract label + clean subcategory (label-driven match)
                def extract_label(text):
                    if pd.isna(text): return None
                    m2 = re.match(r"\s*([A-Za-z0-9])\)\s*", str(text))
                    return m2.group(1).upper() if m2 else None

                def clean_subcategory(text):
                    if pd.isna(text): return text
                    t = re.sub(r"^\s*[A-Za-z0-9]+\)\s*", "", str(text).strip())   # remove 'A) '
                    parts = [p.strip() for p in t.split("***")]                    # keep last *** chunk
                    return parts[-1] if parts else t

                df_expense["CatLabel"] = df_expense["Sub-Category"].apply(extract_label)
                df_expense["Sub-Category"] = df_expense["Sub-Category"].apply(clean_subcategory)

                # Map CatLabel -> Budget Category
                label_map = (
                    df_budget[["CatLabel","Category"]]
                    .drop_duplicates()
                    .set_index("CatLabel")["Category"]
                    .to_dict()
                )
                df_expense["Budget Category"] = df_expense["CatLabel"].map(label_map)

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
                    final_view[col] = final_view[col].astype(float).round(2)

                final_view = final_view[["Category", "Sub-Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]]
                final_view.sort_values(["Category", "Sub-Category"], inplace=True)

                # Show subcategory table (display "Out of Budget" where budget is NaN)
                def fmt_budget(x):
                    return "Out of Budget" if pd.isna(x) else f"{x:.2f}"

                with st.expander("📄 Expenditures (USD) — Subcategory", expanded=False):
                    st.dataframe(
                        final_view.style
                            .format({"Amount Spent (USD)": "{:.2f}", "Variance (USD)": "{:.2f}"})
                            .format(fmt_budget, subset=["Amount Budgeted"]),
                        use_container_width=True
                    )

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

                cat_view = cat_view[["Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]]
                cat_view.sort_values("Category", inplace=True)

                with st.expander("📊Expenditure Summary (USD) — Category", expanded=False):
                    st.dataframe(
                        cat_view.style.format({
                            "Amount Budgeted": "{:.2f}",
                            "Amount Spent (USD)": "{:.2f}",
                            "Variance (USD)": "{:.2f}",
                        }),
                        use_container_width=True
                    )

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
                    oob_items["Amount Budgeted"] = "OOB"
                    oob_items["Variance (USD)"] = -oob_items["Amount Spent (USD)"]

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
                    if isinstance(val, str) and val == "OOB":
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

                    # ---- Add arrow prefix to subcategories (not totals) ----
                    df_display.loc[df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""), "Sub-Category"] = (
                        "→ " + df_display.loc[df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""), "Sub-Category"].astype(str)
                    )

                    # ---- Reset index so no row numbers show ----
                    df_display.reset_index(drop=True, inplace=True)

                    # ---- Columns to show ----
                    display_cols = ["Category", "Sub-Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]

                    # ---- Style: bold category total rows (where Sub-Category is blank) ----
                    st.dataframe(
                        df_display[display_cols].style
                            .apply(lambda row: ["font-weight: bold" if not row["Sub-Category"] or row["Sub-Category"] == "→ " else "" for _ in row], axis=1)
                            .format({
                                "Amount Budgeted": fmt_budget,
                                "Amount Spent (USD)": "{:,.2f}",
                                "Variance (USD)": "{:,.2f}",
                            }),
                        use_container_width=True
                    )
