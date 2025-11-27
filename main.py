import streamlit as st
import bcrypt
import base64

import requests

from functions.auth import auth_flow
from functions.db import *
from functions.drive_utils import upload_to_drive_and_log
from analysis import process_budget, process_expenses
from fxhelper import get_usd_rates, convert_row_amount_to_usd
from functions.dashboard_classification import dashboard
from functions.report_generator import render_generate_report_section

#Seeding a default admin user if the application has no users at startup.
seed_admin_user()
# Constants
INACTIVITY_LIMIT_MINUTES = 10

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
def variance_colour_style(row):
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



#Authentication Screen(Login)
if not auth_flow():
    st.stop()

# Main dashboard
st.title("MSGIT Budget Reporter")
# === Templates download (Budget & Expenses) ===

ip = get_ip()
log_login_activity(st.session_state.email, "Login", ip)

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
                
                            delete_user(sel_email)
                            st.success("✅ User removed.")
                            st.rerun()
                        
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
                        st.rerun()
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
    variance_colour_style=variance_colour_style,
    get_variance_status=get_variance_status    
)

                

