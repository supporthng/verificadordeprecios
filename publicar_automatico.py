"""Revisión automática de precios para los equipos sin internet (la ejecuta GitHub Actions).

Cuando la fuente es Google Drive / Sheets, los precios pueden cambiar en Google sin pasar
por la app: este script lee la fuente activa y, SOLO si algo cambió, publica la versión
nueva para los equipos. Si nada cambió, no escribe nada.

Necesita .streamlit/secrets.toml (GitHub Actions lo crea desde el secreto STREAMLIT_SECRETS).
"""
import os
import sys


def main():
    if not os.path.exists(os.path.join(".streamlit", "secrets.toml")):
        print("Falta el secreto STREAMLIT_SECRETS en GitHub: la revisión automática está apagada.")
        return 0
    import publicar_equipos as pe
    antes = pe.estado()
    if antes is None:
        print("Todavía no se publicó nada para los equipos: no hay nada que mantener al día.")
        return 0
    nuevo = pe.publicar()
    if nuevo.get("version") != antes.get("version"):
        print(f"Precios nuevos publicados: {nuevo['productos']:,} productos ({nuevo['inventario']}).")
    elif nuevo != antes:
        print("Configuración actualizada (apariencia, logo, QR o clave); los precios no cambiaron.")
    else:
        print(f"Sin cambios: {nuevo['productos']:,} productos ({nuevo['inventario']}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:   # falla visible en GitHub (y aviso por correo al dueño del repositorio)
        print(f"::error::No se pudo revisar los precios: {exc}")
        sys.exit(1)
