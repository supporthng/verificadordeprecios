"""Prezio · buscar servidores de base de datos en la red del negocio.

1. Toma las redes privadas de esta PC (192.168.x.0/24, 10.x.x.0/24, 172.16–31.x.0/24).
2. Prueba en cada equipo los puertos de SQL Server (1433), MySQL/MariaDB (3306), PostgreSQL (5432) y Firebird (3050),
   y confirma el motor cuando el servidor se presenta (MySQL saluda con su versión; PostgreSQL responde al pedido SSL).
3. Pregunta al «SQL Server Browser» (UDP 1434) qué instancias hay: así aparecen también las instancias con nombre
   (SQLEXPRESS…) que usan otro puerto.
Solo mira la red local; no prueba claves ni entra a ninguna base.
"""
import ipaddress
import socket
import struct
from concurrent.futures import ThreadPoolExecutor

PUERTOS = {1433: "sqlserver", 3306: "mysql", 5432: "postgresql", 3050: "firebird"}
NOMBRES = {"sqlserver": "SQL Server", "mysql": "MySQL / MariaDB", "postgresql": "PostgreSQL", "firebird": "Firebird"}
PRIVADAS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]


def _privada(ip: ipaddress.IPv4Address) -> bool:
    return any(ip in n for n in PRIVADAS)


def ips_locales() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    for destino in ("10.255.255.255", "192.168.255.255", "172.31.255.255"):
        try:   # no envía nada: solo pregunta qué IP usaría la PC para esa red
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((destino, 1))
                ips.add(s.getsockname()[0])
        except OSError:
            pass
    return sorted(i for i in ips if _privada(ipaddress.ip_address(i)))


def redes_locales() -> list[str]:
    """Las /24 privadas de esta PC (máximo 4)."""
    redes = []
    for ip in ips_locales():
        n = str(ipaddress.ip_network(f"{ip}/24", strict=False))
        if n not in redes:
            redes.append(n)
    return redes[:4]


def validar_red(red: str) -> ipaddress.IPv4Network:
    n = ipaddress.ip_network(red.strip(), strict=False)
    if n.version != 4 or n.num_addresses > 1024 or not (_privada(n.network_address) or n.network_address.is_loopback):
        raise ValueError("Solo redes locales privadas, de hasta 1024 direcciones (ej.: 192.168.1.0/24)")
    return n


# ---------------------------------------------------------------- probar un puerto
def _saludo_mysql(s: socket.socket) -> str | None:
    """MySQL/MariaDB saludan al conectar: [largo 3][seq 1][protocolo 10][versión\\0]…"""
    try:
        datos = s.recv(256)
    except OSError:
        return None
    if len(datos) > 6 and datos[4] == 10:
        fin = datos.find(b"\x00", 5)
        if fin > 5:
            v = datos[5:fin].decode("latin-1", "replace")
            return v.replace("5.5.5-", "") if "MariaDB" in v else v
    return None


def _es_postgresql(s: socket.socket) -> bool:
    try:
        s.sendall(struct.pack("!ii", 8, 80877103))   # SSLRequest
        r = s.recv(1)
    except OSError:
        return False
    return r in (b"S", b"N")


def probar(host: str, puerto: int, motor: str, espera: float = 0.4) -> dict | None:
    try:
        with socket.create_connection((host, puerto), timeout=espera) as s:
            s.settimeout(max(espera, 0.8))
            version = None
            if motor == "mysql":
                version = _saludo_mysql(s)
                if version is None:
                    return None   # el puerto está abierto pero no es MySQL
            elif motor == "postgresql" and not _es_postgresql(s):
                return None
            return {"host": host, "puerto": puerto, "motor": motor, "version": version}
    except OSError:
        return None


# ---------------------------------------------------------------- SQL Server Browser (instancias con nombre)
def leer_browser(datos: bytes, origen: str) -> list[dict]:
    """Respuesta SVR_RESP: 0x05, largo (2 bytes), «ServerName;PC;InstanceName;SQLEXPRESS;…;tcp;1433;;» por instancia."""
    if len(datos) < 3 or datos[0] != 0x05:
        return []
    texto = datos[3:].decode("latin-1", "replace")
    instancias = []
    for bloque in texto.split(";;"):
        partes = bloque.split(";")
        d = {partes[i].lower(): partes[i + 1] for i in range(0, len(partes) - 1, 2)}
        if not d.get("instancename"):
            continue
        tcp = d.get("tcp", "")
        instancias.append({
            "host": origen, "motor": "sqlserver", "puerto": int(tcp) if tcp.isdigit() else None,
            "instancia": "" if d["instancename"].upper() == "MSSQLSERVER" else d["instancename"],
            "equipo": d.get("servername") or None, "version": _version_sql(d.get("version", "")),
        })
    return instancias


def _version_sql(v: str) -> str | None:
    mayor = v.split(".")[0] if v else ""
    nombres = {"8": "2000", "9": "2005", "10": "2008", "11": "2012", "12": "2014", "13": "2016", "14": "2017",
               "15": "2019", "16": "2022", "17": "2025"}
    return f"SQL Server {nombres[mayor]}" if mayor in nombres else (v or None)


def preguntar_browser(destinos: list[str], espera: float = 1.5, puerto: int = 1434) -> list[dict]:
    """Difusión (0x02) a las redes y consulta directa (0x03) a los equipos con SQL Server; junta las respuestas."""
    encontrados: list[dict] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.3)
        for d in destinos:
            try:
                s.sendto(b"\x02" if d.endswith(".255") else b"\x03", (d, puerto))
            except OSError:
                pass
        import time
        fin = time.monotonic() + espera
        while time.monotonic() < fin:
            try:
                datos, (origen, _) = s.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            encontrados.extend(leer_browser(datos, origen))
    return encontrados


# ---------------------------------------------------------------- todo junto
def _nombre_equipo(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except OSError:
        return None


def buscar(redes: list[str] | None = None, puertos: dict | None = None, espera: float = 0.4, hilos: int = 192,
           browser: bool = True, avance=None) -> list[dict]:
    """Servidores encontrados: [{host, puerto, motor, nombre_motor, instancia, equipo, version}]."""
    redes = redes if redes is not None else redes_locales()
    puertos = puertos or PUERTOS
    hosts: list[str] = []
    for r in redes:
        n = validar_red(r)
        hosts += [str(h) for h in (n.hosts() if n.num_addresses > 2 else [n.network_address])]
    trabajos = [(h, p, m) for h in hosts for p, m in puertos.items()]
    hallados: dict[tuple, dict] = {}
    hechos = 0
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for r in pool.map(lambda t: probar(*t, espera=espera), trabajos):
            hechos += 1
            if avance and hechos % 200 == 0:
                avance(hechos / max(1, len(trabajos)))
            if r:
                hallados[(r["host"], r["motor"], r["puerto"])] = {**r, "instancia": "", "equipo": None}
    if browser:
        destinos = [str(validar_red(r).broadcast_address) for r in redes if validar_red(r).num_addresses > 2]
        destinos += sorted({h for (h, m, _) in hallados if m == "sqlserver"})
        for inst in preguntar_browser(destinos):
            if not inst["puerto"] and not inst["instancia"]:
                continue
            clave = (inst["host"], "sqlserver", inst["puerto"])
            previo = hallados.get(clave, {})
            hallados[clave] = {**previo, **{k: v for k, v in inst.items() if v not in (None, "") or k == "instancia"}}
    lista = list(hallados.values())
    unicos = sorted({x["host"] for x in lista})
    with ThreadPoolExecutor(max_workers=32) as pool:
        nombres = dict(zip(unicos, pool.map(_nombre_equipo, unicos)))
    for x in lista:
        x["equipo"] = x.get("equipo") or nombres.get(x["host"])
        x["nombre_motor"] = NOMBRES[x["motor"]]
    if avance:
        avance(1.0)
    return sorted(lista, key=lambda x: (tuple(int(p) for p in x["host"].split(".")), x["motor"], x.get("instancia") or ""))
