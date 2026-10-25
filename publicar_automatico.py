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
    # Respaldo diario de todo el sistema (se guardan los últimos 14 en la nube privada «respaldos»).
    try:
        import respaldo
        hecho = respaldo.automatico()
        if hecho:
            print(f"Respaldo automático guardado: {hecho}")
    except Exception as exc:   # el respaldo nunca impide mantener los precios al día
        print(f"::warning::No se pudo guardar el respaldo automático: {exc}")
    import publicar_equipos as pe
    antes = pe.estado()
    if antes is None:
        print("Todavía no se publicó nada para los equipos: no hay nada que mantener al día.")
        return 0
    # Códigos pedidos desde la app ("Buscar con el navegador ahora"): se buscan primero.
    prioridad = [c.strip() for c in os.environ.get("FOTOS_CODIGOS", "").split(",") if c.strip()]
    if prioridad:
        try:
            import fotos_productos
            fotos_productos.priorizar(prioridad)
            print(f"Fotos pedidas desde la app: {', '.join(prioridad)}")
        except Exception as exc:
            print(f"::warning::No se pudieron priorizar los códigos: {exc}")
    # Índice semanal de tiendas sin catálogo público (Merkapp…), recorriendo sus categorías.
    try:
        import fotos_navegador
        for tienda, cantidad in fotos_navegador.actualizar_indices().items():
            print(f"Índice de {tienda}: {cantidad} productos.")
    except ImportError:
        pass
    except Exception as exc:
        print(f"::warning::No se pudo actualizar el índice de tiendas: {exc}")
    # Fotos de los productos consultados que todavía no tienen (se buscan en internet).
    try:
        import fotos_productos
        r = fotos_productos.procesar_pendientes()
        print(f"Fotos: {r['halladas']} encontradas, {r['sin_foto']} sin foto en internet, "
              f"{r['pendientes']} quedan para la próxima vuelta.")
    except Exception as exc:   # las fotos nunca impiden mantener los precios al día
        print(f"::warning::No se pudieron buscar fotos: {exc}")
    # Las que siguen sin foto: con un navegador real (Bing Imágenes, descarga o captura).
    try:
        import fotos_navegador
        r = fotos_navegador.procesar(prioridad=prioridad)
        if r["intentados"]:
            print(f"Fotos con navegador: {r['halladas']} de {r['intentados']} encontradas.")
    except ImportError:
        print("Fotos con navegador: falta Playwright en el flujo de GitHub (ver publicar-equipos.yml).")
    except Exception as exc:
        print(f"::warning::No se pudo usar el navegador para las fotos: {exc}")
    nuevo = pe.publicar()
    if nuevo.get("version") != antes.get("version"):
        print(f"Precios nuevos publicados: {nuevo['productos']:,} productos ({nuevo['inventario']}).")
    elif nuevo != antes:
        print("Configuración actualizada (apariencia, logo, QR, fotos o clave); los precios no cambiaron.")
    else:
        print(f"Sin cambios: {nuevo['productos']:,} productos ({nuevo['inventario']}).")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:   # falla visible en GitHub (y aviso por correo al dueño del repositorio)
        print(f"::error::No se pudo revisar los precios: {exc}")
        sys.exit(1)
