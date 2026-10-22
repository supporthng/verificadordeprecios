"""Conexión con Supabase: claves y cabeceras en UN solo lugar.

Supabase está reemplazando sus claves "legacy" (anon y service_role, textos que
empiezan con "eyJ") por claves nuevas (sb_publishable_... y sb_secret_...), y
planea retirar las legacy a fines de 2026. Las dos clases se envían distinto:

- Legacy (JWT):  cabeceras  apikey: <clave>   +   Authorization: Bearer <clave>
- Nuevas (sb_):  cabecera   apikey: <clave>   (NO van en Authorization: no son JWT)

Este módulo detecta qué clase de clave hay en Secrets y arma las cabeceras
correctas, así la app funciona con cualquiera de las dos y el cambio de claves
se hace solo en Streamlit Secrets, sin tocar el código.

Nombres aceptados en Secrets (el primero que tenga valor):
- Clave del servidor (acceso total): SUPABASE_SECRET_KEY o SUPABASE_SERVICE_ROLE_KEY
- Clave pública (solo lectura con RLS): SUPABASE_PUBLISHABLE_KEY o SUPABASE_ANON_KEY
"""
import streamlit as st


def _secreto(*nombres):
    for nombre in nombres:
        valor = str(st.secrets.get(nombre, "") or "").strip()
        if valor:
            return valor
    return ""


def url():
    return _secreto("SUPABASE_URL").rstrip("/")


def clave_servidor():
    """Clave con acceso total (solo en el servidor, nunca en el navegador)."""
    return _secreto("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY")


def clave_publica():
    """Clave pública: lectura limitada por las reglas (RLS) de la base."""
    return _secreto("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY")


def es_clave_legacy(clave):
    """Las claves legacy son JWT (empiezan con 'eyJ'); las nuevas, con 'sb_'."""
    return str(clave).startswith("eyJ")


def cabeceras(clave=None, extra=None):
    """Cabeceras de autenticación correctas para la clave dada (por defecto, la del servidor)."""
    clave = clave if clave is not None else clave_servidor()
    h = {"apikey": clave}
    if es_clave_legacy(clave):
        h["Authorization"] = "Bearer " + clave
    if extra:
        h.update(extra)
    return h
