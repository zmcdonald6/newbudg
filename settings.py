import os, json
import streamlit as st
from google.oauth2 import service_account

def _get_secret(key, default=None):
    try:
        return st.secrets[key]
    except Exception:
        return default

def _from_env_json(var_name):
    v = os.getenv(var_name)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None

def _from_env_file(var_name):
    path = os.getenv(var_name)
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

SHEET_ID = _get_secret("SHEET_ID") or os.getenv("SHEET_ID")
PARENT_FOLDER_ID = _get_secret("PARENT_FOLDER_ID") or os.getenv("PARENT_FOLDER_ID")

_GOOGLE = (
    _get_secret("GOOGLE")
    or _from_env_json("GOOGLE_SERVICE_ACCOUNT_JSON")
    or _from_env_file("GOOGLE_SERVICE_ACCOUNT_FILE")
)

def google_credentials(scopes):
    if not _GOOGLE:
        raise RuntimeError(
            "Google credentials not found. Provide st.secrets['GOOGLE'] or env "
            "GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE."
        )
    return service_account.Credentials.from_service_account_info(dict(_GOOGLE), scopes=scopes)
