"""
sync_items.py — Descarga ítems de facturas desde Genexus → Supabase.

Estrategia:
  1. Escanea teso_facturasww.aspx con 50 filas/página para construir un mapa
     global  {client_id: {comprobante_norm: genexus_factura_id}}.
  2. Para cada comprobante pendiente en Supabase (saldo > 0), busca su ID en
     ese mapa y scrape la vista de factura (teso_facturasview.aspx?{ID},):
       - Solapa General : neto, IVA, total
       - Solapa Detalle : renglones (artículo, cantidad, precio, etc.)
  3. Guarda en comprobante_items y actualiza cuenta_corriente.

Uso:
    python sync_items.py            # solo procesa los que no tienen ítems aún
    python sync_items.py --force    # re-descarga todos aunque ya tengan ítems
"""

import os
import re
import sys
from datetime import datetime
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

MAX_PAGES_SCAN = 40   # 40 páginas × 50 filas = hasta 2000 facturas escaneadas


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_sb():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def ar_num(s) -> float:
    """Convierte formato argentino '2.030,42' → float 2030.42"""
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except Exception:
        return 0.0


def norm_comp(s: str) -> str:
    """Normaliza un número de comprobante para comparar: quita espacios extras."""
    return re.sub(r"\s+", " ", str(s).strip().upper())


# ── Login ──────────────────────────────────────────────────────────────────────

def do_login(page: Page) -> bool:
    try:
        page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print("  ERROR: No se pudo conectar al servidor Genexus.")
        return False

    page.fill("#vSECUSERNAME",     FEDAFAR_USER)
    page.fill("#vSECUSERPASSWORD", FEDAFAR_PASS)
    page.click("#BTNENTER")

    try:
        page.wait_for_function(
            "() => !window.location.href.includes('seclogin')", timeout=10000
        )
        print("  Login OK.")
        return True
    except PWTimeout:
        print("  ERROR: Login fallido. Verificar credenciales.")
        return False


# ── Paso 1: escanear lista de facturas → mapa global ─────────────────────────

def _leer_filas_facturas(page: Page, client_id: int, comp_set: set) -> dict:
    """
    Lee todas las páginas del listado de facturas filtrado por client_id.
    Retorna { comp_norm: fac_id } para ese cliente.
    Usa paginación por número de página en la barra '.PaginationBar'.
    """
    id_map  = {}
    hallados = set()

    for pagina in range(1, 30):   # máximo 30 páginas por cliente
        links = page.locator("a[href*='teso_facturasview']")
        n = links.count()
        if n == 0:
            break

        for i in range(n):
            try:
                lnk   = links.nth(i)
                href  = lnk.get_attribute("href") or ""
                m     = re.search(r"teso_facturasview\.aspx\?(\d+)", href)
                if not m:
                    continue
                fac_id = int(m.group(1))

                row    = lnk.locator("xpath=ancestor::tr[1]")
                celdas = row.locator("td")
                if celdas.count() < 11:
                    continue

                # Verificar que pertenece al cliente correcto
                cli_str = celdas.nth(10).inner_text().strip()
                try:
                    if int(cli_str) != client_id:
                        continue
                except ValueError:
                    continue

                tipo    = celdas.nth(5).inner_text().strip()
                letra   = celdas.nth(6).inner_text().strip()
                pto_vta = celdas.nth(7).inner_text().strip()
                numero  = celdas.nth(8).inner_text().strip()
                comp    = norm_comp(f"{tipo} {letra} {pto_vta}-{numero}")

                id_map[comp] = fac_id
                if comp in comp_set:
                    hallados.add(comp)

            except Exception:
                continue

        # ¿Ya encontramos todo lo que buscamos?
        if comp_set and hallados >= comp_set:
            break

        # Siguiente página: Genexus muestra números de página en .PaginationBar
        sig_pag = pagina + 1

        # Esperar que desaparezca el spinner/mask de Genexus antes de clickear
        try:
            page.wait_for_selector(".gx-mask", state="hidden", timeout=5000)
        except Exception:
            pass  # si no hay mask, continuar igual

        next_link = page.locator(f".PaginationBar a:has-text('{sig_pag}')").first
        if next_link.count() == 0 or not next_link.is_visible():
            break

        # Usar JS click para bypassar cualquier overlay residual
        page.evaluate(
            f"Array.from(document.querySelectorAll('.PaginationBar a'))"
            f".find(a => a.textContent.trim() === '{sig_pag}')?.click()"
        )
        page.wait_for_load_state("networkidle", timeout=8000)
        page.wait_for_timeout(600)

    return id_map


def scan_all_facturas(page: Page, por_cliente: dict) -> dict:
    """
    Escanea teso_facturasww.aspx filtrando por código de cliente (vFILTERFULLTEXT).
    Retorna { client_id (int): { comprobante_norm (str): genexus_factura_id (int) } }

    Estructura de celdas por fila (confirmada con debug_genexus.py):
        td[3]  = ID interno Genexus
        td[5]  = tipo comprobante  (FAC, NCRE, …)
        td[6]  = letra             (A, B)
        td[7]  = punto de venta    (00006)
        td[8]  = número            (00011529)
        td[10] = código de cliente (1248, 540, …)
    """
    mapping = {}

    try:
        page.goto(f"{BASE_URL}/teso_facturasww.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=12000)
        page.wait_for_timeout(800)
    except PWTimeout:
        print("  ERROR: timeout abriendo lista de facturas.")
        return mapping

    filtro = page.locator("#vFILTERFULLTEXT")
    if filtro.count() == 0:
        print("  ERROR: no se encontró el input de filtro (vFILTERFULLTEXT).")
        return mapping

    for client_id, comps in por_cliente.items():
        comp_set = {norm_comp(c["comprobante"]) for c in comps
                    if not c.get("genexus_factura_id")}
        if not comp_set:
            continue

        print(f"  Cliente {client_id}: buscando {len(comp_set)} comprobantes...")

        # Filtrar por código de cliente
        filtro.fill(str(client_id))
        filtro.press("Enter")
        page.wait_for_load_state("networkidle", timeout=10000)
        page.wait_for_timeout(600)

        client_map = _leer_filas_facturas(page, client_id, comp_set)
        encontrados = len([c for c in comp_set if c in client_map])
        print(f"    {encontrados}/{len(comp_set)} encontrados ({len(client_map)} facturas mapeadas)")

        if client_map:
            mapping[client_id] = client_map

    total = sum(len(v) for v in mapping.values())
    print(f"  Escaneo terminado: {total} facturas de {len(mapping)} clientes.")
    return mapping


# ── Paso 2: scrapear ítems y totales de una factura ───────────────────────────

def scrape_factura(page: Page, factura_id: int) -> tuple:
    """
    Entra a teso_facturasview.aspx?{ID}, y extrae:
      - totales (dict): neto, iva, total
      - items  (list of dict): renglones de la factura

    Retorna (items, totales). Ambos pueden ser vacíos si hay error.
    """
    url = f"{BASE_URL}/teso_facturasview.aspx?{factura_id},"
    try:
        page.goto(url, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=12000)
    except PWTimeout:
        print(f"    ERROR: timeout cargando factura {factura_id}.")
        return [], {}

    totales = {}
    items   = []

    # ── Solapa General: totales ────────────────────────────────────────────────
    try:
        tab = page.get_by_text("General", exact=True).first
        tab.click()
        page.wait_for_timeout(800)

        rows = page.locator("table tr")
        for i in range(rows.count()):
            try:
                cells = rows.nth(i).locator("td")
                if cells.count() < 2:
                    continue
                label = (cells.nth(0).inner_text() or "").strip().lower()
                value = (cells.nth(1).inner_text() or "").strip()

                if "neto exento"    in label: totales["neto_exento"]  = ar_num(value)
                elif "neto gravado" in label: totales["neto_gravado"] = ar_num(value)
                elif label == "neto":         totales["neto"]         = ar_num(value)
                elif "impuesto"     in label: totales["impuestos"]    = ar_num(value)
                elif label in ("iva", "i.v.a."): totales["iva"]      = ar_num(value)
                elif label == "total":        totales["total"]        = ar_num(value)
            except Exception:
                continue

    except Exception as e:
        print(f"    WARN totales: {e}")

    # ── Solapa Detalle: ítems ─────────────────────────────────────────────────
    try:
        tab = page.get_by_text("Detalle", exact=True).first
        tab.click()
        page.wait_for_timeout(1000)

        # Encontrar la tabla que contiene columna "Artículo" o "Cantidad"
        tables = page.locator("table")
        items_table = None
        for i in range(tables.count()):
            t = tables.nth(i)
            try:
                hdr = (t.locator("thead").inner_text() or "").lower()
            except Exception:
                hdr = ""
            try:
                fila1 = (t.locator("tr").first.inner_text() or "").lower()
            except Exception:
                fila1 = ""
            texto = hdr + fila1
            if "artículo" in texto or "articulo" in texto or ("cantidad" in texto and "precio" in texto):
                items_table = t
                break

        if items_table is None:
            print(f"    WARN: tabla de ítems no encontrada en factura {factura_id}.")
            return items, totales

        # Leer encabezados
        col = {}
        try:
            ths = items_table.locator("thead tr th")
            if ths.count() == 0:
                ths = items_table.locator("tr").first.locator("td, th")
            for j in range(ths.count()):
                h = (ths.nth(j).inner_text() or "").strip().lower()
                if "artículo"   in h or "articulo"   in h: col["articulo"]    = j
                elif "laboratorio" in h:                    col["laboratorio"]  = j
                elif "cantidad"    in h and "devuelta" not in h: col["cantidad"] = j
                elif "precio total" in h:                   col["precio_total"] = j
                elif h == "precio":                         col["precio"]       = j
                elif "iva" in h or "i.v.a" in h:           col["iva_label"]    = j
                elif "subtotal"    in h:                    col["subtotal"]     = j
                elif "impuesto"    in h:                    col["impuesto"]     = j
                elif h in ("línea", "linea"):               col["linea"]        = j
                elif h in ("item", "#"):                    col["item_num"]     = j
        except Exception as e:
            print(f"    WARN leyendo encabezados: {e}")

        def celda(cells, campo):
            idx = col.get(campo)
            if idx is None: return ""
            try: return (cells.nth(idx).inner_text() or "").strip()
            except: return ""

        filas = items_table.locator("tbody tr")
        for r in range(filas.count()):
            cells = filas.nth(r).locator("td")
            if cells.count() == 0:
                continue
            articulo = celda(cells, "articulo")
            if not articulo:
                continue

            items.append({
                "item_num":     int(celda(cells, "item_num") or 0),
                "articulo":     articulo,
                "laboratorio":  celda(cells, "laboratorio"),
                "cantidad":     ar_num(celda(cells, "cantidad")),
                "precio":       ar_num(celda(cells, "precio")),
                "iva_label":    celda(cells, "iva_label"),
                "precio_total": ar_num(celda(cells, "precio_total")),
                "subtotal":     ar_num(celda(cells, "subtotal")),
                "impuesto":     ar_num(celda(cells, "impuesto")),
                "linea":        ar_num(celda(cells, "linea")),
            })

    except Exception as e:
        print(f"    WARN ítems: {e}")

    return items, totales


# ── Paso 3: guardar en Supabase ───────────────────────────────────────────────

def guardar(sb, factura_id: int, gx_client_id: int,
            comprobante: str, items: list, totales: dict):
    now = datetime.now().isoformat()

    sb.table("comprobante_items").delete().eq("genexus_factura_id", factura_id).execute()

    if items:
        records = [{
            "genexus_factura_id": factura_id,
            "genexus_client_id":  gx_client_id,
            "comprobante":        comprobante,
            "item_num":           it["item_num"],
            "articulo":           it["articulo"],
            "laboratorio":        it["laboratorio"],
            "cantidad":           it["cantidad"],
            "precio":             it["precio"],
            "iva_label":          it["iva_label"],
            "precio_total":       it["precio_total"],
            "subtotal":           it["subtotal"],
            "impuesto":           it["impuesto"],
            "linea":              it["linea"],
            "actualizado_en":     now,
        } for it in items]
        sb.table("comprobante_items").insert(records).execute()
        print(f"    {len(records)} ítems guardados.")
    else:
        print(f"    Sin ítems encontrados.")

    update = {"genexus_factura_id": factura_id}
    if totales.get("iva"):    update["iva_total"]     = totales["iva"]
    if totales.get("total"):  update["total_factura"] = totales["total"]

    sb.table("cuenta_corriente") \
      .update(update) \
      .eq("genexus_client_id", gx_client_id) \
      .eq("comprobante", comprobante) \
      .execute()


# ── Main ───────────────────────────────────────────────────────────────────────

def sync_items(force: bool = False):
    sb = get_sb()

    # Obtener comprobantes pendientes
    res = sb.table("cuenta_corriente") \
            .select("genexus_client_id,comprobante,genexus_factura_id") \
            .gt("saldo", 0) \
            .execute()
    todos = res.data or []

    if not force:
        ya_ids = {
            str(r["genexus_factura_id"])
            for r in (sb.table("comprobante_items").select("genexus_factura_id").execute().data or [])
        }
        pendientes = [
            c for c in todos
            if not c.get("genexus_factura_id") or str(c["genexus_factura_id"]) not in ya_ids
        ]
    else:
        pendientes = todos

    if not pendientes:
        print("[sync_items] Todo actualizado. Usá --force para re-sincronizar.")
        return

    print(f"[sync_items] Comprobantes a procesar: {len(pendientes)}")

    # Comprobantes que ya tienen ID interno (no necesitan escaneo)
    sin_id = [c for c in pendientes if not c.get("genexus_factura_id")]
    con_id = [c for c in pendientes if c.get("genexus_factura_id")]

    # Agrupar por cliente
    por_cliente: dict[int, list] = {}
    for c in pendientes:
        por_cliente.setdefault(c["genexus_client_id"], []).append(c)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        if not do_login(page):
            browser.close()
            return

        # ── Escanear lista de facturas para encontrar IDs internos ───────────
        if sin_id:
            n_sin = len(sin_id)
            print(f"\n[Paso 1] Buscando ID interno para {n_sin} comprobantes (por cliente)...")

            # Agrupar solo los sin_id por cliente
            por_cliente_sin: dict[int, list] = {}
            for c in sin_id:
                por_cliente_sin.setdefault(c["genexus_client_id"], []).append(c)

            mapa = scan_all_facturas(page, por_cliente_sin)

            # Asignar IDs encontrados
            for c in sin_id:
                clave  = norm_comp(c["comprobante"])
                cli_id = c["genexus_client_id"]
                fac_id = mapa.get(cli_id, {}).get(clave)
                if fac_id:
                    c["genexus_factura_id"] = fac_id
                    con_id.append(c)
                else:
                    print(f"  [SKIP] Sin ID interno para: {c['comprobante']} (cliente {cli_id})")
        else:
            print("[Paso 1] Todos los comprobantes ya tienen ID interno. Salteando escaneo.")

        # ── Descargar ítems para cada factura ────────────────────────────────
        print(f"\n[Paso 2] Descargando ítems de {len(con_id)} facturas...")
        total_ok = 0
        for c in con_id:
            fac_id = c["genexus_factura_id"]
            print(f"  Factura {fac_id} — {c['comprobante']} (cliente {c['genexus_client_id']})")
            items, totales = scrape_factura(page, fac_id)
            guardar(sb, fac_id, c["genexus_client_id"], c["comprobante"], items, totales)
            total_ok += 1

        browser.close()

    print(f"\n[sync_items] Completado: {total_ok} facturas procesadas.")


if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        sys.exit(1)
    force = "--force" in sys.argv
    sync_items(force=force)
