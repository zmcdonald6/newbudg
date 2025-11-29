import time
import streamlit as st
import streamlit.components.v1 as components
import bcrypt
import base64
import os
from datetime import datetime, timedelta

from streamlit_cookies_manager import EncryptedCookieManager

from functions.db import (
    get_user_by_email,
    update_password,
    log_login_activity,
    get_ip
)

if "client_id" not in st.session_state:
    st.session_state.client_id = base64.b64encode(os.urandom(32)).decode()
    

# ============================================================
# COOKIE MANAGER (using secrets)
# ============================================================
cookies = EncryptedCookieManager(
    prefix=st.secrets["cookies"]["prefix"],
    password=st.secrets["cookies"]["password"],
    key = st.session_state.client_id
)

# EncryptedCookieManager must be ready before using cookies
if not cookies.ready():
    st.stop()

COOKIE_NAME = st.secrets["cookies"]["name"]
COOKIE_LIFETIME_SECONDS = 24 * 3600  # 1 day (requested)


# ============================================================
# INITIALIZE SESSION STATE
# ============================================================
def init_auth_session():
    defaults = {
        "authenticated": False,
        "email": "",
        "name": "",
        "user_record": {},
        "force_pw_change": False,
        "last_active": datetime.now(),
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ============================================================
# COOKIE → AUTO LOGIN (WITH 1-DAY EXPIRY)
# ============================================================
def cookie_auto_login():
    if COOKIE_NAME not in cookies:
        return

    raw_value = cookies[COOKIE_NAME]  # stored as: email|timestamp

    # Parse the cookie
    try:
        email, ts = raw_value.split("|")
        ts = int(ts)
    except:
        # Bad cookie → delete it
        del cookies[COOKIE_NAME]
        cookies.save()
        return

    # Check 1-day expiration
    if time.time() - ts > COOKIE_LIFETIME_SECONDS:
        del cookies[COOKIE_NAME]
        cookies.save()
        return

    # Restore user data
    user = get_user_by_email(email)
    if user:
        st.session_state.authenticated = True
        st.session_state.email = email
        st.session_state.name = user["name"]
        st.session_state.user_record = user
        st.session_state.force_pw_change = False
        st.session_state.last_active = datetime.now()


# ============================================================
# INACTIVITY TIMEOUT (separate from cookie expiration)
# ============================================================
INACTIVITY_MINUTES = 10

def inactivity_timeout():
    if st.session_state.authenticated:
        elapsed = datetime.now() - st.session_state.last_active
        if elapsed > timedelta(minutes=INACTIVITY_MINUTES):
            st.warning("⏱ Session timed out due to inactivity.")
            ip = get_ip()
            log_login_activity(st.session_state.email, "Auto Logout (Inactivity)", ip)
            logout_user()
            st.rerun()
        else:
            st.session_state.last_active = datetime.now()


# ============================================================
# LOGOUT LOGIC (CLEARS COOKIE + SESSION)
# ============================================================
def logout_user():
    # Clear session
    st.session_state.authenticated = False
    st.session_state.email = ""
    st.session_state.name = ""
    st.session_state.user_record = {}
    st.session_state.force_pw_change = False

    # Clear persistent cookie
    if COOKIE_NAME in cookies:
        del cookies[COOKIE_NAME]
        cookies.save()


# ============================================================
# LOGIN SCREEN
# ============================================================
def render_login_screen():
    st.header("🔐 Login")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")

        if submit:
            user = get_user_by_email(email)

            if not user:
                st.error("❌ Email not found.")
                return

            # Check password
            try:
                decoded = base64.b64decode(user["hashed_password"])
            except:
                st.error("❌ Corrupted stored password.")
                return

            if not bcrypt.checkpw(password.encode(), decoded):
                st.error("❌ Incorrect password.")
                return

            # Success → set session state
            st.session_state.authenticated = True
            st.session_state.email = email
            st.session_state.name = user["name"]
            st.session_state.user_record = user
            st.session_state.last_active = datetime.now()

            # First login → force password change
            if user.get("first_login", False):
                st.session_state.force_pw_change = True
                st.rerun()

            # Save persistent cookie with timestamp
            token_value = f"{email}|{int(time.time())}"
            cookies[COOKIE_NAME] = token_value
            cookies.save()

            st.rerun()


# ============================================================
# FIRST LOGIN → PASSWORD RESET
# ============================================================
def render_first_login_reset():
    st.title("🔑 Reset Password")

    with st.form("reset_form"):
        pw1 = st.text_input("New Password", type="password")
        pw2 = st.text_input("Confirm New Password", type="password")
        submit = st.form_submit_button("Update Password")

        if submit:
            if len(pw1) < 8:
                st.error("Password must be at least 8 characters.")
                return
            if pw1 != pw2:
                st.error("Passwords do not match.")
                return

            # Hash the new password
            new_hash = bcrypt.hashpw(pw1.encode(), bcrypt.gensalt())
            encoded = base64.b64encode(new_hash).decode()

            update_password(st.session_state.email, encoded)

            # Update session state
            st.session_state.user_record["first_login"] = False
            st.session_state.user_record["hashed_password"] = encoded
            st.session_state.force_pw_change = False

            # Renew cookie (timestamp resets)
            token_value = f"{st.session_state.email}|{int(time.time())}"
            cookies[COOKIE_NAME] = token_value
            cookies.save()

            st.success("Password updated successfully.")
            st.rerun()


# ============================================================
# MAIN AUTH FLOW ENTRY POINT
# ============================================================
def auth_flow():
    init_auth_session()
    cookie_auto_login()
    inactivity_timeout()
    if COOKIE_NAME in cookies and not st.session_state.get("just_logged_in", False):
        st.session_state.just_logged_in = True
        st.success(f"👋 Welcome back, {st.session_state.name}!")
    # Not logged in
    if not st.session_state.authenticated and not st.session_state.force_pw_change:
        render_login_screen()
        return False

    # User must reset password
    if st.session_state.force_pw_change:
        render_first_login_reset()
        return False

    # Logged in → show logout button
    if st.button("🚪 Logout"):
        ip = get_ip()
        log_login_activity(st.session_state.email, "Logout", ip)
        logout_user()
        st.rerun()

    return True
