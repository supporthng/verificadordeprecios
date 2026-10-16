"""Servidor LAN independiente para Consulta de Precios. No modifica el proyecto Streamlit."""
import json
import os
import re
import secrets
import threading
from pathlib import Path
from urllib.parse import quote_plus

import requests
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi import Depends
from sqlalchemy import create_engine, text

BASE = Path(__file__).resolve().parent
CONFIG = BASE / 'config.json'
EXAMPLE = BASE / 'config.example.json'
LOCK = threading.Lock()
app = FastAPI(title='Consulta de Precios LAN', docs_url=None, redoc_url=None)
security = HTTPBasic()
ENGINES = ['sqlite','sqlserver','mysql','mariadb','postgresql','firebird','access','oracle','db2','sqlanywhere','odbc','api_rest','supabase']


def cfg():
    path = CONFIG if CONFIG.exists() else EXAMPLE
    return json.loads(path.read_text(encoding='utf-8'))


def admin_auth(credentials: HTTPBasicCredentials = Depends(security)):
    expected = os.getenv('LOCAL_ADMIN_PASSWORD', '')
    if not expected:
        raise HTTPException(503, 'Configure LOCAL_ADMIN_PASSWORD en Windows antes de administrar')
    if not (secrets.compare_digest(credentials.username, 'admin') and secrets.compare_digest(credentials.password, expected)):
        raise HTTPException(401, 'Acceso denegado', headers={'WWW-Authenticate': 'Basic realm="Administracion local"'})
    return True


def sql_connection(c):
    engine = c['engine']
    host = c.get('host','127.0.0.1')
    port = c.get('port','')
    db = c.get('database','')
    user = quote_plus(c.get('username',''))
    pw = quote_plus(os.getenv('SOURCE_DB_PASSWORD',''))
    addr = f'{host}:{port}' if port else host
    if engine == 'sqlite':
        return create_engine('sqlite:///' + db.replace('\\','/'), connect_args={'timeout':5})
    if engine in ('mysql','mariadb'):
        return create_engine(f'mysql+pymysql://{user}:{pw}@{addr}/{quote_plus(db)}', pool_pre_ping=True)
    if engine == 'postgresql':
        return create_engine(f'postgresql+psycopg2://{user}:{pw}@{addr}/{quote_plus(db)}', pool_pre_ping=True)
    if engine in ('sqlserver','access','sqlanywhere','odbc'):
        driver = c.get('odbc_driver','ODBC Driver 18 for SQL Server')
        if engine == 'access':
            conn = f'DRIVER={{{driver}}};DBQ={db};'
        else:
            conn = f'DRIVER={{{driver}}};SERVER={addr};DATABASE={db};UID={c.get("username","")};PWD={os.getenv("SOURCE_DB_PASSWORD","")};'
            if engine == 'sqlserver':
                conn += 'Encrypt=yes;TrustServerCertificate=no;'
        # pyodbc SQL Server dialect; generic ODBC dialect compatibility depends on driver.
        return create_engine('mssql+pyodbc:///?odbc_connect='+quote_plus(conn), pool_pre_ping=True)
    if engine == 'oracle':
        return create_engine(f'oracle+oracledb://{user}:{pw}@{host}:{port or "1521"}/?service_name={quote_plus(db)}',pool_pre_ping=True)
    if engine == 'firebird':
        return create_engine(f'firebird+firebird://{user}:{pw}@{host}:{port or "3050"}/{db}',pool_pre_ping=True)
    if engine == 'db2':
        return create_engine(f'db2+ibm_db://{user}:{pw}@{addr}/{db}',pool_pre_ping=True)
    raise ValueError('Motor no soportado para SQL; use API REST si su controlador no es compatible')


def checked_select(sql, need_barcode=False):
    s = sql.strip()
    if not re.match(r'^SELECT\s', s, re.I) or ';' in s or '--' in s or '/*' in s:
        raise ValueError('Solo se permite una consulta SELECT sencilla, sin comentarios ni punto y coma')
    if need_barcode and ':barcode' not in s:
        raise ValueError('La consulta de búsqueda debe incluir :barcode')
    return s


def normalize(row):
    data = dict(row)
    if not {'barcode','name','price'} <= set(data):
        raise ValueError('La consulta debe devolver barcode, name y price')
    return {'barcode':str(data['barcode']).strip(), 'name':str(data['name']), 'price':float(data['price'])}


def remote_lookup(c, barcode):
    url = c.get('api_url','').strip()
    if not url.startswith('https://') and not (url.startswith('http://127.0.0.1') or url.startswith('http://localhost')):
        raise ValueError('API externa requiere HTTPS (o localhost para pruebas)')
    headers = {}
    token = os.getenv(c.get('api_key_env','SOURCE_API_KEY'), '')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if c['engine'] == 'supabase':
        anon = os.getenv('SUPABASE_ANON_KEY','')
        headers.update({'apikey':anon,'Authorization':'Bearer '+anon})
        url = os.getenv('SUPABASE_URL','').rstrip('/')+'/rest/v1/products'
        params = {'select':'barcode,name,price','barcode':'eq.'+barcode,'limit':'1'}
    else:
        params = {c.get('api_barcode_param','barcode'):barcode}
    response = requests.get(url, params=params, headers=headers, timeout=8)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload,dict) and 'product' in payload:
        payload=payload['product']
    if isinstance(payload,list):
        payload=payload[0] if payload else None
    return normalize(payload) if payload else None


def local_lookup(c, barcode):
    if c['engine'] in ('api_rest','supabase'):
        return remote_lookup(c,barcode)
    sql = checked_select(c.get('sql_lookup',''),need_barcode=True)
    engine = sql_connection(c)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(sql),{'barcode':barcode}).mappings().first()
            return normalize(row) if row else None
    finally:
        engine.dispose()


def cloud_lookup(barcode):
    url = os.getenv('SUPABASE_URL','').rstrip('/')
    key = os.getenv('SUPABASE_ANON_KEY','')
    if not url or not key:
        raise ValueError('Faltan SUPABASE_URL y SUPABASE_ANON_KEY')
    resp=requests.get(url+'/rest/v1/products',params={'select':'barcode,name,price','barcode':'eq.'+barcode,'limit':'1'},headers={'apikey':key,'Authorization':'Bearer '+key},timeout=8)
    resp.raise_for_status()
    items=resp.json()
    return normalize(items[0]) if items else None


def lookup(barcode):
    c=cfg()
    mode=c.get('mode','local')
    if mode == 'cloud':
        return cloud_lookup(barcode), 'nube'
    if mode == 'local':
        return local_lookup(c,barcode), 'local'
    if mode == 'auto':
        try:
            return local_lookup(c,barcode), 'local'
        except Exception:
            return cloud_lookup(barcode), 'nube (respaldo)'
    raise ValueError('Modo inválido')


HTML = '''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Consulta de precios</title><style>
*{box-sizing:border-box}body{margin:0;background:#f2f6fc;font-family:Arial,sans-serif;color:#102b50}.wrap{max-width:820px;margin:0 auto;padding:12px}.head{background:linear-gradient(120deg,#123963,#0759c9);border-radius:17px;color:white;text-align:center;padding:18px 10px}.head h1{font-size:clamp(21px,5vw,34px);margin:0}.head p{margin:5px 0 0}.label{text-align:center;font-size:clamp(19px,5vw,27px);font-weight:800;margin:24px 0 12px}input{width:100%;font-size:26px;padding:13px;border:2px solid #a7c5e9;border-radius:13px;text-align:center}.card{background:white;border-radius:17px;padding:25px 12px;text-align:center;margin-top:18px;box-shadow:0 5px 20px #1234}.name{font-size:clamp(23px,6vw,40px);font-weight:800;overflow-wrap:anywhere}.price{font-size:clamp(40px,9vw,74px);font-weight:900;color:#0759c9}.muted{color:#65758b}.error{color:#a42020}.hidden{display:none}@media(max-height:520px) and (orientation:landscape){.wrap{padding:4px}.head{padding:8px}.head h1{font-size:23px}.head p{display:none}.label{margin:8px 0}.card{margin-top:8px;padding:10px}.price{font-size:42px}}
</style></head><body><main class="wrap"><div id="waiting"><div class="head"><h1>🏷️ CONSULTA DE PRECIOS</h1><p>Escanea un producto</p></div><div class="label">ESCANEA TU CÓDIGO AQUÍ</div><form id="form"><input id="barcode" aria-label="Código de barras" autocomplete="off" autofocus inputmode="none"></form></div><div id="result" class="hidden card"></div></main><script>
const form=document.getElementById('form'),input=document.getElementById('barcode'),wait=document.getElementById('waiting'),result=document.getElementById('result');let timer=null;
function reset(){result.classList.add('hidden');wait.classList.remove('hidden');input.value='';input.focus()}
form.addEventListener('submit',async e=>{e.preventDefault();const code=input.value.trim();if(!code)return;clearTimeout(timer);wait.classList.add('hidden');result.classList.remove('hidden');result.textContent='Buscando...';try{const r=await fetch('/api/product/'+encodeURIComponent(code));const d=await r.json();if(!r.ok)throw Error(d.detail||'Error de conexión');result.replaceChildren();if(d.product){const n=document.createElement('div'),b=document.createElement('div'),p=document.createElement('div'),s=document.createElement('div');n.className='name';n.textContent=d.product.name;b.className='muted';b.textContent='Código: '+d.product.barcode;p.className='price';p.textContent='RD$ '+Number(d.product.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});s.className='muted';s.textContent='Origen: '+d.source;result.append(n,b,p,s)}else result.textContent='Producto no encontrado';}catch(err){result.textContent='No se pudo consultar el precio: '+err.message;result.classList.add('error')}timer=setTimeout(reset,10000)});
window.addEventListener('load',()=>input.focus());
</script></body></html>'''


@app.get('/',response_class=HTMLResponse)
def home():
    return HTML


@app.get('/api/product/{barcode}')
def product(barcode: str):
    if not barcode or len(barcode)>128:
        raise HTTPException(400,'Código inválido')
    try:
        item,source=lookup(barcode)
        return {'product':item,'source':source}
    except Exception as exc:
        # No revelar host/credenciales/detalles SQL a usuarios de la red.
        print('Error consulta:',type(exc).__name__,str(exc)[:300])
        raise HTTPException(503,'Fuente de precios no disponible') from None


@app.get('/admin',response_class=HTMLResponse)
def admin_page(_:bool=Depends(admin_auth)):
    c=cfg()
    def esc(x):
        import html
        return html.escape(str(x),quote=True)
    options=''.join(f'<option value="{e}" {"selected" if c.get("engine")==e else ""}>{e}</option>' for e in ENGINES)
    modes=''.join(f'<option value="{e}" {"selected" if c.get("mode")==e else ""}>{e}</option>' for e in ('local','cloud','auto'))
    fields=''.join(f'<label>{name}<input name="{key}" value="{esc(c.get(key,""))}"></label>' for key,name in [('host','Servidor/IP'),('port','Puerto'),('database','Base de datos o ruta de archivo'),('username','Usuario de solo lectura'),('odbc_driver','Driver ODBC'),('api_url','URL de API REST HTTPS'),('api_key_env','Variable de entorno de token API'),('api_barcode_param','Parámetro de código de barras')])
    return HTMLResponse(f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fuentes de datos</title><style>body{{font-family:Arial;max-width:780px;margin:auto;padding:18px;background:#f2f6fc}}form{{background:white;padding:18px;border-radius:12px}}label{{display:block;margin:10px 0;font-weight:bold}}input,select,textarea{{width:100%;padding:10px;box-sizing:border-box}}textarea{{min-height:90px}}button{{padding:12px;margin:8px 4px 0 0;cursor:pointer}}small{{color:#555}}</style><h1>Configuración de fuentes de datos</h1><p>Esta pantalla se abre en el servidor Windows. Requiere usuario <b>admin</b> y LOCAL_ADMIN_PASSWORD.</p><form method="post" action="/admin/save"><label>Modo<select name="mode">{modes}</select></label><label>Motor<select name="engine">{options}</select></label>{fields}<label>SQL para buscar producto (columnas barcode, name, price; parámetro :barcode)<textarea name="sql_lookup">{esc(c.get('sql_lookup',''))}</textarea></label><label>SQL para sincronización (columnas barcode, name, price)<textarea name="sql_sync">{esc(c.get('sql_sync',''))}</textarea></label><button type="submit">Guardar configuración</button></form><form method="post" action="/admin/test"><button type="submit">Probar conexión y consulta</button></form><p><small>Las contraseñas no se guardan aquí: SOURCE_DB_PASSWORD, SOURCE_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY y SUPABASE_SERVICE_ROLE_KEY se configuran como variables de entorno en Windows. Use una cuenta de lectura para el origen.</small></p><p><a href="/">Abrir verificador local</a></p></html>''')


@app.post('/admin/save')
async def save(request:Request, _:bool=Depends(admin_auth)):
    form=await request.form()
    allowed={'mode','engine','host','port','database','username','odbc_driver','api_url','api_key_env','api_barcode_param','sql_lookup','sql_sync'}
    current=cfg()
    for k in allowed:
        if k in form:
            current[k]=str(form[k]).strip()
    if current['mode'] not in ('local','cloud','auto') or current['engine'] not in ENGINES:
        raise HTTPException(400,'Modo o motor inválido')
    if current['engine'] not in ('api_rest','supabase'):
        checked_select(current['sql_lookup'],True)
        checked_select(current['sql_sync'])
    with LOCK:
        tmp=CONFIG.with_suffix('.tmp')
        tmp.write_text(json.dumps(current,indent=2,ensure_ascii=False),encoding='utf-8')
        tmp.replace(CONFIG)
    return RedirectResponse('/admin',status_code=303)


@app.post('/admin/test',response_class=HTMLResponse)
def test(_:bool=Depends(admin_auth)):
    try:
        c=cfg()
        if c.get('mode')=='cloud':
            cloud_lookup('__PRUEBA_INEXISTENTE__')
        elif c.get('engine') in ('api_rest','supabase'):
            remote_lookup(c,'__PRUEBA_INEXISTENTE__')
        else:
            engine=sql_connection(c)
            try:
                with engine.connect() as conn:
                    conn.execute(text('SELECT 1'))
            finally:
                engine.dispose()
        message='Conexión establecida. Compruebe también un código de barras real en el verificador.'
    except Exception as exc:
        message=f'No se pudo conectar: {type(exc).__name__}. Consulte la consola del servidor.'
        print('Error prueba:',type(exc).__name__,str(exc)[:500])
    import html
    return f'<h2>{html.escape(message)}</h2><p><a href="/admin">Volver a configuración</a></p>'
