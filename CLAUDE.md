# FEDAFAR — App de Clientes

## ¿Qué es esto?
App web para farmacias clientes de FEDAFAR Droguería Integral (Salta, Argentina).
Permite ver el catálogo de productos con precios, armar pedidos y consultar el estado de cuenta corriente.

## Stack
- **Backend**: Python / Flask + Flask-Login + Supabase (PostgreSQL)
- **Frontend**: Vanilla JS + HTML + CSS (sin frameworks)
- **Deploy**: Render (free tier) — se duerme tras 15 min de inactividad
- **Repo**: github.com/saucesit/fedafar-tools (branch: main)

## Archivos clave
| Archivo | Descripción |
|---|---|
| `api_app.py` | Backend Flask: autenticación, endpoints API, lógica de precios y stock |
| `fedafar-app/index.html` | UI principal del cliente (login + tienda + carrito + mi cuenta) |
| `fedafar-app/app.js` | Lógica frontend completa |
| `fedafar-app/style.css` | Estilos |
| `templates/admin.html` | Panel admin para gestionar farmacias |
| `sync_cta_cte.py` | Sincroniza estado de cuenta desde Genexus → Supabase (Playwright) |
| `sync_diario.bat` | Script para tarea programada Windows (2 AM diario) |
| `full_price_list.txt` | Lista de precios en texto plano (UTF-16) |
| `.env` | Variables de entorno locales (no subir a git) |

## URLs
- **App clientes**: https://fedafar-tools.onrender.com/tienda/
- **Panel admin**: https://fedafar-tools.onrender.com/admin
- **Stock interno**: http://192.168.0.35/fedafar/ALM_ArticulosPorDepositoExport-.xlsx (solo red local)
- **Genexus ERP**: http://192.168.0.35/fedafar (solo red local)

## Supabase
- **URL**: https://kznxtqqbbrrljrarlbqa.supabase.co
- **Tablas**: `clientes`, `cuenta_corriente`
- **RLS**: deshabilitado (intencional por ahora)

## Autenticación
- **Clientes**: Flask-Login con sesión cookie. Tabla `clientes` en Supabase.
- **Admin**: sesión Flask con `session['is_admin']`. Contraseña en `ADMIN_PASSWORD` (env var).

## Sincronización de cuenta corriente
- Script: `sync_cta_cte.py`
- Uso: `python sync_cta_cte.py --todos` (todos los clientes activos) o `python sync_cta_cte.py 1248`
- El script usa Playwright (Chromium headless) para loguearse al Genexus y exportar el Excel
- El Excel tiene 6 filas de cabecera antes de los datos reales
- Columnas: Fecha de Comprobante, Comprobante, Fecha de Vencimiento, Importe, Saldo
- La API filtra `saldo > 0` para mostrar solo comprobantes pendientes
- Tarea programada Windows: "FEDAFAR - Sync Cta Cte", corre a las 2 AM

## Precios y categorías
- Dos tipos de precio: `contado` y `cta-cte`
- Categorías: Antibióticos, Analgésicos, Cardiovascular, Corticoides, Descartables, Otros
- Descartables tienen IVA 21% aplicado (`price * 1.21`)
- Stock se verifica en tiempo real contra el servidor interno (si no hay red, muestra todo)

## Usuarios locales
- Windows: `FEDAFAR` en `DESKTOP-H72FNCB`
- GitHub: saucesit
- Python: `C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe`
