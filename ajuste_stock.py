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

BASE_DIR_EARLY = os.path.dirname(os.path.abspath(__file__))
# Reuso EXACTO del buscador de artículos del agente de pedidos (misma búsqueda,
# mismo autosuggest de Genexus): tokens_clave / score_match / autosuggest.
sys.path.insert(0, os.path.join(BASE_DIR_EARLY, "pedidos"))
import cargar_genexus as cg   # noqa: E402

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


# ── Asignación FEFO de lotes (lote más viejo primero) ──────────────────────────
def _parse_venc(v):
    """Convierte 'dd/mm/aaaa' a una tupla ordenable (aaaa, mm, dd). Sin fecha → +inf."""
    try:
        d, m, a = str(v).strip().split("/")
        return (int(a), int(m), int(d))
    except Exception:
        return (9999, 99, 99)   # sin vencimiento válido → va al final


def asignar_lotes(necesita, lotes):
    """Reparte `necesita` unidades entre `lotes`, usando el más viejo (menor
    vencimiento) primero, solo lotes con existencia > 0.
    `lotes`: [{'lote':str, 'venc':'dd/mm/aaaa', 'existencia':float}]
    Devuelve (asignaciones, faltante):
        asignaciones = [{'lote', 'venc', 'cantidad'}]  en orden de consumo
        faltante     = unidades que NO se pudieron cubrir (0 si alcanzó)."""
    disponibles = [l for l in lotes if float(l.get('existencia') or 0) > 0]
    disponibles.sort(key=lambda l: _parse_venc(l.get('venc')))
    asign, resto = [], float(necesita)
    for l in disponibles:
        if resto <= 0:
            break
        toma = min(resto, float(l['existencia']))
        if toma <= 0:
            continue
        asign.append({'lote': l['lote'], 'venc': l.get('venc'),
                      'cantidad': int(toma) if toma == int(toma) else toma})
        resto -= toma
    return asign, (int(resto) if resto == int(resto) else resto)


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
INS_URL = f"{BASE_URL}/alm_movimientosstock.aspx?INS,0"

def _form_alta_listo(page: Page) -> bool:
    try:
        page.wait_for_selector("#MOVSTOCKFECHA", state="visible", timeout=8000)
        return True
    except PWTimeout:
        return False

def abrir_alta(page: Page) -> bool:
    # 1) Intento directo por URL en modo INS (lo más confiable en GeneXus)
    print(f"  Abriendo alta directo: {INS_URL}")
    try:
        page.goto(INS_URL, timeout=15000)
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass
    if "alm_movimientosstock.aspx" in page.url and _form_alta_listo(page):
        print(f"  Formulario de alta abierto (directo): {page.url}")
        return True

    # 2) Fallback: entrar por el Work With y clickear Agregar
    print("  (directo no anduvo) Navegando a Movimientos de Stock y clickeando Agregar...")
    page.goto(WW_URL, timeout=15000)
    page.wait_for_load_state("networkidle", timeout=15000)
    try:
        with page.expect_navigation(wait_until="networkidle", timeout=15000):
            page.click("#BTNINSERT")
    except PWTimeout:
        page.wait_for_load_state("networkidle", timeout=15000)
    if "alm_movimientosstock.aspx" in page.url and _form_alta_listo(page):
        print(f"  Formulario de alta abierto (botón): {page.url}")
        return True

    # 3) Diagnóstico: listar botones/enlaces reales del Work With
    print(f"  ⚠ No se pudo abrir el alta. URL actual: {page.url}")
    ctrls = page.evaluate("""
        () => Array.from(document.querySelectorAll('input[type=button],input[type=submit],button,a'))
            .filter(b => b.offsetParent !== null)
            .map(b => ({ tag:b.tagName, id:b.id, val:(b.value||b.textContent||'').trim().slice(0,40), href:b.getAttribute('href')||'' }))
            .filter(b => b.id || b.val || b.href)
    """)
    print("  Controles visibles en la pantalla:")
    for c in ctrls:
        print("   ", c)
    return False


# ── Cabecera (Paso 6) — foco explícito por ID, robusto a los postbacks de GX ────
def cargar_cabecera(page: Page, detalle: str, tipo_mov: str = TIPO_MOV_EGRESO) -> bool:
    print("  Cargando cabecera (EGRESO)...")

    # 1) Tipo Movimiento = EGRESO. Elijo por TEXTO (el value cambia según el ambiente).
    opciones = page.evaluate(
        """() => { const e = document.querySelector('#TIPOMOVSTOCKID');
            return e ? Array.from(e.options).map(o => ({v:o.value, t:(o.text||'').trim()})) : null; }""")
    print(f"    opciones Tipo Movimiento: {opciones}")
    # Busco el value cuyo texto contenga EGRESO
    val_egreso = None
    for o in (opciones or []):
        if "EGRESO" in o["t"].upper():
            val_egreso = o["v"]; break
    if not val_egreso:
        print("  ⚠ No encontré una opción 'EGRESO' en el select. Abortando cabecera.")
        return False
    page.focus("#TIPOMOVSTOCKID")
    page.select_option("#TIPOMOVSTOCKID", val_egreso)
    page.wait_for_load_state("networkidle")
    # El autocompletado de "Tipo" viene por el postback del onchange: esperamos a que
    # efectivamente pase a 'E' (no leemos antes de tiempo). Si no, probamos con Tab.
    def _tipo_ok():
        try:
            return page.input_value("#TIPOMOVSTOCKTIPO") == "E"
        except Exception:
            return False
    try:
        page.wait_for_function(
            "() => { const e=document.querySelector('#TIPOMOVSTOCKTIPO'); return e && e.value==='E'; }",
            timeout=8000)
    except PWTimeout:
        # Fallback: forzar el commit con Tab desde el select
        page.focus("#TIPOMOVSTOCKID")
        page.keyboard.press("Tab")
        page.wait_for_load_state("networkidle")
    tipo = page.input_value("#TIPOMOVSTOCKTIPO")
    print(f"    Tipo Movimiento value={val_egreso} (EGRESO) → Tipo='{tipo}'")
    if tipo != "E":
        print(f"  ⚠ El 'Tipo' no se autocompletó a E (quedó '{tipo}').")
        return False

    # 2) Depósito: debe quedar en DEPOSITO (value 1). Solo lo toco si no está seteado.
    try:
        dep = page.input_value("#DEPOSITOID")
        if dep not in ("1",):
            print(f"    Depósito estaba en '{dep}', lo seteo a 1 (DEPOSITO).")
            page.focus("#DEPOSITOID")
            page.select_option("#DEPOSITOID", "1")
            page.keyboard.press("Tab")
            page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"    (no pude leer/setear Depósito: {e})")

    # 3) Detalle: enfoco el campo directo (NO por cadena de TAB, que el postback rompe),
    #    escribo y Tab para commitear.
    page.focus("#MOVSTOCKDETALLE")
    page.fill("#MOVSTOCKDETALLE", detalle)
    page.keyboard.press("Tab")
    page.wait_for_load_state("networkidle")
    det = page.input_value("#MOVSTOCKDETALLE")
    if det != detalle:
        print(f"  ⚠ El Detalle no quedó bien (esperado '{detalle}', quedó '{det}').")

    # 4) Dejo el foco en la primera fila de artículo, listo para cargar.
    try:
        page.focus("#vARTICULOID_0001")
    except Exception:
        pass
    print(f"  Cabecera OK. Tipo={tipo}, Detalle='{det}'.")
    return True


def _dump_lote_select(page: Page, s: str):
    """Muestra las opciones del select de lote/stock del renglón (diagnóstico Paso 7)."""
    opts = page.evaluate(
        """(sel) => { const e = document.querySelector(sel);
            return e ? Array.from(e.options).map(o => ({v:o.value, t:o.text})) : null; }""",
        f"#ARTICULODEPOSITOSTOCKID{s}")
    print(f"    lote select ARTICULODEPOSITOSTOCKID{s}: {opts}")


def _snapshot_fila(page: Page, s: str, titulo: str):
    """Lista TODOS los elementos con id de la fila (id que termina en el sufijo s),
    con su value/texto y opciones — para descubrir la estructura real de la grilla."""
    campos = page.evaluate(
        """(suf) => Array.from(document.querySelectorAll('[id]'))
            .filter(e => e.id && e.id.endsWith(suf) && ['INPUT','SELECT','TEXTAREA','SPAN','TD','DIV'].includes(e.tagName))
            .map(e => ({
                id: e.id,
                tag: e.tagName.toLowerCase(),
                value: ((e.value !== undefined && e.tagName === 'INPUT') ? e.value : (e.innerText || '')).slice(0, 60),
                opts: e.tagName === 'SELECT' ? Array.from(e.options).map(o => o.value + '=' + o.text.slice(0,30)) : undefined
            }))""",
        s)
    print(f"    ── {titulo} (fila {s}) ──")
    for c in campos:
        extra = f"  opts={c['opts']}" if c.get('opts') is not None else ""
        print(f"       {c['id']}  [{c['tag']}]  value='{c['value']}'{extra}")


def explorar_lotes(page: Page, s: str, maximo: int = 25):
    """Recorre el select de lote parándose en cada opción y leyendo la existencia
    y el vencimiento que aparecen. Sirve para descubrir de qué elemento salen y
    para validar el orden FEFO (arriba = más viejo)."""
    sel = f"#ARTICULODEPOSITOSTOCKID{s}"
    opts = page.evaluate(
        "(x)=>{const e=document.querySelector(x); return e?Array.from(e.options).map(o=>({v:o.value,t:o.text})):[]}", sel)
    utiles = [o for o in opts if o["v"]]
    print(f"    ── Explorando lotes (fila {s}) — {len(utiles)} lote(s) ──")
    # "Despertar" la lista como en el uso manual: abajo y arriba
    try:
        page.focus(sel); page.keyboard.press("ArrowDown"); page.keyboard.press("ArrowUp")
        page.wait_for_load_state("networkidle")
    except Exception:
        pass
    for o in utiles[:maximo]:
        try:
            page.select_option(sel, o["v"])
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"       lote '{o['t']}': no pude seleccionar ({e})"); continue
        datos = page.evaluate(
            """(suf)=>{const r={};
                document.querySelectorAll('[id]').forEach(e=>{
                    if(!e.id.endsWith(suf)) return;
                    const up=e.id.toUpperCase();
                    if(/EXIST|STOCK|SALDO|VENC|CANT/.test(up)){
                        r[e.id]=(e.value!==undefined&&e.tagName==='INPUT')?e.value:(e.innerText||'').trim();
                    }
                });
                return r;}""", s)
        print(f"       lote v={o['v']} '{o['t']}' → {datos}")


def explorar_lotes_teclado(page: Page, s: str, pasos: int = 14):
    """Navega el select de lote con FLECHAS (como el uso manual) leyendo la
    existencia y el vencimiento que aparecen en cada lote. La existencia solo se
    revela al 'pararse' en el lote con el teclado, no con select_option."""
    sel  = f"#ARTICULODEPOSITOSTOCKID{s}"
    ex   = f"#span_ARTICULODEPOSITOSTOCKCANTIDAD{s}"
    vc   = f"#span_ARTICULODEPOSITOSTOCKFECHAVCTO{s}"
    print(f"    ── Explorando lotes por TECLADO (fila {s}) ──")
    try:
        page.focus(sel)
        page.keyboard.press("ArrowDown"); page.wait_for_timeout(600)
        page.keyboard.press("ArrowUp");   page.wait_for_timeout(600)   # vuelve al 1° y revela cantidad
    except Exception as e:
        print(f"       (no pude enfocar el select: {e})"); return
    visto = set()
    for _ in range(pasos):
        try:
            val = page.eval_on_selector(sel, "e => e.value")
            existencia = (page.inner_text(ex) or "").strip()
            venc = (page.inner_text(vc) or "").strip()
        except Exception as e:
            print(f"       (error leyendo: {e})"); break
        clave = str(val)
        if clave not in visto:
            print(f"       lote='{val}'  existencia='{existencia}'  vto='{venc}'")
            visto.add(clave)
        page.keyboard.press("ArrowDown")
        page.wait_for_timeout(700)
        # si tras la flecha se perdió el foco (postback), re-enfoco
        try:
            if page.evaluate("() => document.activeElement && document.activeElement.id") != sel.lstrip("#"):
                page.focus(sel)
        except Exception:
            pass


# ── Buscar/seleccionar el artículo en la fila (reusa el matching de pedidos) ────
def buscar_articulo_fila(page: Page, s: str, nombre: str, codigo=None) -> dict:
    """Carga el artículo en el campo #vARTICULOID{s} usando el MISMO buscador que
    el agente de pedidos (autosuggest de Genexus). Si viene `codigo`, lo usa como
    atajo; si no (o no resuelve), busca por nombre con tokens_clave + score."""
    campo = page.locator(f"#vARTICULOID{s}")
    sug = page.locator("#gxAutosuggestElement div:visible")

    # Atajo por código
    if codigo:
        cg.escribir_en_autosuggest(page, campo, str(codigo))
        page.wait_for_timeout(1000)
        valor = campo.input_value()
        if cg._RE_RESUELTO_ARTICULO.search(valor):
            campo.press("Tab"); page.wait_for_load_state("networkidle")
            return {"ok": True, "matcheado": valor, "score": 1.0, "termino": f"#{codigo}"}
        if sug.count() == 1:
            sug.first.click(); page.wait_for_load_state("networkidle")
            return {"ok": True, "matcheado": campo.input_value(), "score": 1.0, "termino": f"#{codigo}"}
        print(f"    (código {codigo} no resolvió, caigo a búsqueda por nombre)")

    # Búsqueda por nombre. En VENTA INF el nombre es EXACTO al del catálogo/Genexus,
    # así que probamos PRIMERO el nombre completo (resuelve a un único artículo) y
    # solo si no encuentra, caemos a menos palabras.
    terminos = list(dict.fromkeys([
        nombre.strip(),
        cg.tokens_clave(nombre, 3),
        cg.tokens_clave(nombre, 2),
        cg.primer_token_clave(nombre),
    ]))
    opciones = []
    for termino in terminos:
        cg.escribir_en_autosuggest(page, campo, termino)
        valor = campo.input_value()
        if cg._RE_RESUELTO_ARTICULO.search(valor):     # autocompletó directo (1 resultado)
            campo.press("Tab"); page.wait_for_load_state("networkidle")
            return {"ok": True, "matcheado": valor, "score": 1.0, "termino": termino}
        n = sug.count()
        for espera in (1500, 2500):
            if n > 0:
                break
            page.wait_for_timeout(espera); n = sug.count()
        if n == 0:
            _diag_autosuggest(page, termino)            # ¿otro contenedor de sugerencias?
            continue                                    # probar con menos palabras
        opciones = [(cg.score_match(nombre, sug.nth(k).inner_text()), sug.nth(k).inner_text(), k)
                    for k in range(n)]
        opciones.sort(key=lambda x: -x[0])
        mejor, segundo = opciones[0][0], (opciones[1][0] if len(opciones) > 1 else -1)
        if mejor == 0:
            continue
        if mejor == segundo:
            return {"ok": False, "motivo": "match ambiguo (empate)", "termino": termino,
                    "opciones": [o[1] for o in opciones]}
        sug.nth(opciones[0][2]).click()
        page.wait_for_load_state("networkidle")
        return {"ok": True, "matcheado": opciones[0][1], "score": mejor, "termino": termino}

    return {"ok": False, "motivo": "sin resultados", "termino": terminos[-1] if terminos else nombre}


def _diag_autosuggest(page: Page, termino: str):
    """Si no aparecieron sugerencias en #gxAutosuggestElement, muestra qué
    contenedores de autosuggest existen en la página (para hallar el correcto)."""
    info = page.evaluate("""() => {
        const out = [];
        document.querySelectorAll("[id*='utosuggest'],[class*='utosuggest'],[role='listbox']").forEach(e => {
            const vis = e.offsetParent !== null;
            out.push({ id:e.id, cls:e.className, role:e.getAttribute('role'), visible:vis,
                       hijos:e.querySelectorAll('div,li,option').length,
                       muestra:(e.innerText||'').replace(/\\s+/g,' ').slice(0,80) });
        });
        return out;
    }""")
    print(f"    [diag autosuggest] término='{termino}' → contenedores: {info}")


# ── Carga FEFO real ─────────────────────────────────────────────────────────────
def _reset_lote_top(page: Page, sel: str):
    """Deja el select de lote parado en el primer lote (más viejo) y revela su
    existencia — replica el 'abajo y arriba' del uso manual."""
    page.focus(sel)
    page.keyboard.press("ArrowDown"); page.wait_for_timeout(600)
    page.keyboard.press("ArrowUp");   page.wait_for_timeout(600)


def escanear_lotes(page: Page, s: str) -> list:
    """Navega los lotes con teclado (única forma de que aparezca la existencia) y
    devuelve [{idx, value, existencia, venc}] en el orden del dropdown (más viejo
    arriba = orden FEFO)."""
    sel = f"#ARTICULODEPOSITOSTOCKID{s}"
    ex  = f"#span_ARTICULODEPOSITOSTOCKCANTIDAD{s}"
    vc  = f"#span_ARTICULODEPOSITOSTOCKFECHAVCTO{s}"
    _reset_lote_top(page, sel)
    n = page.eval_on_selector(sel, "e => e.options.length")
    lotes = []
    for i in range(n):
        val = page.eval_on_selector(sel, "e => e.value")
        existencia = cg._num(page.inner_text(ex))
        venc = (page.inner_text(vc) or "").strip()
        lotes.append({"idx": i, "value": val, "existencia": existencia, "venc": venc})
        page.keyboard.press("ArrowDown"); page.wait_for_timeout(650)
    return lotes


def _ir_a_lote(page: Page, s: str, idx: int):
    """Deja el select parado en el lote de índice `idx` (0 = más viejo)."""
    sel = f"#ARTICULODEPOSITOSTOCKID{s}"
    _reset_lote_top(page, sel)
    for _ in range(idx):
        page.keyboard.press("ArrowDown"); page.wait_for_timeout(450)


def _filas_actuales(page: Page) -> int:
    """Cantidad de renglones de detalle disponibles en la grilla."""
    return page.evaluate("() => document.querySelectorAll(\"input[id^='vARTICULOID_']\").length")


def _agregar_fila(page: Page) -> bool:
    """Click en 'Nueva fila' para sumar un renglón cuando se llenan las 5 base."""
    try:
        page.get_by_text("Nueva fila", exact=False).first.click(timeout=5000)
        page.wait_for_load_state("networkidle")
        return True
    except Exception as e:
        print(f"    ⚠ No pude clickear 'Nueva fila': {e}")
        return False


def _asegurar_fila(page: Page, n: int) -> bool:
    """Garantiza que exista el renglón n (agrega filas si hace falta)."""
    guard = 0
    while _filas_actuales(page) < n and guard < n + 3:
        if not _agregar_fila(page):
            break
        guard += 1
    return _filas_actuales(page) >= n


def _tab_poblar_lotes(page: Page, s: str):
    page.focus(f"#vARTICULOID{s}")
    page.keyboard.press("Tab")
    page.wait_for_load_state("networkidle")
    try:
        page.wait_for_function(
            "(sel)=>{const e=document.querySelector(sel); return e && e.options.length>0;}",
            arg=f"#ARTICULODEPOSITOSTOCKID{s}", timeout=6000)
    except PWTimeout:
        pass


def cargar_articulo(page: Page, fila_base: int, nombre: str, necesita, codigo=None, max_fila=5) -> dict:
    """Carga un artículo en el movimiento repartiendo `necesita` unidades entre los
    lotes con stock (FEFO, más viejo primero). Usa una fila por lote. Devuelve
    {ok, egresado, pendiente, filas_usadas, detalle:[{fila,lote,venc,cantidad}]}.
    Lo que no se pueda cubrir (sin stock, o se acaban las filas) queda en `pendiente`."""
    _asegurar_fila(page, fila_base)
    s = f"_{fila_base:04d}"
    res = buscar_articulo_fila(page, s, nombre, codigo)
    if not res.get("ok"):
        return {"ok": False, "motivo": res.get("motivo"), "egresado": 0, "pendiente": float(necesita),
                "filas_usadas": 0, "detalle": []}
    _tab_poblar_lotes(page, s)
    lotes = escanear_lotes(page, s)
    con_stock = [l for l in lotes if l["existencia"] > 0]

    resto = float(necesita)
    detalle, fila = [], fila_base
    for l in con_stock:
        if resto <= 0:
            break
        toma = min(resto, l["existencia"])
        _asegurar_fila(page, fila)                 # agrega 'Nueva fila' si hace falta
        sk = f"_{fila:04d}"
        # La primera fila ya tiene el artículo; las siguientes hay que cargarlo de nuevo.
        if fila != fila_base:
            r2 = buscar_articulo_fila(page, sk, nombre, codigo)
            if not r2.get("ok"):
                break
            _tab_poblar_lotes(page, sk)
        _ir_a_lote(page, sk, l["idx"])
        cant = int(toma) if float(toma) == int(toma) else toma
        page.fill(f"#MOVSTOCKDETCANTIDAD{sk}", str(cant))
        page.keyboard.press("Tab")
        page.wait_for_load_state("networkidle")
        detalle.append({"fila": fila, "lote": l["value"], "venc": l["venc"], "cantidad": cant})
        print(f"    fila {fila}: lote '{l['value']}' (vto {l['venc']}, exist {l['existencia']}) → egreso {cant}")
        resto -= toma
        fila += 1

    # Si el artículo no tenía stock en ningún lote, limpio la fila para no dejar
    # un renglón con artículo y cantidad 0 (que rechazaría el Confirmar).
    if not detalle:
        try:
            page.fill(f"#vARTICULOID{s}", "")
            page.keyboard.press("Tab")
            page.wait_for_load_state("networkidle")
        except Exception:
            pass

    egresado = float(necesita) - resto
    return {"ok": True, "egresado": egresado, "pendiente": resto,
            "filas_usadas": len(detalle), "detalle": detalle}


def cargar_movimiento(page: Page, items: list) -> dict:
    """Carga TODOS los items en un único movimiento (agrega 'Nueva fila' según haga
    falta). `items`: [{'nombre', 'cantidad', 'codigo'(opcional)}].
    Devuelve {detalle:[...], pendientes:[{nombre,cantidad,motivo}], filas}."""
    fila = 1
    detalle_total, pendientes = [], []
    for it in items:
        nombre, cant = it["nombre"], float(it["cantidad"])
        print(f"  → {nombre}  x{cant}")
        r = cargar_articulo(page, fila, nombre, cant, codigo=it.get("codigo"))
        if not r.get("ok"):
            pendientes.append({"nombre": nombre, "cantidad": cant, "motivo": r.get("motivo", "no se pudo cargar")})
            continue
        detalle_total += r["detalle"]
        if r.get("pendiente", 0) > 0:
            pendientes.append({"nombre": nombre, "cantidad": r["pendiente"],
                               "motivo": "stock insuficiente en lotes"})
        fila += r.get("filas_usadas", 0)
    return {"detalle": detalle_total, "pendientes": pendientes, "filas": fila - 1}


# ── Cargar un renglón de detalle (diagnóstico — Paso 7) ─────────────────────────
def cargar_renglon(page: Page, i: int, nombre, cantidad, codigo=None, lote=None) -> bool:
    s = f"_{i:04d}"
    print(f"  Renglón {i}: '{nombre}' (código={codigo}), cantidad={cantidad}")

    # Snapshot ANTES: para ver los IDs reales de la fila vacía.
    _snapshot_fila(page, s, "ANTES de cargar")

    res = buscar_articulo_fila(page, s, str(nombre), codigo)
    print(f"    búsqueda artículo: {res}")
    if not res.get("ok"):
        print(f"    ⚠ No se cargó el artículo: {res.get('motivo')}")
        return False

    # Tras seleccionar el artículo, forzar el postback (Tab) que puebla el select
    # de lotes y las columnas de existencia/vencimiento. Espero a que aparezcan.
    page.focus(f"#vARTICULOID{s}")
    page.keyboard.press("Tab")
    page.wait_for_load_state("networkidle")
    try:
        page.wait_for_function(
            "(sel)=>{const e=document.querySelector(sel); return e && e.options.length>0;}",
            arg=f"#ARTICULODEPOSITOSTOCKID{s}", timeout=6000)
    except PWTimeout:
        print("    ⚠ El select de lotes no se pobló tras el Tab (revisar postback).")

    # Snapshot DESPUÉS: qué resolvió el artículo, existencia, vencimiento, lotes.
    _snapshot_fila(page, s, "DESPUÉS de resolver")
    _dump_lote_select(page, s)
    explorar_lotes_teclado(page, s)

    # NOTA: los IDs de lote/cantidad se confirman con el snapshot de arriba.
    # Por ahora, intento no-fatal para no cortar el diagnóstico.
    if lote is not None:
        try:
            page.select_option(f"#ARTICULODEPOSITOSTOCKID{s}", str(lote))
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"    (lote: no pude setear {lote}: {e})")
    try:
        page.fill(f"#MOVSTOCKDETCANTIDAD{s}", str(cantidad))
        page.keyboard.press("Tab")
        page.wait_for_load_state("networkidle")
        print(f"    cantidad seteada: {page.input_value(f'#MOVSTOCKDETCANTIDAD{s}')}")
    except Exception as e:
        print(f"    (cantidad: no pude setear todavía: {e})")
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
    ap.add_argument("--test-nombre", help="Nombre del artículo a buscar (usa el mismo buscador que pedidos).")
    ap.add_argument("--test-articulo", help="Código de artículo (atajo directo, sin buscar por nombre).")
    ap.add_argument("--cantidad", default="1", help="Cantidad para el artículo de prueba.")
    ap.add_argument("--lote", default=None, help="Value del select de lote (si hay que elegirlo).")
    ap.add_argument("--detalle", default=DETALLE_DEFAULT, help="Texto del detalle del movimiento.")
    ap.add_argument("--headed", action="store_true", help="Mostrar el navegador (no headless).")
    ap.add_argument("--cargar", action="store_true",
                    help="Además de la cabecera, intentar cargar el artículo (Paso 7, en desarrollo).")
    args = ap.parse_args()

    if not FEDAFAR_USER or not FEDAFAR_PASS:
        print("ERROR: faltan FEDAFAR_USER / FEDAFAR_PASS en .env"); sys.exit(1)
    if not args.test_nombre and not args.test_articulo:
        print("Usá --test-nombre \"ALGODON 500 GR\" (busca por nombre) y/o --test-articulo <código>.")
        sys.exit(1)

    print(f"=== Ajuste de Stock (DRY_RUN={'ON' if DRY_RUN else 'OFF'}) ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_context().new_page()
        try:
            if not do_login(page):                       return
            if not abrir_alta(page):                     return
            if not cargar_cabecera(page, args.detalle):  return
            if args.cargar:
                nombre = args.test_nombre or args.test_articulo
                r = cargar_articulo(page, 1, nombre, float(args.cantidad), codigo=args.test_articulo)
                print(f"  RESULTADO: {r}")
                if r.get("pendiente", 0) > 0:
                    print(f"  ⚠ Quedaron {r['pendiente']} un. PENDIENTES de impactar (iría a la alerta de la app).")
                finalizar(page)
            else:
                print("  ✋ FRENO ACÁ: cabecera completa, foco en la primera fila de artículo.")
                print("     (Para probar la carga del artículo, agregá --cargar cuando lo trabajemos.)")
                shot = os.path.join(BASE_DIR, "ajuste_debug.png")
                page.screenshot(path=shot, full_page=True)
                print(f"     Screenshot: {shot}")
            print("=== Fin del circuito de prueba ===")
        finally:
            if args.headed:
                input("  [Enter para cerrar el navegador]")
            browser.close()


if __name__ == "__main__":
    main()
