"""Simple authentication for Streamlit dashboard."""

import hmac
import os

import streamlit as st


def check_password():
    """Returns True if the user has the correct credentials.

    Credentials are read from environment variables:
      DASHBOARD_USER
      DASHBOARD_PASSWORD
    """

    if st.session_state.get("authenticated"):
        return True

    # ── Login form ──

    st.markdown("""<style>
    .block-container { max-width: 420px; padding-top: 12vh; }
    </style>""", unsafe_allow_html=True)

    st.markdown("### Fermato Creative Intelligence")
    st.caption("Prihlaste se pro pristup k dashboardu")

    with st.form("login"):
        username = st.text_input("Uzivatel")
        password = st.text_input("Heslo", type="password")
        submitted = st.form_submit_button("Prihlasit se", use_container_width=True, type="primary")

    if submitted:
        expected_user = os.environ.get("DASHBOARD_USER")
        expected_pass = os.environ.get("DASHBOARD_PASSWORD")
        if not expected_user or not expected_pass:
            st.error("Server chyba: prihlasovaci udaje nejsou nastaveny")
            return False
        if (
            hmac.compare_digest(username, expected_user)
            and hmac.compare_digest(password, expected_pass)
        ):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Nespravne prihlasovaci udaje")

    return False
