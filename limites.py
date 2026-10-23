"""Límites de consultas para la Consulta Móvil PÚBLICA (enlace del QR).

Evita que alguien sature el sistema con miles de consultas: un límite por
teléfono y otro global entre todos los teléfonos. El verificador de la tienda
y el personal con sesión iniciada NO pasan por aquí.

Los contadores viven en la memoria del servidor de Streamlit (compartidos por
todas las sesiones). Si la app se reinicia, empiezan de cero: es suficiente
como freno, no pretende ser un registro.
"""
import threading
import time
from collections import deque

import streamlit as st

POR_TELEFONO = 20       # consultas por minuto desde un mismo teléfono (sesión del navegador)
POR_RED = 120           # por minuto desde una misma IP: en la tienda, todos los clientes
                        # del mismo Wi-Fi comparten IP, por eso es más alto
GLOBAL = 300            # consultas públicas por minuto entre todos
VENTANA = 60.0          # segundos
LARGO_MAXIMO = 64       # un código de barras real nunca es más largo


@st.cache_resource
def _contadores():
    return {"lock": threading.Lock(), "por_cliente": {}, "global": deque()}


def _ip():
    """IP real del cliente (detrás del proxy de Streamlit Cloud), o "" si no se conoce."""
    try:
        ip = getattr(st.context, "ip_address", None)
        if not ip:
            reenviada = st.context.headers.get("X-Forwarded-For", "")
            ip = reenviada.split(",")[0].strip() if reenviada else ""
        return ip or ""
    except Exception:
        return ""


def _telefono():
    """Identificador de la sesión del navegador (cada teléfono tiene la suya)."""
    st.session_state.setdefault("_id_limite", f"s:{id(st.session_state)}:{time.time()}")
    return st.session_state["_id_limite"]


def _limpiar(cola, ahora):
    while cola and ahora - cola[0] > VENTANA:
        cola.popleft()


def permitir_consulta():
    """Devuelve (True, "") si se puede consultar, o (False, mensaje) si se pasó del límite."""
    c = _contadores()
    ahora = time.monotonic()
    claves = [(_telefono(), POR_TELEFONO, "Hiciste muchas consultas seguidas. Espera {s} segundos.")]
    ip = _ip()
    if ip:
        claves.append(("ip:" + ip, POR_RED, "Hay muchas consultas desde esta red. Espera {s} segundos."))
    with c["lock"]:
        _limpiar(c["global"], ahora)
        if len(c["global"]) >= GLOBAL:
            return False, "Hay muchas consultas en este momento. Intenta de nuevo en unos segundos."
        colas = []
        for clave, limite, mensaje in claves:
            cola = c["por_cliente"].setdefault(clave, deque())
            _limpiar(cola, ahora)
            if len(cola) >= limite:
                return False, mensaje.format(s=int(VENTANA - (ahora - cola[0])) + 1)
            colas.append(cola)
        for cola in colas:
            cola.append(ahora)
        c["global"].append(ahora)
        # Olvidar teléfonos inactivos para no acumular memoria.
        if len(c["por_cliente"]) > 5000:
            for k in [k for k, q in c["por_cliente"].items() if not q or ahora - q[-1] > VENTANA]:
                del c["por_cliente"][k]
    return True, ""


def codigo_valido(codigo):
    """Un código razonable: no vacío, sin saltos de línea y de largo normal."""
    codigo = str(codigo or "").strip()
    return 0 < len(codigo) <= LARGO_MAXIMO and not any(ch in codigo for ch in "\r\n\t")
