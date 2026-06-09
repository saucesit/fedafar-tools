"""
sync_items.py — Descarga ítems de facturas desde Genexus → Supabase.

Para cada comprobante pendiente (saldo > 0) en cuenta_corriente:
  1. Si no tiene genexus_factura_id → lo busca scrapeando la página de
     comprobantes por cliente en Genexus (teso_comprobantesdecliente.aspx).
  2. Entra a teso_facturasview.aspx?{ID}, y extrae:
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

PYTHON_EXE   = r"C:\Users\FEDAFAR\AppData\Local\Programs\Python\Python312\python.exe"


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


# ── Paso 1: obtener el ID interno de Genexus por cliente ─────────────────────

def _seleccionar_cliente(page: Page, client_id: int) -> bool:
    """Selecciona el cliente en el autocomplete de Genexus. Devuelve True si OK."""
    selectors = [
        "input[id*='Cliente']", "input[id*='cliente']",
        "input[id*='AV6']",     "input[id*='Cli']",
    ]
    client_input = None
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                client_input = loc
                break
        except Exception:
            continue
    if not client_input:
        client_input = page.locator("input[type='text']:visible").first

    client_input.click()
    client_input.press("Control+a")
    client_input.press("Delete")
    page.wait_for_timeout(300)
    client_input.type(str(client_id), delay=150)
    page.wait_for_timeout(3000)
    client_input.press("ArrowDown")
    page.wait_for_timeout(400)

    for _ in range(25):
        val = client_input.input_value()
        if re.match(rf"^\s*{client_id}\b", val):
            client_input.press("Enter")
            page.wait_for_timeout(800)
            return True
        client_input.press("ArrowDown")
        page.wait_for_timeout(200)

    # Fallback con Tab
    client_input.click()
    client_input.press("Control+a")
    client_input.press("Delete")
    page.wait_for_timeout(200)
    client_input.type(str(client_id), delay=120)
    page.wait_for_timeout(2000)
    client_input.press("Tab")
    page.wait_for_timeout(1500)
    val = client_input.input_value()
    return bool(re.match(rf"^\s*{client_id}\b", val))


def buscar_ids_cliente(page: Page, client_id: int) -> dict:
    """
    Navega a teso_comprobantesdecliente.aspx, selecciona el cliente y scrapea
    los links a facturas individuales para obtener el ID interno de Genexus.

    Retorna dict { numero_comprobante_norm: genexus_factura_id (int) }
    """
    id_map = {}

    try:
        page.goto(f"{BASE_URL}/teso_comprobantesdecliente.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        print(f"    ERROR: timeout abriendo comprobantes cliente {client_id}.")
        return id_map

    if not _seleccionar_cliente(page, client_id):
        print(f"    ERROR: no se pudo seleccionar cliente {client_id}.")
        return id_map

    page.wait_for_timeout(2500)

    # Buscar links a teso_facturasview en la grilla cargada
    try:
        links = page.locator("a[href*='teso_facturasview']")
        n = links.count()
        print(f"    Links a facturas encontrados: {n}")

        for i in range(n):
            lnk = links.nth(i)
            href = lnk.get_attribute("href") or ""
            m = re.search(r"teso_facturasview\.aspx\?(\d+)", href)
            if not m:
                continue
            fac_id = int(m.group(1))

            # Intentar leer el número de comprobante desde la fila
            row_text = ""
            try:
                row = lnk.locator("xpath=ancestor::tr[1]")
                row_text = row.inner_text()
            except Exception:
                row_text = lnk.inner_text()

            # Patrón típico Genexus: "FAC-B 0001-00012345" o "NC-B 0001-00001234"
            comps = re.findall(r"[A-Z]{2,4}-[A-Z]\s+\d{4}-\d+", row_text)
            if comps:
                for c in comps:
                    id_map[norm_comp(c)] = fac_id
            else:
                # El link mismo puede tener el número como texto
                link_text = (lnk.inner_text() or "").strip()
                if link_text and re.search(r"\d{4}-\d+", link_text):
                    id_map[norm_comp(link_text)] = fac_id

    except Exception as e:
        print(f"    WARN al scrapear links: {e}")

    # Fallback: si no encontramos links en teso_comprobantesdecliente,
    # buscar en teso_facturasww.aspx filtrando por las primeras páginas
    if not id_map:
        print(f"    No se encontraron links en comprobantes. Buscando en lista de facturas...")
        id_map = buscar_ids_en_lista_facturas(page, client_id)

    print(f"    IDs mapeados para cliente {client_id}: {len(id_map)}")
    return id_map


def buscar_ids_en_lista_facturas(page: Page, client_id: int) -> dict:
    """
    Fallback: va a teso_facturasww.aspx y pagina buscando facturas del cliente.
    Retorna dict { numero_comprobante_norm: genexus_factura_id }
    """
    id_map = {}
    try:
        page.goto(f"{BASE_URL}/teso_facturasww.aspx", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=12000)
    except PWTimeout:
        print("    ERROR: timeout en lista de facturas.")
        return id_map

    # Intentar filtrar por código de cliente
    try:
        filter_inputs = page.locator("input[type='text']:visible")
        for i in range(min(filter_inputs.count(), 10)):
            inp = filter_inputs.nth(i)
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            iid = (inp.get_attribute("id") or "").lower()
            if any(x in iid or x in placeholder for x in ["cli", "client", "cod"]):
                inp.fill(str(client_id))
                inp.press("Enter")
                page.wait_for_load_state("networkidle", timeout=8000)
                page.wait_for_timeout(1000)
                break
    except Exception:
        pass

    # Paginar hasta 10 páginas máximo
    for pagina in range(1, 11):
        try:
            links = page.locator("a[href*='teso_facturasview']")
            n = links.count()
            if n == 0:
                break

            for i in range(n):
                lnk = links.nth(i)
                href = lnk.get_attribute("href") or ""
                m = re.search(r"teso_facturasview\.aspx\?(\d+)", href)
                if not m:
                    continue
                fac_id = int(m.group(1))

                row_text = ""
                try:
                    row = lnk.locator("xpath=ancestor::tr[1]")
                    row_text = row.inner_text()
                except Exception:
                    row_text = lnk.inner_text()

                # Solo incluir si el client_id aparece en la fila
                if str(client_id) not in row_text:
                    continue

                comps = re.findall(r"[A-Z]{2,4}-[A-Z]\s+\d{4}-\d+", row_text)
                for c in comps:
                    id_map[norm_comp(c)] = fac_id

            # Siguiente página
            siguiente = page.locator("a:has-text('Siguiente'), a:has-text('>'), a[id*='Next'], a[id*='Sig']").first
            if siguiente.count() == 0 or not siguiente.is_visible():
                break
            siguiente.click()
            page.wait_for_load_state("networkidle", timeout=8000)
            page.wait_for_timeout(800)

        except Exception as e:
            print(f"    WARN paginando facturas (página {pagina}): {e}")
            break

    return id_map


# ── Paso 2: scrapear ítems y totales de una factura ───────────────────────────

def scrape_factura(page: Page, factura_id: int) -> tuple:
    """
    Entra a teso_facturasview.aspx?{ID}, y extrae:
      - totales (dict): neto_exento, neto_gravado, neto, iva, total
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

        # Leer todos los pares etiqueta/valor de la página
        # Genexus suele renderizarlos como <td>Etiqueta</td><td>Valor</td>
        rows = page.locator("table tr")
        for i in range(rows.count()):
            try:
                cells = rows.nth(i).locator("td")
                if cells.count() < 2:
                    continue
                label = (cells.nth(0).inner_text() or "").strip().lower()
                value = (cells.nth(1).inner_text() or "").strip()

                if "neto exento"  in label: totales["neto_exento"]  = ar_num(value)
                elif "neto gravado" in label: totales["neto_gravado"] = ar_num(value)
                elif label == "neto":         totales["neto"]         = ar_num(value)
                elif "impuesto"   in label: totales["impuestos"]    = ar_num(value)
                elif label in ("iva", "i.v.a."): totales["iva"]     = ar_num(value)
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

        # Leer filas del tbody
        filas = items_table.locator("tbody tr")
        for r in range(filas.count()):
            cells = filas.nth(r).locator("td")
            if cells.count() == 0:
                continue
            articulo = celda(cells, "articulo")
            if not articulo:
                continue   # fila vacía o de separador

            items.append({
                "item_num":    int(celda(cells, "item_num") or 0),
                "articulo":    articulo,
                "laboratorio": celda(cells, "laboratorio"),
                "cantidad":    ar_num(celda(cells, "cantidad")),
                "precio":      ar_num(celda(cells, "precio")),
                "iva_label":   celda(cells, "iva_label"),
                "precio_total":ar_num(celda(cells, "precio_total")),
                "subtotal":    ar_num(celda(cells, "subtotal")),
                "impuesto":    ar_num(celda(cells, "impuesto")),
                "linea":       ar_num(celda(cells, "linea")),
            })

    except Exception as e:
        print(f"    WARN ítems: {e}")

    return items, totales


# ── Paso 3: guardar en Supabase ───────────────────────────────────────────────

def guardar(sb, factura_id: int, gx_client_id: int,
            comprobante: str, items: list, totales: dict):
    now = datetime.now().isoformat()

    # Limpiar ítems anteriores de esta factura
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
        print(f"    Sin ítems para guardar.")

    # Actualizar cuenta_corriente con el ID interno y totales
    update = {"genexus_factura_id": factura_id}
    if totales.get("iva"):   update["iva_total"]      = totales["iva"]
    if totales.get("total"): update["total_factura"]  = totales["total"]

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
        # Excluir los que ya tienen ítems
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

    # Agrupar por cliente para minimizar navegaciones
    por_cliente = {}
    for c in pendientes:
        gx = c["genexus_client_id"]
        por_cliente.setdefault(gx, []).append(c)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page    = context.new_page()

        if not do_login(page):
            browser.close()
            return

        total_ok = 0

        for gx_id, comps in por_cliente.items():
            print(f"\n  Cliente {gx_id} — {len(comps)} comprobante(s)")

            # Separar los que ya tienen ID interno de los que no
            sin_id     = [c for c in comps if not c.get("genexus_factura_id")]
            con_id     = [c for c in comps if c.get("genexus_factura_id")]

            # Buscar IDs para los que no los tienen
            if sin_id:
                id_map = buscar_ids_cliente(page, gx_id)

                for c in sin_id:
                    clave = norm_comp(c["comprobante"])
                    fac_id = id_map.get(clave)
                    if fac_id:
                        c["genexus_factura_id"] = fac_id
                        con_id.append(c)
                    else:
                        print(f"    [SKIP] No se encontró ID para: {c['comprobante']}")

            # Descargar ítems para cada factura con ID conocido
            for c in con_id:
                fac_id = c["genexus_factura_id"]
                print(f"    Factura {fac_id} — {c['comprobante']}")
                items, totales = scrape_factura(page, fac_id)
                guardar(sb, fac_id, gx_id, c["comprobante"], items, totales)
                total_ok += 1

        browser.close()

    print(f"\n[sync_items] Completado: {total_ok} facturas procesadas.")


if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        sys.exit(1)
    force = "--force" in sys.argv
    sync_items(force=force)
