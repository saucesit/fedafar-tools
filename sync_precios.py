"""
sync_precios.py — Descarga la lista de precios desde Genexus y actualiza price_list.xlsx

Flujo:
    1. Login con Playwright
    2. Navegar a vta_listaspreciosview.aspx?1,DSP, (vista de articulos)
    3. Limpiar campos Buscar
    4. Interceptar la URL del XHR con JS antes de clickear Excel
    5. Descargar el .xlsx con requests usando las cookies y headers de sesion

Uso:
    python sync_precios.py

Requisitos en .env:
    FEDAFAR_USER, FEDAFAR_PASS
"""

import os
import shutil
import requests
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


# ── Descarga ───────────────────────────────────────────────────────────────────

def download_price_list(page: Page) -> bool:
    """
    Navega a la vista de articulos, limpia los campos Buscar,
    intercepta la URL del XHR del boton Excel y descarga el archivo.
    """

    # ── 1. Navegar directo a la pestaña Articulos ─────────────────────────────
    VIEW_URL = f"{BASE_URL}/vta_listaspreciosview.aspx?1,DSP,#Articulos"
    print(f"  Navegando a {VIEW_URL} ...")
    try:
        page.goto(VIEW_URL, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(3000)  # esperar que el WebComponent renderice
        print("  [OK] Pagina cargada.")
    except PWTimeout:
        print("  ERROR: No se pudo cargar la vista de articulos.")
        return False

    # ── 2. Esperar que el boton Excel este listo ──────────────────────────────
    try:
        page.locator("#W0033BTNEXPORT").wait_for(state="visible", timeout=15000)
        print("  [OK] Boton Excel visible.")
    except:
        print("  ERROR: El boton Excel no aparecio.")
        return False

    # ── 3. Limpiar campos Buscar ──────────────────────────────────────────────
    print("  Limpiando campos Buscar...")
    for field_id in [
        "W0033vLISTAPRECIOARTICULONOMBRECOMPUESTO",
        "W0033vLISTAPRECIOARTICULOLABORATORIONOMBRE",
    ]:
        try:
            inp = page.locator(f"#{field_id}")
            if inp.is_visible(timeout=2000):
                val = inp.input_value()
                if val:
                    inp.fill("")
                    print(f"  [OK] Campo limpiado (tenia: '{val[:30]}').")
                else:
                    print(f"  [OK] Campo ya estaba vacio.")
        except:
            pass

    page.wait_for_timeout(500)

    # ── 4. Capturar todos los requests para debug ────────────────────────────
    all_requests = []
    page.on("request", lambda req: all_requests.append(req.url))

    # ── 5. Intentar con expect_download (captura cualquier descarga) ──────────
    print("  Clickeando boton Excel (modo download)...")
    try:
        with page.expect_download(timeout=15000) as dl_info:
            page.locator("#W0033BTNEXPORT").click()
        download = dl_info.value
        path = download.path()
        shutil.copy(path, OUTPUT_PATH)
        kb = os.path.getsize(OUTPUT_PATH) / 1024
        print(f"  [OK] price_list.xlsx descargado ({kb:.1f} KB).")
        return True
    except Exception as e:
        print(f"  [AVISO] expect_download no funciono: {e}")

    # ── 6. Fallback: buscar URL en los requests capturados ────────────────────
    page.wait_for_timeout(3000)
    xlsx_urls = [u for u in all_requests if "WCExport" in u.upper() or "xlsx" in u.lower()]
    print(f"  Requests capturados con xlsx/WCExport: {xlsx_urls}")
    print(f"  Total requests capturados: {len(all_requests)}")
    if len(all_requests) > 0:
        print(f"  Ultimos 5 requests: {all_requests[-5:]}")

    if not xlsx_urls:
        print("  ERROR: No se capturo ninguna URL de descarga.")
        return False

    xlsx_url = xlsx_urls[0]
    if not xlsx_url.startswith("http"):
        xlsx_url = f"{BASE_URL}/{xlsx_url.lstrip('/')}"
    print(f"  [OK] URL capturada: {xlsx_url}")

    try:
        token = page.evaluate("window.gx.sec.secToken")
    except:
        token = ""

    response = page.context.request.get(
        xlsx_url,
        headers={
            "AJAX_SECURITY_TOKEN": token,
            "X-SPA-MP":           "wwpbaseobjects.workwithplusmasterpage",
            "X-SPA-REQUEST":      "1",
            "Referer":            VIEW_URL,
        }
    )
    with open(OUTPUT_PATH, "wb") as f:
        f.write(response.body())

    kb = len(response.body()) / 1024
    print(f"  [OK] price_list.xlsx actualizado ({kb:.1f} KB).")
    return True


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        exit(1)

    print("=== Sync Lista de Precios ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # downloads no funcionan en headless
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()

        if not do_login(page):
            browser.close()
            exit(1)

        success = download_price_list(page)
        browser.close()

    if success:
        print("\n[OK] Lista de precios actualizada exitosamente.")
    else:
        print("\n[ERROR] No se pudo actualizar la lista de precios.")
        exit(1)
