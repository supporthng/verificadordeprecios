"""Consulta de Precios para Windows: verificador de precios tipo quiosco.

- Abre la app sin internet (GitHub Pages) a pantalla completa, siempre encima, sin bordes.
- Usa WebView2 (el motor de Microsoft Edge, ya incluido en Windows 10/11): los precios
  quedan guardados en el equipo y funciona SIN internet.
- Bloquea Alt+Tab, Alt+Esc, Ctrl+Esc, Alt+F4, Alt+Espacio y la tecla Windows.
- No se puede cerrar ni minimizar: se sale SOLO desde el menú ✕ de la app, con la clave de salida.
- Una sola copia abierta a la vez.

Ctrl+Alt+Supr no se puede bloquear desde un programa (es una protección de Windows). Para un
bloqueo total, usar además "Acceso asignado" de Windows (ver la guía en Equipos sin internet).
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import webview

DIRECCION = "https://supporthng.github.io/verificadordeprecios/"
VERSION = "1.0.0"
DATOS = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ConsultaPrecios", "WebView")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# --------------------------------------------------------------------------- una sola copia
def ya_abierta():
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW(None, False, "Local\\ConsultaPreciosKiosco")
    return ctypes.get_last_error() == 183   # ERROR_ALREADY_EXISTS


# --------------------------------------------------------------------------- bloqueo de teclas
WH_KEYBOARD_LL = 13
LLKHF_ALTDOWN = 0x20
VK_TAB, VK_ESCAPE, VK_SPACE, VK_F4 = 0x09, 0x1B, 0x20, 0x73
VK_LWIN, VK_RWIN, VK_APPS, VK_CONTROL = 0x5B, 0x5C, 0x5D, 0x11
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


def tecla_bloqueada(vk, flags, ctrl_presionado):
    """True si la combinación debe ignorarse (sacaría al cliente de la app)."""
    alt = bool(flags & LLKHF_ALTDOWN)
    if vk in (VK_LWIN, VK_RWIN, VK_APPS):
        return True
    if alt and vk in (VK_TAB, VK_ESCAPE, VK_F4, VK_SPACE):
        return True
    if ctrl_presionado and vk == VK_ESCAPE:
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
            if tecla_bloqueada(datos.vkCode, datos.flags, ctrl):
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


# --------------------------------------------------------------------------- puente con la app web
class Kiosco:
    """Lo que la app web puede pedir (window.pywebview.api.*), solo tras la clave de salida."""

    def __init__(self):
        self._ventana = None
        self._permitir_cierre = False

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
        if self._ventana:
            self._ventana.destroy()
        return True

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
        "Consulta de Precios", DIRECCION, js_api=api,
        fullscreen=True, frameless=True, on_top=True, easy_drag=False,
        background_color="#F4F8FF", text_select=False, zoomable=False, confirm_close=False)
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
    # private_mode=False + storage_path: los precios guardados sobreviven al cerrar y reiniciar.
    webview.start(gui="edgechromium", private_mode=False, storage_path=DATOS, debug=False)
    teclado.quitar()


if __name__ == "__main__":
    main()
