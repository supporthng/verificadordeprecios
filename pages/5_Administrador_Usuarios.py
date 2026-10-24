import streamlit as st
from auth_usuarios import LARGO_MINIMO_PASSWORD, PERMISOS, api, cambiar_password, current_user, get_user, hash_password, require

admin = require("usuarios")
st.title("👥 Administrador de Usuarios")

with st.expander("Cambiar mi contraseña"):
    with st.form("mi_password"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input(f"Nueva contraseña (mínimo {LARGO_MINIMO_PASSWORD} caracteres)", type="password")
        confirmar = st.text_input("Confirmar nueva contraseña", type="password")
        ok = st.form_submit_button("Guardar mi contraseña")
    if ok:
        from auth_usuarios import verificar
        if not verificar(actual, admin["password_hash"]):
            st.error("Contraseña actual incorrecta.")
        elif nueva != confirmar:
            st.error("Las contraseñas no coinciden.")
        else:
            try:
                cambiar_password(admin, nueva)
                st.success("Contraseña actualizada.")
            except (ValueError, RuntimeError) as exc:
                st.error(str(exc))

if admin["role"] != "admin" and not admin.get("sucursal_id"):
    st.info("Solo el administrador puede crear y modificar usuarios.")
    st.stop()

# Sucursales (MIGRACION_006): el usuario general asigna cualquier sucursal; el encargado de una
# sucursal solo ve y crea usuarios de la suya (y nunca administradores generales).
import sucursales
try:
    lista_sucursales = sucursales.listar()
except RuntimeError:
    lista_sucursales = []
mi_sucursal = admin.get("sucursal_id")
NOMBRES_SUC = {s["id"]: s["nombre"] for s in lista_sucursales}
OPCIONES_SUC = [None] + [s["id"] for s in lista_sucursales]


def _nombre_suc(sid):
    return "🏢 General (todas las sucursales)" if not sid else "🏬 " + NOMBRES_SUC.get(sid, "Sucursal borrada")


def _elegir_sucursal(clave, actual=None):
    if not lista_sucursales:
        return None
    if mi_sucursal:
        st.caption("Sucursal: " + _nombre_suc(mi_sucursal))
        return mi_sucursal
    return st.selectbox("Sucursal", OPCIONES_SUC, index=OPCIONES_SUC.index(actual) if actual in OPCIONES_SUC else 0,
                        format_func=_nombre_suc, key=clave,
                        help="General: ve y administra todas. Con sucursal: solo ve la suya (sus equipos, "
                             "sus precios y sus informes).")


ROLES = ["usuario"] if mi_sucursal else ["usuario", "admin"]

st.subheader("Crear usuario")
with st.form("crear_usuario"):
    username = st.text_input("Nombre de usuario")
    password = st.text_input("Contraseña", type="password")
    role = st.selectbox("Rol", ROLES)
    perms = st.multiselect("Permisos", options=list(PERMISOS), format_func=lambda p: PERMISOS[p])
    sucursal_nueva = _elegir_sucursal("suc_nuevo")
    submit = st.form_submit_button("Crear usuario")
if submit:
    username = username.strip().lower()
    if not username or not all(c.isalnum() or c in "._-" for c in username):
        st.error("Nombre de usuario inválido.")
    elif len(password) < LARGO_MINIMO_PASSWORD:
        st.error(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")
    else:
        try:
            if get_user(username):
                st.error("Ese usuario ya existe.")
            else:
                nuevo = {"username": username, "password_hash": hash_password(password),
                         "role": role, "permissions": perms, "active": True, "must_change_password": False}
                if sucursal_nueva:
                    nuevo["sucursal_id"] = sucursal_nueva
                api("POST", data=nuevo)
                st.success("Usuario creado. Puede iniciar sesión con la contraseña asignada.")
        except RuntimeError as exc:
            st.error(str(exc))

st.subheader("Usuarios existentes")
try:
    columnas = "id,username,role,permissions,active,must_change_password"
    try:
        users = api("GET", {"select": columnas + ",sucursal_id", "order": "username.asc"})
    except RuntimeError:
        users = api("GET", {"select": columnas, "order": "username.asc"})   # sin MIGRACION_006
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()
if mi_sucursal:
    users = [u for u in users if u.get("sucursal_id") == mi_sucursal]
for u in users:
    etiqueta = u["username"] + (" (inactivo)" if not u["active"] else "")
    if lista_sucursales and not mi_sucursal:
        etiqueta += " · " + _nombre_suc(u.get("sucursal_id")).split(" ", 1)[1]
    with st.expander(etiqueta):
        with st.form("editar_" + str(u["id"])):
            role = st.selectbox("Rol", ROLES if u["role"] in ROLES else ["usuario", "admin"],
                index=0 if u["role"] == "usuario" else 1, key="rol_"+str(u["id"]))
            perms = st.multiselect("Permisos", list(PERMISOS),
                default=[p for p in u["permissions"] or [] if p in PERMISOS],
                format_func=lambda p: PERMISOS[p], key="perms_"+str(u["id"]))
            active = st.checkbox("Cuenta activa", value=u["active"], key="activo_"+str(u["id"]))
            sucursal_u = _elegir_sucursal("suc_" + str(u["id"]), u.get("sucursal_id"))
            reset = st.text_input(f"Nueva contraseña (opcional, mínimo {LARGO_MINIMO_PASSWORD} caracteres)",
                type="password", key="reset_"+str(u["id"]))
            save = st.form_submit_button("Guardar cambios")
        if save:
            if u["id"] == admin["id"] and (not active or (role != "admin" and admin["role"] == "admin")):
                st.error("No puedes quitarte tu propio acceso de administrador.")
            elif reset and len(reset) < LARGO_MINIMO_PASSWORD:
                st.error(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")
            else:
                changes = {"role": role, "permissions": perms, "active": active}
                if lista_sucursales:
                    changes["sucursal_id"] = sucursal_u
                if reset:
                    changes.update(password_hash=hash_password(reset),
                                   must_change_password=False)
                try:
                    api("PATCH", {"id": "eq." + str(u["id"])}, changes)
                    st.success("Cambios guardados.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
