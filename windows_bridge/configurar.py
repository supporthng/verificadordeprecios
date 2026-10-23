"""Asistente gráfico para configurar el conector, sin Python instalado en el equipo final."""
import os
import secrets
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

DEST = Path(os.environ.get("PROGRAMDATA", str(Path.home()))) / "ConsultaPrecios" / "bridge.env"
TASK = "ConsultaPreciosConectorLAN"


def existing():
    result = {}
    if DEST.exists():
        for line in DEST.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip()
    return result


def save():
    url = url_var.get().strip().rstrip("/")
    key = key_var.get().strip()
    pwd = pwd_var.get()
    confirm = confirm_var.get()
    networks = networks_var.get().strip()
    if urlparse(url).scheme != "https" or not urlparse(url).netloc:
        messagebox.showerror("Validación", "La URL de Supabase debe comenzar por https://")
        return
    if not key:
        messagebox.showerror("Validación", "Introduce la clave secreta de Supabase.")
        return
    if len(pwd) < 12 or pwd != confirm:
        messagebox.showerror("Validación", "La contraseña debe tener 12 o más caracteres y coincidir.")
        return
    import ipaddress
    try:
        for item in networks.split(","):
            net = ipaddress.ip_network(item.strip(), strict=False)
            if net.version != 4 or net.num_addresses > 256:
                raise ValueError("Utiliza redes IPv4 de máximo 256 direcciones")
    except ValueError as e:
        messagebox.showerror("Red no válida", str(e))
        return
    # Conservar ajustes no gestionados por esta pantalla.
    cfg = existing()
    cfg.pop("SUPABASE_SERVICE_ROLE_KEY", None)   # una sola clave: la que se escribe aquí
    cfg.update({
        "SUPABASE_URL": url,
        "SUPABASE_SECRET_KEY": key,
        "BRIDGE_PASSWORD": pwd,
        "ALLOWED_NETWORKS": networks,
        "BRIDGE_HOST": "0.0.0.0",
        "BRIDGE_PORT": "8765",
    })
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".tmp")
    tmp.write_text("".join(f"{k}={v}\n" for k, v in cfg.items()), encoding="utf-8")
    os.replace(tmp, DEST)
    # ProgramData ACLs inherited; warn to restrict folder to Administrators/SYSTEM.
    try:
        subprocess.run(["schtasks", "/End", "/TN", TASK], capture_output=True, timeout=12)
        start = subprocess.run(["schtasks", "/Run", "/TN", TASK],
                               capture_output=True, timeout=12)
        if start.returncode:
            messagebox.showinfo("Configuración guardada",
                                f"Guardado en {DEST}.\nInicia la tarea {TASK} desde Programador de tareas.")
        else:
            messagebox.showinfo("Listo", "Configuración guardada. Se solicitó el reinicio del conector.")
    except (OSError, subprocess.TimeoutExpired):
        messagebox.showinfo("Configuración guardada",
                            f"Guardado en {DEST}. Reinicia la tarea desde Windows.")
    root.destroy()


def make_password():
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    value = "".join(secrets.choice(alphabet) for _ in range(20))
    pwd_var.set(value)
    confirm_var.set(value)


root = tk.Tk()
root.title("Consulta de Precios - Configuración inicial")
root.geometry("650x480")
root.minsize(580, 440)
frame = ttk.Frame(root, padding=22)
frame.pack(fill="both", expand=True)
ttk.Label(frame, text="Configurar Conector Windows", font=("Segoe UI", 17, "bold")).pack(anchor="w")
ttk.Label(frame, text="Los datos se guardan únicamente en este equipo. No los compartas.").pack(anchor="w", pady=(2, 15))
previous = existing()
url_var = tk.StringVar(value=previous.get("SUPABASE_URL", ""))
key_var = tk.StringVar(value=previous.get("SUPABASE_SECRET_KEY", "") or previous.get("SUPABASE_SERVICE_ROLE_KEY", ""))
pwd_var = tk.StringVar(value=previous.get("BRIDGE_PASSWORD", ""))
confirm_var = tk.StringVar(value=previous.get("BRIDGE_PASSWORD", ""))
networks_var = tk.StringVar(value=previous.get("ALLOWED_NETWORKS", "192.168.1.0/24"))
for label, var, secret in [
    ("URL de Supabase (https://...supabase.co)", url_var, False),
    ("Clave secreta de Supabase (sb_secret_... o service_role)", key_var, True),
    ("Contraseña para entrar al buscador", pwd_var, True),
    ("Confirmar contraseña", confirm_var, True),
    ("Red local autorizada (ej.: 10.0.0.0/24)", networks_var, False),
]:
    ttk.Label(frame, text=label).pack(anchor="w", pady=(7, 1))
    ttk.Entry(frame, textvariable=var, show="*" if secret else "").pack(fill="x")
ttk.Button(frame, text="Generar contraseña segura", command=make_password).pack(anchor="w", pady=7)
ttk.Button(frame, text="Guardar y reiniciar conector", command=save).pack(fill="x", pady=12)
ttk.Label(frame, text="No guardes claves en GitHub. Requiere permisos de administrador.",
          foreground="#555555").pack(anchor="w")
root.mainloop()
