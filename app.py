"""
Corte de Caja y Estadísticas – Grupo Médico AG (versión web)
Streamlit + Supabase. Ejecutar local:
    streamlit run app.py
Necesita .streamlit/secrets.toml con SUPABASE_URL y SUPABASE_ANON_KEY
(ver secrets.toml.example).
"""

import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import auth
import db

st.set_page_config(page_title="Corte de Caja – GMAG", page_icon="🧾", layout="wide")

st.markdown(
    """
    <div style="background-color:#1F3864; padding:14px 20px; border-radius:8px; margin-bottom:8px;">
        <span style="color:#FFFFFF; font-size:22px; font-weight:700;">🧾 Corte de Caja y Estadísticas</span>
        <span style="color:#8FD9AE; font-size:16px; font-weight:600;"> · Grupo Médico AG</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────────────
# LOGIN
# ──────────────────────────────────────────────────────────────────────────

if not auth.esta_autenticado():
    _, col_login, _ = st.columns([1, 1.1, 1])
    with col_login:
        st.write("")
        with st.container(border=True):
            st.markdown("##### Iniciar sesión")
            st.caption("Usa el usuario y contraseña que te dio tu administrador.")
            with st.form("form_login"):
                usuario = st.text_input("Usuario")
                password = st.text_input("Contraseña", type="password")
                entrar = st.form_submit_button("Iniciar sesión", type="primary", use_container_width=True)
            if entrar:
                ok, error = auth.iniciar_sesion(usuario, password)
                if ok:
                    st.rerun()
                else:
                    st.error(error)
    st.stop()

client = auth.get_client()
sucursal = auth.sucursal_actual()
es_admin = auth.es_admin()

# ──────────────────────────────────────────────────────────────────────────
# BARRA LATERAL — fecha fija en hoy, con candado por PIN para cambiarla
# ──────────────────────────────────────────────────────────────────────────

ZONA_MEXICO = ZoneInfo("America/Mexico_City")
HOY = datetime.datetime.now(ZONA_MEXICO).date()
st.session_state.setdefault("fecha_desbloqueada", False)

with st.sidebar:
    st.markdown(f"**Sucursal:** {sucursal}")
    st.markdown(f"**Rol:** {'Admin' if es_admin else 'Sucursal'}")
    st.divider()

    if not st.session_state.fecha_desbloqueada:
        st.markdown(f"**Fecha:** {HOY.isoformat()} 🔒")
        with st.expander("Capturar un día distinto"):
            st.caption("Requiere el PIN de autorización de Admin.")
            pin_ingresado = st.text_input("PIN", type="password", key="pin_fecha")
            if st.button("Desbloquear fecha"):
                if pin_ingresado and pin_ingresado == st.secrets.get("ADMIN_PIN", ""):
                    st.session_state.fecha_desbloqueada = True
                    st.rerun()
                else:
                    st.error("PIN incorrecto.")
        fecha = HOY
    else:
        fecha = st.date_input("Fecha (desbloqueada)", value=HOY)
        if st.button("🔒 Regresar a hoy y bloquear"):
            st.session_state.fecha_desbloqueada = False
            st.rerun()

    st.divider()
    if st.button("Cerrar sesión"):
        auth.cerrar_sesion()
        st.rerun()

fecha_str = fecha.isoformat()

# ──────────────────────────────────────────────────────────────────────────
# DATOS DEL DÍA — se calculan una sola vez, antes de dividir en columnas,
# para que tanto el panel principal como el lateral usen los mismos valores.
# ──────────────────────────────────────────────────────────────────────────

corte_existente_glob = db.obtener_corte(client, sucursal, fecha_str)
categorias_guardadas = db.categorias_guardadas_del_dia(client, sucursal, fecha_str)
faltan_categorias = set(db.CATEGORIAS_PROGRESO) - categorias_guardadas
turnos_guardados_dia = db.medicos_con_datos(client, sucursal, fecha_str)

detalle_1a_dia = db.obtener_detalle(client, sucursal, fecha_str, "1A")
detalle_most_dia = db.obtener_detalle(client, sucursal, fecha_str, "MOSTRADOR")
agregado_sub_dia = db.obtener_agregado(client, sucursal, fecha_str, "SUB")
agregado_rev_dia = db.obtener_agregado(client, sucursal, fecha_str, "REV")
promos_dia = db.obtener_promociones(client, sucursal, fecha_str)

ingreso_1a_dia = sum(v["ingreso"] for v in detalle_1a_dia.values())
ingreso_most_dia = sum(v["ingreso"] for v in detalle_most_dia.values())
ingreso_sub_dia = agregado_sub_dia["ingreso"]
ingreso_rev_dia = agregado_rev_dia["ingreso"]
ingreso_promo_dia = sum(p["importe"] for p in promos_dia)
gran_total_final = ingreso_1a_dia + ingreso_most_dia + ingreso_sub_dia + ingreso_rev_dia + ingreso_promo_dia

cuadra_final = False
cuadra_interno_corte = False
atribuible_final = None
diferencia_estadisticas = None
if corte_existente_glob:
    atribuible_final = corte_existente_glob["total_ingresos"]
    diferencia_estadisticas = atribuible_final - gran_total_final
    cuadra_final = abs(diferencia_estadisticas) < 0.01

    diferencia_interna = corte_existente_glob["total_ingresos"] - (
        corte_existente_glob["efectivo"] + corte_existente_glob["tarjeta"]
    )
    cuadra_interno_corte = abs(diferencia_interna) < 0.01

pasos = [("Corte de caja capturado", bool(corte_existente_glob))]
for cat in db.CATEGORIAS_PROGRESO:
    pasos.append((db.CATEGORIAS_PROGRESO_LABEL[cat], cat in categorias_guardadas))
pasos.append(("Efectivo + Tarjeta = Ingresos", cuadra_interno_corte))
pasos.append(("Cuadra con Estadísticas", cuadra_final))

completados = sum(1 for _, ok in pasos if ok)
total_pasos = len(pasos)
puede_enviar = completados == total_pasos

# Candado de "enviado": si el día ya se mandó, una sucursal normal ya no
# puede editar nada — solo Admin, y cuando lo hace queda registrado.
dia_ya_enviado = bool(corte_existente_glob and corte_existente_glob.get("enviado"))
edicion_bloqueada = dia_ya_enviado and not es_admin
es_correccion_admin = dia_ya_enviado and es_admin
MENSAJE_BLOQUEO = "🔒 Este día ya fue enviado. Contacta a un Admin para corregirlo."

# ──────────────────────────────────────────────────────────────────────────
# LAYOUT: panel principal (más compacto) + panel lateral de estado/resumen
# ──────────────────────────────────────────────────────────────────────────

col_main, col_aside = st.columns([2, 1], gap="large")

with col_main:
    etiquetas_tabs = ["Corte de Caja", "Estadísticas"]
    if es_admin:
        etiquetas_tabs.append("Admin")
    tabs = st.tabs(etiquetas_tabs)

    # ── CORTE DE CAJA ────────────────────────────────────────────────────
    with tabs[0]:
        st.subheader(f"Corte de Caja · {sucursal} · {fecha_str}")
        corte_existente = corte_existente_glob

        def _valor(campo, default=0.0):
            return float(corte_existente[campo]) if corte_existente else default

        st.markdown("**Ingresos**")
        c1, c2 = st.columns(2)
        ventas = c1.number_input("Ventas del día", min_value=0.0, step=0.01, format="%.2f", value=_valor("ventas"))
        consultas = c2.number_input("Consultas", min_value=0.0, step=0.01, format="%.2f", value=_valor("consultas"))

        st.caption("Informativo — no suman al Ingreso Neto (Dental se maneja aparte; Geovanes/Cinerarias ya están dentro de Ventas del día).")
        c1b, c2b = st.columns(2)
        dental = c1b.number_input("Dental", min_value=0.0, step=0.01, format="%.2f", value=_valor("dental"))
        geovanes = c2b.number_input("Geovanes", min_value=0.0, step=0.01, format="%.2f", value=_valor("geovanes"))
        cinerarias = c1b.number_input("Cinerarias", min_value=0.0, step=0.01, format="%.2f", value=_valor("cinerarias"))

        st.markdown("**Descuentos**")
        c3, c4 = st.columns(2)
        desc_consulta = c3.number_input("Desc. Consulta", min_value=0.0, step=0.01, format="%.2f", value=_valor("desc_consulta"))
        desc_producto = c4.number_input("Desc. Producto", min_value=0.0, step=0.01, format="%.2f", value=_valor("desc_producto"))
        cort_consulta = c3.number_input("Cort. Consulta", min_value=0.0, step=0.01, format="%.2f", value=_valor("cort_consulta"))
        cort_producto = c4.number_input("Cort. Producto", min_value=0.0, step=0.01, format="%.2f", value=_valor("cort_producto"))

        st.markdown("**Gastos**")
        catalogo_gastos = db.obtener_catalogo_gastos(client)
        categorias_gasto = [c["categoria"] for c in catalogo_gastos]
        tipo_por_categoria = {c["categoria"]: c["tipo_gasto"] for c in catalogo_gastos}
        if not categorias_gasto:
            st.info("No hay categorías de gasto configuradas todavía — un Admin puede agregarlas en la pestaña Admin.")
        st.caption("\"Detalle\" es el dato específico: a quién se le entregó, qué periodo, o qué se compró.")

        gastos_previos = corte_existente["gastos"] if corte_existente else []
        df_gastos_ini = (
            pd.DataFrame([
                {"Categoría": g.get("categoria"), "Detalle": g["descripcion"], "Importe": g["importe"]}
                for g in gastos_previos
            ]) if gastos_previos else pd.DataFrame(columns=["Categoría", "Detalle", "Importe"])
        )
        columnas_gasto = {"Importe": st.column_config.NumberColumn(format="%.2f", min_value=0.0)}
        if categorias_gasto:
            columnas_gasto["Categoría"] = st.column_config.SelectboxColumn(options=categorias_gasto)
        df_gastos = st.data_editor(
            df_gastos_ini, num_rows="dynamic", use_container_width=True, key=f"editor_gastos_{fecha_str}",
            column_config=columnas_gasto, column_order=["Categoría", "Detalle", "Importe"],
        )

        st.markdown("**Pagos recibidos**")
        c5, c6 = st.columns(2)
        efectivo = c5.number_input("Efectivo", min_value=0.0, step=0.01, format="%.2f", value=_valor("efectivo"))
        tarjeta = c6.number_input("Tarjeta", min_value=0.0, step=0.01, format="%.2f", value=_valor("tarjeta"))

        total_gastos = float(df_gastos["Importe"].fillna(0).sum()) if not df_gastos.empty else 0.0
        total_ingresos = (ventas + consultas) - (
            desc_consulta + desc_producto + cort_consulta + cort_producto
        )
        total_general = total_ingresos - total_gastos
        diferencia_corte = round(total_ingresos - (efectivo + tarjeta), 2)

        if abs(diferencia_corte) < 0.01:
            st.success(
                f"Cuadre correcto · Ingreso Neto: ${total_ingresos:,.2f} · "
                f"Efectivo disponible: ${total_general:,.2f}"
            )
        else:
            st.error(
                f"No cuadra · Ingreso Neto esperado ${total_ingresos:,.2f} vs recibido "
                f"${efectivo + tarjeta:,.2f} (dif. ${diferencia_corte:,.2f})"
            )

        if edicion_bloqueada:
            st.warning(MENSAJE_BLOQUEO)
        else:
            if st.button("Guardar corte", type="primary"):
                campos = dict(
                    ventas=ventas, consultas=consultas, dental=dental, geovanes=geovanes, cinerarias=cinerarias,
                    desc_consulta=desc_consulta, desc_producto=desc_producto,
                    cort_consulta=cort_consulta, cort_producto=cort_producto,
                    efectivo=efectivo, tarjeta=tarjeta,
                    total_ingresos=total_ingresos, total_gastos=total_gastos, total_general=total_general,
                )
                gastos_lista = []
                for _, row in df_gastos.iterrows():
                    categoria = row.get("Categoría")
                    if not categoria or pd.isna(categoria):
                        continue
                    detalle = row.get("Detalle")
                    detalle = "" if pd.isna(detalle) else detalle
                    importe_valor = row.get("Importe")
                    importe = 0.0 if pd.isna(importe_valor) else float(importe_valor)
                    gastos_lista.append({
                        "categoria": categoria, "descripcion": detalle, "importe": importe,
                        "tipo_gasto": tipo_por_categoria.get(categoria),
                    })
                db.guardar_corte(
                    client, sucursal, fecha_str, campos, gastos_lista,
                    es_correccion=es_correccion_admin, usuario=auth.usuario_actual_id(),
                )
                if es_correccion_admin:
                    st.success(f"Corrección del {fecha_str} guardada y registrada.")
                else:
                    st.success(f"Corte del {fecha_str} guardado correctamente.")
                st.rerun()

    # ── ESTADÍSTICAS ─────────────────────────────────────────────────────
    with tabs[1]:
        st.subheader(f"Estadísticas · {sucursal} · {fecha_str}")
        corte_del_dia = corte_existente_glob

        etiqueta_por_codigo = db.MEDICO_TIPOS_LABEL
        codigo_por_etiqueta = {v: k for k, v in etiqueta_por_codigo.items()}
        etiquetas_seleccion = st.multiselect(
            "¿Qué turnos trabajaron hoy?",
            options=[etiqueta_por_codigo[m] for m in db.MEDICO_TIPOS],
            default=[etiqueta_por_codigo[m] for m in turnos_guardados_dia],
            key=f"turnos_del_dia_{fecha_str}",
        )
        turnos_seleccionados = [codigo_por_etiqueta[e] for e in etiquetas_seleccion]
        if not turnos_seleccionados:
            st.info("Selecciona al menos un turno para capturar Primera Vez y Mostrador.")

        sub = st.tabs(["Primera Vez", "Mostrador", "Subsecuentes", "Revisiones", "Promociones"])

        def _tabla_canal_medico(categoria: str, prefijo: str, turnos: list) -> float:
            if not turnos:
                st.caption("Selecciona arriba qué turnos trabajaron hoy para capturar esta sección.")
                return 0.0
            canales = db.canales_de_categoria(categoria)
            datos = db.obtener_detalle(client, sucursal, fecha_str, categoria)
            st.caption("Captura por turno y canal de canalización · # de pacientes y $")
            encabezado = st.columns([1.2] + [1] * len(canales))
            encabezado[0].markdown("**Turno**")
            for i, canal in enumerate(canales, start=1):
                encabezado[i].markdown(f"**{db.CANALES_LABEL[canal]}**")

            nuevo = {}
            for medico in turnos:
                fila = st.columns([1.2] + [1] * len(canales))
                fila[0].markdown(db.MEDICO_TIPOS_LABEL[medico])
                for i, canal in enumerate(canales, start=1):
                    actual = datos[(medico, canal)]
                    with fila[i]:
                        px = st.number_input(
                            "#", min_value=0, step=1, value=int(actual["px"]),
                            key=f"{prefijo}_{fecha_str}_px_{medico}_{canal}", label_visibility="collapsed",
                        )
                        ingreso = st.number_input(
                            "$", min_value=0.0, step=0.01, format="%.2f", value=float(actual["ingreso"]),
                            key=f"{prefijo}_{fecha_str}_ingreso_{medico}_{canal}", label_visibility="collapsed",
                        )
                    nuevo[(medico, canal)] = {"px": px, "ingreso": ingreso}

            total_px = sum(v["px"] for v in nuevo.values())
            total_ingreso = sum(v["ingreso"] for v in nuevo.values())
            st.markdown(f"**Total: {total_px} pacientes · ${total_ingreso:,.2f}**")
            if edicion_bloqueada:
                st.warning(MENSAJE_BLOQUEO)
            elif st.button(f"Guardar {prefijo}", key=f"guardar_{prefijo}"):
                db.guardar_detalle(client, sucursal, fecha_str, categoria, nuevo, turnos)
                db.marcar_categoria_guardada(client, sucursal, fecha_str, categoria)
                db.marcar_no_enviado(client, sucursal, fecha_str, es_correccion=es_correccion_admin, usuario=auth.usuario_actual_id())
                st.success("Guardado.")
                st.rerun()
            return total_ingreso

        with sub[0]:
            ingreso_1a = _tabla_canal_medico("1A", "1a", turnos_seleccionados)
        with sub[1]:
            ingreso_most = _tabla_canal_medico("MOSTRADOR", "mostrador", turnos_seleccionados)

        def _agregado(categoria: str, titulo: str, prefijo: str) -> float:
            datos = db.obtener_agregado(client, sucursal, fecha_str, categoria)
            c1, c2, c3 = st.columns(3)
            total_px = c1.number_input(f"Total {titulo}", min_value=0, step=1, value=int(datos["total_px"]), key=f"{prefijo}_{fecha_str}_total")
            esperados = c2.number_input(f"{titulo} Esperados", min_value=0, step=1, value=int(datos["esperados"]), key=f"{prefijo}_{fecha_str}_esp")
            ingreso = c3.number_input(f"Total $ {titulo}", min_value=0.0, step=0.01, format="%.2f", value=float(datos["ingreso"]), key=f"{prefijo}_{fecha_str}_ing")
            if edicion_bloqueada:
                st.warning(MENSAJE_BLOQUEO)
            elif st.button(f"Guardar {titulo}", key=f"guardar_{prefijo}"):
                db.guardar_agregado(client, sucursal, fecha_str, categoria, {
                    "total_px": total_px, "esperados": esperados, "ingreso": ingreso,
                })
                db.marcar_categoria_guardada(client, sucursal, fecha_str, categoria)
                db.marcar_no_enviado(client, sucursal, fecha_str, es_correccion=es_correccion_admin, usuario=auth.usuario_actual_id())
                st.success("Guardado.")
                st.rerun()
            return ingreso

        with sub[2]:
            ingreso_sub = _agregado("SUB", "Subsecuentes", "sub")
        with sub[3]:
            ingreso_rev = _agregado("REV", "Revisiones", "rev")

        with sub[4]:
            nombres_catalogo = db.obtener_nombres_promociones(client)
            precios_catalogo = db.obtener_precios_vigentes_en_fecha(client, fecha_str)
            combos_activos = db.obtener_combos_activos(client)
            opciones_campana = ["Regular"] + sorted({c for camps in combos_activos.values() for c in camps})

            if not nombres_catalogo:
                st.info("No hay promociones en el catálogo todavía — un Admin puede agregarlas en la pestaña Admin.")
            else:
                sin_precio_esa_fecha = [n for n in nombres_catalogo if n not in precios_catalogo]
                if sin_precio_esa_fecha:
                    st.caption(
                        f"⚠️ Sin precio vigente para el {fecha_str}: {', '.join(sin_precio_esa_fecha)} "
                        "(su importe saldrá en $0 hasta que Admin agregue un precio para esa fecha)."
                    )

            st.caption(
                "Elige la promoción y el # de frascos — el importe se calcula solo con el precio vigente. "
                "\"Campaña\" solo aplica si esa promoción tiene un combo especial definido por Admin. "
                "\"Redes\" da $10 de descuento por frasco si se vendió por redes sociales."
            )
            promos_previas = db.obtener_promociones(client, sucursal, fecha_str)
            df_promos_ini = (
                pd.DataFrame([
                    {"Promoción": p["promocion"], "Campaña": p.get("campana", "Regular"),
                     "Frascos": p["frascos"], "Redes": p.get("redes", False)}
                    for p in promos_previas
                ]) if promos_previas else pd.DataFrame(columns=["Promoción", "Campaña", "Frascos", "Redes"])
            )
            columnas_promo = {
                "Frascos": st.column_config.NumberColumn(min_value=0, step=1),
                "Campaña": st.column_config.SelectboxColumn(options=opciones_campana, default="Regular"),
                "Redes": st.column_config.CheckboxColumn(default=False),
            }
            if nombres_catalogo:
                columnas_promo["Promoción"] = st.column_config.SelectboxColumn(options=nombres_catalogo)
            df_promos = st.data_editor(
                df_promos_ini, num_rows="dynamic", use_container_width=True, key=f"editor_promos_{fecha_str}",
                column_config=columnas_promo,
                column_order=["Promoción", "Campaña", "Frascos", "Redes"],
            )

            # El importe se calcula aquí, fuera del editor — no es algo que se capture a mano.
            # Se usa pd.isna() en vez de "or 0": una celda vacía en una fila nueva llega como
            # NaN, y "NaN or 0" sigue siendo NaN (NaN es "truthy" en Python) — eso era lo que
            # tronaba al convertir a int.
            filas_calculadas = []
            advertencias_promo = []
            errores_promo = []
            for _, row in df_promos.iterrows():
                nombre = row.get("Promoción")
                if not nombre or pd.isna(nombre):
                    continue
                frascos_valor = row.get("Frascos")
                frascos = 0 if pd.isna(frascos_valor) else int(frascos_valor)
                if frascos == 0:
                    errores_promo.append(f"\"{nombre}\" tiene 0 frascos — captura una cantidad o elimina esa fila para poder guardar.")
                    continue
                campana = row.get("Campaña")
                campana = "Regular" if not campana or pd.isna(campana) else campana
                redes = bool(row.get("Redes")) and not pd.isna(row.get("Redes"))

                if campana != "Regular":
                    combo = combos_activos.get(nombre, {}).get(campana)
                    if combo is None:
                        advertencias_promo.append(f"\"{campana}\" no aplica para {nombre} — se usó precio Regular.")
                        campana, precio_unit = "Regular", precios_catalogo.get(nombre, 0.0)
                    else:
                        multiplo = combo["multiplo_requerido"]
                        if multiplo > 1 and frascos % multiplo != 0:
                            advertencias_promo.append(
                                f"{nombre} ({campana}): debe ser múltiplo de {multiplo} — capturaste {frascos}."
                            )
                        precio_unit = combo["precio_unitario"]
                else:
                    precio_unit = precios_catalogo.get(nombre, 0.0)

                if redes:
                    precio_unit = max(0.0, precio_unit - 10)

                importe = precio_unit * frascos
                filas_calculadas.append({
                    "promocion": nombre, "frascos": frascos, "precio_unitario": precio_unit,
                    "importe": importe, "campana": campana, "redes": redes,
                })

            for err in errores_promo:
                st.error(f"🚫 {err}")
            for adv in advertencias_promo:
                st.warning(f"⚠️ {adv}")

            total_promo = sum(f["importe"] for f in filas_calculadas)
            total_frascos_promo = sum(f["frascos"] for f in filas_calculadas)
            st.markdown(f"**Total: {total_frascos_promo} frascos · ${total_promo:,.2f}**")
            if edicion_bloqueada:
                st.warning(MENSAJE_BLOQUEO)
            elif errores_promo:
                st.caption("Corrige lo de arriba para poder guardar.")
            elif st.button("Guardar Promociones"):
                db.guardar_promociones(client, sucursal, fecha_str, filas_calculadas)
                db.marcar_categoria_guardada(client, sucursal, fecha_str, "PROMOCIONES")
                db.marcar_no_enviado(client, sucursal, fecha_str, es_correccion=es_correccion_admin, usuario=auth.usuario_actual_id())
                st.success("Guardado.")
                st.rerun()
            ingreso_promo = total_promo

        st.divider()
        gran_total = ingreso_1a + ingreso_most + ingreso_sub + ingreso_rev + ingreso_promo
        if corte_del_dia:
            atribuible = corte_del_dia["total_ingresos"]
            diferencia_est = round(gran_total - atribuible, 2)
            if abs(diferencia_est) < 0.01:
                st.success(
                    f"Cuadra con el Corte de Caja · Total Estadísticas: ${gran_total:,.2f} "
                    f"(Ingreso Neto del Corte: ${atribuible:,.2f})"
                )
            else:
                st.error(
                    f"No cuadra con el Corte · Total Estadísticas: ${gran_total:,.2f} vs "
                    f"Ingreso Neto: ${atribuible:,.2f} (dif. ${diferencia_est:,.2f})"
                )
        else:
            st.warning(f"Aún no hay Corte de Caja guardado para el {fecha_str} · Total Estadísticas: ${gran_total:,.2f}")

    # ── ADMIN ────────────────────────────────────────────────────────────
    if es_admin:
        with tabs[2]:
            st.subheader("Panel Admin")

            st.markdown("**Sucursales pendientes de enviar**")
            fecha_revisar = st.date_input("Fecha a revisar", value=HOY, key="admin_fecha_revisar")
            todas_sucursales = db.listar_sucursales(client)
            enviaron = db.sucursales_enviadas_en_fecha(client, fecha_revisar.isoformat())
            faltantes = sorted(set(todas_sucursales) - enviaron)
            if not todas_sucursales:
                st.caption("Todavía no hay sucursales con usuario de captura configurado.")
            elif faltantes:
                st.warning(
                    f"**{len(faltantes)} de {len(todas_sucursales)}** sucursales no han enviado el "
                    f"{fecha_revisar.isoformat()}: {', '.join(faltantes)}"
                )
            else:
                st.success(f"Las {len(todas_sucursales)} sucursales ya enviaron el {fecha_revisar.isoformat()}.")

            st.divider()
            st.markdown("**Consolidado de Cortes por sucursal**")
            c1, c2 = st.columns(2)
            desde = c1.date_input("Desde", value=fecha, key="admin_desde")
            hasta = c2.date_input("Hasta", value=fecha, key="admin_hasta")
            if st.button("Consultar"):
                filas = db.listar_cortes_rango(client, desde.isoformat(), hasta.isoformat())
                if filas:
                    df = pd.DataFrame(filas)
                    columnas = ["sucursal", "fecha", "ventas", "consultas", "dental",
                                "total_ingresos", "total_gastos", "total_general", "enviado"]
                    st.dataframe(df[columnas], use_container_width=True)
                    st.download_button(
                        "Descargar CSV", df[columnas].to_csv(index=False).encode("utf-8"),
                        file_name=f"cortes_{desde}_{hasta}.csv",
                    )
                else:
                    st.info("No hay cortes guardados en ese rango.")

            st.divider()
            st.markdown("**Historial de precios de Promociones**")
            st.caption(
                "Cada promoción puede tener varios precios a lo largo del tiempo. Al capturar una "
                "venta, la app usa el precio que estaba vigente en la fecha capturada — no el actual. "
                "Para subir un precio, agrega una fila nueva con la fecha desde la que aplica; no edites "
                "las anteriores, así el histórico de ventas pasadas se queda correcto."
            )
            historial = db.listar_historial_precios(client)
            if historial:
                for p in historial:
                    hc1, hc2, hc3, hc4 = st.columns([3, 1.2, 1.2, 1])
                    hc1.write(p["nombre"])
                    hc2.write(f"${p['precio']:,.2f}")
                    hc3.write(f"desde {p['vigente_desde']}")
                    if hc4.button("Eliminar", key=f"eliminar_precio_{p['id']}"):
                        db.eliminar_precio_promocion(client, p["id"])
                        st.rerun()
            else:
                st.caption("Todavía no hay ninguna promoción con precio definido.")

            with st.form("form_nuevo_precio"):
                nc1, nc2, nc3 = st.columns([3, 1.2, 1.2])
                nombre_nuevo = nc1.text_input("Promoción (nueva o existente)")
                precio_nuevo = nc2.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
                vigente_desde_nuevo = nc3.date_input("Vigente desde", value=HOY)
                if st.form_submit_button("Agregar precio"):
                    if nombre_nuevo.strip():
                        db.agregar_precio_promocion(
                            client, nombre_nuevo.strip(), precio_nuevo, vigente_desde_nuevo.isoformat()
                        )
                        st.rerun()
                    else:
                        st.error("Escribe un nombre.")

            st.divider()
            st.markdown("**Combos especiales**")
            st.caption(
                "Ej. \"Combo Navideño\": 3 piezas a $139 c/u. Solo aplica a la promoción exacta que "
                "elijas aquí — el resto sigue usando únicamente el precio Regular de arriba."
            )
            combos = db.listar_combos(client)
            if combos:
                for c in combos:
                    cc1, cc2, cc3, cc4, cc5 = st.columns([2.5, 1.5, 1, 1, 1])
                    cc1.write(c["nombre"])
                    cc2.write(c["campana"])
                    cc3.write(f"${c['precio_unitario']:,.2f}")
                    cc4.write(f"×{c['multiplo_requerido']}")
                    if cc5.button("Eliminar", key=f"eliminar_combo_{c['id']}"):
                        db.eliminar_combo(client, c["id"])
                        st.rerun()
            else:
                st.caption("Todavía no hay combos especiales configurados.")

            with st.form("form_nuevo_combo"):
                fc1, fc2, fc3, fc4 = st.columns([2.5, 1.5, 1, 1])
                nombre_promo_combo = fc1.selectbox("Promoción", options=db.obtener_nombres_promociones(client))
                campana_nueva = fc2.text_input("Campaña", placeholder="Combo Navideño")
                precio_combo = fc3.number_input("Precio c/u", min_value=0.0, step=0.01, format="%.2f")
                multiplo_combo = fc4.number_input("Múltiplo", min_value=1, step=1, value=1)
                if st.form_submit_button("Agregar combo"):
                    if campana_nueva.strip():
                        db.agregar_combo(client, nombre_promo_combo, campana_nueva.strip(), precio_combo, int(multiplo_combo))
                        st.rerun()
                    else:
                        st.error("Escribe el nombre de la campaña.")

            st.divider()
            st.markdown("**Catálogo de Gastos (Tesorería)**")
            st.caption("El Tipo de Gasto (Fijo/Variable) se autocompleta según la categoría al capturar — no lo elige la sucursal.")
            catalogo_gastos_admin = db.obtener_catalogo_gastos(client)
            if catalogo_gastos_admin:
                for g in catalogo_gastos_admin:
                    gc1, gc2, gc3 = st.columns([2.5, 1.5, 1])
                    gc1.write(g["categoria"])
                    gc2.write(g["tipo_gasto"])
                    if gc3.button("Eliminar", key=f"eliminar_categoria_gasto_{g['id']}"):
                        db.eliminar_categoria_gasto(client, g["id"])
                        st.rerun()
            else:
                st.caption("Todavía no hay categorías de gasto configuradas.")

            with st.form("form_nueva_categoria_gasto"):
                gn1, gn2, gn3 = st.columns([2.5, 1.5, 3])
                categoria_nueva = gn1.text_input("Categoría")
                tipo_nuevo = gn2.selectbox("Tipo de Gasto", options=["Gasto Fijo", "Gasto Variable"])
                ejemplo_nuevo = gn3.text_input("Ejemplo de Detalle (opcional)")
                if st.form_submit_button("Agregar categoría"):
                    if categoria_nueva.strip():
                        db.agregar_categoria_gasto(client, categoria_nueva.strip(), tipo_nuevo, ejemplo_nuevo.strip() or None)
                        st.rerun()
                    else:
                        st.error("Escribe el nombre de la categoría.")

with col_aside:
    # ── Estado del día ───────────────────────────────────────────────────
    filas_html = []
    for etiqueta, ok in pasos:
        if ok:
            circulo = (
                "<div style='width:18px;height:18px;border-radius:50%;background:#2E9E5B;"
                "display:flex;align-items:center;justify-content:center;flex-shrink:0;'>"
                "<span style='color:white;font-size:11px;line-height:1;'>✓</span></div>"
            )
            estilo_texto = ""
        else:
            circulo = (
                "<div style='width:18px;height:18px;border-radius:50%;"
                "border:1.5px solid #C2C7D0;flex-shrink:0;'></div>"
            )
            estilo_texto = "color:#8A8F98;"
        filas_html.append(
            f"<div style='display:flex;align-items:center;gap:8px;padding:3px 0;'>{circulo}"
            f"<span style='font-size:13px;{estilo_texto}'>{etiqueta}</span></div>"
        )

    pct = int(100 * completados / total_pasos)
    st.markdown(
        f"""
        <div style='background:#FFFFFF;border:1px solid #E3E7ED;border-radius:12px;padding:16px 18px;'>
            <div style='display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;'>
                <span style='font-weight:600;font-size:15px;color:#26344A;'>Estado del día</span>
                <span style='font-size:13px;color:#8A8F98;'>{completados}/{total_pasos}</span>
            </div>
            <div style='height:4px;background:#E3E7ED;border-radius:2px;margin-bottom:12px;overflow:hidden;'>
                <div style='height:100%;width:{pct}%;background:#2E9E5B;border-radius:2px;'></div>
            </div>
            {''.join(filas_html)}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    if puede_enviar and not corte_existente_glob.get("enviado"):
        if st.button("📤 Enviar corte del día", type="primary", use_container_width=True):
            db.marcar_enviado(client, sucursal, fecha_str)
            st.success("Enviado correctamente.")
            st.rerun()
    elif corte_existente_glob and corte_existente_glob.get("enviado"):
        marca_tiempo = (corte_existente_glob.get("enviado_en") or "")[:19].replace("T", " ")
        st.success(f"✅ Enviado{f' el {marca_tiempo} UTC' if marca_tiempo else ''}.")
    else:
        st.caption(f"Faltan {total_pasos - completados} punto(s) para habilitar \"Enviar\".")

    st.write("")

    # ── Resumen del día ──────────────────────────────────────────────────
    def _tarjeta_chica(etiqueta, monto, guardado):
        valor = f"${monto:,.2f}" if guardado else "Pendiente"
        color_valor = "#26344A" if guardado else "#ADB2BC"
        return (
            "<div style='background:#F4F6F8;border-radius:8px;padding:10px 12px;'>"
            f"<div style='font-size:11px;color:#8A8F98;margin-bottom:2px;'>{etiqueta}</div>"
            f"<div style='font-size:15px;font-weight:600;color:{color_valor};'>{valor}</div>"
            "</div>"
        )

    tarjetas_chicas = [
        _tarjeta_chica("Primera vez", ingreso_1a_dia, "1A" in categorias_guardadas),
        _tarjeta_chica("Mostrador", ingreso_most_dia, "MOSTRADOR" in categorias_guardadas),
        _tarjeta_chica("Subsecuentes", ingreso_sub_dia, "SUB" in categorias_guardadas),
        _tarjeta_chica("Revisiones", ingreso_rev_dia, "REV" in categorias_guardadas),
        _tarjeta_chica("Promociones", ingreso_promo_dia, "PROMOCIONES" in categorias_guardadas),
    ]
    valor_ingresos = f"${corte_existente_glob['total_ingresos']:,.2f}" if corte_existente_glob else "Pendiente"
    valor_ingresos_estadisticas = f"${gran_total_final:,.2f}"

    st.markdown(
        f"""
        <div style='background:#FFFFFF;border:1px solid #E3E7ED;border-radius:12px;padding:16px 18px;'>
            <div style='font-weight:600;font-size:15px;color:#26344A;margin-bottom:12px;'>Resumen del día</div>
            <div style='background:#1F3864;border-radius:10px;padding:14px 16px;margin-bottom:10px;'>
                <div style='color:#AFC3E0;font-size:12px;margin-bottom:2px;'>Ingresos del corte</div>
                <div style='color:#FFFFFF;font-size:26px;font-weight:700;'>{valor_ingresos}</div>
            </div>
            <div style='background:#2E9E5B;border-radius:10px;padding:14px 16px;margin-bottom:12px;'>
                <div style='color:#D9F2E4;font-size:12px;margin-bottom:2px;'>Ingresos Estadísticas</div>
                <div style='color:#FFFFFF;font-size:26px;font-weight:700;'>{valor_ingresos_estadisticas}</div>
            </div>
            <div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;'>
                {''.join(tarjetas_chicas)}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.write("")
    if atribuible_final is None:
        st.info("Guarda el Corte de Caja para calcular cuánto falta para cuadrar.")
    elif abs(diferencia_estadisticas) < 0.01:
        st.success(f"✅ En cuadre — estadísticas ${gran_total_final:,.2f} coinciden con el corte.")
    else:
        verbo = "Falta capturar" if diferencia_estadisticas > 0 else "Hay de más capturado"
        st.warning(f"{verbo} para cuadrar: **${abs(diferencia_estadisticas):,.2f}**")