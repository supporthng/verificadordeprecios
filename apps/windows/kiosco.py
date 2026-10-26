"""Prezio para Windows: verificador de precios tipo quiosco.

- Abre Prezio (SITIO/equipo) a pantalla completa, siempre encima, sin bordes.
- Usa WebView2 (el motor de Microsoft Edge, ya incluido en Windows 10/11): los precios
  quedan guardados en el equipo y funciona SIN internet.
- Bloquea Alt+Tab, Alt+Esc, Ctrl+Esc, Ctrl+Shift+Esc, Alt+F4, Alt+Espacio y la tecla Windows.
- Oculta la barra de tareas (Inicio) mientras está abierta; vuelve a aparecer al cerrar la app.
- No se puede cerrar ni minimizar: se sale SOLO desde el menú ⓘ › «Salir de la app», con la clave de salida.
- Se actualiza sola: al abrir y cada hora revisa SITIO/apps.json e instala la versión nueva en silencio.
- Una sola copia abierta a la vez.

Ctrl+Alt+Supr no se puede bloquear desde un programa (es una protección de Windows). Para un
bloqueo total, usar además "Acceso asignado" de Windows.
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from ctypes import wintypes

import webview

# La compilación (GitHub Actions) reemplaza estos tres valores.
SITIO = "https://prezio-jade.vercel.app"
VERSION = "1.0.0"
# Solo se aceptan actualizaciones publicadas en las descargas de Prezio.
ORIGEN_ACTUALIZACION = "https://github.com/supporthng/prezio/releases/download/"
DIRECCION = SITIO + "/equipo"
DATOS = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Prezio", "WebView")
REGISTRO = os.path.join(os.path.dirname(DATOS), "actualizacion.log")
APPS_JSON = SITIO + "/apps.json"
CADA_REVISION_S = 60 * 60


def anotar(texto):
    """Registro breve de las actualizaciones (para revisar si algo falla)."""
    try:
        os.makedirs(os.path.dirname(REGISTRO), exist_ok=True)
        if os.path.exists(REGISTRO) and os.path.getsize(REGISTRO) > 200_000:
            os.replace(REGISTRO, REGISTRO + ".1")
        with open(REGISTRO, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + texto + "\n")
    except Exception:
        pass


def version_mayor(a, b):
    def partes(v):
        try:
            return [int(x) for x in str(v).split(".")[:3]] + [0] * (3 - len(str(v).split(".")[:3]))
        except ValueError:
            return [0, 0, 0]
    return partes(a) > partes(b)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# --------------------------------------------------------------------------- una sola copia
def ya_abierta():
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW(None, False, "Local\\PrezioKiosco")
    return ctypes.get_last_error() == 183   # ERROR_ALREADY_EXISTS


# --------------------------------------------------------------------------- bloqueo de teclas
WH_KEYBOARD_LL = 13
LLKHF_ALTDOWN = 0x20
VK_TAB, VK_ESCAPE, VK_SPACE, VK_F4 = 0x09, 0x1B, 0x20, 0x73
VK_LWIN, VK_RWIN, VK_APPS, VK_CONTROL, VK_SHIFT = 0x5B, 0x5C, 0x5D, 0x11, 0x10
WM_QUIT = 0x0012


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def tecla_bloqueada(vk, flags, ctrl_presionado, shift_presionado=False):
    """True si la combinación debe ignorarse (sacaría al cliente de la app)."""
    alt = bool(flags & LLKHF_ALTDOWN)
    if vk in (VK_LWIN, VK_RWIN, VK_APPS):
        return True
    if alt and vk in (VK_TAB, VK_ESCAPE, VK_F4, VK_SPACE):
        return True
    if ctrl_presionado and vk == VK_ESCAPE:   # Ctrl+Esc (Inicio) y Ctrl+Shift+Esc (Administrador de tareas)
        return True
    return False


class Teclado:
    def __init__(self):
        self._gancho = None
        self._hilo_id = None
        self._proc = HOOKPROC(self._filtro)   # se guarda: si se libera, Windows llamaría a basura

    def _filtro(self, codigo, wparam, lparam):
        if codigo == 0:
            datos = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
            shift = bool(user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
            if tecla_bloqueada(datos.vkCode, datos.flags, ctrl, shift):
                return 1
        return user32.CallNextHookEx(self._gancho, codigo, wparam, lparam)

    def _bucle(self):
        self._hilo_id = kernel32.GetCurrentThreadId()
        self._gancho = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        mensaje = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) > 0:
            pass
        if self._gancho:
            user32.UnhookWindowsHookEx(self._gancho)
            self._gancho = None

    def poner(self):
        threading.Thread(target=self._bucle, name="bloqueo-teclas", daemon=True).start()

    def quitar(self):
        if self._hilo_id:
            user32.PostThreadMessageW(self._hilo_id, WM_QUIT, 0, 0)


teclado = Teclado()


# --------------------------------------------------------------------------- barra de tareas
SW_HIDE, SW_SHOW = 0, 5
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL


def _barras_de_tareas():
    """La barra principal y las de otros monitores."""
    barras = []
    principal = user32.FindWindowW("Shell_TrayWnd", None)
    if principal:
        barras.append(principal)
    otra = None
    while True:
        otra = user32.FindWindowExW(None, otra, "Shell_SecondaryTrayWnd", None)
        if not otra:
            break
        barras.append(otra)
    return barras


class BarraDeTareas:
    """Oculta la barra de tareas (y el botón Inicio) mientras la app está abierta."""

    def __init__(self):
        self._oculta = False
        self._hilo = None

    def ocultar(self):
        self._oculta = True
        for b in _barras_de_tareas():
            user32.ShowWindow(b, SW_HIDE)
        if not self._hilo:
            # Si Windows la vuelve a mostrar (reinicio del Explorador, otro monitor), ocultarla otra vez.
            self._hilo = threading.Thread(target=self._vigilar, name="barra-tareas", daemon=True)
            self._hilo.start()

    def _vigilar(self):
        while self._oculta:
            time.sleep(2)
            if self._oculta:
                for b in _barras_de_tareas():
                    if user32.IsWindowVisible(b):
                        user32.ShowWindow(b, SW_HIDE)

    def mostrar(self):
        self._oculta = False
        for b in _barras_de_tareas():
            user32.ShowWindow(b, SW_SHOW)


barra = BarraDeTareas()


# --------------------------------------------------------------------------- puente con la app web
class Kiosco:
    """Lo que la página /equipo puede pedir (window.pywebview.api.*); salir, solo tras la clave de salida."""

    def __init__(self):
        self._ventana = None
        self._permitir_cierre = False
        self._actualizando = False

    def esApp(self):
        return True

    def plataforma(self):
        return "windows"

    def version(self):
        return VERSION

    def bloqueoTotal(self):
        return False

    def salir(self):
        self._permitir_cierre = True
        teclado.quitar()
        barra.mostrar()
        if self._ventana:
            self._ventana.destroy()
        return True

    def cerrar(self):
        """Botón ✕: cierra la app (no hay Ajustes que abrir en Windows)."""
        return self.salir()

    def buscarActualizacion(self):
        """Desde el menú del equipo: revisar ahora y avisar en pantalla."""
        threading.Thread(target=self._revisar, args=(True,), name="revisar-ahora", daemon=True).start()
        return True

    def _instalar_desde(self, url):
        if not isinstance(url, str) or not url.startswith(ORIGEN_ACTUALIZACION) or not url.endswith(".exe"):
            anotar(f"actualización rechazada (dirección no permitida): {url!r}")
            return False
        if self._actualizando:
            return True
        self._actualizando = True
        threading.Thread(target=self._actualizar, args=(url,), name="actualizar-app", daemon=True).start()
        return True

    def _revisar(self, avisar=False):
        """Lee apps.json; si trae una versión más nueva, se instala sola (sin preguntar)."""
        if avisar:
            self._avisar("buscando")
        try:
            pedido = urllib.request.Request(f"{APPS_JSON}?t={int(time.time())}",
                                            headers={"Cache-Control": "no-cache", "User-Agent": "Prezio/" + VERSION})
            with urllib.request.urlopen(pedido, timeout=20) as r:
                info = json.loads(r.read().decode("utf-8")).get("windows") or {}
            nueva = str(info.get("version") or "")
            if nueva and version_mayor(nueva, VERSION):
                anotar(f"hay versión nueva {nueva} (esta es {VERSION})")
                if not self._instalar_desde(str(info.get("url") or "")) and avisar:
                    self._avisar("error", "dirección de descarga no permitida")
            elif avisar:
                self._avisar("al_dia")
            return True
        except Exception as exc:
            anotar(f"no se pudo revisar apps.json ({exc})")
            if avisar:
                self._avisar("error", f"no se pudo leer apps.json: {exc}")
            return False

    def revisar_cada_rato(self):
        time.sleep(5)           # dejar que la app abra y cargue los precios
        while True:
            for _ in range(5):
                if self._revisar():
                    break
                time.sleep(60)
            time.sleep(CADA_REVISION_S)

    def _avisar(self, estado, detalle=""):
        """Avisa a la pantalla; en un error manda también el motivo (para saber qué falló)."""
        try:
            motivo = json.dumps(str(detalle)[:140])
            self._ventana.evaluate_js(f"window.__prezioActualizacion && window.__prezioActualizacion('{estado}', {motivo})")
        except Exception:
            pass

    def _actualizar(self, url):
        try:
            anotar(f"descargando {url}")
            self._avisar("descargando")
            destino = os.path.join(tempfile.gettempdir(), f"Instalador_Prezio_{int(time.time())}.exe")
            pedido = urllib.request.Request(url, headers={"User-Agent": "Prezio/" + VERSION})
            with urllib.request.urlopen(pedido, timeout=180) as respuesta, open(destino, "wb") as archivo:
                while True:
                    bloque = respuesta.read(1 << 16)
                    if not bloque:
                        break
                    archivo.write(bloque)
            tamano = os.path.getsize(destino)
            with open(destino, "rb") as f:
                es_exe = f.read(2) == b"MZ"
            if tamano < 500_000 or not es_exe:
                raise RuntimeError(f"la descarga no es un instalador válido ({tamano} bytes)")
            anotar(f"descargado ({tamano:,} bytes); instalando en silencio")
            self._avisar("instalando")
            # El instalador espera a que esta app se cierre, reemplaza los archivos y la vuelve a abrir.
            subprocess.Popen([destino, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                             close_fds=True, creationflags=0x00000008 | 0x00000200)  # DETACHED | NEW_GROUP
            time.sleep(1)
            self.salir()
        except Exception as exc:
            anotar(f"error al actualizar: {exc}")
            self._actualizando = False
            self._avisar("error", exc)

    def recargar(self):
        if self._ventana:
            self._ventana.load_url(DIRECCION)
        return True


def main():
    if ya_abierta():
        sys.exit(0)
    os.makedirs(DATOS, exist_ok=True)
    api = Kiosco()
    ventana = webview.create_window(
        "Prezio", DIRECCION, js_api=api,
        fullscreen=True, frameless=True, on_top=True, easy_drag=False,
        background_color="#102A43", text_select=False, zoomable=False, confirm_close=False)
    api._ventana = ventana

    def al_cerrar():
        return api._permitir_cierre      # False = no se cierra (Alt+F4, etc.)

    def al_minimizar():
        time.sleep(0.2)
        try:
            ventana.restore()
        except Exception:
            pass

    ventana.events.closing += al_cerrar
    ventana.events.minimized += al_minimizar
    teclado.poner()
    barra.ocultar()
    threading.Thread(target=api.revisar_cada_rato, name="revisar-actualizacion", daemon=True).start()
    import atexit
    atexit.register(barra.mostrar)      # pase lo que pase, la barra de tareas vuelve al salir
    # private_mode=False + storage_path: los precios guardados sobreviven al cerrar y reiniciar.
    try:
        webview.start(gui="edgechromium", private_mode=False, storage_path=DATOS, debug=False)
    finally:
        teclado.quitar()
        barra.mostrar()


if __name__ == "__main__":
    main()
