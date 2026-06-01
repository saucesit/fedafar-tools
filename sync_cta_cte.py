"""
sync_cta_cte.py — Sincronización de estado de cuenta desde Genexus → Supabase
Usa Playwright (browser real) para autenticarse y exportar el Excel.

Uso:
    python sync_cta_cte.py 1248              # sincroniza un cliente
    python sync_cta_cte.py 1248 1249 1250   # sincroniza varios
    python sync_cta_cte.py --todos           # sincroniza todos los activos en Supabase

Requisitos en .env:
    FEDAFAR_USER, FEDAFAR_PASS, SUPABASE_URL, SUPABASE_KEY
"""

import os
import sys
import tempfile
import pandas as pd
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

# ── Configuración ──────────────────────────────────────────────────────────────
BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# ── Login ──────────────────────────────────────────────────────────────────────

def do_login(page: Page) -> bool:
    """Navega a la página de login y se autentica."""
    print("  Abriendo página de login...")
    try:
        page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("  ERROR: No se pudo conectar al servidor interno.")
        print("         Verificar que estás en la red de Fedafar.")
        return False

    # Completar formulario
    page.fill("#vSECUSERNAME",    FEDAFAR_USER)
    page.fill("#vSECUSERPASSWORD", FEDAFAR_PASS)
    page.click("#BTNENTER")

    # Esperar que redirija (sale de seclogin.aspx)
    try:
        page.wait_for_function(
            "() => !window.location.href.includes('seclogin')",
            timeout=10000
        )
        print(f"  Login exitoso.")
        return True
    except PWTimeout:
        print("  ERROR: Login fallido. Verificar credenciales en .env")
        return False


# ── Export ─────────────────────────────────────────────────────────────────────

def export_cta_cte(page: Page, client_id: int) -> Optional[pd.DataFrame]:
    """Navega a Comprobantes de Clientes, selecciona el cliente y descarga el Excel."""
    try:
        page.goto(f"{BASE_URL}/teso_comprobantesdecliente.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print(f"    ERROR: No se pudo abrir la página de comprobantes.")
        return None

    # ── 1. Campo de cliente (autocomplete GeneXus) ─────────────────────────────
    client_selectors = [
        "input[id*='Cliente']",
        "input[id*='cliente']",
        "input[id*='AV6']",
        "input[id*='Cli']",
    ]
    client_input = None
    for sel in client_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                client_input = loc
                print(f"    Campo cliente encontrado: {sel}")
                break
        except:
            continue

    if not client_input:
        client_input = page.locator("input[type='text']:visible").first
        print("    Usando primer input visible como campo cliente.")

    # Limpiar el campo con Ctrl+A + Delete para asegurar que esté vacío
    client_input.click()
    client_input.press("Control+a")
    client_input.press("Delete")
    page.wait_for_timeout(300)
    client_input.type(str(client_id), delay=150)
    page.wait_for_timeout(3000)  # esperar sugerencias del autocomplete

    import re as _re

    # Navegar el dropdown con ArrowDown hasta encontrar el cliente correcto.
    # En Genexus, ArrowDown actualiza el valor del input con la sugerencia resaltada.
    client_input.press("ArrowDown")
    page.wait_for_timeout(400)

    confirmed = False
    for attempt in range(25):
        current_val = client_input.input_value()
        if _re.match(rf'^\s*{client_id}\b', current_val):
            client_input.press("Enter")
            page.wait_for_timeout(800)
            confirmed = True
            print(f"    [OK] Cliente confirmado (intento {attempt + 1}): '{current_val.strip()[:60]}'")
            break
        client_input.press("ArrowDown")
        page.wait_for_timeout(200)

    if not confirmed:
        # Último recurso: limpiar, escribir y Tab
        print(f"    [AVISO] No encontrado en dropdown. Reintentando con Tab...")
        client_input.click()
        client_input.press("Control+a")
        client_input.press("Delete")
        page.wait_for_timeout(200)
        client_input.type(str(client_id), delay=120)
        page.wait_for_timeout(2000)
        client_input.press("Tab")
        page.wait_for_timeout(1500)
        current_val = client_input.input_value()
        if _re.match(rf'^\s*{client_id}\b', current_val):
            confirmed = True
            print(f"    [OK] Cliente confirmado tras Tab: '{current_val.strip()[:60]}'")
        else:
            print(f"    [ERROR] ERROR: no se pudo seleccionar cliente {client_id}. Abortando.")
            return None

    # ── 2. Tildar "Mostrar solo con saldo" ────────────────────────────────────
    page.wait_for_timeout(2000)  # esperar que la página actualice tras seleccionar cliente
    tildado = False

    # Intentar todos los checkboxes visibles de la página
    checkbox_selectors = [
        "input[type='checkbox'][id*='aldo']",
        "input[type='checkbox'][id*='Saldo']",
        "input[type='checkbox'][id*='SALDO']",
        "input[type='checkbox'][id*='MostrarSaldo']",
        "input[type='checkbox'][id*='Solo']",
        "input[type='checkbox'][id*='solo']",
        "input[type='checkbox'][id*='Mostrar']",
    ]
    for sel in checkbox_selectors:
        try:
            cbs = page.locator(sel)
            if cbs.count() > 0:
                for idx in range(cbs.count()):
                    cb = cbs.nth(idx)
                    if cb.is_visible():
                        if not cb.is_checked():
                            cb.click()
                            page.wait_for_timeout(500)
                        print(f"    Checkbox 'Mostrar solo con saldo' tildado ({sel}).")
                        tildado = True
                        break
            if tildado:
                break
        except:
            continue

    if not tildado:
        # Buscar todos los checkboxes de la página y tildar el primero visible
        try:
            all_cbs = page.locator("input[type='checkbox']")
            for idx in range(all_cbs.count()):
                cb = all_cbs.nth(idx)
                if cb.is_visible():
                    cb_id = cb.get_attribute("id") or ""
                    if not cb.is_checked():
                        cb.click()
                        page.wait_for_timeout(500)
                    print(f"    Checkbox tildado por fallback (id='{cb_id}').")
                    tildado = True
                    break
        except:
            pass

    if not tildado:
        print("    AVISO: No se encontró ningún checkbox en la página.")

    # ── 3. Click en Exportar y capturar la descarga ───────────────────────────
    export_selectors = [
        "input[name='DOUEXPORTAR']",
        "input[id*='EXPORT']",
        "input[value*='Exportar']",
        "button[id*='EXPORT']",
        "input[value*='xportar']",
    ]
    export_btn = None
    for sel in export_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                export_btn = loc
                print(f"    Botón exportar encontrado: {sel}")
                break
        except:
            continue

    if not export_btn:
        # Buscar por texto
        export_btn = page.get_by_text("Exportar").first
        print("    Usando botón por texto 'Exportar'.")

    try:
        with page.expect_download(timeout=20000) as dl_info:
            export_btn.click()
        download = dl_info.value

        # Leer el Excel desde el archivo temporal
        path = download.path()

        # Buscar la fila real del encabezado (el Excel de Genexus tiene títulos arriba)
        keywords = ['saldo', 'importe', 'comprobante', 'fecha', 'vencimiento']
        raw = pd.read_excel(path, header=None)
        header_row = 0
        for i, row in raw.iterrows():
            row_lower = ' '.join(str(v).lower() for v in row.values if pd.notna(v))
            matches = sum(1 for kw in keywords if kw in row_lower)
            if matches >= 2:
                header_row = i
                break

        df = pd.read_excel(path, skiprows=header_row, header=0)
        df.columns = [str(c).strip() for c in df.columns]
        # Eliminar filas completamente vacías
        df = df.dropna(how='all')

        print(f"    Encabezado encontrado en fila {header_row}.")
        print(f"    {len(df)} comprobantes descargados.")
        print(f"    Columnas encontradas: {list(df.columns)}")
        return df

    except PWTimeout:
        print(f"    ERROR: Timeout esperando descarga del Excel.")
        return None
    except Exception as e:
        print(f"    ERROR al descargar/leer Excel: {e}")
        return None


# ── Supabase ───────────────────────────────────────────────────────────────────

def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL o SUPABASE_KEY no configurados en .env")
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def ensure_client_exists(sb, genexus_client_id: int):
    """Crea un registro placeholder en clientes si no existe todavía."""
    res = sb.table("clientes") \
            .select("id") \
            .eq("genexus_client_id", genexus_client_id) \
            .execute()
    if not res.data:
        sb.table("clientes").insert({
            "username":          f"cliente_{genexus_client_id}",
            "password_hash":     "PENDIENTE",
            "nombre":            f"Cliente {genexus_client_id}",
            "tipo_precio":       "contado",
            "genexus_client_id": genexus_client_id,
            "activo":            False,   # inactivo hasta que se configure el login
        }).execute()
        print(f"    Cliente {genexus_client_id} creado en Supabase (pendiente configurar login).")


def upload_to_supabase(genexus_client_id: int, df: pd.DataFrame):
    """Reemplaza los comprobantes del cliente en Supabase con datos frescos."""
    sb = get_supabase_client()
    if not sb:
        return

    # Garantizar que el cliente exista antes de insertar sus comprobantes
    ensure_client_exists(sb, genexus_client_id)

    sb.table("cuenta_corriente") \
      .delete() \
      .eq("genexus_client_id", genexus_client_id) \
      .execute()

    if df.empty:
        print("    Sin comprobantes para subir.")
        return

    col_map = {
        "fecha_comprobante": ["Fecha de Comprobante", "FechaComprobante", "Fecha Comprobante", "Fecha"],
        "comprobante":       ["Comprobante", "Nro. Comprobante", "Nro Comprobante", "Número", "Numero"],
        "fecha_vencimiento": ["Fecha de Vencimiento", "FechaVencimiento", "Fecha Vencimiento", "Vencimiento"],
        "importe":           ["Importe", "Monto", "Total"],
        "saldo":             ["Saldo", "Saldo Actual", "Saldo Pendiente", "Debe"],
    }

    def find_col(df, candidates):
        # Exact match primero
        for c in candidates:
            if c in df.columns:
                return c
        # Case-insensitive match
        cols_lower = {col.lower(): col for col in df.columns}
        for c in candidates:
            if c.lower() in cols_lower:
                return cols_lower[c.lower()]
        # Partial match (el candidato está contenido en la columna o viceversa)
        for c in candidates:
            for col in df.columns:
                if c.lower() in col.lower() or col.lower() in c.lower():
                    return col
        return None

    # Filtrar la fila de totales que Genexus agrega al final del Excel
    fecha_col = find_col(df, col_map["fecha_comprobante"])
    comp_col  = find_col(df, col_map["comprobante"])
    if fecha_col:
        df = df[pd.to_datetime(df[fecha_col], errors='coerce').notna()]
    if comp_col:
        comp_str = df[comp_col].astype(str).str.strip()
        df = df[~comp_str.str.lower().str.contains('total', na=False)]
        df = df[comp_str.ne('') & comp_str.ne('nan')]
    df = df.reset_index(drop=True)

    if df.empty:
        print("    Sin comprobantes válidos para subir.")
        return

    print(f"    {len(df)} comprobantes válidos (sin fila de totales).")

    records = []
    now = datetime.now().isoformat()
    for _, row in df.iterrows():
        record = {"genexus_client_id": genexus_client_id, "actualizado_en": now}
        for field, candidates in col_map.items():
            col = find_col(df, candidates)
            if col:
                val = row[col]
                if field in ("importe", "saldo"):
                    try:
                        record[field] = float(val) if pd.notna(val) else 0.0
                    except (ValueError, TypeError):
                        record[field] = 0.0
                else:
                    record[field] = str(val) if pd.notna(val) else ""
            else:
                record[field] = 0.0 if field in ("importe", "saldo") else ""
        records.append(record)

    sb.table("cuenta_corriente").insert(records).execute()
    print(f"    {len(records)} registros subidos a Supabase.")


def get_all_client_ids() -> list:
    sb = get_supabase_client()
    if not sb:
        return []
    res = sb.table("clientes") \
            .select("genexus_client_id, nombre") \
            .eq("activo", True) \
            .not_.is_("genexus_client_id", "null") \
            .execute()
    return res.data or []


# ── Main ───────────────────────────────────────────────────────────────────────

def sync_clientes(client_ids: list):
    if not client_ids:
        print("Sin clientes para sincronizar.")
        return

    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()

        # Login una sola vez para todos los clientes
        if not do_login(page):
            browser.close()
            return

        total = len(client_ids)
        for i, cid in enumerate(client_ids, 1):
            print(f"[{i}/{total}] Sincronizando cliente {cid}...")
            df = export_cta_cte(page, cid)
            if df is not None:
                upload_to_supabase(cid, df)

        browser.close()

    print(f"\nSincronización completada: {total} cliente(s).")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    if args[0] == "--todos":
        print("Obteniendo lista de clientes desde Supabase...")
        clientes = get_all_client_ids()
        if not clientes:
            print("No se encontraron clientes activos en Supabase.")
            sys.exit(1)
        ids = [c["genexus_client_id"] for c in clientes]
        print(f"Clientes: {[c['nombre'] for c in clientes]}")
        sync_clientes(ids)
    else:
        try:
            ids = [int(x) for x in args]
        except ValueError:
            print("ERROR: Los IDs deben ser números. Ej: python sync_cta_cte.py 1248 1249")
            sys.exit(1)
        sync_clientes(ids)
