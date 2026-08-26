#!/usr/bin/env python3
"""
ajuste_stock.py — Registra un EGRESO de stock en Genexus/DIGIO (Ajustes de Stock)
para impactar lo vendido/consumido en VENTA INF (Fase 3).

Basado en GUIA_PASOS.md (relevada con la extensión sobre el DOM real):
  Login -> Movimientos de Stock (alm_movimientosstockww.aspx)
        -> Agregar (BTNINSERT) -> alm_movimientosstock.aspx?INS,0  "Ajustes de Stock"
        -> Cabecera por TAB (EGRESO + Depósito + Detalle)
        -> Renglones de detalle (Artículo -> Tab puebla lote -> Cantidad -> Tab)
        -> Confirmar (BTNTRN_ENTER)  ⚠ IRREVERSIBLE, impacta stock

SEGURIDAD:
  - DRY_RUN=1 (default) → hace TODO el circuito pero NO confirma: cancela con
    BTNTRN_CANCEL y saca screenshot. Sirve para validar sin tocar el stock real.
  - Solo con DRY_RUN=0 se hace el click en BTNTRN_ENTER.

Uso (probar el circuito con un artículo suelto, sin grabar):
    python ajuste_stock.py --test-articulo 12345 --cantidad 2

Uso (ver la máquina, no headless):
    python ajuste_stock.py --test-articulo 12345 --cantidad 2 --headed

Requisitos en .env: FEDAFAR_USER, FEDAFAR_PASS
Debe correr en una máquina dentro de la red (IP 192.168.0.35 es LAN).
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))

WW_URL       = f"{BASE_URL}/alm_movimientosstockww.aspx"

# Cabecera fija del movimiento
TIPO_MOV_EGRESO = "2"                 # 0=Ninguno 1=INGRESO 2=EGRESO 3=DEVOL 4=DESCARTE
DETALLE_DEFAULT = "VENTA INF"         # texto libre que queda en el detalle del movimiento
MAX_RENGLONES   = 5                   # el form tiene 5 slots (_0001.._0005)

DRY_RUN = os.getenv("DRY_RUN", "1") != "0"


# ── Login ──────────────────────────────────────────────────────────────────────
def do_login(page: Page) -> bool:
    print("  Abriendo página de login...")
    try:
        page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("  ERROR: No se pudo conectar al servidor interno (¿estás en la red?).")
        return False
    page.fill("#vSECUSERNAME",     FEDAFAR_USER)
    page.fill("#vSECUSERPASSWORD", FEDAFAR_PASS)
    page.click("#BTNENTER")
    try:
        page.wait_for_function("() => !window.location.href.includes('seclogin')", timeout=10000)
        print("  Login exitoso.")
        return True
    except PWTimeout:
        print("  ERROR: Login fallido. Verificar credenciales en .env")
        return False


# ── Abrir el alta (modo INS) ───────────────────────────────────────────────────
def abrir_alta(page: Page) -> bool:
    print("  Navegando a Movimientos de Stock...")
    page.goto(WW_URL, timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    print("  Click en Agregar...")
    try:
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.click("#BTNINSERT")
    except PWTimeout:
        # algunos GX no navegan; puede ser postback en la misma URL
        page.wait_for_load_state("networkidle", timeout=15000)
    if "alm_movimientosstock.aspx" not in page.url:
        print(f"  ⚠ URL inesperada tras Agregar: {page.url}")
        return False
    page.wait_for_selector("#MOVSTOCKFECHA", state="visible", timeout=10000)
    print(f"  Formulario de alta abierto: {page.url}")
    return True


# ── Cabecera por TAB (Paso 6 de la guía) ───────────────────────────────────────
def cargar_cabecera(page: Page, detalle: str, tipo_mov: str = TIPO_MOV_EGRESO) -> bool:
    print("  Cargando cabecera (EGRESO)...")
    page.focus("#MOVSTOCKFECHA")
    page.keyboard.press("Tab")                       # -> Tipo Movimiento
    page.select_option("#TIPOMOVSTOCKID", tipo_mov)
    page.keyboard.press("Tab")                       # commit -> autocompleta "Tipo"
    page.wait_for_load_state("networkidle")
    tipo = page.input_value("#TIPOMOVSTOCKTIPO")
    if tipo != "E":
        print(f"  ⚠ El 'Tipo' no se autocompletó a E (quedó '{tipo}').")
        return False
    page.keyboard.press("Tab")                       # Depósito -> Detalle
    page.keyboard.type(detalle)
    page.keyboard.press("Tab")                       # commit -> foco a fila 1
    page.wait_for_load_state("networkidle")
    foco = page.evaluate("() => document.activeElement && document.activeElement.id")
    print(f"  Cabecera OK. Tipo={tipo}, Detalle='{detalle}', foco quedó en '{foco}'.")
    return True


def _dump_lote_select(page: Page, s: str):
    """Muestra las opciones del select de lote/stock del renglón (diagnóstico Paso 7)."""
    opts = page.evaluate(
        """(sel) => { const e = document.querySelector(sel);
            return e ? Array.from(e.options).map(o => ({v:o.value, t:o.text})) : null; }""",
        f"#ARTICULODEPOSITOSTOCKID{s}")
    print(f"    lote select ARTICULODEPOSITOSTOCKID{s}: {opts}")


# ── Cargar un renglón de detalle (Paso 7 — a validar en vivo) ───────────────────
def cargar_renglon(page: Page, i: int, articulo_id, cantidad, lote=None) -> bool:
    s = f"_{i:04d}"
    print(f"  Renglón {i}: artículo={articulo_id}, cantidad={cantidad}")
    try:
        page.fill(f"#vARTICULOID{s}", str(articulo_id))
    except Exception as e:
        print(f"    ⚠ No se encontró #vARTICULOID{s}: {e}")
        return False
    page.keyboard.press("Tab")                       # postback: valida artículo + puebla lote
    page.wait_for_load_state("networkidle")

    # Diagnóstico: ¿qué artículo resolvió? ¿qué lotes aparecieron?
    desc = page.evaluate(
        """(s) => { const cand = ['vARTICULODESCRIPCION'+s,'ARTICULODESCRIPCION'+s,'vARTICULOID'+s+'_description'];
            for (const id of cand){ const e=document.getElementById(id); if(e) return {id, val:(e.value||e.textContent||'').trim()}; }
            return null; }""", s)
    print(f"    artículo resuelto: {desc}")
    _dump_lote_select(page, s)

    if lote is not None:
        try:
            page.select_option(f"#ARTICULODEPOSITOSTOCKID{s}", str(lote))
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"    ⚠ No se pudo elegir lote {lote}: {e}")

    page.fill(f"#MOVSTOCKDETCANTIDAD{s}", str(cantidad))
    page.keyboard.press("Tab")
    page.wait_for_load_state("networkidle")
    print(f"    cantidad seteada: {page.input_value(f'#MOVSTOCKDETCANTIDAD{s}')}")
    return True


# ── Confirmar o cancelar ────────────────────────────────────────────────────────
def finalizar(page: Page) -> bool:
    shot = os.path.join(BASE_DIR, "ajuste_debug.png")
    page.screenshot(path=shot, full_page=True)
    print(f"  Screenshot del estado: {shot}")
    if DRY_RUN:
        print("  DRY_RUN activo → NO se confirma. Cancelando (BTNTRN_CANCEL)...")
        try:
            page.click("#BTNTRN_CANCEL")
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:
            print(f"  (no se pudo cancelar limpio: {e})")
        return False
    print("  ⚠ CONFIRMANDO movimiento (BTNTRN_ENTER) — impacta stock...")
    with page.expect_navigation(wait_until="networkidle", timeout=15000):
        page.click("#BTNTRN_ENTER")
    ok = "alm_movimientosstock.aspx" not in page.url or "INS" not in page.url
    print("  Movimiento grabado." if ok else "  ⚠ Revisar: seguimos en el form (¿error de validación?).")
    return ok


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Registrar EGRESO de stock en Genexus (VENTA INF).")
    ap.add_argument("--test-articulo", help="ID de artículo para probar el circuito (renglón único).")
    ap.add_argument("--cantidad", default="1", help="Cantidad para el artículo de prueba.")
    ap.add_argument("--lote", default=None, help="Value del select de lote (si hay que elegirlo).")
    ap.add_argument("--detalle", default=DETALLE_DEFAULT, help="Texto del detalle del movimiento.")
    ap.add_argument("--headed", action="store_true", help="Mostrar el navegador (no headless).")
    args = ap.parse_args()

    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: faltan FEDAFAR_USER / FEDAFAR_PASS en .env"); sys.exit(1)
    if not args.test_articulo:
        print("Por ahora usá --test-articulo <ID> --cantidad <N> para probar el circuito.")
        print("(La carga automática desde ventas_inf se agrega cuando validemos el Paso 7.)")
        sys.exit(1)

    print(f"=== Ajuste de Stock (DRY_RUN={'ON' if DRY_RUN else 'OFF'}) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_context().new_page()
        try:
            if not do_login(page):                       return
            if not abrir_alta(page):                     return
            if not cargar_cabecera(page, args.detalle):  return
            cargar_renglon(page, 1, args.test_articulo, args.cantidad, args.lote)
            finalizar(page)
            print("=== Fin del circuito de prueba ===")
        finally:
            if args.headed:
                input("  [Enter para cerrar el navegador]")
            browser.close()


if __name__ == "__main__":
    main()
