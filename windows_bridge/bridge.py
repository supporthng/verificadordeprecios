"""Puente de descubrimiento LAN, sin credenciales SQL ni escritura en facturación."""
import asyncio
import html
import ipaddress
import os
import secrets
import logging
from logging.handlers import RotatingFileHandler
import sys
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse


CONFIG_SOURCE = "variables de entorno"

def load_env():
    global CONFIG_SOURCE
    """Prefer explicit config; then ProgramData (installer); then exe directory (portable)."""
    program_data = Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'ConsultaPrecios' / 'bridge.env'
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    candidates = [
        Path(os.environ['CONSULTA_BRIDGE_ENV']) if os.getenv('CONSULTA_BRIDGE_ENV') else None,
        program_data,
        exe_dir / 'bridge.env',
    ]
    for path in candidates:
        if path is not None and path.is_file():
            CONFIG_SOURCE = str(path)
            for line in path.read_text(encoding='utf-8-sig').splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    key, value = line.split('=', 1)
                    # El archivo seleccionado es la fuente autoritativa, no variables antiguas.
                    os.environ[key.strip()] = value.strip()
            return


load_env()
URL = os.getenv('SUPABASE_URL', '').rstrip('/')
KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
PASSWORD = os.getenv('BRIDGE_PASSWORD', '')
ALLOWED = [ipaddress.ip_network(s.strip(), strict=False)
           for s in os.getenv('ALLOWED_NETWORKS', '192.168.1.0/24').split(',') if s.strip()]
PORTS = [(1433, 'SQL Server'), (50517, 'SQL Server'), (3306, 'MySQL / MariaDB'),
         (5432, 'PostgreSQL'), (3050, 'Firebird'), (1521, 'Oracle'),
         (50000, 'IBM Db2'), (2638, 'SQL Anywhere')]
app = FastAPI(title='Puente LAN - Consulta de Precios', docs_url=None, redoc_url=None)
logger = logging.getLogger('conector_lan')
logger.setLevel(logging.INFO)
try:
    log_dir = Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'ConsultaPrecios'
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / 'conector.log', maxBytes=500_000,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
except OSError:
    # El conector sigue funcionando si no tiene permiso para crear el registro.
    pass
logger.info('Conector iniciado; origen de configuración: %s', CONFIG_SOURCE)
SESSIONS = set()


def supabase(method, path, **kwargs):
    if not URL or not KEY:
        raise RuntimeError('Configura SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en .env')
    response = requests.request(method, f'{URL}/rest/v1/{path}',
                                headers={'apikey': KEY, 'Authorization': f'Bearer {KEY}',
                                         'Content-Type': 'application/json', 'Prefer': 'return=representation'},
                                timeout=12, **kwargs)
    logger.info('Supabase %s %s: HTTP %s; tipo=%s; bytes=%s',
                method, path, response.status_code,
                response.headers.get('Content-Type', 'desconocido'), len(response.content))
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        logger.error('Supabase devolvió una respuesta que no es JSON válido')
        raise



def auth(request):
    token = request.cookies.get('lan_session', '')
    if token not in SESSIONS:
        raise HTTPException(401, 'Debes iniciar sesión en el conector Windows.')


def page(body):
    return HTMLResponse('<!doctype html><html lang="es"><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>Conector LAN</title><style>body{font:17px Arial;max-width:850px;'
                        'margin:30px auto;padding:15px;color:#173154}input,button{padding:12px;'
                        'margin:6px}button{background:#0756bb;color:white;border:0;border-radius:8px}'
                        'table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #ddd;'
                        'padding:10px}a{color:#0756bb}</style>' + body + '</html>')


@app.get('/health')
def health():
    return {'ok': True}


@app.get('/login')
def login_page(request_id: str = '', db_request_id: str = ''):
    rid = html.escape(request_id, quote=True)
    db_rid = html.escape(db_request_id, quote=True)
    return page('<h1>Conector local Windows</h1><form method="post" action="/login">'
                f'<input type="hidden" name="request_id" value="{rid}">'
                f'<input type="hidden" name="db_request_id" value="{db_rid}">'
                '<input type="password" name="password" placeholder="Contraseña del conector" required>'
                '<button>Entrar</button></form>')


@app.post('/login')
def login(password: str = Form(...), request_id: str = Form(''), db_request_id: str = Form('')):
    if not PASSWORD or len(PASSWORD) < 12 or not secrets.compare_digest(password, PASSWORD):
        raise HTTPException(403, 'Contraseña incorrecta o insegura')
    token = secrets.token_urlsafe(32)
    SESSIONS.add(token)
    destination = ('/databases?db_request_id=' + quote(db_request_id)) if db_request_id else ('/?request_id=' + quote(request_id))
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie('lan_session', token, httponly=True, samesite='strict', secure=False,
                        max_age=3600)
    return response


@app.get('/')
def index(request: Request, request_id: str = ''):
    if request.cookies.get('lan_session', '') not in SESSIONS:
        return RedirectResponse('/login?request_id=' + quote(request_id))
    rid = html.escape(request_id, quote=True)
    default_network = html.escape(str(ALLOWED[0]) if ALLOWED else '10.0.0.0/24', quote=True)
    return page('<h1>Buscar bases de datos en la red</h1>'
                '<p>La búsqueda se realiza en Windows, no en Streamlit Cloud.</p>'
                '<form method="post" action="/scan">'
                f'<input type="hidden" name="request_id" value="{rid}">'
                f'<label>Subred autorizada <input name="network" value="{default_network}" required></label>'
                '<button>Buscar servidores</button></form>'
                '<p>Solo se detectan puertos abiertos; el motor mostrado es una suposición.</p>'
                '<h2>Agregar servidor manualmente</h2>'
                '<form method="post" action="/select">'
                f'<input type="hidden" name="request_id" value="{rid}">'
                '<label>IP <input name="host" value="10.0.0.150" required></label>'
                '<label>Puerto <input name="port" type="number" min="1" max="65535" value="50517" required></label>'
                '<label>Motor <select name="engine"><option value="SQL Server">SQL Server</option>'
                '<option value="Firebird">Firebird</option><option value="PostgreSQL">PostgreSQL</option>'
                '<option value="MySQL / MariaDB">MySQL / MariaDB</option>'
                '<option value="Oracle">Oracle</option><option value="IBM Db2">IBM Db2</option>'
                '<option value="SQL Anywhere">SQL Anywhere</option></select></label>'
                '<button>Verificar y seleccionar</button></form>')


def probe(item):
    host, port, engine = item
    try:
        with socket.create_connection((str(host), port), timeout=0.23):
            return (str(host), port, engine)
    except (OSError, TimeoutError):
        return None


@app.post('/scan')
async def scan(request: Request, request_id: str = Form(...), network: str = Form(...)):
    auth(request)
    try:
        subnet = ipaddress.ip_network(network.strip(), strict=False)
    except ValueError:
        raise HTTPException(400, 'Subred inválida')
    if subnet.version != 4 or subnet.num_addresses > 256 or not any(subnet.subnet_of(x) for x in ALLOWED):
        raise HTTPException(400, 'Subred no permitida o demasiado grande (máximo /24)')
    if not request_id:
        raise HTTPException(400, 'Inicia la búsqueda desde Streamlit para vincular el resultado')
    # Solo mostrar resultados si la solicitud realmente existe y está pendiente.
    try:
        rows = await asyncio.to_thread(supabase, 'GET', 'lan_discovery_requests',
            params={'id': 'eq.' + request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat(), 'select': 'id'})
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 'desconocido'
        logger.error('Error HTTP consultando solicitud de descubrimiento: HTTP %s', status)
        raise HTTPException(502, f'Supabase rechazó la consulta (HTTP {status}). Revisa URL, clave service_role y permisos de la tabla.') from None
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        # No registrar la excepción completa: algunas bibliotecas incluyen datos sensibles.
        tipo = type(exc).__name__
        logger.error('Error consultando Supabase: %s', tipo)
        raise HTTPException(502, f'Error de consulta a Supabase: {tipo}. Revisa conector.log en ProgramData\\ConsultaPrecios.') from None
    if not rows:
        raise HTTPException(400, 'Solicitud inexistente o vencida. Vuelve a Streamlit.')
    jobs = [(host, port, engine) for host in subnet.hosts() for port, engine in PORTS]
    try:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=48) as pool:
            result = await asyncio.gather(*(loop.run_in_executor(pool, probe, j) for j in jobs))
        found = [x for x in result if x]
    except Exception:
        logger.exception('Fallo durante exploración de red')
        raise HTTPException(500, 'Error al explorar la red. Consulta el registro del conector Windows.') from None
    body = '<h1>Servidores encontrados</h1><p>Selecciona uno para enviarlo a Streamlit.</p>'
    if not found:
        body += '<p>No se detectaron puertos conocidos. Regresa a la pantalla anterior para introducir IP y puerto manualmente.</p>'
    body += '<table><tr><th>IP</th><th>Puerto</th><th>Motor probable</th><th></th></tr>'
    for host, port, engine in found:
        body += ('<tr><td>' + html.escape(host) + '</td><td>' + str(port) + '</td><td>'
                 + html.escape(engine) + '</td><td><form method="post" action="/select">'
                 f'<input type="hidden" name="request_id" value="{html.escape(request_id, quote=True)}">'
                 f'<input type="hidden" name="host" value="{html.escape(host, quote=True)}">'
                 f'<input type="hidden" name="port" value="{port}">'
                 f'<input type="hidden" name="engine" value="{html.escape(engine, quote=True)}">'
                 '<button>Seleccionar</button></form></td></tr>')
    return page(body + '</table>')


@app.post('/select')
async def select(request: Request, request_id: str = Form(...), host: str = Form(...),
                 port: int = Form(...), engine: str = Form(...)):
    auth(request)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(400, 'IP inválida')
    allowed_engines = {name for _, name in PORTS}
    if ip.version != 4 or not any(ip in network for network in ALLOWED):
        raise HTTPException(400, 'Servidor fuera de las redes autorizadas')
    if not 1 <= port <= 65535 or engine not in allowed_engines:
        raise HTTPException(400, 'Puerto o motor inválido')
    # Validar alcance TCP también para entradas manuales; no inicia sesión SQL.
    reachable = await asyncio.to_thread(probe, (str(ip), port, engine))
    if reachable is None:
        raise HTTPException(400, 'No se puede conectar al puerto TCP indicado desde Windows')
    try:
        rows = await asyncio.to_thread(supabase, 'PATCH', 'lan_discovery_requests',
            params={'id': 'eq.' + request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat()},
            json={'selected_host': host, 'selected_port': port,
                  'selected_engine': engine, 'status': 'selected'})
    except requests.RequestException:
        raise HTTPException(502, 'No se pudo comunicar la selección a Supabase')
    if not rows:
        raise HTTPException(409, 'Solicitud vencida o ya utilizada')
    return page('<h1>Selección enviada</h1><p>Regresa a Streamlit y pulsa '
                '<strong>Recibir selección</strong>. No se enviaron contraseñas.</p>')



# Listado de bases: se ejecuta solo en Windows, nunca desde Streamlit Cloud.
# Requiere un usuario SQL de solo lectura configurado localmente en bridge.env.
def sql_databases(host, port):
    import pyodbc
    user = os.getenv('SQL_READ_USER', '').strip()
    password = os.getenv('SQL_READ_PASSWORD', '')
    driver = os.getenv('SQL_ODBC_DRIVER', 'ODBC Driver 18 for SQL Server').strip()
    if not user or not password:
        raise RuntimeError('Faltan SQL_READ_USER o SQL_READ_PASSWORD en bridge.env')
    # No aceptar un servidor arbitrario fuera de la LAN autorizada.
    ip = ipaddress.ip_address(host)
    if ip.version != 4 or not any(ip in network for network in ALLOWED):
        raise ValueError('IP fuera de la red autorizada')
    if not 1 <= int(port) <= 65535:
        raise ValueError('Puerto inválido')
    # Driver configurable; no permitir inyección de parámetros ODBC.
    if any(ch in driver for ch in '{};\x00'):
        raise ValueError('Nombre de controlador ODBC inválido')
    conn_str = (
        f'DRIVER={{{driver}}};SERVER=tcp:{host},{int(port)};'
        'DATABASE=master;'
        'Encrypt=yes;TrustServerCertificate=no;Connection Timeout=6;'
        'ApplicationIntent=ReadOnly;'
    )
    # ODBC escape para credenciales con punto y coma o llaves.
    def enc(value):
        return '{' + value.replace('}', '}}') + '}'
    conn_str += 'UID=' + enc(user) + ';PWD=' + enc(password) + ';'
    with pyodbc.connect(conn_str, timeout=6, autocommit=True) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1 ORDER BY name")
        return [str(row[0]) for row in cursor.fetchall()][:200]


@app.get('/databases')
def databases_page(request: Request, db_request_id: str = ''):
    if request.cookies.get('lan_session', '') not in SESSIONS:
        return RedirectResponse('/login?db_request_id=' + quote(db_request_id))
    rid = html.escape(db_request_id, quote=True)
    return page('<h1>Buscar bases de datos de SQL Server</h1>'
                '<p>La consulta se ejecuta en este equipo Windows con credenciales locales de solo lectura.</p>'
                '<form method="post" action="/databases">'
                f'<input type="hidden" name="db_request_id" value="{rid}">'
                '<button>Consultar bases de datos</button></form>')


@app.post('/databases')
async def databases_run(request: Request, db_request_id: str = Form(...)):
    auth(request)
    try:
        # Solo procesar una solicitud nueva, vigente y creada desde Streamlit.
        import uuid
        uuid.UUID(db_request_id)
        rows = await asyncio.to_thread(supabase, 'GET', 'lan_db_requests',
            params={'id': 'eq.' + db_request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat(),
                    'select': 'id,host,port,engine'})
        if not rows:
            raise HTTPException(400, 'Solicitud inexistente, vencida o ya utilizada. Regresa a Streamlit.')
        item = rows[0]
        if item['engine'] != 'SQL Server':
            raise HTTPException(400, 'Este botón solo admite SQL Server')
        names = await asyncio.to_thread(sql_databases, item['host'], int(item['port']))
        updated = await asyncio.to_thread(supabase, 'PATCH', 'lan_db_requests',
            params={'id': 'eq.' + db_request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat()},
            json={'status': 'done', 'database_names': names})
        if not updated:
            raise HTTPException(409, 'La solicitud venció durante la consulta')
        return page('<h1>Consulta completada</h1><p>Se encontraron '
                    + str(len(names)) + ' bases accesibles. Regresa a Streamlit y pulsa '
                    '<strong>Recibir bases de datos</strong>.</p>')
    except HTTPException:
        raise
    except Exception as exc:
        # No registrar cadenas de conexión ni mensajes ODBC que puedan incluir secretos.
        logger.warning('Fallo en búsqueda de bases SQL: tipo=%s', type(exc).__name__)
        return page('<h1>No se pudieron consultar las bases</h1>'
                    '<p>Revisa el usuario SQL de solo lectura, el controlador ODBC 18 y '
                    'el certificado TLS de SQL Server. Tipo de error: '
                    + html.escape(type(exc).__name__) + '.</p>'
                    '<p>La solicitud no fue completada; puedes reintentar.</p>')

def main():
    if not URL or not KEY or not PASSWORD or len(PASSWORD) < 12:
        raise SystemExit('Configura bridge.env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY y BRIDGE_PASSWORD (12+ caracteres).')
    uvicorn.run(app, host=os.getenv('BRIDGE_HOST', '0.0.0.0'),
                port=int(os.getenv('BRIDGE_PORT', '8765')))


if __name__ == '__main__':
    main()
