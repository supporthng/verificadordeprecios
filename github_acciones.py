"""Iniciar desde la app la tarea de GitHub que busca fotos con un navegador real.

Necesita en Streamlit Secrets una clave de GitHub (token "fine-grained") con permiso
"Actions: Read and write" SOLO sobre este repositorio:
    GITHUB_TOKEN_ACCIONES = "github_pat_..."
Opcional: GITHUB_REPO = "dueño/repositorio" (por defecto supporthng/verificadordeprecios).
"""
import requests
import streamlit as st

FLUJO = "publicar-equipos.yml"
API = "https://api.github.com"


def _secreto(nombre):
    """Busca la clave arriba de todo en Secrets o, si quedó pegada debajo de una sección
    ([algo]), dentro de esa sección. Acepta también el nombre en minúsculas."""
    try:
        for clave in (nombre, nombre.lower()):
            if st.secrets.get(clave):
                return str(st.secrets.get(clave)).strip()
        for _, valor in st.secrets.items():
            if hasattr(valor, "get"):
                for clave in (nombre, nombre.lower()):
                    if valor.get(clave):
                        return str(valor.get(clave)).strip()
    except Exception:
        pass
    return ""


def _config():
    token = _secreto("GITHUB_TOKEN_ACCIONES")
    repo = _secreto("GITHUB_REPO") or "supporthng/verificadordeprecios"
    return token, repo


def configurado():
    return bool(_config()[0])


def _cabeceras(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}


def iniciar(codigos=()):
    """Inicia la tarea (con los códigos a buscar primero). Devuelve (True, '') o (False, motivo)."""
    token, repo = _config()
    if not token:
        return False, "Falta GITHUB_TOKEN_ACCIONES en los Secrets de Streamlit."
    try:
        info = requests.get(f"{API}/repos/{repo}", headers=_cabeceras(token), timeout=15)
        if info.status_code in (401, 403, 404):
            return False, "La clave de GitHub no es válida o no tiene acceso al repositorio."
        rama = (info.json() or {}).get("default_branch") or "main"
        r = requests.post(f"{API}/repos/{repo}/actions/workflows/{FLUJO}/dispatches", headers=_cabeceras(token),
                          json={"ref": rama, "inputs": {"codigos": ",".join(codigos)}}, timeout=15)
        if r.status_code == 422 and "inputs" in r.text.lower():
            # El flujo de GitHub todavía es la versión anterior (sin el campo de códigos).
            r = requests.post(f"{API}/repos/{repo}/actions/workflows/{FLUJO}/dispatches",
                              headers=_cabeceras(token), json={"ref": rama}, timeout=15)
    except (requests.RequestException, ValueError) as exc:
        return False, f"No se pudo conectar con GitHub: {exc}"
    if r.status_code == 204:
        return True, ""
    if r.status_code in (401, 403):
        return False, "La clave de GitHub no tiene permiso «Actions: Read and write» en este repositorio."
    return False, f"GitHub respondió HTTP {r.status_code}: {r.text[:200]}"


def ultima_ejecucion():
    """{estado, resultado, fecha, enlace} de la última ejecución de la tarea, o None."""
    token, repo = _config()
    if not token:
        return None
    try:
        r = requests.get(f"{API}/repos/{repo}/actions/workflows/{FLUJO}/runs", params={"per_page": 1},
                         headers=_cabeceras(token), timeout=15)
        runs = (r.json() or {}).get("workflow_runs") or [] if r.ok else []
    except (requests.RequestException, ValueError):
        return None
    if not runs:
        return None
    x = runs[0]
    return {"estado": x.get("status"), "resultado": x.get("conclusion"), "fecha": x.get("created_at"),
            "enlace": x.get("html_url"), "evento": x.get("event")}
