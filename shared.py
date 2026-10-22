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


# ---------------------------------------------------------------------------
# Formas equivalentes de un código de barras
# ---------------------------------------------------------------------------
# Un mismo producto puede estar guardado de varias formas: UPC-E (8 dígitos,
# envases pequeños), UPC-A (12), EAN-13 (13, con un 0 delante del UPC-A), y
# muchas veces SIN los ceros iniciales (Excel los borra). Los lectores también
# entregan formas distintas según su configuración. Para no responder
# "no encontrado" por una diferencia de formato, se buscan todas.

def _digito_control(cuerpo):
    """Dígito verificador GS1 (EAN/UPC) para una cadena de dígitos."""
    suma = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(cuerpo)))
    return str((10 - suma % 10) % 10)


def upce_a_upca(upce):
    """'08780538' (UPC-E) -> '087800000058' (UPC-A). None si no es UPC-E válido."""
    if len(upce) != 8 or not upce.isdigit() or upce[0] not in "01":
        return None
    ns, d, control = upce[0], upce[1:7], upce[7]
    ultimo = d[5]
    if ultimo in "012":
        cuerpo = d[0:2] + ultimo + "0000" + d[2:5]
    elif ultimo == "3":
        cuerpo = d[0:3] + "00000" + d[3:5]
    elif ultimo == "4":
        cuerpo = d[0:4] + "00000" + d[4]
    else:
        cuerpo = d[0:5] + "0000" + ultimo
    upca = ns + cuerpo + control
    return upca if _digito_control(upca[:11]) == control else None


def upca_a_upce(upca):
    """'087800000058' (UPC-A) -> ['08780538'] : todas las formas UPC-E válidas
    (algunos UPC-A admiten más de una). Lista vacía si no se puede comprimir."""
    if len(upca) != 12 or not upca.isdigit() or upca[0] not in "01":
        return []
    ns, fab, prod, control = upca[0], upca[1:6], upca[6:11], upca[11]
    candidatos = []
    if fab[2] in "012" and fab[3:] == "00" and prod[:2] == "00":
        candidatos.append(fab[0:2] + prod[2:5] + fab[2])
    if fab[3:] == "00" and prod[:3] == "000":
        candidatos.append(fab[0:3] + prod[3:5] + "3")
    if fab[4] == "0" and prod[:4] == "0000":
        candidatos.append(fab[0:4] + prod[4] + "4")
    if prod[:4] == "0000" and prod[4] in "56789":
        candidatos.append(fab + prod[4])
    return [ns + d + control for d in candidatos if upce_a_upca(ns + d + control) == upca]


def variantes_codigo(codigo):
    """Formas equivalentes de un código, en orden de preferencia (la exacta primero)."""
    codigo = str(codigo).strip()
    formas = [codigo]
    if not codigo.isdigit():
        return formas
    upca = None
    if len(codigo) == 13 and codigo[0] == "0":
        upca = codigo[1:]
    elif len(codigo) == 12:
        upca = codigo
    elif len(codigo) == 8:
        upca = upce_a_upca(codigo)
    if upca:
        formas += [upca, "0" + upca]
        formas += upca_a_upce(upca)
    # Sin ceros iniciales (Excel suele borrarlos), solo si queda un código largo.
    formas += [f.lstrip("0") for f in list(formas) if len(f.lstrip("0")) >= 6]
    vistas, unicas = set(), []
    for f in formas:
        if f and f not in vistas:
            vistas.add(f)
            unicas.append(f)
    return unicas
