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

def get_client() -> Client:
    if "supabase_client" not in st.session_state:
        st.session_state.supabase_client = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"]
        )
    return st.session_state.supabase_client


def esta_autenticado() -> bool:
    return "perfil" in st.session_state and st.session_state.perfil is not None


def iniciar_sesion(correo: str, password: str) -> tuple[bool, str]:
    client = get_client()
    try:
        resultado = client.auth.sign_in_with_password({"email": correo, "password": password})
    except Exception as e:
        return False, "Correo o contraseña incorrectos."

    if not resultado.user:
        return False, "Correo o contraseña incorrectos."

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
