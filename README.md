# Corte de Caja y Estadísticas – Grupo Médico AG (versión web)

App en Streamlit + Supabase. Reemplaza la versión de escritorio: ya no hay
archivos `.db` por sucursal ni Dropbox — todo vive en una sola base Postgres
compartida (proyecto Supabase **gmag-corte-caja**), con seguridad a nivel de
fila (RLS) para que cada sucursal solo vea sus propios datos.

## Ya está listo en Supabase

- Proyecto: `gmag-corte-caja` (organización GMAG), plan gratis.
- Tablas creadas: `perfiles`, `cortes`, `gastos`, `estadisticas_detalle`,
  `estadisticas_agregado`, `estadisticas_promociones`, `promociones_catalogo`.
- RLS activado en las 7: cada sucursal solo ve/edita sus propias filas; el
  rol `admin` ve todas.

## Paso 1 · Crear los usuarios (tú, desde el dashboard de Supabase)

1. Entra a [supabase.com](https://supabase.com) → proyecto `gmag-corte-caja`.
2. **Authentication → Users → Add user** — captura correo + contraseña para
   cada sucursal (y para ti como Admin). Ejemplo: `apizaco@gmag.mx`.
3. Avísame el correo (y si es Admin o de qué sucursal) de cada usuario que
   crees — yo enlazo el perfil (sucursal/rol) por SQL. También puedes
   hacerlo tú directo en **Table Editor → perfiles → Insert row**:
   - `id`: copia el UUID del usuario desde Authentication → Users
   - `sucursal`: el nombre exacto de la sucursal (ej. `Apizaco`)
   - `rol`: `sucursal` o `admin`

Sin esta fila en `perfiles`, el login funciona pero la app avisa que falta
el perfil — es intencional, para no dejar a nadie sin sucursal asignada.

## Paso 2 · Correr local

```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edita `.streamlit/secrets.toml` y pega tu `SUPABASE_ANON_KEY` (la pública,
no la `service_role` — esa nunca debe salir del backend). La URL ya viene
puesta. Luego:

```
streamlit run app.py
```

## Paso 3 · Subir a GitHub

`.streamlit/secrets.toml` ya está en `.gitignore` — nunca lo subas al
repositorio (solo el `.example`).

```
git init
git add .
git commit -m "Corte de caja y estadísticas - primera versión web"
git remote add origin <URL_DE_TU_REPO>
git push -u origin main
```

## Paso 4 · Desplegar en Streamlit Community Cloud (gratis)

1. Entra a [share.streamlit.io](https://share.streamlit.io) con tu cuenta
   de GitHub.
2. "New app" → selecciona el repositorio y `app.py` como archivo principal.
3. En **Advanced settings → Secrets**, pega el mismo contenido de tu
   `.streamlit/secrets.toml` (URL + anon key).
4. Deploy. La URL pública queda como
   `https://<algo>.streamlit.app` — esa es la que comparten las 25
   sucursales.

Sin costo, sin tarjeta. Nota: la app "duerme" tras un rato sin visitas y
tarda unos segundos en despertar en la siguiente visita — normal en el plan
gratis, no afecta los datos guardados.

## Cómo está organizado el código

- `auth.py` — login/logout contra Supabase Auth. El cliente de Supabase se
  guarda en `st.session_state` (no en `st.cache_resource`) para que la
  sesión de una persona nunca se mezcle con la de otra.
- `db.py` — todas las consultas a las 7 tablas (Corte, gastos, las 3 tablas
  de Estadísticas, catálogo de promociones).
- `app.py` — la interfaz: login, pestaña Corte de Caja, pestaña
  Estadísticas (con sub-pestañas para los 5 rubros), y pestaña Admin
  (solo visible si `rol = admin`).

## Reglas de cuadre (igual que la versión de escritorio)

- **Corte de Caja**: Efectivo + Tarjeta debe coincidir con el Total de
  Ingresos (Ventas + Consultas + Dental + Geovanes + Cinerarias −
  Descuentos). Los Gastos no entran en esa comparación — son una salida
  aparte.
- **Estadísticas**: la suma de las 5 tarjetas (Primera Vez + Mostrador +
  Subsecuentes + Revisiones + Promociones) debe coincidir con
  **Total Ingresos − Dental** del Corte de esa misma fecha.

Ninguna de las dos reglas bloquea el guardado si no cuadra — solo avisa en
rojo, para que la persona decida si corregir o guardar así.

## Diferencias a propósito frente a la versión de escritorio

Para mantenerlo simple en esta primera versión web:

- **Guardado directo por rubro**: en Estadísticas, cada rubro (Primera Vez,
  Mostrador, Subsecuentes, Revisiones, Promociones) tiene su propio botón
  "Guardar" que escribe directo a la base — no hay un paso intermedio de
  "guardar en memoria" como en la app de escritorio, porque aquí cada
  guardado ya es un solo movimiento a una base real (no hay riesgo de
  perder el archivo local).
- **Catálogo de promociones compartido**: como ahora es una sola base para
  las 25 sucursales, el catálogo vive en una tabla (`promociones_catalogo`)
  y es el mismo para todas — ya no hay que copiar un archivo a cada equipo.
- **Nombre del Dr. por turno**: no se incluyó en esta versión (no lo
  pediste esta vez); si lo quieres de vuelta, se agrega fácil.

## Próximos pasos sugeridos

- Cuando tengan más de 1 sucursal activa, el Panel Admin ya funciona igual
  para las 25 — no hay que tocar código, solo crear los usuarios.
- Si quieres exportar a Excel con el mismo formato bonito que la versión de
  escritorio (colores, totales resaltados) en vez de CSV plano, lo puedo
  agregar con `openpyxl` sin mucho esfuerzo.
- Si más adelante quieres restringir por IP, agregar 2FA, o exportar
  reportes automáticos por correo, todo eso se apoya en lo que ya está
  armado.
