"""Puente de descubrimiento LAN, sin credenciales SQL ni escritura en facturación."""
import asyncio
import html
import ipaddress
import os
import secrets
import re
import logging
from logging.handlers import RotatingFileHandler
import sys
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time
import traceback
from pathlib import Path
from urllib.parse import quote, urlencode

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
WORKER_LAST_POLL = 0.0
WORKER_LAST_JOB = None
WORKER_LAST_ERROR = None
WORKER_JOB_COUNT = 0
LOG_FILE = None
LOG_READY = False
logger = logging.getLogger('conector_lan')
logger.setLevel(logging.INFO)
try:
    log_dir = Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'ConsultaPrecios'
    log_dir.mkdir(parents=True, exist_ok=True)
    LOG_FILE = log_dir / 'conector.log'
    handler = RotatingFileHandler(LOG_FILE, maxBytes=500_000,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    LOG_READY = True
except OSError:
    # El conector sigue funcionando si no tiene permiso para crear el registro.
    pass
logger.info('Conector v4 iniciado; pid=%s; origen de configuración: %s; registro=%s', os.getpid(), CONFIG_SOURCE, LOG_FILE)
SESSIONS = set()
DB_RESULTS = {}  # session-token -> (request id, accessible database names)
WIZARD_REQUESTS = {}  # db request id -> discovery request id


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
    return {'ok': True, 'version': 'asistente-universal-v4',
            'worker_age_seconds': (round(time.monotonic() - WORKER_LAST_POLL, 1)
                                   if WORKER_LAST_POLL else None),
            'worker_job_count': WORKER_JOB_COUNT,
            'last_job_utc': WORKER_LAST_JOB,
            'last_error_type': WORKER_LAST_ERROR,
            'log_path': str(LOG_FILE) if LOG_FILE else None,
            'log_enabled': LOG_READY}


@app.get('/login')
def login_page(request_id: str = '', db_request_id: str = '', next: str = ''):
    rid = html.escape(request_id, quote=True)
    db_rid = html.escape(db_request_id, quote=True)
    next_url = html.escape(next if next.startswith('/configure-sql?') else '', quote=True)
    return page('<h1>Conector local Windows</h1><form method="post" action="/login">'
                f'<input type="hidden" name="request_id" value="{rid}">'
                f'<input type="hidden" name="db_request_id" value="{db_rid}">'
                f'<input type="hidden" name="next" value="{next_url}">'
                '<input type="password" name="password" placeholder="Contraseña del conector" required>'
                '<button>Entrar</button></form>')


@app.post('/login')
def login(password: str = Form(...), request_id: str = Form(''), db_request_id: str = Form(''), next: str = Form('')):
    if not PASSWORD or len(PASSWORD) < 12 or not secrets.compare_digest(password, PASSWORD):
        raise HTTPException(403, 'Contraseña incorrecta o insegura')
    token = secrets.token_urlsafe(32)
    SESSIONS.add(token)
    destination = (next if next.startswith('/configure-sql?') and '\\' not in next and '//' not in next else
                   ('/databases?db_request_id=' + quote(db_request_id)) if db_request_id else
                   ('/?request_id=' + quote(request_id)))
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie('lan_session', token, httponly=True, samesite='strict', secure=False,
                        max_age=3600)
    return response


@app.get('/')
def index(request: Request, request_id: str = ''):
    if request.cookies.get('lan_session', '') not in SESSIONS:
        return RedirectResponse('/login?request_id=' + quote(request_id))
    if not request_id:
        return page('<h1>Conector Windows</h1><p>Abre Fuentes de datos en Streamlit '
                    'y pulsa Iniciar búsqueda en Windows para vincular la configuración.</p>')
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
                '<label>IP <input name="host" placeholder="192.168.1.100" required></label>'
                '<label>Puerto <input name="port" type="number" min="1" max="65535" value="1433" required></label>'
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
    if not request_id:
        raise HTTPException(400, 'Inicia la búsqueda desde Streamlit')
    # Validar alcance TCP también para entradas manuales; no inicia sesión SQL.
    reachable = await asyncio.to_thread(probe, (str(ip), port, engine))
    if reachable is None:
        raise HTTPException(400, 'No se puede conectar al puerto TCP indicado desde Windows')
    try:
        rows = await asyncio.to_thread(supabase, 'PATCH', 'lan_discovery_requests',
            params={'id': 'eq.' + request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat()},
            json={'selected_host': host, 'selected_port': port,
                  'selected_engine': engine})
    except requests.RequestException:
        raise HTTPException(502, 'No se pudo comunicar la selección a Supabase')
    if not rows:
        raise HTTPException(409, 'Solicitud vencida o ya utilizada')
    # Continuar dentro de esta misma pestaña: crear la solicitud SQL automáticamente.
    if engine == 'SQL Server':
        import uuid
        rid = str(uuid.uuid4())
        try:
            await asyncio.to_thread(supabase, 'POST', 'lan_db_requests', json={
                'id': rid, 'host': str(ip), 'port': port, 'engine': engine,
                'status': 'pending',
                'expires_at': (datetime.now(timezone.utc) + __import__('datetime').timedelta(minutes=15)).isoformat()
            })
        except Exception as exc:
            logger.warning('No se pudo iniciar la consulta SQL: %s', type(exc).__name__)
            return page('<h1>Servidor seleccionado</h1><p>No se pudo abrir el paso SQL. '
                        'Revisa el registro del conector y vuelve a intentarlo.</p>')
        # Guardar vínculo entre la solicitud LAN y la consulta de bases.
        WIZARD_REQUESTS[rid] = request_id
        return RedirectResponse('/databases?' + urlencode({'db_request_id': rid}), status_code=303)
    return page('<h1>Servidor seleccionado</h1><p>La configuración automática de bases '
                'está disponible actualmente para SQL Server.</p>')



# Credenciales SQL protegidas con DPAPI para la cuenta Windows del conector.
# Nunca se transmiten a Supabase ni se escriben en bridge.env.
import base64
import ctypes
import json
from ctypes import wintypes

CREDENTIALS_PATH = Path(os.environ.get('PROGRAMDATA', str(Path.home()))) / 'ConsultaPrecios' / 'sql_credentials.dpapi'

class _BLOB(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]

def _blob(data):
    buf = ctypes.create_string_buffer(data)
    return _BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))), buf

def _dpapi(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('El almacenamiento seguro requiere Windows')
    source, keepalive = _blob(data)
    result = _BLOB()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if decrypt:
        ok = fn(ctypes.byref(source), None, None, None, None, 0x01, ctypes.byref(result))
    else:
        ok = fn(ctypes.byref(source), 'ConsultaPrecios SQL', None, None, None, 0x01, ctypes.byref(result))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(result.pbData)

def _saved_credentials():
    if not CREDENTIALS_PATH.is_file():
        return {}
    return json.loads(_dpapi(base64.b64decode(CREDENTIALS_PATH.read_bytes()), True).decode('utf-8'))

def _save_credentials(data):
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    saved = _saved_credentials()
    saved[data['server']] = {k: data[k] for k in ('mode', 'user', 'password', 'driver', 'trust_certificate', 'instance')}
    encrypted = base64.b64encode(_dpapi(json.dumps(saved).encode('utf-8')))
    tmp = CREDENTIALS_PATH.with_suffix('.tmp')
    tmp.write_bytes(encrypted)
    tmp.replace(CREDENTIALS_PATH)

def _server_key(host, port):
    return f'{host}:{int(port)}'

def _sql_target(host, port, instance=''):
    """Use the selected LAN IP; optionally address a named instance on that host."""
    ip = ipaddress.ip_address(host)
    if ip.version != 4 or not any(ip in network for network in ALLOWED):
        raise ValueError('IP fuera de la red autorizada')
    if not 1 <= int(port) <= 65535:
        raise ValueError('Puerto inválido')
    instance = instance.strip()
    if instance:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', instance):
            raise ValueError('Nombre de instancia inválido')
        # A named instance is resolved by SQL Browser, without assuming the scanned port.
        return f'{host}\\{instance}'
    return f'tcp:{host},{int(port)}'


def sql_databases(host, port, mode, user='', password='', driver='SQL Server',
                  trust_certificate=False, instance=''):
    import pyodbc
    server = _sql_target(host, port, instance)
    available = pyodbc.drivers()
    if driver not in ('SQL Server', 'ODBC Driver 17 for SQL Server',
                      'ODBC Driver 18 for SQL Server') or driver not in available:
        raise ValueError('Controlador ODBC no instalado o no admitido')
    conn_str = f'DRIVER={{{driver}}};SERVER={server};DATABASE=master;Connection Timeout=8;'
    if driver != 'SQL Server':
        conn_str += 'Encrypt=yes;TrustServerCertificate=' + ('yes' if trust_certificate else 'no') + ';'
    if mode == 'windows':
        conn_str += 'Trusted_Connection=yes;'
    elif mode == 'sql':
        if not user or not password:
            raise ValueError('Indica usuario y contraseña SQL')
        def enc(value):
            return '{' + value.replace('}', '}}') + '}'
        conn_str += 'UID=' + enc(user) + ';PWD=' + enc(password) + ';'
    else:
        raise ValueError('Autenticación inválida')
    with pyodbc.connect(conn_str, timeout=8, autocommit=True) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1 ORDER BY name")
        return [str(row[0]) for row in cursor.fetchall()][:200]

def discover_sql_instances(host):
    """Best-effort SQL Browser UDP/1434 discovery. May return [] when blocked."""
    ip = ipaddress.ip_address(host)
    if ip.version != 4 or not any(ip in network for network in ALLOWED):
        raise ValueError('IP fuera de la red autorizada')
    result = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(1.0)
            sock.sendto(bytes([3]), (str(ip), 1434))
            packet, source = sock.recvfrom(8192)
            if source[0] != str(ip):
                return []
        fields = packet.decode('latin-1', errors='replace').split(';')
        for i in range(len(fields) - 1):
            if fields[i].lower() == 'instancename':
                name = fields[i + 1].strip()
                if re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) and name not in result:
                    result.append(name)
    except (OSError, TimeoutError):
        pass
    return result[:30]


async def _db_request(db_request_id):
    import uuid
    uuid.UUID(db_request_id)
    rows = await asyncio.to_thread(supabase, 'GET', 'lan_db_requests',
        params={'id': 'eq.' + db_request_id, 'status': 'eq.pending',
                'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat(),
                'select': 'id,host,port,engine'})
    if not rows:
        raise HTTPException(400, 'Solicitud inexistente, vencida o utilizada. Regresa a Streamlit.')
    if rows[0]['engine'] != 'SQL Server':
        raise HTTPException(400, 'Solo se admite SQL Server')
    return rows[0]

@app.get('/databases')
async def databases_page(request: Request, db_request_id: str = ''):
    if request.cookies.get('lan_session', '') not in SESSIONS:
        return RedirectResponse('/login?db_request_id=' + quote(db_request_id))
    try:
        item = await _db_request(db_request_id)
    except Exception:
        return page('<h1>Solicitud vencida o inválida</h1><p>Inicia otra búsqueda desde Streamlit.</p>')
    host, port = item['host'], item['port']
    server = _server_key(host, port)
    try:
        saved = await asyncio.to_thread(_saved_credentials)
        has_saved = server in saved
    except Exception:
        has_saved = False
    rid = html.escape(db_request_id, quote=True)
    content = ('<h1>Conectar a SQL Server</h1><p>Servidor: <strong>' + html.escape(server) + '</strong></p>'
               '<p>La contraseña se utiliza solo en Windows; no se envía a Supabase.</p>'
               '<form method="post" action="/databases">'
               f'<input type="hidden" name="db_request_id" value="{rid}">')
    if has_saved:
        content += ('<p>Hay credenciales protegidas guardadas para este servidor.</p>'
                    '<button name="use_saved" value="yes">Conectar con credenciales guardadas</button><hr>')
    instances = await asyncio.to_thread(discover_sql_instances, host)
    if instances:
        content += '<p><label>Instancias detectadas <select name="detected_instance"><option value="">Usar IP y puerto</option>'
        for name in instances:
            content += ('<option value="' + html.escape(name, quote=True) + '">'
                        + html.escape(host + '\\\\' + name) + '</option>')
        content += '</select></label></p>'
    else:
        content += '<p>No se detectaron nombres de instancia mediante SQL Browser. Puedes escribir uno manualmente.</p>'
    content += ('<label>Autenticación <select name="mode">'
                '<option value="sql">SQL Server (usuario y contraseña)</option>'
                '<option value="windows">Windows (cuenta que ejecuta el conector)</option>'
                '</select></label><p><label>Usuario SQL <input name="user" autocomplete="username"></label></p>'
                '<p><label>Contraseña SQL <input type="password" name="password" autocomplete="current-password"></label></p>'
                '<p><label>Instancia SQL (opcional) <input name="instance" placeholder="Ej.: technotel"></label></p>'
                '<p><label>Controlador <select name="driver">'
                '<option value="SQL Server">SQL Server (clásico)</option>'
                '<option value="ODBC Driver 18 for SQL Server">ODBC Driver 18</option>'
                '<option value="ODBC Driver 17 for SQL Server">ODBC Driver 17</option>'
                '</select></label></p>'
                '<p><label><input type="checkbox" name="trust_certificate" value="yes"> '
                'Confiar en certificado del servidor (solo redes de confianza)</label></p>'
                '<p><label><input type="checkbox" name="save" value="yes"> Guardar protegidas en este Windows</label></p>'
                '<button>Probar conexión y consultar bases</button></form>'
                '<p>La autenticación Windows usa la identidad de la tarea programada, no necesariamente tu sesión.</p>')
    return page(content)

@app.post('/databases')
async def databases_run(request: Request, db_request_id: str = Form(...),
                        mode: str = Form('sql'), user: str = Form(''),
                        password: str = Form(''), save: str = Form(''),
                        use_saved: str = Form(''), driver: str = Form('SQL Server'),
                        instance: str = Form(''), trust_certificate: str = Form(''),
                        detected_instance: str = Form('')):
    auth(request)
    # Evita formularios enviados desde otros sitios al conector local.
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origen de formulario no autorizado')
    try:
        item = await _db_request(db_request_id)
        server = _server_key(item['host'], item['port'])
        if use_saved == 'yes':
            cred = (await asyncio.to_thread(_saved_credentials)).get(server)
            if not cred:
                raise ValueError('No hay credenciales guardadas para este servidor')
            mode, user, password = cred['mode'], cred['user'], cred['password']
            driver = cred.get('driver', 'SQL Server')
            instance = cred.get('instance', '')
            trust_certificate = 'yes' if cred.get('trust_certificate') else ''
        if not instance.strip() and detected_instance.strip():
            instance = detected_instance.strip()
        names = await asyncio.to_thread(sql_databases, item['host'], int(item['port']),
                                        mode, user, password, driver,
                                        trust_certificate == 'yes', instance)
        if save == 'yes' and use_saved != 'yes':
            await asyncio.to_thread(_save_credentials, {'server': server, 'mode': mode,
                                                       'user': user if mode == 'sql' else '',
                                                       'password': password if mode == 'sql' else '',
                                                        'driver': driver, 'instance': instance,
                                                        'trust_certificate': trust_certificate == 'yes'})
        updated = await asyncio.to_thread(supabase, 'PATCH', 'lan_db_requests',
            params={'id': 'eq.' + db_request_id, 'status': 'eq.pending',
                    'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat()},
            json={'status': 'done', 'database_names': names})
        if not updated:
            raise HTTPException(409, 'La solicitud venció durante la consulta')
        session = request.cookies.get('lan_session', '')
        DB_RESULTS[session] = (db_request_id, names)
        options = ''.join('<option value="' + html.escape(name, quote=True) + '">'
                          + html.escape(name) + '</option>' for name in names)
        return page('<h1>Bases de datos encontradas</h1><p>Conexión correcta. '
                    'Selecciona la base que deseas utilizar:</p>'
                    '<form method="post" action="/choose-database">'
                    '<select name="database" required>' + options + '</select>'
                    '<button>Confirmar base de datos</button></form>'
                    '<p>La lista de bases ya fue enviada a Supabase. '
                    'La selección individual aún requiere integración con Streamlit.</p>')
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning('Fallo en búsqueda de bases SQL: tipo=%s', type(exc).__name__)
        return page('<h1>No se pudieron consultar las bases</h1><p>Tipo de error: '
                    + html.escape(type(exc).__name__) + '.</p>'
                    '<p>Comprueba las credenciales, permisos SQL y certificado TLS. '
                    'No se guardaron credenciales si la conexión falló.</p>'
                    '<p>La solicitud sigue pendiente; puedes reintentar.</p>')

@app.post('/choose-database')
async def choose_database(request: Request, database: str = Form(...)):
    auth(request)
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origen de formulario no autorizado')
    session = request.cookies.get('lan_session', '')
    entry = DB_RESULTS.get(session)
    if not entry or database not in entry[1]:
        raise HTTPException(400, 'Selección no válida o sesión vencida')
    db_request_id = entry[0]
    discovery_id = WIZARD_REQUESTS.get(db_request_id)
    if not discovery_id:
        raise HTTPException(409, 'La sesión del asistente venció. Inicia otra búsqueda.')
    try:
        updated = await asyncio.to_thread(supabase, 'PATCH', 'lan_discovery_requests',
            params={'id': 'eq.' + discovery_id, 'status': 'eq.pending'},
            json={'selected_database': database, 'status': 'selected'})
    except requests.RequestException:
        raise HTTPException(502, 'No se pudo enviar la selección final a Supabase') from None
    if not updated:
        raise HTTPException(409, 'La solicitud ya fue utilizada o venció')
    DB_RESULTS.pop(session, None)
    WIZARD_REQUESTS.pop(db_request_id, None)
    return_url = os.getenv('STREAMLIT_RETURN_URL', 'https://verificadordeprecios.streamlit.app/2_Fuentes_de_datos').strip()
    if return_url.startswith('https://'):
        return RedirectResponse(return_url.rstrip('/') + ('&' if '?' in return_url else '?') + urlencode({'lan_result': discovery_id}), status_code=303)
    return page('<h1>Configuración completada</h1><p>Base de datos: <strong>'
                + html.escape(database) + '</strong>.</p><p>Para volver automáticamente '
                'a Streamlit, configura STREAMLIT_RETURN_URL en bridge.env.</p>')




# Procesadores de solicitudes de consulta externas.
# Las credenciales SQL permanecen cifradas mediante DPAPI en Windows.
def _sql_identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128 or '\x00' in value:
        raise ValueError('Nombre de columna, esquema o tabla inválido')
    return '[' + value.replace(']', ']]') + ']'


def _external_connection(host, port, database):
    try:
        import pyodbc
    except ModuleNotFoundError as exc:
        raise RuntimeError('Falta el modulo pyodbc dentro del conector compilado. Recompila usando requirements.txt y build_windows.ps1 de v4.1.') from exc
    host = str(host)
    port = int(port)
    # _sql_target verifica que el servidor esté en una subred autorizada.
    server = _sql_target(host, port)
    saved = _saved_credentials().get(_server_key(host, port))
    if not saved:
        raise ValueError('Faltan credenciales SQL guardadas en este Windows para el servidor seleccionado')
    driver = saved.get('driver', 'SQL Server')
    if driver not in ('SQL Server', 'ODBC Driver 17 for SQL Server', 'ODBC Driver 18 for SQL Server'):
        raise ValueError('Controlador ODBC no admitido')
    if driver not in pyodbc.drivers():
        raise ValueError('El controlador ODBC seleccionado no está instalado')
    if not isinstance(database, str) or not database or len(database) > 128 or any(c in database for c in ';{}\x00'):
        raise ValueError('Nombre de base de datos inválido')
    server = _sql_target(host, port, saved.get('instance', ''))
    cs = f'DRIVER={{{driver}}};SERVER={server};DATABASE={database};Connection Timeout=8;'
    if driver != 'SQL Server':
        cs += 'Encrypt=yes;TrustServerCertificate=' + ('yes' if saved.get('trust_certificate') else 'no') + ';'
    if saved.get('mode') == 'windows':
        cs += 'Trusted_Connection=yes;'
    elif saved.get('mode') == 'sql':
        def esc(value):
            return '{' + str(value).replace('}', '}}') + '}'
        cs += 'UID=' + esc(saved.get('user', '')) + ';PWD=' + esc(saved.get('password', '')) + ';'
    else:
        raise ValueError('Autenticación SQL no admitida')
    return pyodbc.connect(cs, timeout=8, autocommit=True)


def _execute_metadata(job):
    kind = job['kind']
    if kind not in ('databases', 'tables', 'columns'):
        raise ValueError('Tipo de exploración desconocido')
    database = job.get('database') if kind != 'databases' else 'master'
    if not database:
        raise ValueError('Debes elegir una base de datos')
    with _external_connection(job['host'], job['port'], database) as cn:
        cur = cn.cursor()
        if kind == 'databases':
            cur.execute("SELECT name FROM sys.databases WHERE state_desc='ONLINE' AND HAS_DBACCESS(name)=1 ORDER BY name")
            return [str(r[0]) for r in cur.fetchmany(500)]
        if kind == 'tables':
            cur.execute("SELECT TABLE_SCHEMA,TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE IN ('BASE TABLE','VIEW') ORDER BY TABLE_SCHEMA,TABLE_NAME")
            return [{'schema': str(r[0]), 'table': str(r[1])} for r in cur.fetchmany(2000)]
        schema = job.get('schema_name') or 'dbo'
        table = job.get('table_name')
        _sql_identifier(schema)
        _sql_identifier(table)
        cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=? AND TABLE_NAME=? ORDER BY ORDINAL_POSITION", schema, table)
        return [{'name': str(r[0])} for r in cur.fetchmany(500)]


def _execute_price(job):
    price_started = time.monotonic()
    rows = supabase('GET', 'external_price_sources', params={
        'id': 'eq.' + str(job['configuration_id']),
        'enabled': 'eq.true',
        'select': 'id,engine,host,port,database,schema_name,table_name,code_column,description_column,price_column',
        'limit': '1',
    })
    if not rows:
        raise ValueError('Configuración externa inexistente o deshabilitada')
    config = rows[0]
    logger.info('Precio: configuración leída en %.3f s', time.monotonic() - price_started)
    if config['engine'] != 'SQL Server':
        raise ValueError('Este conector actualmente ejecuta consultas de productos solo en SQL Server')
    schema = _sql_identifier(config.get('schema_name') or 'dbo')
    table = _sql_identifier(config['table_name'])
    code = _sql_identifier(config['code_column'])
    description = _sql_identifier(config['description_column'])
    price = _sql_identifier(config['price_column'])
    barcode = str(job['barcode']).strip()
    if not barcode or len(barcode) > 256:
        raise ValueError('Código de barras inválido')
    # Los identificadores se escapan y el código de barras siempre es un parámetro.
    sql = (f'SELECT TOP (1) {code}, {description}, {price} '
           f'FROM {schema}.{table} WHERE {code} = ?')
    logger.info('Consulta SQL: preparando conexión (sin mostrar credenciales)')
    connect_started = time.monotonic()
    with _external_connection(config['host'], config['port'], config['database']) as cn:
        logger.info('Consulta SQL: conexión establecida en %.3f s', time.monotonic() - connect_started)
        cur = cn.cursor()
        # pyodbc.Connection no garantiza un atributo timeout asignable.
        # El tiempo de conexión se configura en _external_connection.
        logger.info('Consulta SQL: ejecutando SELECT parametrizado')
        select_started = time.monotonic()
        cur.execute(sql, barcode)
        row = cur.fetchone()
        logger.info('Consulta SQL: SELECT finalizado en %.3f s; encontrado=%s; total=%.3f s',
                    time.monotonic() - select_started, row is not None,
                    time.monotonic() - price_started)
        if row is None:
            return None
        if row[2] is None:
            raise ValueError('El producto encontrado no tiene precio')
        # json no admite Decimal directamente; el precio se devuelve como texto decimal.
        return {'barcode': str(row[0]), 'name': str(row[1] or ''),
                'price': str(row[2])}



def _execute_catalog(job):
    """Listado paginado desde la fuente elegida, nunca desde una base fija."""
    rows = supabase('GET', 'external_price_sources', params={
        'id': 'eq.' + str(job['configuration_id']),
        'enabled': 'eq.true',
        'select': 'id,engine,host,port,database,schema_name,table_name,code_column,description_column,price_column',
        'limit': '1',
    })
    if not rows:
        raise ValueError('La configuración seleccionada no existe o está deshabilitada')
    cfg = rows[0]
    if cfg['engine'] != 'SQL Server':
        raise ValueError('El listado externo requiere un conector compatible con este motor; actualmente SQL Server')
    schema = _sql_identifier(cfg.get('schema_name') or 'dbo')
    table = _sql_identifier(cfg['table_name'])
    code = _sql_identifier(cfg['code_column'])
    description = _sql_identifier(cfg['description_column'])
    price = _sql_identifier(cfg['price_column'])
    page = int(job.get('page_number') or 1)
    size = int(job.get('page_size') or 25)
    if page < 1 or not 1 <= size <= 100:
        raise ValueError('Paginación inválida')
    term = str(job.get('search_term') or '').strip()
    if len(term) > 120:
        raise ValueError('Filtro demasiado largo')
    # Convertir código a texto para permitir búsqueda incluso si su tipo es numérico.
    where = (f' WHERE (CONVERT(nvarchar(255), {code}) LIKE ? '
             f'OR CONVERT(nvarchar(4000), {description}) LIKE ?)') if term else ''
    args = ['%' + term.replace('[', '[[]').replace('%','[%]').replace('_','[_]') + '%'] * 2 if term else []
    base = f' FROM {schema}.{table}' + where
    sql_count = 'SELECT COUNT_BIG(1)' + base
    # ROW_NUMBER funciona en SQL Server 2005+ y evita OFFSET/FETCH (2012+).
    # El código configurado se usa como orden estable; no se fija ninguna tabla.
    sql_rows = (
        f'SELECT paged.product_code, paged.product_name, paged.product_price '
        f'FROM (SELECT {code} AS product_code, '
        f'{description} AS product_name, {price} AS product_price, '
        f'ROW_NUMBER() OVER (ORDER BY {code}) AS row_num'
        + base + ') AS paged '
        'WHERE paged.row_num > ? AND paged.row_num <= ? '
        'ORDER BY paged.row_num'
    )
    with _external_connection(cfg['host'], cfg['port'], cfg['database']) as cn:
        cur = cn.cursor()
        cur.execute(sql_count, *args)
        total = int(cur.fetchone()[0])
        start_row = (page - 1) * size
        end_row = start_row + size
        cur.execute(sql_rows, *(args + [start_row, end_row]))
        products = [{'barcode': str(r[0] if r[0] is not None else ''),
                     'name': str(r[1] if r[1] is not None else ''),
                     'price': str(r[2]) if r[2] is not None else None}
                    for r in cur.fetchall()]
    return {'total': total, 'products': products, 'page': page, 'page_size': size}

def _process_external_queue(table, select, execute):
    global WORKER_LAST_JOB, WORKER_LAST_ERROR, WORKER_JOB_COUNT
    now = datetime.now(timezone.utc).isoformat()
    jobs = supabase('GET', table, params={
        'status': 'eq.pending', 'expires_at': 'gt.' + now,
        'order': 'created_at.asc', 'limit': '5', 'select': select,
    })
    for job in jobs:
        jid = str(job['id'])
        claimed = supabase('PATCH', table, params={
            'id': 'eq.' + jid, 'status': 'eq.pending',
            'expires_at': 'gt.' + datetime.now(timezone.utc).isoformat(),
        }, json={'status': 'processing'})
        if not claimed:
            continue
        try:
            WORKER_LAST_JOB = datetime.now(timezone.utc).isoformat()
            WORKER_JOB_COUNT += 1
            logger.info('Iniciando trabajo %s; id=%s', table, jid)
            result = execute(job)
            supabase('PATCH', table, params={
                'id': 'eq.' + jid, 'status': 'eq.processing',
            }, json={'status': 'done', 'result': result, 'error_message': None})
            WORKER_LAST_ERROR = None
            logger.info('Trabajo %s completado; id=%s; encontrado=%s', table, jid, result is not None)
        except Exception as exc:
            WORKER_LAST_ERROR = type(exc).__name__
            # Registrar la ubicación exacta del fallo sin volcar mensajes de
            # excepciones ODBC, que podrían contener datos de conexión.
            logger.error('Error al ejecutar solicitud %s (id=%s): %s\n%s',
                         table, jid, type(exc).__name__,
                         ''.join(traceback.format_tb(exc.__traceback__)))
            try:
                supabase('PATCH', table, params={
                    'id': 'eq.' + jid, 'status': 'eq.processing',
                }, json={'status': 'error', 'error_message': str(exc)[:350]})
            except Exception:
                logger.exception('No se pudo publicar el error de la solicitud')


def _price_worker():
    """Prioridad a precios; no esperar consultas de metadatos o catálogos."""
    global WORKER_LAST_POLL
    while True:
        try:
            _process_external_queue('external_price_jobs',
                                    'id,configuration_id,barcode', _execute_price)
        except Exception as exc:
            logger.error('Fallo al consultar cola external_price_jobs: %s\n%s',
                         type(exc).__name__, ''.join(traceback.format_tb(exc.__traceback__)))
        WORKER_LAST_POLL = time.monotonic()
        time.sleep(1)


def _external_worker():
    """Conservar las otras colas sin bloquear la consulta de precios."""
    while True:
        for table, fields, handler in (
            ('external_metadata_jobs',
             'id,kind,host,port,database,schema_name,table_name', _execute_metadata),
            ('external_catalog_jobs',
             'id,configuration_id,page_number,page_size,search_term', _execute_catalog),
        ):
            try:
                _process_external_queue(table, fields, handler)
            except Exception as exc:
                logger.error('Fallo al consultar cola %s: %s\n%s',
                             table, type(exc).__name__, ''.join(traceback.format_tb(exc.__traceback__)))
        time.sleep(3)


@app.on_event('startup')
def _start_external_worker():
    threading.Thread(target=_price_worker, name='price-jobs', daemon=True).start()
    threading.Thread(target=_external_worker, name='external-jobs', daemon=True).start()
    logger.info('Procesadores de precios y catálogos externos iniciados')



@app.get('/configure-sql')
def configure_sql_page(request: Request, host: str = '', port: int = 1433):
    if request.cookies.get('lan_session', '') not in SESSIONS:
        return RedirectResponse('/login?next=' + quote('/configure-sql?' + urlencode({'host': host, 'port': port}), safe=''))
    try:
        _sql_target(host, port)
    except (ValueError, TypeError):
        raise HTTPException(400, 'Servidor o puerto fuera de la red autorizada')
    server = _server_key(host, port)
    try:
        saved = server in _saved_credentials()
    except Exception:
        saved = False
    options = ''.join(
        '<option value="' + html.escape(driver, quote=True) + '">' + html.escape(driver) + '</option>'
        for driver in ('SQL Server', 'ODBC Driver 17 for SQL Server', 'ODBC Driver 18 for SQL Server')
    )
    return page(
        '<h1>Credenciales SQL Server</h1>'
        '<p>Servidor: <strong>' + html.escape(server) + '</strong></p>'
        '<p>Las credenciales se introducen en este Windows y no pasan por Streamlit ni Supabase.</p>'
        + ('<p>Ya hay credenciales protegidas para este servidor. Puedes actualizarlas.</p>' if saved else '')
        + '<form method="post" action="/configure-sql">'
        + '<input type="hidden" name="host" value="' + html.escape(host, quote=True) + '">'
        + '<input type="hidden" name="port" value="' + str(port) + '">'
        + '<p><label>Autenticación <select name="mode">'
          '<option value="sql">SQL Server (usuario y contraseña)</option>'
          '<option value="windows">Windows (cuenta del conector)</option>'
          '</select></label></p>'
          '<p><label>Usuario SQL <input name="user" autocomplete="username"></label></p>'
          '<p><label>Contraseña SQL <input name="password" type="password" autocomplete="current-password"></label></p>'
          '<p><label>Instancia (opcional) <input name="instance"></label></p>'
          '<p><label>Controlador ODBC <select name="driver">' + options + '</select></label></p>'
          '<p><label><input type="checkbox" name="trust_certificate" value="yes"> Confiar en certificado SQL</label></p>'
          '<button>Probar y guardar credenciales en Windows</button></form>'
          '<p>Tras guardar, regresa a Streamlit y pulsa Detectar bases de datos.</p>'
    )


@app.post('/configure-sql')
async def configure_sql_save(
    request: Request, host: str = Form(...), port: int = Form(...),
    mode: str = Form('sql'), user: str = Form(''), password: str = Form(''),
    driver: str = Form('SQL Server'), instance: str = Form(''),
    trust_certificate: str = Form(''),
):
    auth(request)
    origin = request.headers.get('origin')
    if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Origen de formulario no autorizado')
    try:
        _sql_target(host, port, instance)
        names = await asyncio.to_thread(
            sql_databases, host, port, mode, user, password,
            driver, trust_certificate == 'yes', instance
        )
        await asyncio.to_thread(_save_credentials, {
            'server': _server_key(host, port),
            'mode': mode,
            'user': user if mode == 'sql' else '',
            'password': password if mode == 'sql' else '',
            'driver': driver,
            'instance': instance,
            'trust_certificate': trust_certificate == 'yes',
        })
        return page(
            '<h1>Conexión correcta</h1>'
            '<p>Credenciales protegidas guardadas en este Windows.</p>'
            '<p>Bases accesibles: ' + str(len(names)) + '</p>'
            '<p>Regresa a Configuración de bases externas en Streamlit '
            'y pulsa Detectar bases de datos.</p>'
        )
    except Exception as exc:
        logger.warning('Fallo configurando credenciales SQL: %s', type(exc).__name__)
        return page(
            '<h1>No se pudieron guardar las credenciales</h1>'
            '<p>No se guardó nada porque la prueba de conexión falló.</p>'
            '<p>Comprueba usuario, contraseña, controlador, instancia y certificado.</p>'
            '<p>Tipo de error: ' + html.escape(type(exc).__name__) + '</p>'
            '<p><a href="/configure-sql?' + urlencode({'host': host, 'port': port}) + '">Reintentar</a></p>'
        )


def main():
    if not URL or not KEY or not PASSWORD or len(PASSWORD) < 12:
        raise SystemExit('Configura bridge.env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY y BRIDGE_PASSWORD (12+ caracteres).')
    uvicorn.run(app, host=os.getenv('BRIDGE_HOST', '0.0.0.0'),
                port=int(os.getenv('BRIDGE_PORT', '8765')))


if __name__ == '__main__':
    main()
