"""
Autenticación – Corte de Caja y Estadísticas Grupo Médico AG
Usa el Auth integrado de Supabase (correo + contraseña). El admin crea los
usuarios desde el dashboard de Supabase; esta app solo valida el login y lee
el perfil (sucursal, rol) asociado a cada usuario.

IMPORTANTE: el cliente de Supabase se guarda en st.session_state (no en
st.cache_resource), porque cache_resource es compartido por TODOS los
usuarios del proceso — guardar ahí una sesión autenticada filtraría el
login de una persona hacia otra.
"""

from __future__ import annotations

import streamlit as st
from supabase import create_client, Client

# Para sucursales: "PRADOS_BASE" se convierte internamente en
# "prados_base@gmag.local" antes de mandarlo a Supabase — ese dominio no
# existe de verdad, pero con Auto Confirm + contraseña Supabase nunca le
# intenta mandar nada, así que no hace falta que sea alcanzable.
# Para Admin: si ya escribes un correo real (con "@", ej. admin@grupomedicoag.com),
# se usa tal cual — no se le agrega el dominio interno.
DOMINIO_INTERNO = "gmag.local"


def _correo_desde_usuario(usuario: str) -> str:
    usuario = usuario.strip().lower()
    if "@" in usuario:
        return usuario
    return f"{usuario}@{DOMINIO_INTERNO}"


def get_client() -> Client:
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"]
        )
    return st.session_state.supabase_client


def esta_autenticado() -> bool:
    return "perfil" in st.session_state and st.session_state.perfil is not None


def iniciar_sesion(usuario: str, password: str) -> tuple[bool, str]:
    client = get_client()
    correo = _correo_desde_usuario(usuario)
    try:
        resultado = client.auth.sign_in_with_password({"email": correo, "password": password})
    except Exception:
        return False, "Usuario o contraseña incorrectos."

    if not resultado.user:
        return False, "Usuario o contraseña incorrectos."

    perfil_resp = client.table("perfiles").select("*").eq("id", resultado.user.id).execute()
    if not perfil_resp.data:
        client.auth.sign_out()
        return False, (
            "Tu cuenta existe pero no tiene un perfil asignado (sucursal/rol). "
            "Pídele al administrador que lo configure."
        )

    st.session_state.usuario = resultado.user
    st.session_state.perfil = perfil_resp.data[0]
    return True, ""


def cerrar_sesion() -> None:
    try:
        get_client().auth.sign_out()
    except Exception:
        pass
    for clave in ("supabase_client", "usuario", "perfil"):
        st.session_state.pop(clave, None)


def sucursal_actual() -> str:
    return st.session_state.perfil["sucursal"]


def es_admin() -> bool:
    return st.session_state.perfil.get("rol") == "admin"


def usuario_actual_id() -> str:
    """Correo (o usuario interno) de quien tiene la sesión — para dejar
    constancia de quién hizo una corrección."""
    try:
        return st.session_state.usuario.email
    except Exception:
        return "desconocido"