"""Claves guardadas en la PC, cifradas con Windows (DPAPI): solo esta PC las puede leer.

Nunca se envían a Prezio: las credenciales de la base de datos se quedan en la PC del negocio.
"""
import base64
import os


def _dpapi(datos: bytes, descifrar: bool, equipo: bool = True) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    salida = BLOB()
    # 0x1 sin ventanas; 0x4 = de la PC (la tarea que corre como SYSTEM al encender también la descifra).
    banderas = 0x1 | (0x4 if equipo else 0)
    crypt = ctypes.windll.crypt32
    if descifrar:
        ok = crypt.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, banderas, ctypes.byref(salida))
    else:
        ok = crypt.CryptProtectData(ctypes.byref(entrada), "Prezio", None, None, None, banderas, ctypes.byref(salida))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def proteger(texto: str, equipo: bool = True) -> str:
    """equipo=True: la descifra cualquier cuenta de esta PC (la tarea de SYSTEM). False: solo este usuario de Windows."""
    if not texto:
        return ""
    if os.name == "nt":
        prefijo = "dpapi:" if equipo else "dpapiu:"
        return prefijo + base64.b64encode(_dpapi(texto.encode("utf-8"), False, equipo)).decode()
    return "plano:" + base64.b64encode(texto.encode("utf-8")).decode()   # solo para pruebas fuera de Windows


def revelar(valor: str) -> str:
    if not valor:
        return ""
    tipo, _, datos = valor.partition(":")
    crudo = base64.b64decode(datos)
    if tipo == "dpapi":
        return _dpapi(crudo, True, True).decode("utf-8")
    if tipo == "dpapiu":
        return _dpapi(crudo, True, False).decode("utf-8")
    return crudo.decode("utf-8")
