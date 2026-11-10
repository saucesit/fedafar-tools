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
    python sync_items.py                # solo los que no tienen ítems aún
    python sync_items.py --retruncadas  # repara las que pueden haber quedado
                                        # cortadas (ítems múltiplo exacto de 15)
    python sync_items.py --force        # re-descarga las 302, aunque ya estén
    python sync_items.py --verbose      # logging extra

    python sync_items.py --solo-limpiar            # informa que borraria
    python sync_items.py --solo-limpiar --limpiar  # borra el detalle de las
                                                   # facturas ya pagadas

Nota: comprobante_items guarda TEXTO Y NUMEROS, nunca PDFs ni imagenes. El PDF
se genera al vuelo en api_app._build_comprobante_pdf() cada vez que alguien lo
pide, asi la base no se infla.
"""

import os
import re
import sys
from datetime import datetime
import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

load_dotenv()

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
BASE_URL     = "http://192.168.0.35/fedafar"
FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# La grilla de Detalle de la factura muestra 15 renglones por página y se avanza
# con el link "Sig". El script leía SOLO la primera página, así que toda factura
# de más de 15 renglones quedaba truncada en silencio: se guardaban 15 ítems y
# un total que no cerraba. Se detectó por la distribución de tamaños (baja suave
# de 1 a 14 renglones, salto a 88 facturas con exactamente 15, y cero por
# encima). Caso verificado: la factura 162714 tiene 27 renglones y guardaba 15.
# Renglones que muestra una pagina de la grilla de Detalle. Un corte por el bug
# de paginacion siempre dejaba un multiplo exacto de este numero, asi que sirve
# para detectar las facturas sospechosas de haber quedado truncadas.
PAGINA_DETALLE = 15

MAX_PAGINAS_DETALLE = 30   # 30 × 15 = hasta 450 renglones por factura

# Logging extra. Se activa con --verbose.
VERBOSE = "--verbose" in sys.argv


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

def _exportar_lista_facturas(page: Page) -> str:
    """Descarga el Excel con la lista COMPLETA de facturas. Devuelve la ruta.

    Ojo: hay que limpiar el filtro antes de exportar. El filtro de la grilla
    queda guardado del lado del servidor entre sesiones, y si quedó puesto el
    Excel sale filtrado y faltan facturas (el mismo vicio que ya nos mordió con
    el reporte de stock).
    """
    page.goto(f"{BASE_URL}/teso_facturasww.aspx", timeout=20000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    page.wait_for_timeout(1000)

    try:
        residual = page.locator("#vFILTERFULLTEXT").input_value()
        if residual:
            print(f"  Limpiando filtro residual: {residual!r}")
            page.fill("#vFILTERFULLTEXT", "")
            page.locator("#vFILTERFULLTEXT").press("Enter")
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except PWTimeout:
                pass
            page.wait_for_timeout(1200)
    except Exception as e:
        print(f"  WARN no pude limpiar el filtro: {e}")

    destino = os.path.join(BASE_DIR, "facturas_export.xlsx")
    with page.expect_download(timeout=120000) as di:
        page.click("#BTNEXPORT")
    di.value.save_as(destino)
    print(f"  Excel de facturas descargado ({os.path.getsize(destino)//1024} KB).")
    return destino


def construir_mapa_desde_export(ruta: str) -> dict:
    """Arma { client_id: { comprobante_norm: fac_id } } desde el Excel exportado.

    Columnas del export: ID | Tipo | Letra | Sucursal | Número | Fecha |
    Cliente | Total | Saldo, con el encabezado en la 3ra fila.

    El ID es el id interno de Genexus, el mismo que necesita
    teso_facturasview.aspx?{ID}. Sucursal y Número vienen SIN ceros a la
    izquierda (6 y 13096), mientras que cuenta_corriente los guarda con
    relleno ('FAC A 00006-00013096'), así que hay que rellenar a 5 y 8.
    """
    df = pd.read_excel(ruta, skiprows=2)
    df.columns = [str(c).strip() for c in df.columns]
    # 'Número' con tilde complica el acceso por atributo en itertuples.
    df = df.rename(columns={"Número": "Numero"})

    faltan = {"ID", "Tipo", "Letra", "Sucursal", "Numero", "Cliente"} - set(df.columns)
    if faltan:
        print(f"  ERROR: al export le faltan columnas {faltan}. Columnas: {list(df.columns)}")
        return {}

    def _ent(v) -> str:
        """'6' / '6.0' / ' 6 ' → '6' (el export trae algunos como float)."""
        return str(v).strip().split(".")[0]

    mapa: dict = {}
    for r in df.itertuples(index=False):
        try:
            m = re.match(r"\s*(\d+)", str(r.Cliente))
            if not m:
                continue
            cli = int(m.group(1))
            comp = norm_comp(f"{str(r.Tipo).strip()} {str(r.Letra).strip()} "
                             f"{_ent(r.Sucursal).zfill(5)}-{_ent(r.Numero).zfill(8)}")
            mapa.setdefault(cli, {})[comp] = int(r.ID)
        except Exception:
            continue

    total = sum(len(v) for v in mapa.values())
    print(f"  Mapa armado: {total} facturas de {len(mapa)} clientes.")
    return mapa


def scan_all_facturas(page: Page, por_cliente: dict) -> dict:
    """{ client_id: { comprobante_norm: fac_id } } para los clientes pedidos.

    Antes esto recorría la grilla de teso_facturasww.aspx filtrando por cliente
    y paginando. No funcionaba: verificado en vivo, el filtro vFILTERFULLTEXT
    NO se aplicaba (tres búsquedas distintas devolvían las mismas 15 filas) y
    la grilla abría en la página que había quedado de la sesión anterior
    ('Página 4 de 4'), así que el escaneo leía páginas al azar. La cobertura
    que lograba era accidental y cambiaba en cada corrida (215/221/217), y
    clientes enteros quedaban en cero: Fleming San Luis (100004) mapeaba 0 de 9.

    Ahora se baja el Excel completo de una sola vez y el mapa se arma offline.
    Es determinístico y no depende de clics. Medido: 302 de 302 pendientes
    mapeados (100%), contra 217 parciales del método anterior.
    """
    ruta = _exportar_lista_facturas(page)
    mapa = construir_mapa_desde_export(ruta)

    # Reportar por cliente qué se encontró, igual que antes.
    salida = {}
    for client_id, comps in por_cliente.items():
        comp_set = {norm_comp(c["comprobante"]) for c in comps
                    if not c.get("genexus_factura_id")}
        if not comp_set:
            continue
        del_cliente = mapa.get(client_id, {})
        hallados = comp_set & set(del_cliente)
        print(f"  Cliente {client_id}: {len(hallados)}/{len(comp_set)} encontrados")
        if del_cliente:
            salida[client_id] = del_cliente
    return salida


def _encontrar_tabla_items(page: Page):
    """Busca la tabla de renglones dentro de la solapa Detalle."""
    tables = page.locator("table")
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
            return t
    return None


def _leer_columnas_items(items_table) -> dict:
    """Mapea nombre de columna → índice, leyendo el encabezado de la grilla."""
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
    return col


def _leer_pagina_items(items_table, col: dict) -> list:
    """Lee los renglones de la página de grilla que está visible ahora."""
    def celda(cells, campo):
        idx = col.get(campo)
        if idx is None: return ""
        try: return (cells.nth(idx).inner_text() or "").strip()
        except Exception: return ""

    salida = []
    filas = items_table.locator("tbody tr")
    for r in range(filas.count()):
        cells = filas.nth(r).locator("td")
        if cells.count() == 0:
            continue
        articulo = celda(cells, "articulo")
        if not articulo:
            continue
        salida.append({
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
    return salida


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

    # ── Solapa Detalle: ítems (TODAS las páginas) ─────────────────────────────
    try:
        tab = page.get_by_text("Detalle", exact=True).first
        tab.click()
        page.wait_for_timeout(1000)

        col    = None
        vistos = set()

        for nro_pagina in range(1, MAX_PAGINAS_DETALLE + 1):
            # La tabla se vuelve a buscar en cada página: el "Sig" hace un
            # postback que reemplaza el DOM y los locators viejos quedan
            # apuntando a nodos que ya no existen.
            items_table = _encontrar_tabla_items(page)
            if items_table is None:
                if nro_pagina == 1:
                    print(f"    WARN: tabla de ítems no encontrada en factura {factura_id}.")
                break

            if col is None:
                col = _leer_columnas_items(items_table)

            agregados = 0
            for it in _leer_pagina_items(items_table, col):
                # Dedup por número correlativo de renglón (1, 2, 3...). Si la
                # grilla no lo trae, cae a artículo+cantidad+precio.
                clave = it["item_num"] or (it["articulo"], it["cantidad"], it["precio"])
                if clave in vistos:
                    continue
                vistos.add(clave)
                items.append(it)
                agregados += 1

            # Si la página no aportó nada nuevo, ya estábamos en la última.
            if agregados == 0:
                break

            sig = page.get_by_role("link", name="Sig", exact=True)
            if sig.count() == 0:
                break
            try:
                sig.first.click()
                page.wait_for_timeout(1600)
            except Exception:
                break
        else:
            print(f"    WARN: factura {factura_id} llegó al tope de "
                  f"{MAX_PAGINAS_DETALLE} páginas de detalle.")

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

def _traer_todo(sb, tabla: str, select: str, filtro=None) -> list:
    """Trae TODAS las filas, paginando de a 1000.

    Supabase corta en 1000 filas por consulta. comprobante_items ya tiene casi
    5000, así que la consulta sin paginar solo veía las primeras 1000: el
    script creía que miles de facturas no tenían ítems y las volvía a bajar
    todas las noches al pasar.
    """
    out, off = [], 0
    while True:
        q = sb.table(tabla).select(select)
        if filtro:
            q = filtro(q)
        d = q.range(off, off + 999).execute().data or []
        out += d
        if len(d) < 1000:
            return out
        off += 1000


def limpiar_items_pagados(sb, aplicar: bool = False) -> int:
    """Borra el detalle de las facturas que ya no están pendientes de pago.

    comprobante_items es solo un caché para que la app pueda armar el PDF: la
    factura de verdad vive en Genexus. Una vez que la farmacia pagó y se pasó
    el recibo, el comprobante desaparece de la cuenta corriente y su detalle no
    se puede descargar más desde la app, así que guardarlo es puro peso.

    Medido antes de implementar esto: 3379 de 4852 renglones (70% de la tabla)
    eran de facturas ya pagadas.

    Con aplicar=False solo informa qué borraría (es el default a propósito:
    borrar es irreversible).
    """
    pend = _traer_todo(sb, "cuenta_corriente", "genexus_factura_id",
                       lambda q: q.gt("saldo", 0))
    vivas = {r["genexus_factura_id"] for r in pend if r.get("genexus_factura_id")}

    filas = _traer_todo(sb, "comprobante_items", "genexus_factura_id")
    por_factura: dict = {}
    for r in filas:
        fid = r["genexus_factura_id"]
        por_factura[fid] = por_factura.get(fid, 0) + 1

    muertas = [fid for fid in por_factura if fid not in vivas]
    renglones = sum(por_factura[f] for f in muertas)

    if not muertas:
        print("[limpieza] No hay detalle de facturas pagadas para borrar.")
        return 0

    if not aplicar:
        print(f"[limpieza] Se borrarían {renglones} renglones de {len(muertas)} "
              f"facturas ya pagadas. Usá --limpiar para aplicarlo.")
        return 0

    borrados = 0
    for i in range(0, len(muertas), 100):   # de a 100 ids por request
        lote = muertas[i:i + 100]
        try:
            sb.table("comprobante_items").delete() \
              .in_("genexus_factura_id", lote).execute()
            borrados += sum(por_factura[f] for f in lote)
        except Exception as e:
            print(f"  WARN borrando lote: {e}")
    print(f"[limpieza] Borrados {borrados} renglones de {len(muertas)} facturas pagadas.")
    return borrados


def _verificar_ids(sb, todos: list) -> tuple[set, dict]:
    """Corrige en Supabase los genexus_factura_id que no coinciden con Genexus.

    Devuelve (claves corregidas, mapa del export) para que el llamador fuerce
    el re-escaneo de esas facturas y reutilice el mapa sin bajarlo de nuevo.

    La corrección se escribe en el momento, antes de bajar ningún ítem: así, si
    la corrida se interrumpe, la factura queda apuntando a un ID sin detalle
    (la app esconde el botón) en vez de seguir mostrando el detalle ajeno.
    """
    con_id = [c for c in todos if c.get("genexus_factura_id")]
    if not con_id:
        return set(), {}

    por_cliente: dict = {}
    for c in todos:
        por_cliente.setdefault(c["genexus_client_id"], []).append(c)

    print(f"\n[Paso 0] Verificando el ID interno de {len(con_id)} comprobantes "
          "contra el export de Genexus...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        page    = context.new_page()
        if not do_login(page):
            browser.close()
            print("  No se pudo loguear: se saltea la verificación.")
            return set(), {}
        try:
            # El mapa COMPLETO, no scan_all_facturas(): esa función recorta la
            # salida a los clientes que tienen comprobantes sin ID, y acá
            # justamente queremos revisar los que ya lo tienen.
            mapa = construir_mapa_desde_export(_exportar_lista_facturas(page))
        finally:
            browser.close()

    corregidas, sin_mapear = set(), 0
    for c in con_id:
        cli_id = c["genexus_client_id"]
        clave  = norm_comp(c["comprobante"])
        real   = mapa.get(cli_id, {}).get(clave)
        if not real:
            sin_mapear += 1
            continue
        if str(real) == str(c["genexus_factura_id"]):
            continue
        print(f"  [CORRIGE] {c['comprobante']} (cliente {cli_id}): "
              f"ID {c['genexus_factura_id']} -> {real}")
        sb.table("cuenta_corriente") \
          .update({"genexus_factura_id": real}) \
          .eq("genexus_client_id", cli_id) \
          .eq("comprobante", c["comprobante"]) \
          .execute()
        c["genexus_factura_id"] = real
        corregidas.add((cli_id, clave))

    print(f"  IDs corregidos: {len(corregidas)} | "
          f"no estaban en el export: {sin_mapear} | "
          f"correctos: {len(con_id) - len(corregidas) - sin_mapear}")
    return corregidas, mapa


def sync_items(force: bool = False, retruncadas: bool = False,
               limpiar: bool = False):
    sb = get_sb()

    # Obtener comprobantes pendientes
    todos = _traer_todo(sb, "cuenta_corriente",
                        "genexus_client_id,comprobante,genexus_factura_id",
                        lambda q: q.gt("saldo", 0))

    filas_items = _traer_todo(sb, "comprobante_items", "genexus_factura_id")
    cuenta_items: dict = {}
    for r in filas_items:
        k = str(r["genexus_factura_id"])
        cuenta_items[k] = cuenta_items.get(k, 0) + 1
    ya_ids = set(cuenta_items)

    # ── Verificar el ID interno de TODOS los pendientes ──────────────────────
    # No alcanza con buscarle ID a los que no lo tienen: un ID ya guardado puede
    # estar MAL. Las corridas viejas leían la grilla de facturas y a veces se
    # llevaban la fila equivocada, así que dos comprobantes distintos del mismo
    # cliente podían quedar apuntando al mismo ID — y la farmacia terminaba
    # viendo el detalle de otra factura. El export de Genexus es la verdad.
    corregidas, mapa_export = _verificar_ids(sb, todos)

    if retruncadas:
        # Modo reparación: re-leer solo las facturas que pueden haber quedado
        # cortadas por el bug de paginación del detalle. La grilla trae 15
        # renglones por página, así que un corte siempre deja un múltiplo
        # exacto de 15. Una factura con 15 ítems justos es ambigua (puede estar
        # completa o truncada) y no hay forma de saberlo sin releerla; releerla
        # es inofensivo porque el guardado reemplaza los renglones.
        # Mucho más barato que --force: ~87 facturas en lugar de 302.
        pendientes = [
            c for c in todos
            if c.get("genexus_factura_id")
            and cuenta_items.get(str(c["genexus_factura_id"]), 0) > 0
            and cuenta_items[str(c["genexus_factura_id"])] % PAGINA_DETALLE == 0
        ]
        print(f"[sync_items] Modo --retruncadas: {len(pendientes)} facturas con "
              f"un múltiplo exacto de {PAGINA_DETALLE} renglones (posible corte).")
    elif force:
        pendientes = todos
    else:
        pendientes = [
            c for c in todos
            if not c.get("genexus_factura_id") or str(c["genexus_factura_id"]) not in ya_ids
        ]

    # Las de ID corregido van siempre: su detalle nuevo todavía no está bajado.
    if corregidas:
        ya = {(c["genexus_client_id"], norm_comp(c["comprobante"])) for c in pendientes}
        extra = [c for c in todos
                 if (c["genexus_client_id"], norm_comp(c["comprobante"])) in corregidas
                 and (c["genexus_client_id"], norm_comp(c["comprobante"])) not in ya]
        if extra:
            print(f"[sync_items] + {len(extra)} con ID corregido, se re-bajan.")
            pendientes += extra

    if not pendientes:
        print("[sync_items] Todo actualizado. Usá --force para re-sincronizar "
              "o --retruncadas para reparar las que puedan estar cortadas.")
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
        context = browser.new_context(accept_downloads=True)
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

            # El export ya se bajó en el Paso 0: no se baja de nuevo.
            mapa = mapa_export or scan_all_facturas(page, por_cliente_sin)

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

    # Sacar el detalle de las que ya se pagaron: no se pueden descargar más.
    print()
    limpiar_items_pagados(sb, aplicar=limpiar)


if __name__ == "__main__":
    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
        sys.exit(1)

    # --solo-limpiar no toca Genexus: solo purga el detalle de las pagadas.
    if "--solo-limpiar" in sys.argv:
        limpiar_items_pagados(get_sb(), aplicar="--limpiar" in sys.argv)
        sys.exit(0)

    sync_items(force="--force" in sys.argv,
               retruncadas="--retruncadas" in sys.argv,
               limpiar="--limpiar" in sys.argv)
