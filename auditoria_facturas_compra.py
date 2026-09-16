#!/usr/bin/env python3
"""
auditoria_facturas_compra.py — Investiga si las facturas de compra cargadas
en Genexus (Compras > Facturas de Compra) realmente impactaron el stock.

Flujo:
  1. Lee comp_facturasww.aspx (Excel), filtra al rango de dias pedido.
  2. Para cada factura, entra a comp_facturasview.aspx?ID -> tab Detalle
     y lee sus items (articulo, nombre, lote, vencimiento, cantidad).
  3. Para cada item, consulta alm_articulosdepositostockww.aspx (stock por
     lote) filtrando por codigo de articulo, y compara:
       - Lote facturado NO existe en stock -> sospecha fuerte de que no impacto.
       - Lote existe pero con vencimiento DISTINTO al facturado -> sospecha
         (probablemente es un lote viejo homonimo, no el que entro ahora).
       - Lote existe, vencimiento coincide, pero existencia << cantidad
         facturada -> puede ser normal (ya se vendio), se marca como aviso,
         no como fallo.

No modifica nada en Genexus. Es de solo lectura.

Uso:
    python auditoria_facturas_compra.py --dias 15
"""
import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()
_QUIET = False
BASE_URL = "http://192.168.0.35/fedafar"
USER = os.getenv("FEDAFAR_USER")
PASS = os.getenv("FEDAFAR_PASS")


def do_login(page: Page) -> bool:
    page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx", timeout=15000)
    page.fill("#vSECUSERNAME", USER)
    page.fill("#vSECUSERPASSWORD", PASS)
    page.click("#BTNENTER")
    try:
        page.wait_for_function("() => !window.location.href.includes('seclogin')", timeout=10000)
        return True
    except PWTimeout:
        return False


def listar_facturas(page: Page, dias: int) -> list:
    """Lee la grilla de Facturas de Compra directo (sin exportar ni buscar
    fila por fila, que resulto poco confiable: numeros que matchean filas
    equivocadas, filtros residuales de sesiones previas). La grilla trae el
    id interno en el link 'Visualizar' de cada fila, en una sola carga."""
    page.goto(f"{BASE_URL}/comp_facturasww.aspx", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(1000)

    # El campo de busqueda arrastra el valor de la ultima sesion/prueba (mismo
    # comportamiento visto en sync_precios.py): limpiarlo siempre.
    filtro = page.locator("#vFILTERFULLTEXT")
    valor_previo = filtro.input_value()
    if valor_previo:
        print(f"  (limpiando filtro residual: {valor_previo!r})")
        filtro.fill("")
        page.keyboard.press("Enter")
        page.wait_for_load_state("networkidle", timeout=10000)
        page.wait_for_timeout(800)

    desde = datetime.now() - timedelta(days=dias)
    out, vistos = [], set()
    filas = page.query_selector_all("#GridContainerTbl tr")
    for tr in filas[1:]:
        link = tr.query_selector("a[href*='comp_facturasview.aspx']")
        if not link:
            continue
        href = link.get_attribute("href") or ""
        m = re.search(r"comp_facturasview\.aspx\?(\d+)", href)
        if not m:
            continue
        fid = m.group(1)
        if fid in vistos:
            continue
        # Columnas reales confirmadas en vivo: [icon x4, id, orden, Tipo,
        # Letra, Sucursal, Numero, Fecha, cod.prov, Proveedor, Total, Saldo, Estado]
        tds = [td.inner_text().strip() for td in tr.query_selector_all("td")]
        if len(tds) < 15:
            continue
        tipo, numero, fecha_str, proveedor, estado = tds[6], tds[9], tds[10], tds[12], tds[-1]
        try:
            fecha = datetime.strptime(fecha_str, "%d/%m/%Y")
        except ValueError:
            continue
        if fecha < desde:
            continue
        vistos.add(fid)
        out.append({"id": fid, "fecha": fecha, "tipo": tipo, "numero": numero,
                    "proveedor": proveedor, "estado": estado})
    out.sort(key=lambda f: f["fecha"])
    return out


def leer_items_factura(page: Page, fid: str) -> list:
    """Abre una factura y devuelve sus items del tab Detalle."""
    page.goto(f"{BASE_URL}/comp_facturasview.aspx?{fid},", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(1000)
    try:
        page.click("#Tab_TABSContainerpanel2", timeout=5000)
    except Exception:
        return []
    page.wait_for_load_state("networkidle", timeout=10000)
    page.wait_for_timeout(1000)

    # Estructura real de cada <tr> de la grilla (confirmada en vivo, id=16069):
    #  0:Item  1:OC  2:ItemOC  3:codigo-corto(sin ceros)  4:codigo-padded
    #  5:Nombre  6:Lote  7:Vencimiento  8:Cantidad  9:PrecioBruto ...
    filas = page.query_selector_all("#W0033GridContainerTbl tr")
    items = []
    for tr in filas:
        tds = [td.inner_text().strip() for td in tr.query_selector_all("td")]
        if len(tds) < 9:
            continue
        codigo = tds[4]
        if not re.match(r"^\d{6,}$", codigo):
            continue
        items.append({
            "codigo": codigo, "nombre": tds[5], "lote": tds[6],
            "vencimiento": tds[7], "cantidad": tds[8],
        })
    return items


def consultar_lotes_stock(page: Page, codigo: str) -> list:
    """Consulta alm_articulosdepositostockww.aspx filtrado por codigo de
    articulo. Devuelve [{lote, vencimiento, existencia}]."""
    page.goto(f"{BASE_URL}/alm_articulosdepositostockww.aspx", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(800)
    codigo_sin_ceros = codigo.lstrip("0") or "0"
    try:
        page.fill("#vARTICULOCODIGO1", codigo_sin_ceros)
        page.keyboard.press("Tab")
        page.wait_for_load_state("networkidle", timeout=10000)
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"    (no pude filtrar por codigo {codigo}: {e})")
        return []

    filas = page.query_selector_all("#GridContainerTbl tr")
    lotes = []
    for tr in filas[1:]:
        tds = [td.inner_text().strip() for td in tr.query_selector_all("td")]
        tds = [t for t in tds if t != ""]
        if len(tds) < 5:
            continue
        # Articulo | Principio Activo | Deposito | Lote | Vencimiento | Existencia
        lotes.append({"lote": tds[-3], "vencimiento": tds[-2], "existencia": tds[-1]})
    return lotes


def consultar_movimientos_articulo(page: Page, nombre: str, desde: str, hasta: str, codigo: str = None) -> list:
    """Consulta alm_movimientoarticulosreporte.aspx (historial real de
    movimientos, INGRESO/EGRESO) para un articulo en un rango de fechas.
    Resuelve el articulo por CODIGO (confiable, un solo resultado siempre) en
    vez de por nombre libre (puede ser ambiguo -p.ej. "X 1" vs "X 10"- y
    quedar sin resolver, lo que da un falso 'cero movimientos'). Si no hay
    codigo, cae a buscar por nombre y clickea la sugerencia que matchee.
    Devuelve [{fecha, lote, vencimiento, tipo, comprobante, cantidad, existencia}]."""
    page.goto(f"{BASE_URL}/alm_movimientoarticulosreporte.aspx", timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(600)
    campo = page.locator("#vARTICULOID")
    campo.click(); campo.fill("")
    page.wait_for_timeout(200)
    def _intentar(termino):
        campo.click(); campo.fill("")
        page.wait_for_timeout(150)
        page.keyboard.type(termino, delay=25)
        page.wait_for_timeout(900)
        resuelto = campo.input_value()
        if " - " in resuelto:
            return True
        sug = page.locator("#gxAutosuggestElement div:visible")
        n = sug.count()
        if n == 0:
            return False
        elegido = None
        if codigo:
            for i in range(n):
                if codigo in sug.nth(i).inner_text() or codigo.lstrip("0") in sug.nth(i).inner_text():
                    elegido = i; break
        if elegido is None and n == 1:
            elegido = 0
        if elegido is None:
            return None  # ambiguo, no confundir con "sin resultados"
        sug.nth(elegido).click()
        page.wait_for_timeout(500)
        return True

    # 1er intento: codigo corto (sin ceros). 2do intento (si ambiguo/vacio):
    # codigo completo con ceros, que suele ser mas especifico.
    ok = _intentar(codigo.lstrip("0") if codigo else nombre)
    if ok is not True and codigo:
        ok = _intentar(codigo)
    if ok is not True:
        print(f"    ⚠ no pude resolver el articulo (codigo {codigo!r}) con certeza — salteo "
              f"(no confundir con 'sin movimientos').")
        return None
    page.keyboard.press("Tab")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass
    page.fill("#vFECHADESDE", desde); page.keyboard.press("Tab"); page.wait_for_timeout(300)
    page.fill("#vFECHAHASTA", hasta); page.keyboard.press("Tab")
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PWTimeout:
        pass
    page.wait_for_timeout(600)

    import pandas as pd
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_movs_tmp.xlsx")
    try:
        with page.expect_download(timeout=15000) as dl:
            page.click("#BTNUEXPORTAR")
        dl.value.save_as(tmp)
    except PWTimeout:
        return []
    try:
        df = pd.read_excel(tmp, skiprows=4, header=0)
    except Exception:
        return []
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    if df.empty or "Fecha" not in "".join(str(c) for c in df.columns) and len(df.columns) < 8:
        pass
    filas = []
    for _, row in df.iterrows():
        vals = row.tolist()
        if len(vals) < 9 or str(vals[0]).strip().lower() in ("nan", ""):
            continue
        filas.append({
            "fecha": str(vals[0])[:10], "lote": str(vals[1]).strip(),
            "vencimiento": str(vals[2])[:10], "tipo": str(vals[3]).strip(),
            "comprobante": str(vals[6]).strip(), "cantidad": vals[7], "existencia": vals[8],
        })
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=15)
    ap.add_argument("--quiet", action="store_true",
                    help="Para corridas automaticas/programadas: no imprime cada item OK, solo alertas y el resumen.")
    args = ap.parse_args()
    global _QUIET
    _QUIET = args.quiet

    if not USER or not PASS:
        print("ERROR: faltan FEDAFAR_USER/FEDAFAR_PASS en .env"); sys.exit(1)

    print(f"=== Auditoria de Facturas de Compra (ultimos {args.dias} dias) ===")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_context().new_page()
        if not do_login(page):
            print("ERROR: login fallido"); return

        facturas = listar_facturas(page, args.dias)
        print(f"Facturas/remitos encontrados: {len(facturas)}")

        # 1) Leer los items de TODAS las facturas primero (rapido, ya viene
        #    andando bien) y agrupar por articulo unico.
        por_codigo = {}   # codigo -> {"nombre":..., "usos": [(factura, item), ...]}
        for f in facturas:
            items = leer_items_factura(page, f["id"])
            if not items:
                if not _QUIET:
                    print(f"  (sin items: {f['fecha'].strftime('%d/%m/%Y')} Nro {f['numero']} {f['proveedor'][:40]})")
                continue
            for it in items:
                por_codigo.setdefault(it["codigo"], {"nombre": it["nombre"], "usos": []})
                por_codigo[it["codigo"]]["usos"].append((f, it))
        if not _QUIET:
            print(f"Articulos unicos a verificar: {len(por_codigo)}\n")

        # 2) Rango para el historial de movimientos: desde el dia mas viejo
        #    de las facturas encontradas, hasta hoy. UNA sola consulta por
        #    articulo (no por factura), aunque el articulo se repita en
        #    varias facturas del periodo.
        desde_str = min(f["fecha"] for f in facturas).strftime("%d/%m/%Y") if facturas else \
                    (datetime.now() - timedelta(days=args.dias)).strftime("%d/%m/%Y")
        hasta_str = datetime.now().strftime("%d/%m/%Y")

        sospechas, ok_count, sin_verificar = [], 0, []
        for i, (codigo, info) in enumerate(por_codigo.items(), 1):
            if not _QUIET:
                print(f"[{i}/{len(por_codigo)}] {info['nombre'][:55]} (cod {codigo})")
            movs = consultar_movimientos_articulo(page, info["nombre"], desde_str, hasta_str, codigo=codigo)
            if movs is None:
                # No se pudo resolver el articulo en el buscador -> NO se
                # puede afirmar "sin movimientos", hay que revisar a mano.
                for f, it in info["usos"]:
                    sin_verificar.append({**f, **it, "motivo": "no se pudo resolver el articulo en el buscador"})
                continue
            ingresos = [m for m in movs if m["tipo"].upper() == "INGRESO"]
            for f, it in info["usos"]:
                # Match por el numero de comprobante (mas confiable que lote+
                # cantidad: es el link real que Genexus deja al comprobante).
                match = next((m for m in ingresos if f["numero"] and f["numero"] in m["comprobante"]), None)
                if match:
                    ok_count += 1
                    if not _QUIET:
                        print(f"   ✓ Nro {f['numero']} ({f['fecha'].strftime('%d/%m')}) → INGRESO registrado "
                              f"cant={match['cantidad']} el {match['fecha']}")
                else:
                    # No confiar en un solo intento: la consulta a veces falla por
                    # timing (export que agarra datos viejos). Antes de marcar
                    # "sospechoso" de verdad, RECONFIRMAR con una consulta nueva
                    # e independiente. Solo se reporta si falla las DOS veces.
                    if not _QUIET:
                        print(f"   ? Nro {f['numero']}: sin match en el primer intento, reconfirmando...")
                    movs2 = consultar_movimientos_articulo(page, info["nombre"], desde_str, hasta_str, codigo=codigo)
                    match2 = None
                    if movs2 is not None:
                        ingresos2 = [m for m in movs2 if m["tipo"].upper() == "INGRESO"]
                        match2 = next((m for m in ingresos2 if f["numero"] and f["numero"] in m["comprobante"]), None)
                    if match2:
                        ok_count += 1
                        if not _QUIET:
                            print(f"   ✓ (en la reconfirmacion) Nro {f['numero']} → INGRESO cant={match2['cantidad']} el {match2['fecha']}")
                    else:
                        print(f"   ⚠ CONFIRMADO Nro {f['numero']} ({f['fecha'].strftime('%d/%m')}, {f['proveedor'][:35]}): "
                              f"cant.facturada={it['cantidad']} lote={it['lote']} → SIN INGRESO vinculado (2/2 intentos)")
                        sospechas.append({**f, **it, "motivo": "sin movimiento de INGRESO vinculado a esta factura (confirmado 2 veces)"})

        print()
        print("=" * 70)
        print(f"RESUMEN: {ok_count} ok · {len(sospechas)} sospechoso(s) · {len(sin_verificar)} sin verificar "
              f"en {len(facturas)} factura(s)/remito(s) ({len(por_codigo)} articulos unicos)")
        if sospechas:
            print()
            print("*** ALERTA: hay facturas/remitos SIN ingreso de stock (reconfirmado 2 veces) ***")
            for s in sospechas:
                print(f"  - SOSPECHOSO: {s['fecha'].strftime('%d/%m/%Y')} Nro {s['numero']} ({s['proveedor'][:40]}): "
                      f"{s['nombre'][:45]} lote={s['lote']} cant={s['cantidad']} — {s['motivo']}")
        elif not _QUIET:
            print("Sin alertas: todas las facturas/remitos del periodo sumaron su stock correctamente.")
        for s in sin_verificar:
            print(f"  - SIN VERIFICAR (revisar a mano): {s['fecha'].strftime('%d/%m/%Y')} Nro {s['numero']} "
                  f"({s['proveedor'][:40]}): {s['nombre'][:45]} — {s['motivo']}")
        b.close()


if __name__ == "__main__":
    main()
