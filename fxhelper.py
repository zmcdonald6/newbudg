import pandas as pd
import numpy as np
import requests
import streamlit as st
from datetime import datetime, timedelta

"""
Contains Helper functions that assist in Converting expense amounts into USD.
"""

FX_TTL_MINUTES = 60  # cache FX for an hour

# -------- internal helpers --------

def _validate_usd_base(rates: dict) -> bool:
    if not isinstance(rates, dict):
        return False
    if "USD" not in rates:
        return False
    try:
        return abs(float(rates["USD"]) - 1.0) < 1e-6
    except Exception:
        return False

def _fetch_exchangerate_host() -> tuple[dict, str]:
    """
    Fetches the latest exchange rates using the exchangerate.host API, USD as the base currency
    
    :return: It returns a dictionary of exchange with their currency codes along with a string stating where the values were fetched from.
    :rtype: tuple[rates, "exchangerate.host"]
    """
    resp = requests.get(
        "https://api.exchangerate.host/latest",
        params={"base": "USD"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    rates = data.get("rates", {})
    if not _validate_usd_base(rates):
        raise RuntimeError("exchangerate.host returned invalid USD base rates")
    return rates, "exchangerate.host"

def _fetch_er_api() -> tuple[dict, str]:
    resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise RuntimeError(f"open.er-api result={data.get('result')}")
    rates = data.get("rates", {})
    if not _validate_usd_base(rates):
        raise RuntimeError("open.er-api returned invalid USD base rates")
    return rates, "open.er-api.com"

# -------- public API --------

def get_usd_rates():
    """
    :rtype: dict
    :Return: dict: {'USD': 1.0, 'JMD': 155.2, 'TTD': 6.78, 'EUR': 0.92, ...}
    meaning 1 USD = X units of that currency.
    Uses session cache, multi-provider fallback, and last-known-good rescue.
    """
    now = datetime.now()
    
    cached_ts = st.session_state.get("fx_fetched_at")
    if isinstance(cached_ts, str):
        try:
            cached_ts = datetime.fromisoformat(cached_ts)
        except Exception:
            cached_ts = None

    if "fx_rates" in st.session_state and cached_ts:
        if now - cached_ts < timedelta(minutes=FX_TTL_MINUTES):
            return st.session_state.fx_rates
    if "fx_rates" in st.session_state and "fx_fetched_at" in st.session_state:
        if now - st.session_state.fx_fetched_at < timedelta(minutes=FX_TTL_MINUTES):
            return st.session_state.fx_rates

    last_error = None
    for fetcher in (_fetch_exchangerate_host, _fetch_er_api):
        try:
            rates, provider = fetcher()
            st.session_state.fx_rates = rates
            st.session_state.fx_fetched_at = now
            st.session_state.fx_provider = provider
            return rates
        except Exception as e:
            last_error = e
            continue

    if "fx_rates" in st.session_state and isinstance(st.session_state.fx_rates, dict):
        st.warning("Using last known FX rates (providers unavailable).")
        return st.session_state.fx_rates

    raise RuntimeError(f"All FX providers failed: {last_error}")

def detect_currency_from_row(row: pd.Series, df_expense: pd.DataFrame) -> str | None:
    col = "Currency"
    if col in df_expense.columns and pd.notna(row.get(col)):
        return str(row[col]).strip().upper()
    return None

def parse_amount_to_number(a) -> float:
    """
    Cleans up data to return a docstring
    """
    #cleaning up data to get plain numbers to convert
    if pd.isna(a):
        return np.nan
    s = str(a).strip()
    s = s.replace("$", "")         # <-- strip stray dollar signs
    s = s.replace(",", "")         # remove thousand separators
    s = s.strip()
    try:
        return float(s)
    except Exception:
        return np.nan


def convert_row_amount_to_usd(row: pd.Series, rates: dict, df_expense: pd.DataFrame) -> float:
    """
    Convert native amount to USD using USD-base table:
      amount_usd = amount_native / rates[currency_code]
    Only converts if Currency is present and != 'USD'.
    """
    amt_native = parse_amount_to_number(row.get("Amount"))
    cur = detect_currency_from_row(row, df_expense)
    if pd.isna(amt_native) or not cur:
        return np.nan
    cur = cur.upper()
    if cur == "USD":
        return amt_native
    if cur not in rates or not rates[cur]:
        return np.nan
    return amt_native / float(rates[cur])
