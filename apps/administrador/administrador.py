"""Prezio Administrador para Windows · la app de cada negocio.

  · Entrar con el código del negocio + usuario + clave (o con correo): las mismas cuentas y permisos de la web.
  · Panel del negocio en su propia ventana (sucursales, inventarios, apariencia, equipos, usuarios…), sin volver
    a entrar: la app le pide a Prezio un enlace de un solo uso con el que el panel abre su propia sesión.
  · Base de datos: busca los servidores de la red (SQL Server, MySQL / MariaDB, PostgreSQL, Firebird), se elige
    uno, se autoriza con las credenciales de la base y se eligen base, tabla y columnas. La app crea sola el
    conector y el inventario en Prezio: no hay claves que copiar.
  · Copia automática: cada pocos minutos envía los precios que cambiaron (también con la PC sin nadie,
    con la tarea de Windows «Prezio Conector»).

Las credenciales de la base de datos se guardan cifradas en esta PC y nunca se envían a Prezio.

  PrezioAdministrador.exe --servicio      (lo arranca la tarea de Windows como SYSTEM: envía los precios)
  PrezioAdministrador.exe --instalar      (crea esa tarea; pide permiso de administrador)
  PrezioAdministrador.exe --desinstalar   (la quita)
"""
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AQUI = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(AQUI))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "conector"))
import cifrado  # noqa: E402
import motores  # noqa: E402
import prezio_conector as pc  # noqa: E402
import red  # noqa: E402

# La compilación (GitHub Actions) reemplaza estos dos valores.
SITIO = "https://prezio-jade.vercel.app"
VERSION = "2.0.0"
TAREA = pc.TAREA
DATOS = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".prezio")) / "Prezio" / "Administrador"
SESION = DATOS / "sesion.json"
ARRANQUE = pc.CARPETA / "arranque.json"          # lo que dejó el paso con permiso de administrador (tarea de Windows)
ACTIVACION = pc.CARPETA / "activacion.json"     # de la PC (todas las cuentas de Windows): la licencia del negocio
USUARIO_VALIDO = r"^[a-z0-9][a-z0-9._-]{2,29}$"
# Solo se instalan actualizaciones publicadas en las descargas de Prezio.
ORIGEN_ACTUALIZACION = "https://github.com/supporthng/prezio/releases/download/"
CADA_REVISION_S = 6 * 60 * 60


class ErrorApp(Exception):
    """Error con un mensaje para mostrar tal cual."""


# ---------------------------------------------------------------- Prezio y Supabase (con la sesión del usuario)
class Prezio:
    def __init__(self, sitio: str = SITIO, abrir=urllib.request.urlopen):
        self.sitio = sitio.rstrip("/")
        self._abrir = abrir
        self._publico: dict | None = None

    def _pedir(self, metodo: str, url: str, cuerpo=None, cabeceras: dict | None = None, segundos: int = 30):
        datos = None if cuerpo is None else json.dumps(cuerpo).encode("utf-8")
        h = {"Content-Type": "application/json", "User-Agent": f"PrezioAdministrador/{VERSION}", **(cabeceras or {})}
        pedido = urllib.request.Request(url, data=datos, method=metodo, headers=h)
        try:
            with self._abrir(pedido, timeout=segundos) as r:
                texto = r.read().decode("utf-8")
                return json.loads(texto) if texto.strip() else None
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read().decode("utf-8") or "{}")
            except ValueError:
                d = {}
            m = d.get("message") or d.get("error_description") or d.get("msg") or d.get("error") or f"Error {e.code}"
            if "Invalid login credentials" in str(m):
                m = "Usuario o clave incorrectos."
            if e.code == 401 and "JWT" in str(m):
                m = "La sesión venció: vuelve a entrar."
            raise ErrorApp(str(m)) from None
        except (urllib.error.URLError, OSError) as e:
            raise ErrorApp(f"Sin conexión con Prezio ({getattr(e, 'reason', e)}). Revisa el internet.") from None

    def publico(self) -> dict:
        if not self._publico:
            self._publico = self._pedir("GET", f"{self.sitio}/api/publico")
            if not self._publico or not self._publico.get("supabase_url"):
                raise ErrorApp("Prezio no respondió con su configuración.")
        return self._publico

    def _cab(self, token: str | None) -> dict:
        p = self.publico()
        return {"apikey": p["clave_publica"], "Authorization": f"Bearer {token or p['clave_publica']}"}

    def auth(self, tipo: str, cuerpo: dict) -> dict:
        p = self.publico()
        return self._pedir("POST", f"{p['supabase_url']}/auth/v1/token?grant_type={tipo}", cuerpo,
                           {"apikey": p["clave_publica"]})

    def rpc(self, nombre: str, args: dict, token: str | None = None):
        return self._pedir("POST", f"{self.publico()['supabase_url']}/rest/v1/rpc/{nombre}", args, self._cab(token))

    def tabla(self, metodo: str, ruta: str, token: str, cuerpo=None):
        cab = self._cab(token)
        if metodo != "GET":
            cab["Prefer"] = "return=representation"
        return self._pedir(metodo, f"{self.publico()['supabase_url']}/rest/v1/{ruta}", cuerpo, cab)

    def enlace_panel(self, token: str) -> str:
        r = self._pedir("POST", f"{self.sitio}/api/sesion-app", {}, {"Authorization": f"Bearer {token}"})
        return r["token_hash"]


def correo_de_usuario(negocio_id: str, usuario: str) -> str:
    """Igual que public.correo_de_usuario: la cuenta interna de un usuario sin correo."""
    return f"{usuario.strip().lower()}@n{negocio_id.replace('-', '')}.prezio.invalid"


def mensaje(e: Exception) -> str:
    if isinstance(e, (ErrorApp, motores.ErrorMotor, pc.ErrorPrezio, ValueError)):
        return str(e)
    t = str(e).splitlines()[0][:240] if str(e) else type(e).__name__
    return t


# ---------------------------------------------------------------- la app
class Api:
    """Lo que la ventana (interfaz.html) llama con window.pywebview.api.*. Todo devuelve {ok…} o {error}.

    pywebview publica para la página TODO lo que no empieza con «_» (también objetos guardados en la instancia,
    recorriéndolos). Por eso los datos internos (la ventana, el cliente de Prezio, las rutas) llevan «_»:
    publicar la ventana rompe la API completa, y publicar el cliente dejaría a la página llamar a Prezio sin control."""

    def __init__(self, prezio: Prezio | None = None, ruta_config: Path = pc.CONFIG, ruta_sesion: Path = SESION,
                 buscar=red.buscar, abrir_ventana=None, ruta_activacion: Path = ACTIVACION):
        self._prezio = prezio or Prezio(self._sitio_guardado(ruta_config))
        self._ruta_config = ruta_config
        self._ruta_sesion = ruta_sesion
        self._ruta_activacion = ruta_activacion
        self._buscar = buscar
        self._abrir_ventana = abrir_ventana     # pruebas: recibe cada dirección a la que navega la ventana
        self._ventana = None                     # la ventana de pywebview (una sola: la app y el panel)
        self._inicio = ""                       # dirección de la pantalla propia de la app (interfaz.html)
        self._panel_listo = False               # el panel ya tiene su sesión en esta ventana
        self._ses: dict | None = None
        self._cx: dict | None = None          # servidor autorizado en el asistente (clave ya cifrada)
        self._ocupado = threading.Lock()
        self._ultimo_envio: dict = {}
        self._cargar_sesion()

    # ---- archivos
    @staticmethod
    def _sitio_guardado(ruta: Path) -> str:
        return (pc.leer_json(ruta, {}) or {}).get("sitio") or SITIO

    def _cfg(self) -> dict:
        return pc.leer_json(self._ruta_config, {}) or {}

    def _guardar_cfg(self, cfg: dict) -> None:
        pc.guardar_json(self._ruta_config, cfg)

    # ---- sesión
    def _cargar_sesion(self) -> None:
        d = pc.leer_json(self._ruta_sesion, None)
        if not d or not d.get("renovar"):
            return
        try:
            self._ses = {**d, "renovar": cifrado.revelar(d["renovar"]), "acceso": None, "vence": 0}
        except Exception:
            self._ses = None

    def _guardar_sesion(self) -> None:
        if not self._ses or not self._ses.get("recordar"):
            try:
                self._ruta_sesion.unlink()
            except OSError:
                pass
            return
        d = {k: v for k, v in self._ses.items() if k not in ("acceso", "vence")}
        d["renovar"] = cifrado.proteger(self._ses["renovar"], equipo=False)   # solo este usuario de Windows
        pc.guardar_json(self._ruta_sesion, d)

    def _token(self) -> str:
        s = self._ses
        if not s:
            raise ErrorApp("Entra con tu usuario.")
        if s.get("acceso") and s.get("vence", 0) - time.time() > 120:
            return s["acceso"]
        try:
            r = self._prezio.auth("refresh_token", {"refresh_token": s["renovar"]})
        except ErrorApp:
            self._ses = None
            self._guardar_sesion()
            raise ErrorApp("La sesión venció: vuelve a entrar.") from None
        self._tomar_tokens(r)
        return s["acceso"]

    def _tomar_tokens(self, r: dict) -> None:
        self._ses["acceso"] = r["access_token"]
        self._ses["renovar"] = r["refresh_token"]
        self._ses["vence"] = time.time() + int(r.get("expires_in") or 3600)
        self._guardar_sesion()

    def _negocios(self, token: str, uid: str) -> list[dict]:
        filas = self._prezio.tabla("GET", f"miembros?select=rol,usuario,permisos,negocios(id,nombre,slug,plan,moneda)&user_id=eq.{uid}", token) or []
        return [{"id": f["negocios"]["id"], "nombre": f["negocios"]["nombre"], "slug": f["negocios"]["slug"],
                 "plan": f["negocios"]["plan"], "rol": f["rol"], "permisos": f.get("permisos") or []}
                for f in filas if f.get("negocios")]

    def _negocio(self) -> dict:
        if not self._ses or not self._ses.get("negocio"):
            raise ErrorApp("Entra con tu usuario.")
        return self._ses["negocio"]

    def _puede(self, permiso: str) -> bool:
        n = self._negocio()
        return n.get("rol") == "dueno" or permiso in (n.get("permisos") or [])

    # ---- activación con la licencia del negocio
    def _activacion(self) -> dict | None:
        a = pc.leer_json(self._ruta_activacion, None)
        return a if a and a.get("negocio_id") and a.get("licencia") else None

    def activar(self, licencia):
        """La primera vez: la licencia PREZIO-XXXX-XXXX-XXXX del negocio. La PC queda amarrada a ese negocio."""
        try:
            import re
            lic = re.sub(r"\s+", "", str(licencia or "")).upper()
            if not re.fullmatch(r"PREZIO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}", lic):
                return {"error": "Escribe la licencia completa: PREZIO-XXXX-XXXX-XXXX."}
            info = self._prezio.rpc("licencia_info", {"p_licencia": lic})
            if not info:
                return {"error": "Esa licencia no existe. Revísala o pídela a tu proveedor de Prezio."}
            actual = self._activacion()
            if actual and actual["negocio_id"] != info["id"]:
                self.salir()
            pc.guardar_json(self._ruta_activacion, {"licencia": info["licencia"], "negocio_id": info["id"], "nombre": info["nombre"],
                                                   "fecha": time.strftime("%Y-%m-%d %H:%M")})
            return {**self.estado(), "aviso": {"vencida": "La licencia está vencida: el negocio funciona en solo lectura hasta que se pague.",
                                                "suspendida": "La licencia está suspendida: comunícate con tu proveedor de Prezio."}.get(info.get("estado"))}
        except Exception as e:
            return {"error": mensaje(e)}

    def desactivar(self):
        """Usar otra licencia en esta PC (solo con la sesión cerrada)."""
        if self._ses:
            return {"error": "Primero sal de tu usuario."}
        try:
            self._ruta_activacion.unlink()
        except OSError:
            pass
        return self.estado()

    # ---- una sola ventana: la pantalla de la app y el panel del negocio
    def _navegar(self, url: str) -> None:
        if self._abrir_ventana:
            self._abrir_ventana(url)
        elif self._ventana is not None:
            self._ventana.load_url(url)

    def _url_actual(self) -> str:
        try:
            return (self._ventana.get_current_url() or "") if self._ventana is not None else ""
        except Exception:
            return ""

    def _desde_la_app(self) -> bool:
        """¿La llamada viene de la pantalla propia de la app? (no de una página de internet abierta en la ventana)."""
        if self._ventana is None:
            return True
        url = self._url_actual().split("#")[0]
        if self._inicio:
            return url == self._inicio
        return bool(url) and not url.startswith(("http://", "https://")) or url.startswith(("http://127.0.0.1", "http://localhost"))

    def _desde_prezio(self) -> bool:
        """La pantalla de la app o una página de Prezio (el panel) — para volver a la app o salir."""
        return self._desde_la_app() or self._url_actual().startswith(self._prezio.sitio + "/")

    def ir_app(self, seccion="inicio"):
        """Desde el panel: volver a la pantalla de la app (Inicio, Base de datos o Copia automática)."""
        seccion = seccion if seccion in ("inicio", "base", "copia") else "inicio"
        self._navegar((self._inicio or "interfaz.html") + "#" + seccion)
        return {"ok": True}

    def mostrar_inicio(self):
        return self.ir_app("inicio")

    def estado(self):
        cfg = self._cfg()
        ses = None
        if self._ses:
            ses = {"nombre": self._ses.get("nombre"), "cuenta": self._ses.get("cuenta"), "negocio": self._ses.get("negocio"),
                   "negocios": self._ses.get("negocios", []), "recordar": bool(self._ses.get("recordar"))}
        return {"ok": True, "version": VERSION, "sitio": self._prezio.sitio, "sesion": ses, "equipo": platform.node(),
                "activacion": self._activacion(),
                "conector": {"fuentes": len(cfg.get("inventarios") or {}), "cada_min": cfg.get("cada_min", 10),
                             "inicio": self._tarea_instalada(), "negocio": (cfg.get("conector") or {}).get("negocio_id")}}

    def entrar(self, d):
        """d = {modo: "usuario"|"correo", negocio, usuario, correo, clave, recordar}"""
        try:
            clave = str(d.get("clave") or "")
            import re
            act = self._activacion()
            if not act:
                return {"error": "Primero activa la app con la licencia del negocio."}
            solo = act["negocio_id"]
            if d.get("modo") == "correo":
                correo = str(d.get("correo") or "").strip().lower()
                if "@" not in correo:
                    return {"error": "Escribe tu correo."}
            else:
                usuario = str(d.get("usuario") or "").strip().lower()
                if not re.match(USUARIO_VALIDO, usuario):
                    return {"error": "Escribe tu usuario."}
                correo = correo_de_usuario(solo, usuario)
            if not clave:
                return {"error": "Escribe tu clave."}
            try:
                r = self._prezio.auth("password", {"email": correo, "password": clave})
            except ErrorApp as e:
                return {"error": "Usuario o clave incorrectos." if "incorrect" in str(e) else str(e)}
            uid = r["user"]["id"]
            negocios = self._negocios(r["access_token"], uid)
            negocios = [n for n in negocios if n["id"] == solo]
            if not negocios:
                return {"error": f"Esa cuenta no tiene acceso a «{act['nombre']}»."}
            meta = r["user"].get("user_metadata") or {}
            cuenta = correo if d.get("modo") == "correo" else str(d.get("usuario") or "").strip().lower()
            self._ses = {"cuenta": cuenta,
                         "nombre": meta.get("nombre") or "", "uid": uid, "negocios": negocios,
                         "negocio": negocios[0], "recordar": bool(d.get("recordar"))}
            self._tomar_tokens(r)
            return self.estado()
        except Exception as e:
            return {"error": mensaje(e)}

    def elegir_negocio(self, nid):
        if not self._ses:
            return {"error": "Entra con tu usuario."}
        if not nid:   # volver a elegir
            self._ses["negocio"] = None
            self._cx = None
            return self.estado()
        n = next((x for x in self._ses.get("negocios", []) if x["id"] == nid), None)
        if not n:
            return {"error": "Negocio no válido."}
        self._ses["negocio"] = n
        self._guardar_sesion()
        return self.estado()

    def salir(self):
        try:
            if self._ses and self._ses.get("acceso"):
                p = self._prezio.publico()
                self._prezio._pedir("POST", f"{p['supabase_url']}/auth/v1/logout", {},
                                   {"apikey": p["clave_publica"], "Authorization": f"Bearer {self._ses['acceso']}"})
        except Exception:
            pass
        self._ses = None
        self._cx = None
        self._guardar_sesion()
        if self._panel_listo:
            self._panel_listo = False
            # El panel cierra su sesión y vuelve solo a la pantalla de entrar de la app.
            self._navegar(f"{self._prezio.sitio}/auth/salir-app")
        return {"ok": True}

    # ---- panel del negocio (en esta misma ventana, con su propia sesión)
    def abrir_panel(self, seccion=""):
        try:
            n = self._negocio()
            seccion = seccion if seccion in ("", "sucursales", "inventarios", "apariencia", "equipos", "usuarios") else ""
            siguiente = f"/n/{n['slug']}" + (f"/{seccion}" if seccion else "")
            if self._panel_listo:
                url = self._prezio.sitio + siguiente     # el panel ya tiene su sesión en esta ventana
            else:
                hash_ = self._prezio.enlace_panel(self._token())
                url = f"{self._prezio.sitio}/auth/confirm?" + urllib.parse.urlencode(
                    {"token_hash": hash_, "type": "magiclink", "siguiente": siguiente})
            self._panel_listo = True
            self._navegar(url)
            return {"ok": True}
        except Exception as e:
            return {"error": mensaje(e)}

    # ---- asistente de la base de datos
    def buscar_servidores(self, redes_texto=""):
        try:
            redes = [r.strip() for r in str(redes_texto or "").replace(";", ",").split(",") if r.strip()] or None
            lista = self._buscar(redes) if redes else self._buscar()
            return {"ok": True, "servidores": lista, "redes": redes or red.redes_locales()}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": "No se pudo buscar en la red: " + mensaje(e)}

    def _conexion_de(self, d: dict) -> dict:
        motor = d.get("motor")
        if motor not in motores.MOTORES:
            raise ErrorApp("Elige el tipo de base de datos.")
        host = str(d.get("host") or "").strip()
        if not host:
            raise ErrorApp("Escribe la IP o el nombre del servidor.")
        cx = {"motor": motor, "host": host, "puerto": int(d["puerto"]) if str(d.get("puerto") or "").isdigit() else None,
              "instancia": str(d.get("instancia") or "").strip() if motor == "sqlserver" else "",
              "auth": "windows" if motor == "sqlserver" and d.get("auth") == "windows" else "sql",
              "usuario": str(d.get("usuario") or "").strip(),
              "ruta": str(d.get("ruta") or "").strip() if motor == "firebird" else ""}
        clave = str(d.get("clave") or "")
        # Si no escribe la clave otra vez, se usa la que ya estaba autorizada para ese mismo servidor.
        if not clave and self._cx and all(self._cx.get(k) == cx.get(k) for k in ("motor", "host", "puerto", "instancia", "usuario")):
            cx["clave"] = self._cx.get("clave", "")
        else:
            cx["clave"] = cifrado.proteger(clave) if clave else ""
        if motor == "firebird" and not cx["ruta"]:
            raise ErrorApp("Escribe la ruta o el alias de la base de Firebird (ej.: C:\\Sistema\\DATOS.FDB).")
        if cx["auth"] == "sql" and not cx["usuario"] and motor != "postgresql":
            raise ErrorApp("Escribe el usuario de la base de datos.")
        return cx

    def autorizar(self, d):
        """Prueba usuario y clave contra el servidor elegido y devuelve sus bases."""
        try:
            cx = self._conexion_de(d)
            lista = motores.bases(cx)
            self._cx = cx
            return {"ok": True, "bases": lista, "nombre": motores.nombre(cx)}
        except Exception as e:
            return {"error": mensaje(e)}

    def _cx_requerida(self) -> dict:
        if not self._cx:
            raise ErrorApp("Primero autoriza el servidor.")
        return self._cx

    def tablas(self, base):
        try:
            cx = self._cx_requerida()
            return {"ok": True, "tablas": motores.tablas(cx, base)}
        except Exception as e:
            return {"error": mensaje(e)}

    def columnas(self, base, tabla):
        try:
            cols = motores.columnas(self._cx_requerida(), base, tabla)
            return {"ok": True, "columnas": cols, "sugeridas": {c: motores.sugerir(cols, c) for c in ("codigo", "nombre", "precio")}}
        except Exception as e:
            return {"error": mensaje(e)}

    def muestra(self, base, mapeo):
        try:
            cx = {**self._cx_requerida(), "base": base}
            filas = motores.leer(cx, {**mapeo, "base": base}, limite=8)
            prods = pc.productos_de(filas)
            return {"ok": True, "productos": prods, "leidas": len(filas),
                    "descartadas": len(filas) - len(prods)}
        except Exception as e:
            return {"error": mensaje(e)}

    @staticmethod
    def _conexion_publica(m: dict) -> dict:
        """Lo que se guarda en Prezio de una conexión para que TODAS las PCs la vean: servidor, base, tabla y
        columnas. La clave de la base NUNCA va aquí: se queda cifrada en cada PC."""
        cx = m.get("conexion") or {}
        return {"motor": cx.get("motor"), "host": cx.get("host"), "puerto": cx.get("puerto"),
                "instancia": cx.get("instancia") or "", "auth": cx.get("auth") or "sql", "usuario": cx.get("usuario") or "",
                "ruta": cx.get("ruta") or "", "base": m.get("base") or cx.get("base") or "", "tabla": m.get("tabla"),
                "codigo": m.get("codigo"), "nombre": m.get("nombre"), "precio": m.get("precio")}

    def inventarios(self):
        try:
            n = self._negocio()
            token = self._token()
            filas = self._prezio.tabla("GET", f"inventarios?select=id,nombre,origen,estado&negocio_id=eq.{n['id']}&order=nombre", token) or []
            cfg = self._cfg()
            mio = (cfg.get("conector") or {}).get("id")
            locales = cfg.get("inventarios") or {}
            lista = []
            for i in filas:
                o = i.get("origen") or {}
                de_esta = o.get("conector_id") == mio and i["id"] in locales
                # Conexiones hechas antes de esta versión: se publican (sin clave) para que las vea cualquier PC.
                if de_esta and o.get("tipo") == "conector" and not o.get("conexion") and self._puede("inventarios"):
                    try:
                        o = {**o, "conexion": self._conexion_publica(locales[i["id"]]), "configurada_en": platform.node()}
                        self._prezio.tabla("PATCH", f"inventarios?id=eq.{i['id']}&negocio_id=eq.{n['id']}", token, {"origen": o})
                    except Exception:
                        pass
                c = o.get("conexion") or {}
                lista.append({
                    "id": i["id"], "nombre": i["nombre"], "origen": o.get("tipo") or "manual", "de_esta_pc": de_esta,
                    "estado": i.get("estado") or {}, "equipo": o.get("configurada_en") or "",
                    "conexion": ({"servidor": motores.nombre({**c, "base": c.get("base")}), "motor": c.get("motor"), "tabla": c.get("tabla"),
                                  "columnas": [c.get("codigo"), c.get("nombre"), c.get("precio")],
                                  "pide_clave": c.get("auth") != "windows"} if c.get("motor") in motores.MOTORES else None)})
            return {"ok": True, "inventarios": lista}
        except Exception as e:
            return {"error": mensaje(e)}

    def adoptar_fuente(self, d):
        """Seguir enviando desde ESTA PC una base ya conectada en otra: solo hace falta la clave de la base
        (el servidor, la tabla y las columnas ya están guardados en Prezio)."""
        try:
            if not self._puede("inventarios"):
                return {"error": "Necesitas la casilla «Inventarios» para conectar una base de datos."}
            n = self._negocio()
            token = self._token()
            iid = str(d.get("inventario_id") or "")
            filas = self._prezio.tabla("GET", f"inventarios?select=id,nombre,origen&id=eq.{iid}&negocio_id=eq.{n['id']}", token) or []
            if not filas:
                return {"error": "No encontré ese inventario."}
            inv = filas[0]
            origen = inv.get("origen") or {}
            c = origen.get("conexion") or {}
            if origen.get("tipo") != "conector" or c.get("motor") not in motores.MOTORES:
                return {"error": "Esa base se conectó con una versión anterior: ábrela una vez en la PC donde se creó, o conéctala de nuevo aquí."}
            clave = str(d.get("clave") or "")
            cx = {"motor": c["motor"], "host": c.get("host") or "", "puerto": c.get("puerto"), "instancia": c.get("instancia") or "",
                  "auth": c.get("auth") or "sql", "usuario": c.get("usuario") or "", "ruta": c.get("ruta") or "",
                  "clave": cifrado.proteger(clave) if clave else ""}
            if cx["auth"] == "sql" and not clave:
                return {"error": "Escribe la clave de la base de datos."}
            base = c.get("base") or cx.get("ruta") or ""
            mapeo = {k: str(c.get(k) or "") for k in ("tabla", "codigo", "nombre", "precio")}
            prueba = pc.productos_de(motores.leer({**cx, "base": base}, {**mapeo, "base": base}, limite=50))
            if not prueba:
                return {"error": "Se conectó, pero esa tabla no devuelve productos con código, nombre y precio."}
            cfg = self._cfg()
            con = self._conector(cfg)
            r = self._prezio.tabla("PATCH", f"inventarios?id=eq.{iid}&negocio_id=eq.{n['id']}", token,
                                   {"origen": {**origen, "conector_id": con["id"], "configurada_en": platform.node()}})
            if not r:
                return {"error": "No se pudo cambiar la PC que envía (¿tienes la casilla «Inventarios»?)."}
            cfg.setdefault("inventarios", {})[iid] = {**mapeo, "base": base, "conexion": {**cx, "base": base}, "titulo": inv["nombre"]}
            cfg.setdefault("cada_min", 10)
            self._guardar_cfg(cfg)
            threading.Thread(target=self._enviar_fondo, daemon=True).start()
            return {"ok": True, "mensaje": f"Listo: «{inv['nombre']}» ahora se envía desde esta PC. Enviando los precios…"}
        except Exception as e:
            return {"error": mensaje(e)}

    def _conector(self, cfg: dict) -> dict:
        """El conector de esta PC para este negocio (lo crea la primera vez, con la sesión de quien está en la app)."""
        n = self._negocio()
        actual = cfg.get("conector") or {}
        if actual.get("negocio_id") == n["id"] and cfg.get("clave"):
            return actual
        r = self._prezio.rpc("conector_para_app", {"p_negocio": n["id"], "p_nombre": f"PC {platform.node()}"[:60]}, self._token())
        cfg["conector"] = {"id": r["id"], "negocio_id": n["id"], "negocio": n["nombre"]}
        cfg["clave"] = cifrado.proteger(r["clave"])
        cfg["sitio"] = self._prezio.sitio
        if actual.get("negocio_id") and actual.get("negocio_id") != n["id"]:
            cfg["inventarios"] = {}   # era de otro negocio
        return cfg["conector"]

    def guardar_fuente(self, d):
        """d = {base, mapeo{tabla,codigo,nombre,precio}, inventario_id | nuevo_nombre, principal: bool}"""
        try:
            if not self._puede("inventarios"):
                return {"error": "Necesitas la casilla «Inventarios» para conectar una base de datos."}
            cx = self._cx_requerida()
            mapeo = {k: str((d.get("mapeo") or {}).get(k) or "") for k in ("tabla", "codigo", "nombre", "precio")}
            if not all(mapeo.values()):
                return {"error": "Elige la tabla y las columnas de código, nombre y precio."}
            base = str(d.get("base") or cx.get("ruta") or "")
            prueba = pc.productos_de(motores.leer({**cx, "base": base}, {**mapeo, "base": base}, limite=50))
            if not prueba:
                return {"error": "Esa tabla no devuelve productos con código, nombre y precio: revisa las columnas."}
            cfg = self._cfg()
            token = self._token()
            con = self._conector(cfg)
            n = self._negocio()
            entrada = {**mapeo, "base": base, "conexion": {**cx, "base": base}}
            origen = {"tipo": "conector", "conector_id": con["id"], "conexion": self._conexion_publica(entrada),
                      "configurada_en": platform.node()}
            iid = str(d.get("inventario_id") or "")
            if iid:
                r = self._prezio.tabla("PATCH", f"inventarios?id=eq.{iid}&negocio_id=eq.{n['id']}", token, {"origen": origen})
                if not r:
                    return {"error": "No se pudo usar ese inventario (¿tienes la casilla «Inventarios»?)."}
                nombre_inv = r[0]["nombre"]
            else:
                nombre_inv = str(d.get("nuevo_nombre") or "").strip()[:60] or f"Base de datos · {base or mapeo['tabla']}"[:60]
                r = self._prezio.tabla("POST", "inventarios", token, {"negocio_id": n["id"], "nombre": nombre_inv, "origen": origen})
                iid = r[0]["id"]
            cfg.setdefault("inventarios", {})[iid] = {**entrada, "titulo": nombre_inv}
            cfg.setdefault("cada_min", 10)
            self._guardar_cfg(cfg)
            aviso = ""
            if d.get("principal"):
                try:
                    s = self._prezio.tabla("PATCH", f"sucursales?negocio_id=eq.{n['id']}&es_principal=eq.true", token,
                                          {"fuente": {"tipo": "inventario", "inventario_id": iid}})
                    if not s:
                        aviso = " No se pudo asignar a la Principal (falta la casilla «Sucursales»): hazlo en el panel › Sucursales."
                except ErrorApp:
                    aviso = " No se pudo asignar a la Principal: hazlo en el panel › Sucursales."
            threading.Thread(target=self._enviar_fondo, daemon=True).start()
            return {"ok": True, "inventario": iid, "nombre": nombre_inv,
                    "mensaje": f"Listo: «{nombre_inv}» se llena desde {motores.nombre({**cx, 'base': base})}. Enviando los precios…{aviso}"}
        except Exception as e:
            return {"error": mensaje(e)}

    def fuentes(self):
        """Lo que esta PC envía: un renglón por inventario."""
        cfg = self._cfg()
        est = pc.leer_json(pc.ESTADO, {})
        lista = []
        for iid, m in (cfg.get("inventarios") or {}).items():
            cx = m.get("conexion") or (pc.conexion_legada(cfg["sql"]) if cfg.get("sql") else {})
            e = est.get(iid, {})
            lista.append({"id": iid, "nombre": m.get("titulo") or "Inventario", "origen": motores.nombre({**cx, "base": m.get("base") or cx.get("base")}) if cx else "—",
                          "tabla": m.get("tabla"), "columnas": [m.get("codigo"), m.get("nombre"), m.get("precio")],
                          "productos": e.get("productos"), "hora": e.get("hora")})
        return {"ok": True, "fuentes": lista, "ultimo": self._ultimo_envio, "cada_min": cfg.get("cada_min", 10),
                "inicio": self._tarea_instalada()}

    def quitar_fuente(self, iid):
        cfg = self._cfg()
        if (cfg.get("inventarios") or {}).pop(str(iid), None) is None:
            return {"error": "No estaba configurado."}
        self._guardar_cfg(cfg)
        return {"ok": True, "mensaje": "Esta PC ya no lo envía. El inventario sigue en Prezio con sus últimos precios."}

    # ---- copia automática
    def _enviar_fondo(self):
        self._enviar()

    def enviar_ahora(self):
        return self._enviar()

    def _enviar(self):
        if not self._ocupado.acquire(blocking=False):
            return {"error": "Ya se está enviando. Espera un momento."}
        try:
            cfg = self._cfg()
            if not cfg.get("clave"):
                return {"error": "Todavía no hay ninguna base conectada."}
            r = pc.sincronizar(cfg)
            self._ultimo_envio = {"hora": time.time(), **r}
            return {"ok": True, **r}
        except pc.ErrorPrezio as e:
            self._ultimo_envio = {"hora": time.time(), "error": str(e)}
            return {"error": "Prezio rechazó el conector de esta PC: vuelve a conectar la base." if e.estado == 401 else str(e)}
        except Exception as e:
            self._ultimo_envio = {"hora": time.time(), "error": mensaje(e)}
            return {"error": mensaje(e)}
        finally:
            self._ocupado.release()

    def guardar_frecuencia(self, minutos):
        cfg = self._cfg()
        try:
            cfg["cada_min"] = max(1, min(1440, int(minutos or 10)))
        except (TypeError, ValueError):
            return {"error": "Escribe los minutos con números."}
        self._guardar_cfg(cfg)
        return {"ok": True, "cada_min": cfg["cada_min"]}

    @staticmethod
    def _consulta_tarea() -> bool:
        if os.name != "nt":
            return False
        try:
            r = subprocess.run(["schtasks", "/Query", "/TN", TAREA], capture_output=True, text=True, errors="replace",
                               creationflags=0x08000000)
            return r.returncode == 0
        except OSError:
            return False

    def _tarea_instalada(self):
        """Windows a veces no deja a una cuenta normal consultar una tarea creada como SYSTEM: en ese caso
        vale lo que dejó anotado el paso con permiso de administrador."""
        if self._consulta_tarea():
            return True
        return bool((pc.leer_json(ARRANQUE, {}) or {}).get("instalada"))

    def arranque(self, activar):
        """Crear o quitar la tarea de Windows (pide permiso de administrador con la ventana de Windows)."""
        if os.name != "nt":
            return {"error": "Solo en Windows."}
        import ctypes
        frozen = getattr(sys, "frozen", False)
        argumentos = ("--instalar" if activar else "--desinstalar") if frozen \
            else f'"{Path(__file__).resolve()}" ' + ("--instalar" if activar else "--desinstalar")
        inicio = time.time()
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, argumentos, None, 0)
        if r <= 32:
            return {"error": "Windows no dio permiso de administrador."}
        accion = "instalar" if activar else "desinstalar"
        for _ in range(80):          # hasta 40 s: el programa con permiso tarda en abrir y crear la tarea
            time.sleep(0.5)
            res = pc.leer_json(ARRANQUE, {}) or {}
            if res.get("accion") == accion and float(res.get("hora") or 0) >= inicio - 1:
                if res.get("ok"):
                    return {"ok": True, "inicio": bool(activar)}
                detalle = " ".join(str(res.get("salida") or "").split())[:200]
                return {"error": f"Windows no pudo {'crear' if activar else 'quitar'} la tarea" + (f": {detalle}" if detalle else ".")}
            if self._consulta_tarea() == bool(activar):
                return {"ok": True, "inicio": bool(activar)}
        return {"error": "Windows no respondió a tiempo. Si apareció la ventana de permiso, acéptala y vuelve a intentarlo."}

    def registro(self):
        try:
            lineas = (pc.CARPETA / "conector.log").read_text(encoding="utf-8", errors="replace").splitlines()[-60:]
        except OSError:
            lineas = []
        return {"ok": True, "lineas": lineas}

    # ---- actualizaciones
    def version_nueva(self):
        """Al abrir: ¿hay una versión más nueva publicada? (la ventana la instala sola)."""
        info = version_publicada(self._prezio.sitio)
        return {"ok": True, **info} if info else {"ok": True, "version": None}

    def actualizar(self):
        """Descarga la versión nueva y la instala; la app se cierra y el instalador la vuelve a abrir."""
        info = version_publicada(self._prezio.sitio)
        if not info:
            return {"ok": True, "version": None}
        try:
            ruta = descargar_instalador(info["url"])
            if os.name != "nt":
                return {"error": "Solo en Windows."}
            import ctypes
            # Pide permiso de administrador (la app está instalada para toda la PC).
            r = ctypes.windll.shell32.ShellExecuteW(None, "runas", ruta,
                                                    "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS", None, 0)
            if r <= 32:
                return {"error": "Windows no dio permiso para instalar la actualización. Se seguirá usando esta versión."}
            anotar_actualizacion(f"instalando {info['version']} (desde la ventana)")

            def cerrar():
                time.sleep(1.5)
                try:
                    if self._ventana is not None:
                        self._ventana.destroy()
                finally:
                    os._exit(0)
            threading.Thread(target=cerrar, daemon=True).start()
            return {"ok": True, "version": info["version"]}
        except Exception as e:
            anotar_actualizacion(f"error al actualizar: {e}")
            return {"error": "No se pudo descargar la actualización: " + mensaje(e)}

    def abrir_en_navegador(self, url):
        """Desde el panel: abrir una página de Prezio (p. ej. el verificador) en el navegador, sin dejar la ventana sin salida."""
        if str(url).startswith(self._prezio.sitio + "/"):
            webbrowser.open(str(url))
            return {"ok": True}
        return {"error": "Solo se pueden abrir páginas de Prezio."}

    def abrir_enlace(self, url):
        if str(url).startswith("https://"):
            webbrowser.open(str(url))
        return {"ok": True}


# Lo que hace cosas en la PC (bases de datos, claves, archivos) solo responde a la pantalla propia de la app:
# si en la ventana se abre otra página, no puede usarlo. Desde el panel de Prezio solo se vuelve a la app o se sale.
def _solo(permitido):
    import functools

    def envolver(f):
        @functools.wraps(f)
        def w(self, *a, **k):
            if not permitido(self):
                return {"error": "No permitido desde esta página."}
            return f(self, *a, **k)
        return w
    return envolver


for _n in ("estado", "activar", "desactivar", "entrar", "elegir_negocio", "abrir_panel", "buscar_servidores", "autorizar", "tablas",
           "columnas", "muestra", "inventarios", "adoptar_fuente", "guardar_fuente", "fuentes", "quitar_fuente", "enviar_ahora", "guardar_frecuencia",
           "arranque", "registro", "version_nueva", "actualizar", "abrir_enlace"):
    setattr(Api, _n, _solo(Api._desde_la_app)(getattr(Api, _n)))
for _n in ("salir", "ir_app", "mostrar_inicio", "abrir_en_navegador"):
    setattr(Api, _n, _solo(Api._desde_prezio)(getattr(Api, _n)))


# ---------------------------------------------------------------- actualizaciones
def anotar_actualizacion(texto: str) -> None:
    try:
        pc.log.info("Actualización: %s", texto)
    except Exception:
        pass


def version_publicada(sitio: str, abrir=urllib.request.urlopen) -> dict | None:
    """{version, url} si en apps.json hay una versión más nueva que esta, publicada en las descargas de Prezio."""
    try:
        pedido = urllib.request.Request(f"{sitio}/apps.json?t={int(time.time())}",
                                        headers={"Cache-Control": "no-cache", "User-Agent": "PrezioAdministrador/" + VERSION})
        with abrir(pedido, timeout=15) as r:
            info = json.loads(r.read().decode("utf-8")).get("administrador") or {}
    except Exception as e:
        anotar_actualizacion(f"no se pudo revisar apps.json ({e})")
        return None
    nueva, url = str(info.get("version") or ""), str(info.get("url") or "")
    if nueva and _version_mayor(nueva, VERSION) and url.startswith(ORIGEN_ACTUALIZACION) and url.endswith(".exe"):
        return {"version": nueva, "url": url}
    return None


def descargar_instalador(url: str, abrir=urllib.request.urlopen) -> str:
    if not url.startswith(ORIGEN_ACTUALIZACION) or not url.endswith(".exe"):
        raise ValueError("Dirección de actualización no permitida")
    import tempfile
    destino = os.path.join(tempfile.gettempdir(), f"Instalador_Prezio_Administrador_{int(time.time())}.exe")
    pedido = urllib.request.Request(url, headers={"User-Agent": "PrezioAdministrador/" + VERSION})
    with abrir(pedido, timeout=300) as respuesta, open(destino, "wb") as archivo:
        while True:
            bloque = respuesta.read(1 << 16)
            if not bloque:
                break
            archivo.write(bloque)
    with open(destino, "rb") as f:
        es_exe = f.read(2) == b"MZ"
    if os.path.getsize(destino) < 500_000 or not es_exe:
        raise RuntimeError("la descarga no es un instalador válido")
    return destino


def servicio_actualizar(sitio: str) -> None:
    """La copia automática (tarea de Windows como SYSTEM) se actualiza sola, en silencio: al arrancar y cada 6 horas."""
    time.sleep(90)
    while True:
        info = version_publicada(sitio)
        if info:
            try:
                ruta = descargar_instalador(info["url"])
                anotar_actualizacion(f"instalando {info['version']} en silencio (copia automática)")
                # /SERVICIO: el instalador vuelve a arrancar la tarea, no la ventana (no hay nadie en esta sesión).
                subprocess.Popen([ruta, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/SERVICIO"],
                                 close_fds=True, creationflags=0x00000008 | 0x00000200)
                return
            except Exception as e:
                anotar_actualizacion(f"error al actualizar: {e}")
        time.sleep(CADA_REVISION_S)


def _version_mayor(a, b):
    def partes(v):
        try:
            return [int(x) for x in str(v).split(".")[:3]]
        except ValueError:
            return [0, 0, 0]
    return partes(a) > partes(b)


# ---------------------------------------------------------------- arranque
def _anotar_arranque(accion: str, codigo: int, salida: str, instalada: bool) -> None:
    """Deja dicho cómo salió (la app normal lo lee para confirmar el cambio o mostrar el motivo)."""
    try:
        pc.guardar_json(ARRANQUE, {"accion": accion, "hora": time.time(), "ok": codigo == 0, "codigo": codigo,
                                   "salida": (salida or "")[:400], "instalada": instalada})
    except Exception:
        pass


def instalar_tarea():
    destino = f'"{sys.executable}" --servicio' if getattr(sys, "frozen", False) \
        else f'"{sys.executable}" "{Path(__file__).resolve()}" --servicio'
    try:
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", TAREA, "/SC", "ONSTART", "/RU", "SYSTEM", "/RL", "HIGHEST",
                            "/TR", destino], capture_output=True, text=True, errors="replace", creationflags=0x08000000)
        codigo, salida = r.returncode, (r.stdout or "") + " " + (r.stderr or "")
        if codigo == 0:
            subprocess.run(["schtasks", "/Run", "/TN", TAREA], capture_output=True, creationflags=0x08000000)
    except Exception as e:
        codigo, salida = 1, str(e)
    _anotar_arranque("instalar", codigo, salida, codigo == 0)
    return codigo


def quitar_tarea():
    try:
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TAREA], capture_output=True, text=True, errors="replace",
                           creationflags=0x08000000)
        codigo, salida = r.returncode, (r.stdout or "") + " " + (r.stderr or "")
    except Exception as e:
        codigo, salida = 1, str(e)
    _anotar_arranque("desinstalar", codigo, salida, False)
    return codigo


def main():
    args = sys.argv[1:]
    if "--servicio" in args:
        pc.preparar_registro(consola=False)
        cfg = pc.leer_json(pc.CONFIG, None)
        threading.Thread(target=servicio_actualizar, args=((cfg or {}).get("sitio") or SITIO,), daemon=True).start()
        if not cfg or not cfg.get("clave"):
            pc.log.error("Falta conectar la base: abre Prezio Administrador › Base de datos.")
            while True:            # sigue vivo para poder actualizarse
                time.sleep(3600)
        pc.trabajar(cfg)
        return
    if "--instalar" in args:
        sys.exit(instalar_tarea())
    if "--desinstalar" in args:
        sys.exit(quitar_tarea())
    pc.preparar_registro(consola=False)
    import webview
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # enlaces a otros sitios: en el navegador
    api = Api()
    ventana = webview.create_window("Prezio Administrador", str(AQUI / "interfaz.html"), js_api=api,
                                    width=1240, height=860, min_size=(900, 620), background_color="#F3F5F7")
    api._ventana = ventana   # con «_»: pywebview no la publica para la página (publicarla rompe la API)

    def al_cargar():
        if not api._inicio:   # la primera dirección es la pantalla propia de la app
            try:
                api._inicio = (ventana.get_current_url() or "").split("#")[0]
            except Exception:
                pass
    ventana.events.loaded += al_cargar
    DATOS.mkdir(parents=True, exist_ok=True)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(DATOS / "web"))


if __name__ == "__main__":
    main()
