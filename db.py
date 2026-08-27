"""
Capa de datos – Corte de Caja y Estadísticas Grupo Médico AG
Todas las funciones reciben el cliente de Supabase de la sesión actual
(ver auth.get_client()); la seguridad por sucursal la aplica Postgres con
Row Level Security, no este código.
"""

from __future__ import annotations

MEDICO_TIPOS = ["BASE", "CUBRE", "IMPREVISTOS"]
MEDICO_TIPOS_LABEL = {"BASE": "De Base", "CUBRE": "Cubre Descansos", "IMPREVISTOS": "Imprevistos"}

CANALES = ["RADIO", "TV", "VOLANTES", "REDES", "RECOMENDADOS"]
CANALES_LABEL = {
    "RADIO": "Radio", "TV": "TV", "VOLANTES": "Volantes",
    "REDES": "Redes", "RECOMENDADOS": "Recomendados",
}

CAMPOS_CORTE = [
    "ventas", "consultas", "dental", "geovanes", "cinerarias",
    "desc_consulta", "desc_producto", "cort_consulta", "cort_producto",
    "efectivo", "tarjeta", "total_ingresos", "total_gastos", "total_general",
]


# ── Corte de caja ───────────────────────────────────────────────────────

def obtener_corte(client, sucursal: str, fecha: str) -> dict | None:
    res = client.table("cortes").select("*, gastos(*)").eq("sucursal", sucursal).eq("fecha", fecha).execute()
    return res.data[0] if res.data else None


def guardar_corte(client, sucursal: str, fecha: str, campos: dict, gastos: list) -> int:
    payload = {**campos, "sucursal": sucursal, "fecha": fecha}
    res = client.table("cortes").upsert(payload, on_conflict="fecha,sucursal").execute()
    corte_id = res.data[0]["id"]
    client.table("gastos").delete().eq("corte_id", corte_id).execute()
    filas = [{"corte_id": corte_id, "descripcion": g["descripcion"], "importe": g["importe"]} for g in gastos if g.get("descripcion") or g.get("importe")]
    if filas:
        client.table("gastos").insert(filas).execute()
    return corte_id


def listar_cortes_rango(client, fecha_ini: str, fecha_fin: str) -> list:
    """Para el panel Admin: RLS deja ver todas las sucursales si el usuario es admin."""
    res = (
        client.table("cortes").select("*")
        .gte("fecha", fecha_ini).lte("fecha", fecha_fin)
        .order("sucursal").order("fecha")
        .execute()
    )
    return res.data


# ── Estadísticas: detalle (Primera Vez / Mostrador) por médico × canal ──

def obtener_detalle(client, sucursal: str, fecha: str, categoria: str) -> dict:
    """Devuelve {(medico_tipo, canal): {"px":..,"ingreso":..}}, con ceros donde falte."""
    res = (
        client.table("estadisticas_detalle").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).eq("categoria", categoria)
        .execute()
    )
    encontrados = {(r["medico_tipo"], r["canal"]): {"px": r["px"], "ingreso": r["ingreso"]} for r in res.data}
    completo = {}
    for medico in MEDICO_TIPOS:
        for canal in CANALES:
            completo[(medico, canal)] = encontrados.get((medico, canal), {"px": 0, "ingreso": 0.0})
    return completo


def guardar_detalle(client, sucursal: str, fecha: str, categoria: str, filas: dict) -> None:
    """filas: {(medico_tipo, canal): {"px":.., "ingreso":..}}"""
    payload = [
        {"sucursal": sucursal, "fecha": fecha, "categoria": categoria,
         "medico_tipo": medico, "canal": canal, "px": datos["px"], "ingreso": datos["ingreso"]}
        for (medico, canal), datos in filas.items()
    ]
    client.table("estadisticas_detalle").upsert(
        payload, on_conflict="fecha,sucursal,categoria,medico_tipo,canal"
    ).execute()


# ── Estadísticas: agregado (Subsecuentes / Revisiones) ──────────────────

def obtener_agregado(client, sucursal: str, fecha: str, categoria: str) -> dict:
    res = (
        client.table("estadisticas_agregado").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).eq("categoria", categoria)
        .execute()
    )
    if res.data:
        r = res.data[0]
        return {"total_px": r["total_px"], "esperados": r["esperados"], "ingreso": r["ingreso"]}
    return {"total_px": 0, "esperados": 0, "ingreso": 0.0}


def guardar_agregado(client, sucursal: str, fecha: str, categoria: str, datos: dict) -> None:
    payload = {
        "sucursal": sucursal, "fecha": fecha, "categoria": categoria,
        "total_px": datos["total_px"], "esperados": datos["esperados"], "ingreso": datos["ingreso"],
    }
    client.table("estadisticas_agregado").upsert(payload, on_conflict="fecha,sucursal,categoria").execute()


# ── Estadísticas: promociones vendidas ──────────────────────────────────

def obtener_promociones(client, sucursal: str, fecha: str) -> list:
    res = (
        client.table("estadisticas_promociones").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).order("id")
        .execute()
    )
    return res.data


def guardar_promociones(client, sucursal: str, fecha: str, filas: list) -> None:
    client.table("estadisticas_promociones").delete().eq("sucursal", sucursal).eq("fecha", fecha).execute()
    payload = [
        {"sucursal": sucursal, "fecha": fecha, "promocion": f["promocion"],
         "frascos": f["frascos"], "precio_unitario": f["precio_unitario"], "importe": f["importe"]}
        for f in filas if f.get("promocion")
    ]
    if payload:
        client.table("estadisticas_promociones").insert(payload).execute()


# ── Catálogo de promociones (compartido entre sucursales) ───────────────

def obtener_catalogo_promociones(client) -> list:
    res = client.table("promociones_catalogo").select("*").order("nombre").execute()
    return res.data


def agregar_promocion_catalogo(client, nombre: str, precio: float) -> None:
    client.table("promociones_catalogo").upsert({"nombre": nombre, "precio": precio}, on_conflict="nombre").execute()


def eliminar_promocion_catalogo(client, promo_id: int) -> None:
    client.table("promociones_catalogo").delete().eq("id", promo_id).execute()


# ── Totales / cuadre ─────────────────────────────────────────────────────

def calcular_totales_corte(campos: dict) -> dict:
    total_ingreso_bruto = campos["ventas"] + campos["consultas"] + campos["dental"] + campos["geovanes"] + campos["cinerarias"]
    total_descuentos = campos["desc_consulta"] + campos["desc_producto"] + campos["cort_consulta"] + campos["cort_producto"]
    total_ingresos = total_ingreso_bruto - total_descuentos
    return {"total_ingresos": total_ingresos}
