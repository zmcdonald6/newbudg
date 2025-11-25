import streamlit as st
import requests

def get_client_ip():
    """Retrieves the IP address of the user accessing the Streamlit app."""
    try:
        # Check if the runtime client is available and has an IP address
        if st.runtime.client.ip:
            return st.runtime.client.ip
        else:
            return "IP Address Not Found"
    except Exception as e:
        # Fallback for older Streamlit versions or specific environments
        return f"Error accessing IP: {e}"

# Display the IP address in your Streamlit app
ip_address = get_ip_address()
st.title("User IP Address Tracker")
st.info(f"The IP address of the current user is: **{ip_address}**")