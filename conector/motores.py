"""Prezio · motores de base de datos del conector: SQL Server, MySQL / MariaDB, PostgreSQL y Firebird.

Una «conexión» es un diccionario (se guarda en la PC, con la clave cifrada):
    motor        "sqlserver" | "mysql" | "postgresql" | "firebird"
    host         IP o nombre del servidor          puerto     número (vacío = el del motor)
    instancia    solo SQL Server (ej.: SQLEXPRESS)  auth       SQL Server: "sql" | "windows"
    usuario      usuario de la base                 clave      cifrada con cifrado.proteger()
    base         la base elegida                    ruta       solo Firebird: archivo .fdb o alias
Todo es de solo lectura: el conector nunca escribe en la base del negocio.
"""
import os
import re
import sys
from contextlib import closing
from pathlib import Path

from cifrado import revelar

MOTORES = {
    "sqlserver": {"nombre": "SQL Server", "puerto": 1433},
    "mysql": {"nombre": "MySQL / MariaDB", "puerto": 3306},
    "postgresql": {"nombre": "PostgreSQL", "puerto": 5432},
    "firebird": {"nombre": "Firebird", "puerto": 3050},
}
CONTROLADORES_SQLSERVER = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")
BASES_DEL_SISTEMA = {
    "sqlserver": {"master", "tempdb", "model", "msdb"},
    "mysql": {"information_schema", "mysql", "performance_schema", "sys"},
    "postgresql": {"postgres", "template0", "template1"},
}
ESPERA = 10   # segundos para conectar


class ErrorMotor(Exception):
    """Error con un mensaje para el usuario (sin datos secretos)."""


def _texto_seguro(valor, que: str, largo: int = 200) -> str:
    v = str(valor or "").strip()
    if not v or len(v) > largo or any(c in v for c in ";{}\x00\r\n"):
        raise ErrorMotor(f"{que} no válido")
    return v


def puerto_de(cx: dict) -> int:
    try:
        p = int(cx.get("puerto") or MOTORES[cx["motor"]]["puerto"])
    except (TypeError, ValueError, KeyError):
        raise ErrorMotor("Puerto no válido") from None
    if not 1 <= p <= 65535:
        raise ErrorMotor("Puerto no válido")
    return p


def nombre(cx: dict) -> str:
    """Texto corto para mostrar: «SQL Server · 192.168.1.10\\SQLEXPRESS · Ventas»."""
    m = MOTORES.get(cx.get("motor"), {}).get("nombre", cx.get("motor", "?"))
    donde = cx.get("host", "")
    if cx.get("motor") == "sqlserver" and cx.get("instancia"):
        donde += "\\" + cx["instancia"]
    elif cx.get("puerto") and int(cx["puerto"]) != MOTORES.get(cx.get("motor"), {}).get("puerto"):
        donde += f":{cx['puerto']}"
    base = cx.get("ruta") if cx.get("motor") == "firebird" else cx.get("base")
    return " · ".join(x for x in (m, donde, base) if x)


# ---------------------------------------------------------------- SQL Server (ODBC; Windows siempre trae «SQL Server»)
def _sqlserver_servidor(cx: dict) -> str:
    host = _texto_seguro(cx.get("host"), "Servidor")
    inst = str(cx.get("instancia") or "").strip()
    if inst and not re.fullmatch(r"[A-Za-z0-9_$#-]{1,64}", inst):
        raise ErrorMotor("Nombre de instancia no válido")
    # Con el puerto que dio el SQL Browser se entra directo; sin puerto, se le pregunta a la instancia por nombre.
    if inst and not cx.get("puerto"):
        return f"{host}\\{inst}"
    return f"{host},{puerto_de(cx)}"


def cadena_sqlserver(cx: dict, base: str | None, controladores=None) -> str:
    disponibles = controladores if controladores is not None else _controladores_odbc()
    controlador = cx.get("controlador") if cx.get("controlador") in disponibles else next(
        (c for c in CONTROLADORES_SQLSERVER if c in disponibles), "SQL Server")
    if controlador not in CONTROLADORES_SQLSERVER:
        raise ErrorMotor("Controlador ODBC no admitido")
    cs = (f"DRIVER={{{controlador}}};SERVER={_sqlserver_servidor(cx)};"
          f"DATABASE={_texto_seguro(base or cx.get('base') or 'master', 'Base de datos', 128)};")
    if controlador != "SQL Server":
        cs += "Encrypt=yes;TrustServerCertificate=" + ("yes" if cx.get("confiar_certificado", True) else "no") + ";"
    if cx.get("auth") == "windows":
        cs += "Trusted_Connection=yes;"
    else:
        def esc(v):
            return "{" + str(v).replace("}", "}}") + "}"
        cs += "UID=" + esc(cx.get("usuario", "")) + ";PWD=" + esc(revelar(cx.get("clave", ""))) + ";"
    return cs + "APP=Prezio Conector;"


def _controladores_odbc() -> list[str]:
    try:
        import pyodbc
        return list(pyodbc.drivers())
    except Exception:
        return ["SQL Server"]


# ---------------------------------------------------------------- Firebird: usa fbclient.dll (incluido en la app)
def _firebird_cliente() -> None:
    from firebird.driver import driver_config
    for carpeta in (Path(getattr(sys, "_MEIPASS", "")) / "firebird", Path(sys.executable).parent / "firebird",
                    Path(__file__).resolve().parent / "firebird"):
        dll = carpeta / ("fbclient.dll" if os.name == "nt" else "libfbclient.so")
        if dll.exists():
            driver_config.fb_client_library.value = str(dll)
            return


# ---------------------------------------------------------------- conectar
def conectar(cx: dict, base: str | None = None):
    """Conexión DB-API de solo lectura. Los errores salen como ErrorMotor con un mensaje claro."""
    motor = cx.get("motor")
    if motor not in MOTORES:
        raise ErrorMotor("Motor de base de datos no admitido")
    host = _texto_seguro(cx.get("host"), "Servidor")
    try:
        if motor == "sqlserver":
            import pyodbc
            try:
                return pyodbc.connect(cadena_sqlserver(cx, base), timeout=ESPERA, autocommit=True, readonly=True)
            except TypeError:   # pyodbc viejo sin «readonly»
                return pyodbc.connect(cadena_sqlserver(cx, base), timeout=ESPERA, autocommit=True)
        if motor == "mysql":
            import pymysql
            return pymysql.connect(host=host, port=puerto_de(cx), user=cx.get("usuario") or "", password=revelar(cx.get("clave", "")),
                                   database=(base or cx.get("base") or None), connect_timeout=ESPERA, read_timeout=300,
                                   charset="utf8mb4", autocommit=True)
        if motor == "postgresql":
            import pg8000.dbapi
            c = pg8000.dbapi.connect(host=host, port=puerto_de(cx), user=cx.get("usuario") or "postgres",
                                     password=revelar(cx.get("clave", "")) or None,
                                     database=base or cx.get("base") or "postgres", timeout=ESPERA,
                                     application_name="Prezio Conector")
            c.autocommit = True
            return c
        # firebird
        import firebird.driver as fb
        _firebird_cliente()
        ruta = _texto_seguro(cx.get("ruta") or base, "Ruta de la base", 400)
        dsn = f"{host}/{puerto_de(cx)}:{ruta}"
        clave = revelar(cx.get("clave", ""))
        try:
            return fb.connect(dsn, user=cx.get("usuario") or "SYSDBA", password=clave, charset="UTF8",
                              auth_plugin_list="Srp256,Srp,Legacy_Auth")
        except TypeError:
            return fb.connect(dsn, user=cx.get("usuario") or "SYSDBA", password=clave, charset="UTF8")
    except ErrorMotor:
        raise
    except ImportError as e:
        raise ErrorMotor(f"Falta el componente para {MOTORES[motor]['nombre']} ({e.name}). Reinstala Prezio Administrador.") from None
    except Exception as e:
        raise ErrorMotor(explicar(e, motor)) from None


def explicar(e: Exception, motor: str = "") -> str:
    """Mensaje en palabras simples para los errores más comunes de cada motor."""
    t = str(e)
    linea = t.splitlines()[0][:300] if t else type(e).__name__
    if re.search(r"Login failed|access denied|password authentication failed|Your user name and password are not defined|"
                 r"28000|1045|18456", t, re.I):
        return "Usuario o clave de la base de datos incorrectos."
    if re.search(r"timeout|timed out|could not connect|can't connect|Unable to complete network request|"
                 r"server was not found|08001|10061|Connection refused", t, re.I):
        return "No se pudo llegar al servidor: revisa que esté encendido, la IP/puerto y el firewall."
    if re.search(r"Cannot open database|Unknown database|does not exist|I/O error .* for file", t, re.I):
        return "La base de datos no existe o el usuario no tiene permiso para abrirla."
    if re.search(r"fbclient|Firebird client library", t, re.I):
        return "Falta el cliente de Firebird (fbclient.dll). Reinstala Prezio Administrador."
    if re.search(r"IM002|Data source name not found", t):
        return "No está instalado el controlador ODBC de SQL Server en esta PC."
    return linea


# ---------------------------------------------------------------- nombres y consultas por motor
def cita(motor: str, nombre_: str) -> str:
    if not nombre_ or len(nombre_) > 128 or "\x00" in nombre_:
        raise ErrorMotor("Nombre de tabla o columna no válido")
    if motor == "sqlserver":
        return "[" + nombre_.replace("]", "]]") + "]"
    if motor == "mysql":
        return "`" + nombre_.replace("`", "``") + "`"
    return '"' + nombre_.replace('"', '""') + '"'


def tabla_citada(motor: str, tabla: str) -> str:
    """«esquema.tabla» (SQL Server, PostgreSQL) o «tabla» (MySQL, Firebird)."""
    if motor in ("sqlserver", "postgresql") and "." in tabla:
        esquema, _, t = tabla.partition(".")
        return cita(motor, esquema) + "." + cita(motor, t)
    return cita(motor, tabla)


def _con_limite(motor: str, sql_sin_limite: str, limite: int | None) -> str:
    if not limite:
        return sql_sin_limite
    n = int(limite)
    if motor == "sqlserver":
        return f"SELECT TOP ({n}) * FROM ({sql_sin_limite}) AS prezio_t"
    if motor == "firebird":
        return f"SELECT FIRST {n} * FROM ({sql_sin_limite}) prezio_t"
    return f"SELECT * FROM ({sql_sin_limite}) AS prezio_t LIMIT {n}"


def consulta(motor: str, mapeo: dict, limite: int | None = None) -> str:
    """SELECT de solo lectura que devuelve (código, nombre, precio)."""
    if mapeo.get("consulta"):
        q = str(mapeo["consulta"]).strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", q) or ";" in q:
            raise ErrorMotor("La consulta propia debe ser un solo SELECT")
        return _con_limite(motor, q, limite)
    base = (f"SELECT {cita(motor, mapeo['codigo'])}, {cita(motor, mapeo['nombre'])}, {cita(motor, mapeo['precio'])} "
            f"FROM {tabla_citada(motor, mapeo['tabla'])}")
    return _con_limite(motor, base, limite)


def _marca(motor: str) -> str:
    return "%s" if motor in ("mysql", "postgresql") else "?"


SQL_BASES = {
    "sqlserver": "SELECT name FROM sys.databases WHERE state_desc = 'ONLINE' AND HAS_DBACCESS(name) = 1 ORDER BY name",
    "mysql": "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name",
    "postgresql": ("SELECT datname FROM pg_database WHERE NOT datistemplate AND datallowconn "
                   "AND has_database_privilege(datname, 'CONNECT') ORDER BY datname"),
}
SQL_TABLAS = {
    "sqlserver": "SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES ORDER BY TABLE_SCHEMA, TABLE_NAME",
    "mysql": "SELECT NULL, table_name FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
    "postgresql": ("SELECT table_schema, table_name FROM information_schema.tables "
                   "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY table_schema, table_name"),
    "firebird": ("SELECT NULL, TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS "
                 "WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 ORDER BY RDB$RELATION_NAME"),
}
SQL_COLUMNAS = {
    "sqlserver": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
    "mysql": "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
    "postgresql": ("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                   "ORDER BY ordinal_position"),
    "firebird": ("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = ? "
                 "ORDER BY RDB$FIELD_POSITION"),
}


def _filas(cx: dict, base, sql: str, *parametros):
    with closing(conectar(cx, base)) as c:
        cur = c.cursor()
        try:
            cur.execute(sql, parametros) if parametros else cur.execute(sql)
            return cur.fetchall()
        except ErrorMotor:
            raise
        except Exception as e:
            raise ErrorMotor(explicar(e, cx.get("motor", ""))) from None


def bases(cx: dict) -> list[str]:
    """Bases que el usuario puede abrir (Firebird no las lista: es el archivo o alias que se escribe)."""
    motor = cx["motor"]
    if motor == "firebird":
        _filas(cx, None, "SELECT 1 FROM RDB$DATABASE")   # prueba la entrada
        return [cx.get("ruta") or ""]
    inicial = {"sqlserver": "master", "mysql": None, "postgresql": cx.get("base") or "postgres"}[motor]
    nombres = [str(r[0]) for r in _filas(cx, inicial, SQL_BASES[motor])]
    sistema = BASES_DEL_SISTEMA.get(motor, set())
    propias = [n for n in nombres if n.lower() not in sistema]
    return propias or nombres


def tablas(cx: dict, base: str) -> list[str]:
    motor = cx["motor"]
    params = (base,) if motor == "mysql" else ()
    filas = _filas(cx, base, SQL_TABLAS[motor], *params)
    return [f"{r[0]}.{r[1]}" if r[0] else str(r[1]) for r in filas][:5000]


def columnas(cx: dict, base: str, tabla: str) -> list[str]:
    motor = cx["motor"]
    if motor in ("sqlserver", "postgresql"):
        esquema, _, t = tabla.rpartition(".")
        params = (esquema or ("dbo" if motor == "sqlserver" else "public"), t)
    elif motor == "mysql":
        params = (base, tabla)
    else:
        params = (tabla,)
    return [str(r[0]).strip() for r in _filas(cx, base, SQL_COLUMNAS[motor], *params)]


def leer(cx: dict, mapeo: dict, limite: int | None = None):
    """Filas (código, nombre, precio) de la tabla elegida."""
    base = cx.get("ruta") if cx["motor"] == "firebird" else (mapeo.get("base") or cx.get("base"))
    return _filas(cx, base, consulta(cx["motor"], mapeo, limite))


def sugerir(cols: list[str], campo: str) -> str | None:
    """Columna probable para código, nombre o precio (por su nombre)."""
    claves = {
        "codigo": ["codigobarra", "codbarra", "codigobarras", "barcode", "upc", "ean", "codigo", "cod", "sku", "referencia"],
        "nombre": ["descripcion", "nombre", "producto", "articulo", "detalle", "desc"],
        "precio": ["precioventa", "precio1", "pventa", "precio", "pvp", "venta", "price"],
    }[campo]
    norm = [(c, re.sub(r"[^a-z0-9]", "", c.lower())) for c in cols]
    for k in claves:
        for c, n in norm:
            if n == k:
                return c
    for k in claves:
        for c, n in norm:
            if n.startswith(k) or k in n:
                return c
    return None
