"""Utilidades compartidas entre páginas."""
import re
import unicodedata


def normalize_header(value):
    """Normaliza un encabezado de Excel: sin acentos, minúsculas y solo [a-z0-9].
    Ej.: 'Código Barra' -> 'codigobarra'."""
    value = unicodedata.normalize('NFKD', str(value))
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', value.lower())
