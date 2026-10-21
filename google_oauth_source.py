"""Google OAuth por instalación, lectura de Excel en Drive y Google Sheets."""
import io
import base64
import hashlib
import hmac
import time
import math
import re
import secrets
from urllib.parse import urlencode, urlparse, parse_qs

import pandas as pd
import requests
import streamlit as st
from cryptography.fernet import Fernet

API_TIMEOUT=30
SCOPES="https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/spreadsheets.readonly"

def setting(name):
    value=str(st.secrets.get(name,"")).strip()
    if not value:
        raise RuntimeError("Falta "+name+" en Streamlit Secrets.")
    return value

def cipher():
    return Fernet(setting("GOOGLE_TOKEN_ENCRYPTION_KEY").encode())

def api(method,table,params=None,payload=None):
    url=setting("SUPABASE_URL").rstrip("/")+"/rest/v1/"+table
    key=setting("SUPABASE_SERVICE_ROLE_KEY")
    response=requests.request(method,url,params=params,json=payload,timeout=API_TIMEOUT,
        headers={"apikey":key,"Authorization":"Bearer "+key,
                 "Content-Type":"application/json","Prefer":"return=representation"})
    response.raise_for_status()
    return response.json() if response.content else []

def config():
    rows=api("GET","google_price_source",{"id":"eq.1","select":"*"})
    return rows[0] if rows else None

def signed_state():
    payload=f"{int(time.time())}:{secrets.token_urlsafe(18)}"
    signature=hmac.new(setting("GOOGLE_TOKEN_ENCRYPTION_KEY").encode(),
                       payload.encode(),hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode((payload+":"+signature).encode()).decode().rstrip("=")

def verify_state(value):
    try:
        decoded=base64.urlsafe_b64decode(value+"="*(-len(value)%4)).decode()
        timestamp,nonce,signature=decoded.split(":")
        payload=timestamp+":"+nonce
        expected=hmac.new(setting("GOOGLE_TOKEN_ENCRYPTION_KEY").encode(),
                          payload.encode(),hashlib.sha256).hexdigest()
        return abs(time.time()-int(timestamp))<600 and hmac.compare_digest(signature,expected)
    except (ValueError, TypeError, UnicodeError, base64.binascii.Error):
        return False

def auth_url(state):
    params={"client_id":setting("GOOGLE_OAUTH_CLIENT_ID"),
            "redirect_uri":setting("GOOGLE_OAUTH_REDIRECT_URI"),
            "response_type":"code","scope":SCOPES,"access_type":"offline",
            "prompt":"consent","state":state,"include_granted_scopes":"true"}
    return "https://accounts.google.com/o/oauth2/v2/auth?"+urlencode(params)

def exchange_code(code):
    r=requests.post("https://oauth2.googleapis.com/token",data={
        "code":code,"client_id":setting("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret":setting("GOOGLE_OAUTH_CLIENT_SECRET"),
        "redirect_uri":setting("GOOGLE_OAUTH_REDIRECT_URI"),
        "grant_type":"authorization_code"},timeout=API_TIMEOUT)
    if not r.ok:
        # Google proporciona un código de error seguro, sin exponer tokens.
        try:
            detail = r.json()
        except ValueError:
            detail = {}
        code = str(detail.get("error", "unknown_error"))
        explanations = {
            "invalid_grant": "El código de autorización venció, ya fue utilizado o la URL de retorno cambió. Vuelve a conectar desde Administración.",
            "invalid_client": "Google no reconoce el ID o el secreto OAuth. Comprueba que ambos pertenezcan al mismo cliente y reemplaza el secreto comprometido.",
            "redirect_uri_mismatch": "La URL de retorno no coincide exactamente con la registrada en Google Cloud.",
            "unauthorized_client": "El cliente OAuth no está autorizado para este tipo de acceso.",
            "invalid_request": "La solicitud de token es inválida. Revisa la URL de retorno y las credenciales del cliente.",
        }
        raise RuntimeError("Google rechazó el token (" + code + "): " + explanations.get(code, "Revisa la configuración OAuth y vuelve a intentarlo."))
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError("Google no devolvió un token de acceso válido.")
    return data

def save_token(data,old=None):
    refresh=data.get("refresh_token") or old
    if not refresh: raise RuntimeError("Google no devolvió permiso de acceso persistente. Desconecta la app en tu cuenta Google y vuelve a autorizar.")
    encrypted=cipher().encrypt(refresh.encode()).decode()
    url = setting("SUPABASE_URL").rstrip("/") + "/rest/v1/google_price_source"
    key = setting("SUPABASE_SERVICE_ROLE_KEY")
    response = requests.post(
        url,
        params={"on_conflict": "id"},
        json={"id": 1, "refresh_token_encrypted": encrypted},
        headers={
            "apikey": key,
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
        timeout=API_TIMEOUT,
    )
    if not response.ok:
        try:
            detail = response.json()
            reason = str(detail.get("code", "")) + ": " + str(detail.get("message", ""))
        except (ValueError, AttributeError):
            reason = "Error de la base de datos"
        raise RuntimeError(
            f"Supabase no pudo guardar la conexión Google (HTTP {response.status_code}): {reason[:350]}"
        )

def connect(data):
    save_token(data)
    # no se guardan tokens de acceso de corta duración
    st.cache_data.clear()

def refresh_access():
    cfg=config()
    if not cfg or not cfg.get("refresh_token_encrypted"):
        raise RuntimeError("Primero conecta una cuenta de Google.")
    token=cipher().decrypt(cfg["refresh_token_encrypted"].encode()).decode()
    r=requests.post("https://oauth2.googleapis.com/token",data={
        "client_id":setting("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret":setting("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token":token,"grant_type":"refresh_token"},timeout=API_TIMEOUT)
    if not r.ok: raise RuntimeError("Google rechazó la conexión. Reconecta la cuenta desde Administración.")
    return r.json()["access_token"]

def google_get(url,params=None):
    r=requests.get(url,params=params,headers={"Authorization":"Bearer "+refresh_access()},timeout=45)
    r.raise_for_status()
    return r

def file_id(raw):
    raw=str(raw).strip()
    m=re.search(r"/(?:file/d|spreadsheets/d)/([\w-]+)",raw)
    if m: return m.group(1)
    u=urlparse(raw)
    if u.hostname in ("drive.google.com","docs.google.com"):
        candidate=parse_qs(u.query).get("id",[""])[0]
        if re.fullmatch(r"[\w-]{20,}",candidate):return candidate
    if re.fullmatch(r"[\w-]{20,}",raw):return raw
    raise ValueError("Pega el enlace válido del archivo de Google.")

@st.cache_data(ttl=30,show_spinner=False)
def read_file(kind,fid,sheet):
    if kind=="excel":
        meta=google_get("https://www.googleapis.com/drive/v3/files/"+fid,
                        {"fields":"id,name,mimeType,size"}).json()
        if meta.get("mimeType")!="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            raise ValueError("El archivo seleccionado no es Excel .xlsx.")
        if int(meta.get("size") or 0)>20*1024*1024:
            raise ValueError("El archivo supera el límite de 20 MB.")
        content=google_get("https://www.googleapis.com/drive/v3/files/"+fid,{"alt":"media"}).content
        if len(content)>20*1024*1024:raise ValueError("El archivo supera el límite de 20 MB.")
        return pd.read_excel(io.BytesIO(content),sheet_name=sheet or 0,dtype=str).fillna("")
    if kind=="sheets":
        meta=google_get("https://sheets.googleapis.com/v4/spreadsheets/"+fid,
                        {"fields":"sheets(properties(title))"}).json()
        titles=[s["properties"]["title"] for s in meta.get("sheets",[])]
        selected=sheet or (titles[0] if titles else "")
        if selected not in titles:raise ValueError("La pestaña no existe.")
        from urllib.parse import quote
        range_name="'"+selected.replace("'","''")+"'!A1:ZZ"
        result=google_get("https://sheets.googleapis.com/v4/spreadsheets/"+fid+"/values/"+quote(range_name,safe=""),
                          {"valueRenderOption":"FORMATTED_VALUE"}).json()
        rows=result.get("values",[])
        if not rows:raise ValueError("La hoja está vacía.")
        headers=[str(x).strip() for x in rows[0]]
        if not headers or any(not h for h in headers) or len(set(headers))!=len(headers):
            raise ValueError("Los encabezados deben ser únicos y no estar vacíos.")
        return pd.DataFrame([(r[:len(headers)]+[""]*len(headers))[:len(headers)] for r in rows[1:]],columns=headers)
    raise ValueError("Tipo de archivo inválido.")

def parse_price(value):
    s=str(value).strip().replace("RD$","").replace("$","").replace(" ","")
    if "," in s and "." in s:
        s=s.replace(",","") if s.rfind(".")>s.rfind(",") else s.replace(".","").replace(",",".")
    elif "," in s:
        s=s.replace(",",".") if len(s.split(",")[-1])<=2 else s.replace(",","")
    value=float(s)
    if not math.isfinite(value) or value<0:raise ValueError("Precio inválido")
    return value

@st.cache_data(ttl=30,show_spinner=False)
def catalog(kind,fid,sheet,code_col,name_col,price_col):
    df=read_file(kind,fid,sheet)
    if len({code_col,name_col,price_col})!=3 or not all(x in df.columns for x in (code_col,name_col,price_col)):
        raise ValueError("Revisa la asignación de columnas.")
    items=[]
    for _,r in df.iterrows():
        code=str(r[code_col]).strip()
        name=str(r[name_col]).strip()
        if not code or not name:continue
        if re.fullmatch(r"\d+\.0",code):code=code[:-2]
        try:price=parse_price(r[price_col])
        except (ValueError,TypeError):continue
        items.append({"barcode":code,"name":name,"price":price})
    if not items:raise ValueError("No se encontraron productos válidos.")
    return pd.DataFrame(items).drop_duplicates("barcode",keep="last")

def activate(kind,fid,sheet,code,name,price):
    api("PATCH","google_price_source",{"id":"eq.1"},
        {"kind":kind,"file_id":fid,"sheet_name":sheet,
         "code_column":code,"name_column":name,"price_column":price})
    api("PATCH","price_source_settings",{"id":"eq.1"},{"source_type":"google"})
    st.cache_data.clear()
