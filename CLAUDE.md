# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Streamlit + Supabase web app for "Corte de Caja y Estadísticas" at Grupo Médico AG: each of ~25 branches (sucursales) captures its daily cash count and patient/income statistics; admins see and correct everything. It replaced a desktop app that used a per-branch `.db` file synced over Dropbox. UI text, identifiers, and comments are in Spanish — keep new code consistent with that.

## Commands

```
pip install -r requirements.txt
streamlit run app.py
```

There are no tests, linter, or build step. Deployment is Streamlit Community Cloud from `main` (`app.py` as entry point); secrets are pasted into the Cloud dashboard.

`.streamlit/secrets.toml` (gitignored, never commit) must define `SUPABASE_URL`, `SUPABASE_ANON_KEY` (the public anon key, never `service_role`), and `ADMIN_PIN`.

## Architecture

Three modules:

- `auth.py` — Supabase Auth login. Branch users type a bare username (e.g. `PRADOS_BASE`), which is turned into `prados_base@gmag.local`; anything containing `@` is used as-is (admins). After login it loads the user's row from `perfiles` (`sucursal`, `rol` = `sucursal` | `admin`); a user without a profile row is signed out on purpose.
- `db.py` — all table access. Every function takes the per-session `client` as its first argument. Every query goes through `_exec()`, which retries transient httpx errors (idle Streamlit sessions leave stale connections). Use `_exec()` for any new query.
- `app.py` — one top-to-bottom Streamlit script: login → sidebar (date lock) → "day data" block that loads everything for `(sucursal, fecha)` once → a main column with tabs (Corte de Caja, Estadísticas with 5 sub-tabs, Admin if `rol == admin`) and a side column showing progress and a summary.

Key invariants:

- **Supabase client lives in `st.session_state`, never `st.cache_resource`.** `cache_resource` is shared across all users in the process and would leak one person's authenticated session to another.
- **Per-branch security is enforced by Postgres RLS, not by app code.** Queries filter by `sucursal` for correctness, but admin visibility across branches (e.g. `listar_cortes_rango`) relies on RLS. Schema and RLS policies live in the Supabase project `gmag-corte-caja`; there are no migrations in this repo.
- Tables: `perfiles`, `cortes` (upserted on `fecha,sucursal`), `gastos` (children of `cortes` via `corte_id`, deleted and reinserted on every save), `estadisticas_detalle` (by médico turn × channel, for categories `1A`/`MOSTRADOR`), `estadisticas_agregado` (`SUB`/`REV`), `estadisticas_promociones`, `estadisticas_progreso` (which of the 5 categories were saved that day, even if zero), `promociones_precios` (prices with `vigente_desde` validity dates), `promociones_combos`, `gastos_catalogo`.
- Turns (`MEDICO_TIPOS`): BASE / CUBRE / IMPREVISTOS. Only the selected turns are saved, and rows for turns that were deselected get deleted. Mostrador has an extra channel, `ORIENTACIONES`.

## Business rules (as implemented in code; the README is partly out of date)

- **Ingreso Neto** (`total_ingresos`) = Ventas + Consultas − (desc_consulta + desc_producto + cort_consulta + cort_producto). Dental, Geovanes, and Cinerarias are captured for information only and do **not** add to it. Gastos are a separate outflow: `total_general = total_ingresos − total_gastos`.
- Internal cash check: Efectivo + Tarjeta must equal `total_ingresos`.
- Statistics check: the sum of the 5 categories (1A + Mostrador + SUB + REV + Promociones) must equal the Corte's `total_ingresos`.
- A failed check shows a red warning but never blocks saving.
- **"Enviar"** only becomes available when every step in the `pasos` list in `app.py` passes: corte saved, all 5 categories saved, and both checks cuadran. Sending sets `cortes.enviado`.
- Any save resets `enviado = False`. Once a day has been sent, branch users can no longer edit it. Admins still can, and their edits are recorded as corrections (`corregido`, `corregido_por`, `corregido_en`, plus `valores_originales` on the corte).
- The date is locked to today in `America/Mexico_City` (`ZONA_MEXICO` in `app.py`). Picking another date requires `ADMIN_PIN` in the sidebar.
