"""
sync_stock.py — Descarga el reporte de stock desde Genexus y guarda stock_data.json

Flujo:
    1. Login con Playwright
    2. Navegar a alm_articulospordeposito.aspx  (Almacén → Reportes → Artículos Por Depósito)
    3. Depósito=DEPOSITO y Tipo Reporte=Resumen ya están por defecto
    4. Clic en "Exportar" → descarga el Excel
    5. Parsear y guardar stock_data.json

Uso:
    python sync_stock.py

Requisitos en .env:
    FEDAFAR_USER, FEDAFAR_PASS
"""

import os
import json
import shutil
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout
from datetime import datetime, timezone

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL', '')
SUPABASE_KEY = os.getenv('SUPABASE_KEY', '')

BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
XLSX_PATH    = os.path.join(BASE_DIR, "stock_temp.xlsx")
OUTPUT_PATH  = os.path.join(BASE_DIR, "stock_data.json")
REPORT_URL   = f"{BASE_URL}/alm_articulospordeposito.aspx"


def do_login(page: Page) -> bool:
    print("  Abriendo página de login...")
    try:
        page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("  ERROR: No se pudo conectar al servidor interno.")
        return False

    page.fill("#vSECUSERNAME",     FEDAFAR_USER)
    page.fill("#vSECUSERPASSWORD", FEDAFAR_PASS)
    page.click("#BTNENTER")

    try:
        page.wait_for_function(
            "() => !window.location.href.includes('seclogin')",
            timeout=10000
        )
        print("  Login exitoso.")
        return True
    except PWTimeout:
        print("  ERROR: Login fallido. Verificar credenciales en .env")
        return False


def download_reporte(page: Page) -> bool:
    print(f"  Navegando a reporte de stock...")
    try:
        page.goto(REPORT_URL, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(1500)
        print("  [OK] Página cargada.")
    except PWTimeout:
        print("  ERROR: No se pudo cargar la página del reporte.")
        return False

    # Buscar botón Exportar (botón violeta junto a Imprimir)
    btn = None
    for selector in [
        "input[value='Exportar']",
        "button:has-text('Exportar')",
        "[id*='EXPORT']",
        "[id*='Export']",
    ]:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=3000):
                btn = loc
                break
        except Exception:
            continue

    if btn is None:
        print("  ERROR: No se encontró el botón Exportar.")
        # Debug: mostrar todos los botones visibles
        btns = page.evaluate("""
            () => Array.from(document.querySelectorAll('input[type=button],input[type=submit],button'))
                .filter(b => b.offsetParent !== null)
                .map(b => ({ id: b.id, val: b.value||b.textContent.trim(), cls: b.className }))
        """)
        print("  Botones visibles:", btns)
        return False

    print("  Descargando reporte Excel...")
    try:
        with page.expect_download(timeout=30000) as dl_info:
            btn.click()
        download = dl_info.value
        download.save_as(XLSX_PATH)
        kb = os.path.getsize(XLSX_PATH) / 1024
        print(f"  [OK] Excel descargado ({kb:.1f} KB).")
        return True
    except Exception as e:
        print(f"  ERROR al descargar: {e}")
        return False


def parse_reporte() -> bool:
    try:
        # El Excel tiene 4 filas de cabecera antes de los datos
        # Fila 4 (índice 4): Articulo | Descripción | Tranzable | Existencia
        df = pd.read_excel(XLSX_PATH, skiprows=4, header=0)
        df.columns = [str(c).strip() for c in df.columns]

        # Detectar columnas — Descripción es el nombre, Articulo es el código numérico
        col_desc  = next((c for c in df.columns if 'desc' in c.lower() or 'nombre' in c.lower()), None)
        col_exist = next((c for c in df.columns if 'exist' in c.lower()), None)

        if not col_desc or not col_exist:
            print(f"  ERROR: Columnas no encontradas. Disponibles: {list(df.columns)}")
            return False

        df[col_exist] = pd.to_numeric(df[col_exist], errors='coerce').fillna(0)
        df = df[df[col_exist] > 0].copy()
        df[col_desc] = df[col_desc].astype(str).str.strip().str.upper()
        df = df[df[col_desc].notna() & (df[col_desc] != '') & (df[col_desc] != 'NAN')]

        stock_dict = {
            row[col_desc]: float(row[col_exist])
            for _, row in df.iterrows()
        }

        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(stock_dict, f, ensure_ascii=False)
        print(f"  [OK] {len(stock_dict)} artículos guardados en stock_data.json")

        _subir_a_supabase(stock_dict)
        return True

    except Exception as e:
        print(f"  ERROR al parsear Excel: {e}")
        return False
    finally:
        try:
            os.remove(XLSX_PATH)
        except Exception:
            pass


def _subir_a_supabase(stock_dict: dict):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [SKIP] Supabase no configurado, solo JSON local.")
        return
    try:
        from supabase import create_client
        sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        ts = datetime.now(timezone.utc).isoformat()
        registros = [{'nombre': k, 'existencia': v, 'actualizado_en': ts}
                     for k, v in stock_dict.items()]
        batch = 500
        for i in range(0, len(registros), batch):
            sb.table('stock_productos').upsert(registros[i:i+batch]).execute()
        # Borrar productos que ya no tienen stock (no aparecieron en este sync)
        sb.table('stock_productos').delete().lt('actualizado_en', ts).execute()
        print(f"  [OK] {len(registros)} productos actualizados en Supabase.")
        # Invalidar caché de productos en Render
        _invalidar_cache_render()
    except Exception as e:
        print(f"  [WARN] No se pudo subir a Supabase: {e}")


def _invalidar_cache_render():
    RENDER_URL = os.getenv('RENDER_URL', 'https://fedafar-tools.onrender.com')
    ADMIN_PASS = os.getenv('ADMIN_PASSWORD', '')
    if not ADMIN_PASS:
        return
    try:
        import requests as req
        s = req.Session()
        s.post(f'{RENDER_URL}/api/admin/login', json={'password': ADMIN_PASS}, timeout=10)
        s.post(f'{RENDER_URL}/api/admin/productos/invalidar-cache', timeout=10)
        print("  [OK] Caché de productos invalidado en Render.")
    except Exception as e:
        print(f"  [WARN] No se pudo invalidar caché en Render: {e}")


if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        exit(1)

    print("=== Sync Stock ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()

        ok = do_login(page) and download_reporte(page)
        browser.close()

    if not ok:
        print("\n[ERROR] No se pudo descargar el reporte.")
        exit(1)

    ok = parse_reporte()
    if ok:
        print("\n[OK] Stock actualizado exitosamente.")
    else:
        print("\n[ERROR] No se pudo parsear el reporte.")
        exit(1)
