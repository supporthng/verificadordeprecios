"""Utilidades compartidas entre páginas."""
import json
import re
import unicodedata


def ejecutar_js_en_pagina(codigo_js, clave):
    """Ejecuta JavaScript en la PÁGINA PRINCIPAL de forma fiable.

    Usa components.html (un iframe que Streamlit siempre ejecuta) e inserta el
    código como <script> en el documento principal, donde están los cuadros de
    texto y las cookies. El iframe queda oculto (display:none no impide que se
    ejecute). Si el contenido no cambia entre recargas, no se vuelve a ejecutar.
    """
    import streamlit as st
    import streamlit.components.v1 as components
    envoltura = (
        "<script>(function(){try{var d=window.parent.document;"
        "var s=d.createElement('script');s.textContent=%s;"
        "d.head.appendChild(s);}catch(e){console.error('JS en página:',e);}})();</script>"
        % json.dumps(codigo_js))
    st.markdown("<style>.st-key-%s{display:none!important}</style>" % clave,
                unsafe_allow_html=True)
    with st.container(key=clave):
        components.html(envoltura, height=0)


def normalize_header(value):
    """Normaliza un encabezado de Excel: sin acentos, minúsculas y solo [a-z0-9].
    Ej.: 'Código Barra' -> 'codigobarra'."""
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', value.lower())


# Formas equivalentes de un código de barras: viven en codigos_barras.py
# (compartido con el conector de Windows).
from codigos_barras import _digito_control, upce_a_upca, upca_a_upce, variantes_codigo  # noqa: F401

