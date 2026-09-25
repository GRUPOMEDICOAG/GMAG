"""
Capa de datos – Corte de Caja y Estadísticas Grupo Médico AG
Todas las funciones reciben el cliente de Supabase de la sesión actual
(ver auth.get_client()); la seguridad por sucursal la aplica Postgres con
Row Level Security, no este código.
"""

from __future__ import annotations

import time
import datetime

import httpx

MEDICO_TIPOS = ["BASE", "CUBRE", "IMPREVISTOS"]
MEDICO_TIPOS_LABEL = {"BASE": "De Base", "CUBRE": "Cubre Descansos", "IMPREVISTOS": "Imprevistos"}

CANALES = ["RADIO", "TV", "VOLANTES", "REDES", "RECOMENDADOS"]
CANALES_LABEL = {
    "RADIO": "Radio", "TV": "TV", "VOLANTES": "Volantes",
    "REDES": "Redes", "RECOMENDADOS": "Recomendados",
    "ORIENTACIONES": "Orientaciones",
}
# "Orientaciones" es un canal exclusivo de Mostrador — Primera Vez sigue
# usando solo los 5 canales de siempre.
CANALES_MOSTRADOR = CANALES + ["ORIENTACIONES"]


def canales_de_categoria(categoria: str) -> list:
    return CANALES_MOSTRADOR if categoria == "MOSTRADOR" else CANALES

CAMPOS_CORTE = [
    "ventas", "consultas", "dental", "geovanes", "cinerarias",
    "desc_consulta", "desc_producto", "cort_consulta", "cort_producto",
    "efectivo", "tarjeta", "total_ingresos", "total_gastos", "total_general",
]

# Errores de red transitorios: pasan sobre todo cuando la sesión de Streamlit
# estuvo abierta un rato sin usarse y la conexión HTTP quedó cerrada del lado
# del servidor sin que el cliente se entere. Un reintento (con una conexión
# nueva) casi siempre lo resuelve solo, sin que la persona vea el error.
ERRORES_RED_REINTENTABLES = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError)
REINTENTOS = 2
ESPERA_ENTRE_REINTENTOS = 0.6


def _exec(query):
    """Ejecuta un query builder de Supabase (…algo…execute) con reintento
    automático ante caídas de conexión transitorias."""
    ultimo_error = None
    for intento in range(REINTENTOS + 1):
        try:
            return query.execute()
        except ERRORES_RED_REINTENTABLES as e:
            ultimo_error = e
            if intento < REINTENTOS:
                time.sleep(ESPERA_ENTRE_REINTENTOS)
    raise ultimo_error


# ── Corte de caja ───────────────────────────────────────────────────────

def obtener_corte(client, sucursal: str, fecha: str) -> dict | None:
    res = _exec(client.table("cortes").select("*, gastos(*)").eq("sucursal", sucursal).eq("fecha", fecha))
    return res.data[0] if res.data else None


def guardar_corte(
    client, sucursal: str, fecha: str, campos: dict, gastos: list,
    es_correccion: bool = False, usuario: str | None = None,
) -> int:
    payload = {**campos, "sucursal": sucursal, "fecha": fecha, "enviado": False}
    if es_correccion:
        ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        existente = obtener_corte(client, sucursal, fecha)
        payload["corregido"] = True
        payload["corregido_por"] = usuario
        payload["corregido_en"] = ahora
        if existente:
            payload["valores_originales"] = {k: existente.get(k) for k in CAMPOS_CORTE}
    res = _exec(client.table("cortes").upsert(payload, on_conflict="fecha,sucursal"))
    corte_id = res.data[0]["id"]
    _exec(client.table("gastos").delete().eq("corte_id", corte_id))
    filas = [
        {"corte_id": corte_id, "categoria": g.get("categoria"), "tipo_gasto": g.get("tipo_gasto"),
         "descripcion": g["descripcion"], "importe": g["importe"]}
        for g in gastos if g.get("categoria") or g.get("descripcion") or g.get("importe")
    ]
    if filas:
        _exec(client.table("gastos").insert(filas))
    return corte_id


def listar_cortes_rango(client, fecha_ini: str, fecha_fin: str) -> list:
    """Para el panel Admin: RLS deja ver todas las sucursales si el usuario es admin."""
    res = _exec(
        client.table("cortes").select("*")
        .gte("fecha", fecha_ini).lte("fecha", fecha_fin)
        .order("sucursal").order("fecha")
    )
    return res.data


def listar_sucursales(client) -> list:
    """Todas las sucursales con un usuario de captura activo (rol='sucursal')."""
    res = _exec(client.table("perfiles").select("sucursal").eq("rol", "sucursal"))
    return sorted(set(r["sucursal"] for r in res.data))


def sucursales_enviadas_en_fecha(client, fecha: str) -> set:
    """Sucursales que ya dieron clic en 'Enviar' para esa fecha."""
    res = _exec(client.table("cortes").select("sucursal").eq("fecha", fecha).eq("enviado", True))
    return set(r["sucursal"] for r in res.data)


def marcar_enviado(client, sucursal: str, fecha: str) -> None:
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _exec(client.table("cortes").update({"enviado": True, "enviado_en": ahora}).eq("sucursal", sucursal).eq("fecha", fecha))


def marcar_no_enviado(client, sucursal: str, fecha: str, es_correccion: bool = False, usuario: str | None = None) -> None:
    """Si ya se había mandado el día y alguien edita Estadísticas después, deja de contar como enviado.
    Si es_correccion=True (Admin corrigiendo un día ya enviado), además deja constancia de quién y cuándo."""
    payload = {"enviado": False}
    if es_correccion:
        ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload.update({"corregido": True, "corregido_por": usuario, "corregido_en": ahora})
    _exec(client.table("cortes").update(payload).eq("sucursal", sucursal).eq("fecha", fecha))


# ── Estadísticas: detalle (Primera Vez / Mostrador) por médico × canal ──

def obtener_detalle(client, sucursal: str, fecha: str, categoria: str) -> dict:
    """Devuelve {(medico_tipo, canal): {"px":..,"ingreso":..}}, con ceros donde falte."""
    res = _exec(
        client.table("estadisticas_detalle").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).eq("categoria", categoria)
    )
    encontrados = {(r["medico_tipo"], r["canal"]): {"px": r["px"], "ingreso": r["ingreso"]} for r in res.data}
    completo = {}
    for medico in MEDICO_TIPOS:
        for canal in canales_de_categoria(categoria):
            completo[(medico, canal)] = encontrados.get((medico, canal), {"px": 0, "ingreso": 0.0})
    return completo


def guardar_detalle(client, sucursal: str, fecha: str, categoria: str, filas: dict, medicos_seleccionados: list) -> None:
    """filas: {(medico_tipo, canal): {"px":.., "ingreso":..}} — solo de los turnos seleccionados.
    Borra cualquier fila vieja de turnos que ya no estén seleccionados, para no dejar basura."""
    if medicos_seleccionados:
        _exec(
            client.table("estadisticas_detalle").delete().eq("sucursal", sucursal).eq("fecha", fecha).eq(
                "categoria", categoria
            ).not_.in_("medico_tipo", medicos_seleccionados)
        )
    else:
        _exec(
            client.table("estadisticas_detalle").delete().eq("sucursal", sucursal).eq("fecha", fecha).eq(
                "categoria", categoria
            )
        )

    payload = [
        {"sucursal": sucursal, "fecha": fecha, "categoria": categoria,
         "medico_tipo": medico, "canal": canal, "px": datos["px"], "ingreso": datos["ingreso"]}
        for (medico, canal), datos in filas.items()
        if medico in medicos_seleccionados
    ]
    if payload:
        _exec(
            client.table("estadisticas_detalle").upsert(
                payload, on_conflict="fecha,sucursal,categoria,medico_tipo,canal"
            )
        )


def medicos_con_datos(client, sucursal: str, fecha: str) -> list:
    """Turnos que ya tienen algo guardado ese día (para preseleccionar el multiselect)."""
    res = _exec(
        client.table("estadisticas_detalle").select("medico_tipo")
        .eq("sucursal", sucursal).eq("fecha", fecha)
    )
    return sorted(set(r["medico_tipo"] for r in res.data))


def existe_estadisticas_del_dia(client, sucursal: str, fecha: str) -> bool:
    """True si hay al menos un dato guardado en cualquiera de las 3 tablas de Estadísticas ese día."""
    for tabla in ("estadisticas_detalle", "estadisticas_agregado", "estadisticas_promociones"):
        res = _exec(client.table(tabla).select("id").eq("sucursal", sucursal).eq("fecha", fecha).limit(1))
        if res.data:
            return True
    return False


CATEGORIAS_PROGRESO = ["1A", "MOSTRADOR", "SUB", "REV", "PROMOCIONES"]
CATEGORIAS_PROGRESO_LABEL = {
    "1A": "Primera Vez", "MOSTRADOR": "Mostrador", "SUB": "Subsecuentes",
    "REV": "Revisiones", "PROMOCIONES": "Promociones",
}


def marcar_categoria_guardada(client, sucursal: str, fecha: str, categoria: str) -> None:
    """Deja constancia de que ese rubro se guardó ese día — aunque el resultado
    sea 'cero' (ej. no se vendió ninguna promoción), sigue contando como guardado."""
    ahora = datetime.datetime.now(datetime.timezone.utc).isoformat()
    _exec(
        client.table("estadisticas_progreso").upsert(
            {"fecha": fecha, "sucursal": sucursal, "categoria": categoria, "guardado_en": ahora},
            on_conflict="fecha,sucursal,categoria",
        )
    )


def categorias_guardadas_del_dia(client, sucursal: str, fecha: str) -> set:
    res = _exec(
        client.table("estadisticas_progreso").select("categoria")
        .eq("sucursal", sucursal).eq("fecha", fecha)
    )
    return set(r["categoria"] for r in res.data)


def calcular_total_estadisticas_dia(client, sucursal: str, fecha: str) -> float:
    """Suma real de las 5 categorías para esa fecha, tal como están guardadas
    en la base — usado para decidir si el día puede enviarse."""
    detalle_1a = obtener_detalle(client, sucursal, fecha, "1A")
    detalle_most = obtener_detalle(client, sucursal, fecha, "MOSTRADOR")
    agregado_sub = obtener_agregado(client, sucursal, fecha, "SUB")
    agregado_rev = obtener_agregado(client, sucursal, fecha, "REV")
    promos = obtener_promociones(client, sucursal, fecha)
    return (
        sum(v["ingreso"] for v in detalle_1a.values())
        + sum(v["ingreso"] for v in detalle_most.values())
        + agregado_sub["ingreso"] + agregado_rev["ingreso"]
        + sum(p["importe"] for p in promos)
    )


# ── Estadísticas: agregado (Subsecuentes / Revisiones) ──────────────────

def obtener_agregado(client, sucursal: str, fecha: str, categoria: str) -> dict:
    res = _exec(
        client.table("estadisticas_agregado").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).eq("categoria", categoria)
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
    _exec(client.table("estadisticas_agregado").upsert(payload, on_conflict="fecha,sucursal,categoria"))


# ── Estadísticas: promociones vendidas ──────────────────────────────────

def obtener_promociones(client, sucursal: str, fecha: str) -> list:
    res = _exec(
        client.table("estadisticas_promociones").select("*")
        .eq("sucursal", sucursal).eq("fecha", fecha).order("id")
    )
    return res.data


def guardar_promociones(client, sucursal: str, fecha: str, filas: list) -> None:
    _exec(client.table("estadisticas_promociones").delete().eq("sucursal", sucursal).eq("fecha", fecha))
    payload = [
        {"sucursal": sucursal, "fecha": fecha, "promocion": f["promocion"],
         "frascos": f["frascos"], "precio_unitario": f["precio_unitario"], "importe": f["importe"],
         "campana": f.get("campana", "Regular"), "redes": f.get("redes", False)}
        for f in filas if f.get("promocion")
    ]
    if payload:
        _exec(client.table("estadisticas_promociones").insert(payload))


# ── Historial de precios de promociones (con vigencia por fecha) ────────

def obtener_nombres_promociones(client) -> list:
    """Todos los nombres de promoción que alguna vez han tenido un precio,
    para el desplegable — sin importar si su precio actual aplica hoy."""
    res = _exec(client.table("promociones_precios").select("nombre"))
    return sorted(set(r["nombre"] for r in res.data))


def obtener_precios_vigentes_en_fecha(client, fecha: str) -> dict:
    """Para cada promoción, el precio que estaba vigente en esa fecha
    (el de 'vigente_desde' más reciente que no sea posterior a 'fecha').
    Si una promoción no tenía ningún precio definido todavía en esa fecha,
    no aparece en el resultado (no truena, solo no se autocalcula su $)."""
    res = _exec(
        client.table("promociones_precios").select("*")
        .lte("vigente_desde", fecha)
        .order("vigente_desde", desc=True)
    )
    vigentes = {}
    for fila in res.data:
        if fila["nombre"] not in vigentes:  # el primero que aparece por nombre es el más reciente <= fecha
            vigentes[fila["nombre"]] = fila["precio"]
    return vigentes


def agregar_precio_promocion(client, nombre: str, precio: float, vigente_desde: str) -> None:
    _exec(client.table("promociones_precios").insert({
        "nombre": nombre, "precio": precio, "vigente_desde": vigente_desde,
    }))


def listar_historial_precios(client) -> list:
    res = _exec(client.table("promociones_precios").select("*").order("nombre").order("vigente_desde", desc=True))
    return res.data


def eliminar_precio_promocion(client, precio_id: int) -> None:
    _exec(client.table("promociones_precios").delete().eq("id", precio_id))


# ── Combos especiales (ej. "Combo Navideño": 3 piezas a $139 c/u) ───────
# Solo aplican a las promociones que Admin decida agregar aquí; el resto
# de las promociones siempre usan el precio "Regular" de siempre.

def obtener_combos_activos(client) -> dict:
    """Devuelve {nombre_promocion: {campana: {"precio_unitario":.., "multiplo_requerido":..}}}"""
    res = _exec(client.table("promociones_combos").select("*").eq("activo", True))
    combos = {}
    for fila in res.data:
        combos.setdefault(fila["nombre"], {})[fila["campana"]] = {
            "precio_unitario": fila["precio_unitario"],
            "multiplo_requerido": fila["multiplo_requerido"],
        }
    return combos


def listar_combos(client) -> list:
    res = _exec(client.table("promociones_combos").select("*").order("nombre").order("campana"))
    return res.data


def agregar_combo(client, nombre: str, campana: str, precio_unitario: float, multiplo_requerido: int) -> None:
    _exec(client.table("promociones_combos").upsert(
        {"nombre": nombre, "campana": campana, "precio_unitario": precio_unitario,
         "multiplo_requerido": multiplo_requerido, "activo": True},
        on_conflict="nombre,campana",
    ))


def eliminar_combo(client, combo_id: int) -> None:
    _exec(client.table("promociones_combos").delete().eq("id", combo_id))


# ── Catálogo de categorías de gasto (Tesorería) ──────────────────────────

def obtener_catalogo_gastos(client) -> list:
    res = _exec(client.table("gastos_catalogo").select("*").order("tipo_gasto").order("categoria"))
    return res.data


def agregar_categoria_gasto(client, categoria: str, tipo_gasto: str, ejemplo_descripcion: str | None = None) -> None:
    _exec(client.table("gastos_catalogo").upsert(
        {"categoria": categoria, "tipo_gasto": tipo_gasto, "ejemplo_descripcion": ejemplo_descripcion},
        on_conflict="categoria",
    ))


def eliminar_categoria_gasto(client, categoria_id: int) -> None:
    _exec(client.table("gastos_catalogo").delete().eq("id", categoria_id))


# ── Totales / cuadre ─────────────────────────────────────────────────────

def calcular_totales_corte(campos: dict) -> dict:
    """Ingreso Neto: Dental, Geovanes y Cinerarias son informativos, no suman aquí."""
    total_descuentos = campos["desc_consulta"] + campos["desc_producto"] + campos["cort_consulta"] + campos["cort_producto"]
    total_ingresos = campos["ventas"] + campos["consultas"] - total_descuentos
    return {"total_ingresos": total_ingresos}