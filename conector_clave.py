"""Cambiar la clave de Supabase del conector de Windows desde la app, sin ir a la PC.

La app deja la clave nueva en el bucket PRIVADO (logo-negocio/conector-clave.json).
El conector la revisa cada 5 minutos con su clave actual, la prueba, la guarda en su
bridge.env, confirma en conector-clave-ok.json y borra la copia.
"""
import json
from datetime import datetime, timezone

import requests

from supabase_cliente import cabeceras, clave_servidor, url

PENDIENTE = "logo-negocio/conector-clave.json"
CONFIRMADA = "logo-negocio/conector-clave-ok.json"


def _leer(ruta):
    try:
        r = requests.get(f"{url()}/storage/v1/object/{ruta}", headers=cabeceras(clave_servidor()), timeout=10)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def estado():
    """{'pendiente': fecha o None, 'confirmada': {...} o None}"""
    pendiente = _leer(PENDIENTE)
    return {"pendiente": (pendiente or {}).get("fecha"), "confirmada": _leer(CONFIRMADA)}


def enviar(clave):
    clave = str(clave or "").strip()
    if not clave.startswith("sb_secret_"):
        raise ValueError("Pega una clave secreta nueva de Supabase: empieza con sb_secret_")
    # Comprobar que la clave funciona antes de enviarla.
    prueba = requests.get(f"{url()}/rest/v1/price_source_settings", params={"select": "id", "limit": "1"},
                          headers={"apikey": clave}, timeout=12)
    if not prueba.ok:
        raise ValueError(f"Supabase rechazó esa clave (HTTP {prueba.status_code}). Cópiala de nuevo desde API Keys.")
    datos = {"clave": clave, "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    r = requests.post(f"{url()}/storage/v1/object/{PENDIENTE}",
                      headers=cabeceras(clave_servidor(), {"Content-Type": "application/json", "x-upsert": "true"}),
                      data=json.dumps(datos).encode("utf-8"), timeout=15)
    if not r.ok:
        raise RuntimeError(f"No se pudo dejar la clave para el conector (HTTP {r.status_code}): {r.text[:200]}")


def cancelar():
    requests.delete(f"{url()}/storage/v1/object/logo-negocio",
                    headers=cabeceras(clave_servidor(), {"Content-Type": "application/json"}),
                    json={"prefixes": ["conector-clave.json"]}, timeout=15)
