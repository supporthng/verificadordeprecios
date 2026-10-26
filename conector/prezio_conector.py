"""Prezio · Conector de bases de datos (SQL Server, MySQL / MariaDB, PostgreSQL y Firebird).

Se instala en la PC donde está el sistema de facturación. Cada pocos minutos lee los precios de la base del
negocio y los envía a Prezio (solo cuando cambiaron). Lo configura la app Prezio Administrador (buscar el
servidor en la red, autorizar con las credenciales de la base y elegir tabla y columnas). Habla únicamente con la dirección de Prezio, con su propia
clave de conector; nunca usa claves de Supabase.

Uso:
    PrezioConector.exe                 la primera vez configura; después trabaja sin parar
    PrezioConector.exe --configurar    cambiar la configuración
    PrezioConector.exe --una-vez       enviar ahora y salir
    PrezioConector.exe --instalar      arrancar solo al encender la PC (tarea de Windows, requiere administrador)
    PrezioConector.exe --desinstalar   quitar el arranque automático
"""

import argparse
import base64
import getpass
import hashlib
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from contextlib import closing
from decimal import Decimal, InvalidOperation
from logging.handlers import RotatingFileHandler
from pathlib import Path

VERSION = "2.0.0"
CARPETA = Path(os.environ.get("PROGRAMDATA") or (Path.home() / ".prezio")) / "Prezio"
CONFIG = CARPETA / "conector.json"
ESTADO = CARPETA / "estado.json"
PARTE = 2000
CONTROLADORES = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")
REENVIAR_HORAS = 12      # aunque nada cambie, se reenvía cada tantas horas
# Actualización automática (solo PrezioConector.exe de consola; la app Prezio Administrador tiene la suya).
ORIGEN_ACTUALIZACION = "https://github.com/supporthng/prezio/releases/download/"
CADA_REVISION_S = 6 * 60 * 60

log = logging.getLogger("prezio")


# ---------------------------------------------------------------- claves guardadas (cifradas con Windows)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cifrado import proteger, revelar  # noqa: E402,F401
import motores  # noqa: E402


# ---------------------------------------------------------------- archivos
def leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


def preparar_registro(consola: bool) -> None:
    CARPETA.mkdir(parents=True, exist_ok=True)
    log.setLevel(logging.INFO)
    archivo = RotatingFileHandler(CARPETA / "conector.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    archivo.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(archivo)
    if consola:
        pantalla = logging.StreamHandler(sys.stdout)
        pantalla.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        log.addHandler(pantalla)


# ---------------------------------------------------------------- Prezio
class ErrorPrezio(Exception):
    def __init__(self, mensaje, estado=0):
        super().__init__(mensaje)
        self.estado = estado


def prezio(cfg: dict, cuerpo: dict, segundos: int = 90) -> dict:
    datos = json.dumps({**cuerpo, "clave": revelar(cfg["clave"])}).encode("utf-8")
    pedido = urllib.request.Request(cfg["sitio"].rstrip("/") + "/api/conector", data=datos, method="POST",
                                    headers={"Content-Type": "application/json", "User-Agent": f"PrezioConector/{VERSION}"})
    try:
        with urllib.request.urlopen(pedido, timeout=segundos) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            mensaje = json.loads(e.read().decode("utf-8")).get("error") or str(e)
        except ValueError:
            mensaje = str(e)
        raise ErrorPrezio(mensaje, e.code) from None
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise ErrorPrezio(f"Sin conexión con Prezio ({getattr(e, 'reason', e)})") from None


def estado_prezio(cfg: dict, error: str | None = None) -> dict:
    return prezio(cfg, {"accion": "estado", "version": VERSION, "equipo": platform.node()[:80], "error": error})


# ---------------------------------------------------------------- SQL Server
def _seguro(valor: str, que: str) -> str:
    if not valor or len(valor) > 200 or any(c in valor for c in ";{}\x00\r\n"):
        raise ValueError(f"{que} no válido")
    return valor


def cadena_conexion(sql: dict, base: str | None = None) -> str:
    controlador = sql.get("controlador") or "SQL Server"
    if controlador not in CONTROLADORES:
        raise ValueError("Controlador ODBC no admitido")
    cs = f"DRIVER={{{controlador}}};SERVER={_seguro(sql['servidor'], 'Servidor')};DATABASE={_seguro(base or sql.get('base') or 'master', 'Base de datos')};"
    if controlador != "SQL Server":
        cs += "Encrypt=yes;TrustServerCertificate=" + ("yes" if sql.get("confiar_certificado", True) else "no") + ";"
    if sql.get("modo") == "windows":
        cs += "Trusted_Connection=yes;"
    else:
        def esc(v):
            return "{" + str(v).replace("}", "}}") + "}"
        cs += "UID=" + esc(sql.get("usuario", "")) + ";PWD=" + esc(revelar(sql.get("clave", ""))) + ";"
    return cs + "APP=Prezio Conector;"


def conectar_sql(sql: dict, base: str | None = None):
    """Conexión a SQL Server con la configuración de la versión 1."""
    return motores.conectar(conexion_legada(sql), base)


def identificador(nombre: str) -> str:
    if not nombre or len(nombre) > 128 or "\x00" in nombre:
        raise ValueError("Nombre de tabla o columna no válido")
    return "[" + nombre.replace("]", "]]") + "]"


def consulta_de(mapeo: dict) -> str:
    """SELECT de solo lectura que devuelve código, nombre y precio."""
    if mapeo.get("consulta"):
        q = mapeo["consulta"].strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", q) or ";" in q:
            raise ValueError("La consulta propia debe ser un solo SELECT")
        return q
    esquema, _, tabla = mapeo["tabla"].rpartition(".")
    origen = (identificador(esquema) + "." if esquema else "") + identificador(tabla)
    return (f"SELECT {identificador(mapeo['codigo'])}, {identificador(mapeo['nombre'])}, {identificador(mapeo['precio'])} "
            f"FROM {origen}")


def codigo_limpio(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, Decimal) and v == v.to_integral_value():
        v = int(v)
    t = str(v).strip()
    return t[:-2] if re.fullmatch(r"\d+\.0", t) else t


def precio_limpio(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).replace("RD$", "").replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None
    if not d.is_finite() or d < 0 or d >= Decimal("1e12"):
        return None
    return float(round(d, 2))


def productos_de(filas) -> list[dict]:
    """Filas (código, nombre, precio) → productos válidos, sin códigos repetidos (gana el último)."""
    vistos: dict[str, dict] = {}
    for f in filas:
        codigo, nombre, precio = codigo_limpio(f[0]), str(f[1] or "").strip()[:200], precio_limpio(f[2])
        if not codigo or len(codigo) > 64 or not nombre or precio is None:
            continue
        vistos[codigo] = {"codigo": codigo, "nombre": nombre, "precio": precio}
    return list(vistos.values())


def conexion_legada(sql: dict) -> dict:
    """La configuración de la versión 1 (solo SQL Server, «servidor» como texto) en el formato de motores."""
    servidor = str(sql.get("servidor") or "")
    host, instancia, puerto = servidor, "", None
    if "," in servidor:
        host, _, p = servidor.partition(",")
        puerto = int(p) if p.strip().isdigit() else None
    if "\\" in host:
        host, _, instancia = host.partition("\\")
    return {"motor": "sqlserver", "host": host.strip(), "instancia": instancia.strip(), "puerto": puerto,
            "auth": "windows" if sql.get("modo") == "windows" else "sql", "usuario": sql.get("usuario", ""),
            "clave": sql.get("clave", ""), "base": sql.get("base"), "controlador": sql.get("controlador"),
            "confiar_certificado": sql.get("confiar_certificado", True)}


def leer_productos(cfg: dict, mapeo: dict, conectar=None) -> list[dict]:
    """Productos válidos de un inventario. Cada inventario tiene su conexión (versión 2) o usa la general (versión 1)."""
    if conectar is not None:   # pruebas: una conexión DB-API cualquiera
        with closing(conectar(cfg["sql"])) as conexion:
            cursor = conexion.cursor()
            cursor.execute(consulta_de(mapeo))
            return productos_de(cursor.fetchall())
    cx = mapeo.get("conexion") or conexion_legada(cfg.get("sql") or {})
    return productos_de(motores.leer(cx, mapeo))


# ---------------------------------------------------------------- enviar
def huella(productos: list[dict]) -> str:
    return hashlib.sha256(json.dumps(sorted((p["codigo"], p["nombre"], p["precio"]) for p in productos)).encode()).hexdigest()


def sincronizar(cfg: dict, conectar=None) -> dict:
    """Una vuelta: pregunta a Prezio qué inventarios llenar, lee SQL y envía lo que cambió."""
    estado = leer_json(ESTADO, {})
    info = estado_prezio(cfg)
    resumen = {"enviados": 0, "sin_cambios": 0, "errores": 0}
    errores = []
    for inv in info.get("inventarios", []):
        iid, nombre = inv["id"], inv["nombre"]
        mapeo = cfg.get("inventarios", {}).get(iid)
        if not mapeo:
            errores.append(f"«{nombre}» sin configurar en el conector")
            prezio(cfg, {"accion": "subir", "inventario": iid, "error": "Falta elegir la tabla en el conector (Configurar)."})
            resumen["errores"] += 1
            continue
        try:
            lista = leer_productos(cfg, mapeo, conectar)
            if not lista:
                raise ValueError("La consulta no devolvió productos con código, nombre y precio")
            h = huella(lista)
            previo = estado.get(iid, {})
            reciente = time.time() - previo.get("hora", 0) < REENVIAR_HORAS * 3600
            if previo.get("huella") == h and reciente and (inv.get("estado") or {}).get("ultimo"):
                resumen["sin_cambios"] += 1
                log.info("«%s»: sin cambios (%s productos)", nombre, len(lista))
                continue
            lote = str(uuid.uuid4())
            total = 0
            for i in range(0, len(lista), PARTE):
                fin = i + PARTE >= len(lista)
                r = prezio(cfg, {"accion": "subir", "inventario": iid, "lote": lote, "productos": lista[i:i + PARTE], "fin": fin})
                if fin:
                    total = r.get("productos", 0)
            estado[iid] = {"huella": h, "hora": time.time(), "productos": total}
            guardar_json(ESTADO, estado)
            resumen["enviados"] += 1
            log.info("«%s»: %s productos enviados", nombre, total)
        except ErrorPrezio:
            raise
        except Exception as e:   # error de SQL o de datos: se avisa al panel y sigue con los demás
            texto = str(e).splitlines()[0][:280] if str(e) else type(e).__name__
            errores.append(f"«{nombre}»: {texto}")
            resumen["errores"] += 1
            log.error("«%s»: %s", nombre, texto)
            try:
                prezio(cfg, {"accion": "subir", "inventario": iid, "error": texto})
            except ErrorPrezio:
                pass
    # Avisa al panel cómo terminó la vuelta (y borra el error anterior si ya se arregló).
    estado_prezio(cfg, "; ".join(errores)[:300] if errores else None)
    if not info.get("inventarios"):
        log.info("Prezio todavía no tiene inventarios para este conector (créalos en Inventarios › Conector).")
    return resumen


def trabajar(cfg: dict) -> None:
    log.info("Prezio Conector %s · enviando a %s cada %s minutos", VERSION, cfg["sitio"], cfg.get("cada_min", 10))
    espera = 60
    revisado = time.time()
    while True:
        if es_conector_de_consola() and time.time() - revisado > CADA_REVISION_S:
            revisado = time.time()
            if auto_actualizar(cfg["sitio"]):
                sys.exit(0)
        try:
            sincronizar(cfg)
            espera = max(1, int(cfg.get("cada_min", 10))) * 60
        except ErrorPrezio as e:
            if e.estado == 401:
                log.error("Prezio rechazó la clave: el conector fue quitado. Crea uno nuevo y ejecuta --configurar.")
                espera = 30 * 60
            else:
                log.warning("%s · se reintenta en %s s", e, espera)
                espera = min(espera * 2, 15 * 60)
        except Exception as e:   # nunca se detiene por un error inesperado
            log.exception("Error inesperado: %s", e)
            espera = 5 * 60
        time.sleep(espera)


# ---------------------------------------------------------------- actualizarse solo
def _version_mayor(a: str, b: str) -> bool:
    def partes(v):
        try:
            return [int(x) for x in str(v).split(".")[:3]]
        except ValueError:
            return [0, 0, 0]
    return partes(a) > partes(b)


def es_conector_de_consola() -> bool:
    """Solo PrezioConector.exe se reemplaza a sí mismo (dentro de Prezio Administrador lo actualiza el instalador)."""
    return bool(getattr(sys, "frozen", False)) and Path(sys.executable).stem.lower() == "prezioconector"


def limpiar_version_vieja() -> None:
    if es_conector_de_consola():
        try:
            Path(sys.executable).with_name("PrezioConector.viejo.exe").unlink()
        except OSError:
            pass


def auto_actualizar(sitio: str, abrir=urllib.request.urlopen) -> bool:
    """Si en apps.json hay una versión más nueva, la descarga, se reemplaza y vuelve a arrancar. True = se reinició."""
    if not es_conector_de_consola():
        return False
    try:
        pedido = urllib.request.Request(f"{sitio.rstrip('/')}/apps.json?t={int(time.time())}",
                                        headers={"Cache-Control": "no-cache", "User-Agent": f"PrezioConector/{VERSION}"})
        with abrir(pedido, timeout=15) as r:
            info = json.loads(r.read().decode("utf-8")).get("conector") or {}
        nueva, url = str(info.get("version") or ""), str(info.get("url") or "")
        if not (nueva and _version_mayor(nueva, VERSION) and url.startswith(ORIGEN_ACTUALIZACION) and url.endswith(".exe")):
            return False
        actual = Path(sys.executable)
        nuevo, viejo = actual.with_name("PrezioConector.nuevo.exe"), actual.with_name("PrezioConector.viejo.exe")
        log.info("Hay versión nueva %s (esta es %s): actualizando…", nueva, VERSION)
        with abrir(urllib.request.Request(url, headers={"User-Agent": f"PrezioConector/{VERSION}"}), timeout=300) as r, open(nuevo, "wb") as f:
            while True:
                bloque = r.read(1 << 16)
                if not bloque:
                    break
                f.write(bloque)
        with open(nuevo, "rb") as f:
            if f.read(2) != b"MZ" or nuevo.stat().st_size < 1_000_000:
                raise RuntimeError("la descarga no es un programa válido")
        try:
            viejo.unlink()
        except OSError:
            pass
        actual.rename(viejo)          # Windows deja renombrar el programa que está corriendo
        nuevo.rename(actual)
        subprocess.Popen([str(actual), *sys.argv[1:]], close_fds=True)
        log.info("Actualizado a %s: arrancando la versión nueva.", nueva)
        return True
    except Exception as e:
        log.warning("No se pudo revisar o instalar la actualización: %s", e)
        return False


# ---------------------------------------------------------------- configurar (preguntas en la consola)
def preguntar(texto: str, defecto: str = "", secreto: bool = False) -> str:
    sufijo = f" [{defecto}]" if defecto and not secreto else ""
    valor = (getpass.getpass(f"{texto}: ") if secreto else input(f"{texto}{sufijo}: ")).strip()
    return valor or defecto


def elegir(texto: str, opciones: list[str], sugerida: int = 0) -> int:
    for i, o in enumerate(opciones, 1):
        print(f"  {i:>3}. {o}")
    while True:
        v = preguntar(texto, str(sugerida + 1))
        if v.isdigit() and 1 <= int(v) <= len(opciones):
            return int(v) - 1
        print("  Escribe uno de los números de la lista.")


def sugerir(columnas: list[str], claves: list[str]) -> int:
    norm = [re.sub(r"[^a-z0-9]", "", c.lower()) for c in columnas]
    for k in claves:
        for i, c in enumerate(norm):
            if c == k or c.startswith(k):
                return i
    return 0


def configurar(cfg: dict | None, conectar=conectar_sql) -> dict:
    cfg = dict(cfg or {})
    print("\n=== Prezio · Conector de SQL Server ===\n")
    cfg["sitio"] = preguntar("Dirección de Prezio", cfg.get("sitio", "https://prezio-jade.vercel.app")).rstrip("/")
    while True:
        clave = preguntar("Clave del conector (Prezio › Inventarios › Conector)" + (" — Enter para dejar la actual" if cfg.get("clave") else ""), secreto=True)
        if clave:
            cfg["clave"] = proteger(clave)
        if not cfg.get("clave"):
            continue
        try:
            info = estado_prezio(cfg)
            print(f"  Conectado a «{info['negocio']['nombre']}» como «{info['conector']['nombre']}».\n")
            break
        except ErrorPrezio as e:
            print(f"  {e}")
            cfg.pop("clave", None)

    import pyodbc
    disponibles = [c for c in CONTROLADORES if c in pyodbc.drivers()] or ["SQL Server"]
    sql = dict(cfg.get("sql") or {})
    while True:
        sql["servidor"] = preguntar("Servidor SQL (ej.: localhost\\SQLEXPRESS o 192.168.1.10,1433)", sql.get("servidor", "localhost"))
        print("Inicio de sesión:")
        sql["modo"] = ["windows", "sql"][elegir("Elige", ["Usuario de Windows de esta PC", "Usuario y clave de SQL Server"], 1 if sql.get("modo") == "sql" else 0)]
        if sql["modo"] == "sql":
            sql["usuario"] = preguntar("Usuario SQL", sql.get("usuario", ""))
            c = preguntar("Clave SQL" + (" (Enter para dejar la actual)" if sql.get("clave") else ""), secreto=True)
            if c:
                sql["clave"] = proteger(c)
        sql["controlador"] = disponibles[0]
        sql["confiar_certificado"] = True
        try:
            with closing(conectar(sql, "master")) as cx:
                cur = cx.cursor()
                cur.execute("SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1 ORDER BY name")
                bases = [r[0] for r in cur.fetchall() if r[0] not in ("master", "tempdb", "model", "msdb")]
            break
        except Exception as e:
            print(f"  No se pudo entrar a SQL Server: {str(e).splitlines()[0][:200]}\n")
    print("\nBase de datos:")
    actual = bases.index(sql["base"]) if sql.get("base") in bases else 0
    sql["base"] = bases[elegir("Elige", bases, actual)]
    cfg["sql"] = sql

    with closing(conectar(sql)) as cx:
        cur = cx.cursor()
        cur.execute("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES ORDER BY TABLE_SCHEMA, TABLE_NAME")
        tablas = [f"{r[0]}.{r[1]}" for r in cur.fetchall()]
        mapas = dict(cfg.get("inventarios") or {})
        for inv in info.get("inventarios", []):
            print(f"\nInventario «{inv['nombre']}»: ¿de qué tabla salen los precios?")
            previo = mapas.get(inv["id"], {})
            sug = tablas.index(previo["tabla"]) if previo.get("tabla") in tablas else sugerir(tablas, ["dboproductos", "dboarticulos", "productos", "articulos", "inventario"])
            tabla = tablas[elegir("Tabla", tablas, sug)]
            esquema, nombre_tabla = tabla.split(".", 1)
            cur.execute("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
                        esquema, nombre_tabla)
            cols = [r[0] for r in cur.fetchall()]
            mapeo = {"tabla": tabla}
            for campo, claves, texto in (
                ("codigo", ["codigobarra", "codbarra", "barcode", "upc", "ean", "codigo"], "Columna del código de barras"),
                ("nombre", ["descripcion", "nombre", "producto", "articulo"], "Columna del nombre"),
                ("precio", ["precioventa", "precio1", "precio", "pvp"], "Columna del precio"),
            ):
                print(f"{texto}:")
                s = cols.index(previo[campo]) if previo.get(campo) in cols else sugerir(cols, claves)
                mapeo[campo] = cols[elegir("Columna", cols, s)]
            cur.execute(f"SELECT TOP 5 * FROM ({consulta_de(mapeo)}) AS t")
            muestra = productos_de(cur.fetchall())
            print("  Muestra:")
            for p in muestra:
                print(f"    {p['codigo']:<16} {p['nombre'][:40]:<40} {p['precio']:>12,.2f}")
            mapas[inv["id"]] = mapeo
        cfg["inventarios"] = mapas
    cfg["cada_min"] = int(preguntar("\nEnviar cada cuántos minutos", str(cfg.get("cada_min", 10))) or 10)
    guardar_json(CONFIG, cfg)
    print(f"\nConfiguración guardada en {CONFIG}")
    return cfg


# ---------------------------------------------------------------- arranque automático (Programador de tareas)
TAREA = "Prezio Conector"


def instalar() -> None:
    exe = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
    destino = f'"{exe}"' if getattr(sys, "frozen", False) else exe
    r = subprocess.run(["schtasks", "/Create", "/F", "/TN", TAREA, "/SC", "ONSTART", "/RU", "SYSTEM", "/RL", "HIGHEST",
                        "/TR", destino], capture_output=True, text=True)
    print(r.stdout or r.stderr)
    if r.returncode == 0:
        subprocess.run(["schtasks", "/Run", "/TN", TAREA], capture_output=True)
        print("Listo: el conector arranca solo al encender la PC (y ya está trabajando).")
    else:
        print("Abre PrezioConector.exe como administrador (clic derecho › Ejecutar como administrador) y repite.")


def desinstalar() -> None:
    r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TAREA], capture_output=True, text=True)
    print(r.stdout or r.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description="Prezio · Conector de SQL Server")
    p.add_argument("--configurar", action="store_true")
    p.add_argument("--una-vez", action="store_true")
    p.add_argument("--instalar", action="store_true")
    p.add_argument("--desinstalar", action="store_true")
    p.add_argument("--version", action="version", version=VERSION)
    a = p.parse_args()
    interactivo = sys.stdin is not None and sys.stdin.isatty()
    preparar_registro(consola=interactivo)
    limpiar_version_vieja()
    if a.desinstalar:
        return desinstalar()
    if a.instalar:
        return instalar()
    cfg = leer_json(CONFIG, None)
    if a.configurar or not cfg:
        if not interactivo:
            log.error("Falta configurar: abre PrezioConector.exe con doble clic.")
            sys.exit(2)
        cfg = configurar(cfg)
        print("\nEnviando por primera vez…")
        print(sincronizar(cfg))
        if os.name == "nt" and preguntar("\n¿Arrancar solo al encender la PC? (s/n)", "s").lower().startswith("s"):
            instalar()
            return
    # Al abrir: si hay versión nueva, se instala sola y vuelve a arrancar con las mismas opciones.
    if auto_actualizar(cfg.get("sitio") or "https://prezio-jade.vercel.app"):
        return
    if a.una_vez:
        print(sincronizar(cfg))
        return
    trabajar(cfg)


if __name__ == "__main__":
    main()
