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
    Navega a Ventas > Listas de precios > Visualizar > Articulos > Export Excel
    """

    # Intentar URLs conocidas del modulo de listas de precios
    candidate_urls = [
        f"{BASE_URL}/VTA_ListasPreciosArticulosWC.aspx",
        f"{BASE_URL}/vta_listaspreciosarticulos.aspx",
        f"{BASE_URL}/VTA_ListasPreciosArticulos.aspx",
        f"{BASE_URL}/vta_listasdepreciosarticulos.aspx",
    ]

    loaded = False
    for url in candidate_urls:
        try:
            print(f"  Intentando: {url}")
            page.goto(url, timeout=10000)
            page.wait_for_load_state("networkidle", timeout=10000)
            title = page.title().lower()
            if "error" not in title and "not found" not in title and "404" not in title:
                print(f"  [OK] Pagina cargada.")
                loaded = True
                break
        except:
            continue

    if not loaded:
        # Navegar desde el menu principal
        print("  URL directa no encontrada. Navegando desde el menu...")
        loaded = navigate_from_menu(page)

    if not loaded:
        print("  ERROR: No se pudo abrir la pagina de lista de precios.")
        return False

    # ── Buscar y hacer clic en el boton Visualizar (lupita) ───────────────────
    print("  Buscando boton Visualizar (lupita)...")
    visualizar_selectors = [
        "input[title*='isualizar']",
        "input[value*='isualizar']",
        "button[title*='isualizar']",
        "img[title*='isualizar']",
        "img[alt*='isualizar']",
        "input[src*='lupa']",
        "img[src*='lupa']",
        "input[src*='search']",
        "img[src*='search']",
    ]
    clicked_visualizar = False
    for sel in visualizar_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                print(f"  [OK] Visualizar clickeado ({sel}).")
                clicked_visualizar = True
                break
        except:
            continue

    if not clicked_visualizar:
        # Intentar por texto
        try:
            btn = page.get_by_text("Visualizar", exact=False).first
            if btn.is_visible(timeout=2000):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                print("  [OK] Visualizar clickeado por texto.")
                clicked_visualizar = True
        except:
            pass

    if not clicked_visualizar:
        print("  [AVISO] No se encontro boton Visualizar. Continuando de todas formas...")

    # ── Navegar a la tab / seccion Articulos ──────────────────────────────────
    print("  Buscando seccion Articulos...")
    articulos_selectors = [
        "td:has-text('Articulos')",
        "a:has-text('Articulos')",
        "span:has-text('Articulos')",
        "input[value*='rticulos']",
        "button:has-text('Articulos')",
    ]
    for sel in articulos_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                page.wait_for_timeout(1500)
                print(f"  [OK] Seccion Articulos seleccionada ({sel}).")
                break
        except:
            continue

    # ── Limpiar el campo Buscar ───────────────────────────────────────────────
    print("  Limpiando campo Buscar...")
    search_selectors = [
        "input[id*='Buscar']",
        "input[id*='buscar']",
        "input[id*='Search']",
        "input[id*='Filtro']",
        "input[placeholder*='uscar']",
    ]
    for sel in search_selectors:
        try:
            inp = page.locator(sel).first
            if inp.is_visible(timeout=1500):
                inp.click()
                inp.press("Control+a")
                inp.press("Delete")
                print(f"  [OK] Campo Buscar limpiado ({sel}).")
                break
        except:
            continue

    page.wait_for_timeout(1000)

    # ── Exportar a Excel ──────────────────────────────────────────────────────
    print("  Buscando boton Excel...")
    excel_selectors = [
        "input[id*='EXPORT']",
        "input[value*='xcel']",
        "input[value*='xportar']",
        "button[id*='EXPORT']",
        "img[title*='xcel']",
        "img[alt*='xcel']",
        "input[src*='xcel']",
        "img[src*='xcel']",
    ]
    export_btn = None
    for sel in excel_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2000):
                export_btn = btn
                print(f"  [OK] Boton Excel encontrado ({sel}).")
                break
        except:
            continue

    if not export_btn:
        # Buscar por texto
        for texto in ["Excel", "Exportar", "Export"]:
            try:
                btn = page.get_by_text(texto, exact=False).first
                if btn.is_visible(timeout=1500):
                    export_btn = btn
                    print(f"  [OK] Boton Excel encontrado por texto '{texto}'.")
                    break
            except:
                continue

    if not export_btn:
        print("  ERROR: No se encontro el boton de exportar Excel.")
        return False

    # Capturar la descarga
    try:
        with page.expect_download(timeout=30000) as dl_info:
            export_btn.click()
        download = dl_info.value
        path = download.path()

        # Sobrescribir price_list.xlsx
        shutil.copy(path, OUTPUT_PATH)
        print(f"  [OK] price_list.xlsx actualizado correctamente.")
        return True

    except PWTimeout:
        print("  ERROR: Timeout esperando la descarga del Excel.")
        return False
    except Exception as e:
        print(f"  ERROR al descargar: {e}")
        return False


def navigate_from_menu(page: Page) -> bool:
    """Navega desde el menu principal de Genexus."""
    try:
        page.goto(f"{BASE_URL}/default.aspx", timeout=10000)
        page.wait_for_load_state("networkidle", timeout=10000)

        # Ventas
        ventas = page.get_by_text("Ventas", exact=True).first
        if ventas.is_visible(timeout=3000):
            ventas.click()
            page.wait_for_timeout(1000)
            print("  Menu Ventas clickeado.")

        # Listas de precios
        listas = page.get_by_text("Listas de precios", exact=False).first
        if listas.is_visible(timeout=3000):
            listas.click()
            page.wait_for_load_state("networkidle", timeout=10000)
            print("  [OK] Listas de precios clickeado.")
            return True
    except Exception as e:
        print(f"  ERROR navegando por menu: {e}")
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
