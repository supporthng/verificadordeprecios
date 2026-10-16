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
DB_RESULTS = {}  # session-token -> (request id, accessible database names)


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
            sock.sendto(b'\\x03', (str(ip), 1434))
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
    # Do not invent a database-selection field in the Supabase schema.
    return page('<h1>Base elegida: ' + html.escape(database) + '</h1>'
                '<p>La consulta de bases se envió a Supabase. '
                'Por ahora selecciona esta misma base en Streamlit; '
                'para automatizar este último paso hay que actualizar también Streamlit y su esquema de datos.</p>')


def main():
    if not URL or not KEY or not PASSWORD or len(PASSWORD) < 12:
        raise SystemExit('Configura bridge.env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY y BRIDGE_PASSWORD (12+ caracteres).')
    uvicorn.run(app, host=os.getenv('BRIDGE_HOST', '0.0.0.0'),
                port=int(os.getenv('BRIDGE_PORT', '8765')))


if __name__ == '__main__':
    main()
