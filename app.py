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

CSS = """
<style>
.stApp { background: #f4f7fc; }
.block-container {
    max-width: 950px;
    padding: 1rem 1rem 2rem;
}
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }
.main-header {
    background: linear-gradient(135deg, #0c2e59, #0759c9);
    border-radius: 20px;
    padding: clamp(12px, 3vw, 28px);
    text-align: center;
    color: white;
    margin-bottom: 12px;
}
.main-header h1 {
    color: white !important;
    font-size: clamp(20px, 4vw, 38px);
    margin: 0;
}
.main-header p {
    color: #dceaff;
    font-size: clamp(12px, 2vw, 17px);
    margin: 6px 0 0;
}
.scan-title {
    color: #102b50;
    text-align: center;
    font-weight: 850;
    font-size: clamp(18px, 3.5vw, 32px);
    margin: 10px 0;
}
div[data-testid="stTextInput"] input {
    text-align: center !important;
    font-size: clamp(18px, 3vw, 28px) !important;
    min-height: 56px;
    border-radius: 14px;
    border: 2px solid #d5e1f1;
    background: white;
}
.product-card {
    background: white;
    border: 1px solid #dce5f2;
    border-radius: 20px;
    padding: clamp(16px, 4vw, 36px);
    text-align: center;
    margin: 10px auto;
    box-shadow: 0 7px 25px rgba(20,50,90,.07);
}
.product-label, .price-label {
    color: #64748b;
    font-weight: 800;
    letter-spacing: 1px;
    font-size: clamp(12px, 2vw, 17px);
}
.product-name {
    color: #102b50;
    font-size: clamp(22px, 4.5vw, 40px);
    font-weight: 850;
    overflow-wrap: anywhere;
    line-height: 1.2;
    margin: 12px 0;
}
.product-code {
    color: #64748b;
    font-size: clamp(14px, 2vw, 21px);
    overflow-wrap: anywhere;
    margin-bottom: 22px;
}
.product-price {
    color: #0757c3;
    font-size: clamp(40px, 8vw, 76px);
    font-weight: 900;
    line-height: 1.1;
    overflow-wrap: anywhere;
    margin-top: 8px;
