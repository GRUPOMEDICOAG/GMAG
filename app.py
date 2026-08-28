"""
Corte de Caja y Estadísticas – Grupo Médico AG (versión web)
Streamlit + Supabase. Ejecutar local:
    streamlit run app.py
Necesita .streamlit/secrets.toml con SUPABASE_URL y SUPABASE_ANON_KEY
(ver secrets.toml.example).
"""

import datetime

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
    st.caption("Inicia sesión con el correo y contraseña que te dio tu administrador.")
    with st.form("form_login"):
        correo = st.text_input("Correo")
        password = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Iniciar sesión", type="primary")
    if entrar:
        ok, error = auth.iniciar_sesion(correo, password)
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

HOY = datetime.date.today()
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

corte_existente_glob = db.obtener_corte(client, sucursal, fecha_str)
estadisticas_guardadas = db.existe_estadisticas_del_dia(client, sucursal, fecha_str)

progreso = (50 if corte_existente_glob else 0) + (50 if estadisticas_guardadas else 0)
st.progress(progreso / 100, text=f"Progreso del {fecha_str}: {progreso}% (Corte {'✅' if corte_existente_glob else '⬜'} · Estadísticas {'✅' if estadisticas_guardadas else '⬜'})")

if progreso == 100:
    if corte_existente_glob.get("enviado"):
        marca_tiempo = (corte_existente_glob.get("enviado_en") or "")[:19].replace("T", " ")
        st.success(f"✅ Día enviado{f' el {marca_tiempo} UTC' if marca_tiempo else ''}.")
    else:
        if st.button("📤 Enviar", type="primary"):
            db.marcar_enviado(client, sucursal, fecha_str)
            st.success("Enviado correctamente.")
            st.rerun()

etiquetas_tabs = ["Corte de Caja", "Estadísticas"]
if es_admin:
    etiquetas_tabs.append("Admin")
tabs = st.tabs(etiquetas_tabs)

# ──────────────────────────────────────────────────────────────────────────
# CORTE DE CAJA
# ──────────────────────────────────────────────────────────────────────────

with tabs[0]:
    st.subheader(f"Corte de Caja · {sucursal} · {fecha_str}")
    corte_existente = corte_existente_glob

    def _valor(campo, default=0.0):
        return float(corte_existente[campo]) if corte_existente else default

    st.markdown("**Ingresos**")
    c1, c2 = st.columns(2)
    ventas = c1.number_input("Ventas del día", min_value=0.0, step=0.01, format="%.2f", value=_valor("ventas"))
    consultas = c2.number_input("Consultas", min_value=0.0, step=0.01, format="%.2f", value=_valor("consultas"))
    dental = c1.number_input("Dental", min_value=0.0, step=0.01, format="%.2f", value=_valor("dental"))
    geovanes = c2.number_input("Geovanes", min_value=0.0, step=0.01, format="%.2f", value=_valor("geovanes"))
    cinerarias = c1.number_input("Cinerarias", min_value=0.0, step=0.01, format="%.2f", value=_valor("cinerarias"))

    st.markdown("**Descuentos**")
    c3, c4 = st.columns(2)
    desc_consulta = c3.number_input("Desc. Consulta", min_value=0.0, step=0.01, format="%.2f", value=_valor("desc_consulta"))
    desc_producto = c4.number_input("Desc. Producto", min_value=0.0, step=0.01, format="%.2f", value=_valor("desc_producto"))
    cort_consulta = c3.number_input("Cort. Consulta", min_value=0.0, step=0.01, format="%.2f", value=_valor("cort_consulta"))
    cort_producto = c4.number_input("Cort. Producto", min_value=0.0, step=0.01, format="%.2f", value=_valor("cort_producto"))

    st.markdown("**Gastos**")
    gastos_previos = corte_existente["gastos"] if corte_existente else []
    df_gastos_ini = (
        pd.DataFrame([{"Descripción": g["descripcion"], "Importe": g["importe"]} for g in gastos_previos])
        if gastos_previos else pd.DataFrame(columns=["Descripción", "Importe"])
    )
    df_gastos = st.data_editor(
        df_gastos_ini, num_rows="dynamic", use_container_width=True, key="editor_gastos",
        column_config={"Importe": st.column_config.NumberColumn(format="%.2f", min_value=0.0)},
    )

    st.markdown("**Pagos recibidos**")
    c5, c6 = st.columns(2)
    efectivo = c5.number_input("Efectivo", min_value=0.0, step=0.01, format="%.2f", value=_valor("efectivo"))
    tarjeta = c6.number_input("Tarjeta", min_value=0.0, step=0.01, format="%.2f", value=_valor("tarjeta"))

    total_gastos = float(df_gastos["Importe"].fillna(0).sum()) if not df_gastos.empty else 0.0
    total_ingresos = (ventas + consultas + dental + geovanes + cinerarias) - (
        desc_consulta + desc_producto + cort_consulta + cort_producto
    )
    total_general = total_ingresos - total_gastos
    diferencia_corte = round(total_ingresos - (efectivo + tarjeta), 2)

    if abs(diferencia_corte) < 0.01:
        st.success(
            f"Cuadre correcto · Ingresos: ${total_ingresos:,.2f} · "
            f"Efectivo disponible tras gastos: ${total_general:,.2f}"
        )
    else:
        st.error(
            f"No cuadra · Ingresos esperados ${total_ingresos:,.2f} vs recibido "
            f"${efectivo + tarjeta:,.2f} (dif. ${diferencia_corte:,.2f})"
        )

    if st.button("Guardar corte", type="primary"):
        campos = dict(
            ventas=ventas, consultas=consultas, dental=dental, geovanes=geovanes, cinerarias=cinerarias,
            desc_consulta=desc_consulta, desc_producto=desc_producto,
            cort_consulta=cort_consulta, cort_producto=cort_producto,
            efectivo=efectivo, tarjeta=tarjeta,
            total_ingresos=total_ingresos, total_gastos=total_gastos, total_general=total_general,
        )
        gastos_lista = [
            {"descripcion": row["Descripción"], "importe": float(row["Importe"] or 0)}
            for _, row in df_gastos.iterrows() if row.get("Descripción")
        ]
        db.guardar_corte(client, sucursal, fecha_str, campos, gastos_lista)
        st.success(f"Corte del {fecha_str} guardado correctamente.")
        st.rerun()

# ──────────────────────────────────────────────────────────────────────────
# ESTADÍSTICAS
# ──────────────────────────────────────────────────────────────────────────

with tabs[1]:
    st.subheader(f"Estadísticas · {sucursal} · {fecha_str}")
    corte_del_dia = corte_existente_glob

    turnos_guardados = db.medicos_con_datos(client, sucursal, fecha_str)
    etiqueta_por_codigo = db.MEDICO_TIPOS_LABEL
    codigo_por_etiqueta = {v: k for k, v in etiqueta_por_codigo.items()}
    etiquetas_seleccion = st.multiselect(
        "¿Qué turnos trabajaron hoy?",
        options=[etiqueta_por_codigo[m] for m in db.MEDICO_TIPOS],
        default=[etiqueta_por_codigo[m] for m in turnos_guardados],
        key="turnos_del_dia",
    )
    turnos_seleccionados = [codigo_por_etiqueta[e] for e in etiquetas_seleccion]
    if not turnos_seleccionados:
        st.info("Selecciona al menos un turno para capturar Primera Vez y Mostrador.")

    sub = st.tabs(["Primera Vez", "Mostrador", "Subsecuentes", "Revisiones", "Promociones"])

    def _tabla_canal_medico(categoria: str, prefijo: str, turnos: list) -> float:
        if not turnos:
            st.caption("Selecciona arriba qué turnos trabajaron hoy para capturar esta sección.")
            return 0.0
        datos = db.obtener_detalle(client, sucursal, fecha_str, categoria)
        st.caption("Captura por turno y canal de canalización · # de pacientes y $")
        encabezado = st.columns([1.2] + [1] * len(db.CANALES))
        encabezado[0].markdown("**Turno**")
        for i, canal in enumerate(db.CANALES, start=1):
            encabezado[i].markdown(f"**{db.CANALES_LABEL[canal]}**")

        nuevo = {}
        for medico in turnos:
            fila = st.columns([1.2] + [1] * len(db.CANALES))
            fila[0].markdown(db.MEDICO_TIPOS_LABEL[medico])
            for i, canal in enumerate(db.CANALES, start=1):
                actual = datos[(medico, canal)]
                with fila[i]:
                    px = st.number_input(
                        "#", min_value=0, step=1, value=int(actual["px"]),
                        key=f"{prefijo}_px_{medico}_{canal}", label_visibility="collapsed",
                    )
                    ingreso = st.number_input(
                        "$", min_value=0.0, step=0.01, format="%.2f", value=float(actual["ingreso"]),
                        key=f"{prefijo}_ingreso_{medico}_{canal}", label_visibility="collapsed",
                    )
                nuevo[(medico, canal)] = {"px": px, "ingreso": ingreso}

        total_px = sum(v["px"] for v in nuevo.values())
        total_ingreso = sum(v["ingreso"] for v in nuevo.values())
        st.markdown(f"**Total: {total_px} pacientes · ${total_ingreso:,.2f}**")
        if st.button(f"Guardar {prefijo}", key=f"guardar_{prefijo}"):
            db.guardar_detalle(client, sucursal, fecha_str, categoria, nuevo, turnos)
            db.marcar_no_enviado(client, sucursal, fecha_str)
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
        total_px = c1.number_input(f"Total {titulo}", min_value=0, step=1, value=int(datos["total_px"]), key=f"{prefijo}_total")
        esperados = c2.number_input(f"{titulo} Esperados", min_value=0, step=1, value=int(datos["esperados"]), key=f"{prefijo}_esp")
        ingreso = c3.number_input(f"Total $ {titulo}", min_value=0.0, step=0.01, format="%.2f", value=float(datos["ingreso"]), key=f"{prefijo}_ing")
        if st.button(f"Guardar {titulo}", key=f"guardar_{prefijo}"):
            db.guardar_agregado(client, sucursal, fecha_str, categoria, {
                "total_px": total_px, "esperados": esperados, "ingreso": ingreso,
            })
            db.marcar_no_enviado(client, sucursal, fecha_str)
            st.success("Guardado.")
            st.rerun()
        return ingreso

    with sub[2]:
        ingreso_sub = _agregado("SUB", "Subsecuentes", "sub")
    with sub[3]:
        ingreso_rev = _agregado("REV", "Revisiones", "rev")

    with sub[4]:
        catalogo = db.obtener_catalogo_promociones(client)
        nombres_catalogo = [p["nombre"] for p in catalogo]
        precios_catalogo = {p["nombre"]: p["precio"] for p in catalogo}
        if not nombres_catalogo:
            st.info("No hay promociones en el catálogo todavía — un Admin puede agregarlas en la pestaña Admin.")

        promos_previas = db.obtener_promociones(client, sucursal, fecha_str)
        df_promos_ini = (
            pd.DataFrame([{"Promoción": p["promocion"], "Frascos": p["frascos"], "Importe": p["importe"]} for p in promos_previas])
            if promos_previas else pd.DataFrame(columns=["Promoción", "Frascos", "Importe"])
        )
        columnas_promo = {
            "Frascos": st.column_config.NumberColumn(min_value=0, step=1),
            "Importe": st.column_config.NumberColumn(format="%.2f", min_value=0.0),
        }
        if nombres_catalogo:
            columnas_promo["Promoción"] = st.column_config.SelectboxColumn(options=nombres_catalogo)
        df_promos = st.data_editor(
            df_promos_ini, num_rows="dynamic", use_container_width=True, key="editor_promos",
            column_config=columnas_promo,
        )

        total_promo = float(df_promos["Importe"].fillna(0).sum()) if not df_promos.empty else 0.0
        st.markdown(f"**Total: {int(df_promos['Frascos'].fillna(0).sum()) if not df_promos.empty else 0} frascos · ${total_promo:,.2f}**")
        if st.button("Guardar Promociones"):
            filas = []
            for _, row in df_promos.iterrows():
                nombre = row.get("Promoción")
                if not nombre:
                    continue
                frascos = int(row.get("Frascos") or 0)
                importe = float(row.get("Importe") or 0)
                precio_unit = precios_catalogo.get(nombre, (importe / frascos) if frascos else 0.0)
                filas.append({"promocion": nombre, "frascos": frascos, "precio_unitario": precio_unit, "importe": importe})
            db.guardar_promociones(client, sucursal, fecha_str, filas)
            db.marcar_no_enviado(client, sucursal, fecha_str)
            st.success("Guardado.")
            st.rerun()
        ingreso_promo = total_promo

    st.divider()
    gran_total = ingreso_1a + ingreso_most + ingreso_sub + ingreso_rev + ingreso_promo
    if corte_del_dia:
        atribuible = corte_del_dia["total_ingresos"] - corte_del_dia["dental"]
        diferencia_est = round(gran_total - atribuible, 2)
        if abs(diferencia_est) < 0.01:
            st.success(
                f"Cuadra con el Corte de Caja · Total Estadísticas: ${gran_total:,.2f} "
                f"(Ingresos − Dental del Corte: ${atribuible:,.2f})"
            )
        else:
            st.error(
                f"No cuadra con el Corte · Total Estadísticas: ${gran_total:,.2f} vs "
                f"Ingresos − Dental: ${atribuible:,.2f} (dif. ${diferencia_est:,.2f})"
            )
    else:
        st.warning(f"Aún no hay Corte de Caja guardado para el {fecha_str} · Total Estadísticas: ${gran_total:,.2f}")

# ──────────────────────────────────────────────────────────────────────────
# ADMIN
# ──────────────────────────────────────────────────────────────────────────

if es_admin:
    with tabs[2]:
        st.subheader("Panel Admin")

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
        st.markdown("**Catálogo de Promociones**")
        catalogo = db.obtener_catalogo_promociones(client)
        for p in catalogo:
            cc1, cc2, cc3 = st.columns([3, 1, 1])
            cc1.write(p["nombre"])
            cc2.write(f"${p['precio']:,.2f}")
            if cc3.button("Eliminar", key=f"eliminar_promo_{p['id']}"):
                db.eliminar_promocion_catalogo(client, p["id"])
                st.rerun()

        with st.form("form_nueva_promo"):
            nc1, nc2 = st.columns([3, 1])
            nombre_nuevo = nc1.text_input("Nombre de la promoción")
            precio_nuevo = nc2.number_input("Precio", min_value=0.0, step=0.01, format="%.2f")
            if st.form_submit_button("Agregar al catálogo"):
                if nombre_nuevo.strip():
                    db.agregar_promocion_catalogo(client, nombre_nuevo.strip(), precio_nuevo)
                    st.rerun()
                else:
                    st.error("Escribe un nombre.")
