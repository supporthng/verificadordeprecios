import html
import time
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Consulta de precios",
    page_icon="🏷️",
    layout="centered",
    initial_sidebar_state="collapsed",
)

SUPABASE_URL = str(st.secrets.get("SUPABASE_URL", "")).strip().rstrip("/")
SUPABASE_ANON_KEY = str(st.secrets.get("SUPABASE_ANON_KEY", "")).strip()

st.markdown("""
<style>
.stApp { background: #f4f7fc; }
.block-container {
    max-width: 1000px;
    padding: 1.2rem 1rem 2rem;
}
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    color: white;
    border-radius: 18px;
    padding: clamp(14px, 3vh, 30px) 16px;
    text-align: center;
    margin-bottom: 14px;
}
.main-header h1 {
    color: white !important;
    margin: 0;
    font-size: clamp(22px, 4vw, 39px);
}
.main-header p { color: #e2efff; margin: 5px 0 0; font-size: clamp(12px, 2vw, 17px); }
.scan-title {
    text-align: center;
    font-weight: 850;
    color: #102b50;
    font-size: clamp(19px, 3.5vw, 32px);
    margin: 12px 0;
}
div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: clamp(19px, 3vw, 29px) !important;
    min-height: 58px;
    font-weight: 750;
    border: 2px solid #cbd9ed;
    border-radius: 14px;
}
.product-card {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 20px;
    padding: clamp(18px, 4vw, 40px);
    margin: 12px auto;
    text-align: center;
    box-shadow: 0 6px 22px rgba(20, 50, 90, .08);
}
.product-label, .price-label {
    color: #64748b;
    font-weight: 800;
    letter-spacing: 1.3px;
    font-size: clamp(12px, 1.8vw, 17px);
}
.product-name {
    color: #102b50;
    font-size: clamp(23px, 4.5vw, 40px);
    font-weight: 850;
    overflow-wrap: anywhere;
    line-height: 1.2;
    margin: 12px 0;
}
.product-code {
    color: #64748b;
    font-size: clamp(14px, 2vw, 21px);
    overflow-wrap: anywhere;
    margin-bottom: 20px;
}
.product-price {
    color: #0757c3;
    font-size: clamp(40px, 8vw, 76px);
    font-weight: 900;
    line-height: 1.15;
    overflow-wrap: anywhere;
    margin-top: 10px;
}
@media (orientation: landscape) and (max-height: 650px) {
    .block-container { padding-top: .4rem; padding-bottom: .5rem; }
    .main-header { padding: 10px 12px; margin-bottom: 7px; }
