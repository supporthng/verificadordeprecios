import streamlit as st
from auth_usuarios import PERMISOS, api, cambiar_password, current_user, get_user, hash_password, require

admin = require("usuarios")
st.title("👥 Administrador de Usuarios")

with st.expander("Cambiar mi contraseña"):
    with st.form("mi_password"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
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

if admin["role"] != "admin":
    st.info("Solo el administrador puede crear y modificar usuarios.")
    st.stop()

st.subheader("Crear usuario")
with st.form("crear_usuario"):
    username = st.text_input("Nombre de usuario")
    password = st.text_input("Contraseña", type="password")
    role = st.selectbox("Rol", ["usuario", "admin"])
    perms = st.multiselect("Permisos", options=list(PERMISOS), format_func=lambda p: PERMISOS[p])
    submit = st.form_submit_button("Crear usuario")
if submit:
    username = username.strip().lower()
    if not username or not all(c.isalnum() or c in "._-" for c in username):
        st.error("Nombre de usuario inválido.")
    elif len(password) < 8:
        st.error("La contraseña debe tener al menos 8 caracteres.")
    else:
        try:
            if get_user(username):
                st.error("Ese usuario ya existe.")
            else:
                api("POST", data={"username": username, "password_hash": hash_password(password),
                                  "role": role, "permissions": perms, "active": True,
                                  "must_change_password": False})
                st.success("Usuario creado. Puede iniciar sesión con la contraseña asignada.")
        except RuntimeError as exc:
            st.error(str(exc))

st.subheader("Usuarios existentes")
try:
    users = api("GET", {"select": "id,username,role,permissions,active,must_change_password",
                        "order": "username.asc"})
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()
for u in users:
    with st.expander(u["username"] + (" (inactivo)" if not u["active"] else "")):
        with st.form("editar_" + str(u["id"])):
            role = st.selectbox("Rol", ["usuario", "admin"],
                index=0 if u["role"] == "usuario" else 1, key="rol_"+str(u["id"]))
            perms = st.multiselect("Permisos", list(PERMISOS),
                default=[p for p in u["permissions"] or [] if p in PERMISOS],
                format_func=lambda p: PERMISOS[p], key="perms_"+str(u["id"]))
            active = st.checkbox("Cuenta activa", value=u["active"], key="activo_"+str(u["id"]))
            reset = st.text_input("Nueva contraseña (opcional, mínimo 8 caracteres)",
                type="password", key="reset_"+str(u["id"]))
            save = st.form_submit_button("Guardar cambios")
        if save:
            if u["id"] == admin["id"] and (not active or role != "admin"):
                st.error("No puedes quitarte tu propio acceso de administrador.")
            elif reset and len(reset) < 8:
                st.error("La contraseña debe tener al menos 8 caracteres.")
            else:
                changes = {"role": role, "permissions": perms, "active": active}
                if reset:
                    changes.update(password_hash=hash_password(reset),
                                   must_change_password=False)
                try:
                    api("PATCH", {"id": "eq." + str(u["id"])}, changes)
                    st.success("Cambios guardados.")
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
