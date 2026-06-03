"""
sync_precios.py — Descarga la lista de precios desde Genexus y actualiza price_list.xlsx

Navegacion en Genexus:
    Ventas > Listas de precios > Lupita (Visualizar) > Articulos > (limpiar Buscar) > Excel

Uso:
    python sync_precios.py

Requisitos en .env:
    FEDAFAR_USER, FEDAFAR_PASS
"""

import os
import shutil
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH  = os.path.join(BASE_DIR, "price_list.xlsx")


# ── Login ──────────────────────────────────────────────────────────────────────

def do_login(page: Page) -> bool:
    print("  Abriendo pagina de login...")
    try:
        page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("  ERROR: No se pudo conectar al servidor interno.")
        print("         Verificar que estas en la red de Fedafar.")
        return False

    page.fill("#vSECUSERNAME",    FEDAFAR_USER)
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


# ── Descarga de lista de precios ───────────────────────────────────────────────

def download_price_list(page: Page) -> bool:
    """
    Navega a VTA_ListasPreciosArticulosWC.aspx > click lupita (a[href*=DSP]) >
    limpia campos Buscar > click #W0033BTNEXPORT
    """

    # ── 1. Abrir la pagina de listas de precios ───────────────────────────────
    print("  Navegando a lista de precios...")
    try:
        page.goto(f"{BASE_URL}/VTA_ListasPreciosArticulosWC.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
        print("  [OK] Pagina cargada.")
    except PWTimeout:
        print("  ERROR: No se pudo abrir la pagina de listas de precios.")
        return False

    # ── 2. Click en la lupita (Visualizar) ────────────────────────────────────
    print("  Clickeando lupita (Visualizar)...")
    try:
        lupita = page.locator("a[href*='DSP']").first
        lupita.wait_for(timeout=5000)
        lupita.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        print("  [OK] Lupita clickeada. Pagina actual:", page.url)
    except Exception as e:
        print(f"  ERROR: No se encontro la lupita: {e}")
        return False

    # ── 3. Limpiar campo Buscar Articulo y Laboratorio ────────────────────────
    print("  Limpiando campos Buscar...")
    for field_id in [
        "W0033vLISTAPRECIOARTICULONOMBRECOMPUESTO",
        "W0033vLISTAPRECIOARTICULOLABORATORIONOMBRE",
    ]:
        try:
            inp = page.locator(f"#{field_id}")
            if inp.is_visible(timeout=2000):
                current = inp.input_value()
                if current:
                    inp.click()
                    inp.press("Control+a")
                    inp.press("Delete")
                    print(f"  [OK] Campo {field_id[:30]}... limpiado (tenia: '{current[:20]}').")
                else:
                    print(f"  [OK] Campo {field_id[:30]}... ya estaba vacio.")
        except:
            pass

    page.wait_for_timeout(500)

    # ── 4. Click en Excel y capturar descarga ─────────────────────────────────
    print("  Clickeando boton Excel...")
    try:
        export_btn = page.locator("#W0033BTNEXPORT")
        export_btn.wait_for(timeout=5000)

        with page.expect_download(timeout=30000) as dl_info:
            export_btn.click()
        download = dl_info.value
        path = download.path()

        shutil.copy(path, OUTPUT_PATH)
        print(f"  [OK] price_list.xlsx actualizado ({OUTPUT_PATH}).")
        return True

    except PWTimeout:
        print("  ERROR: Timeout esperando la descarga del Excel.")
        return False
    except Exception as e:
        print(f"  ERROR al exportar: {e}")
        return False


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        exit(1)

    print("=== Sync Lista de Precios ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()

        if not do_login(page):
            browser.close()
            exit(1)

        success = download_price_list(page)
        browser.close()

    if success:
        print("\n[OK] Lista de precios actualizada.")
    else:
        print("\n[ERROR] No se pudo actualizar la lista de precios.")
        exit(1)
