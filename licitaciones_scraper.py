#!/usr/bin/env python3
"""Scraper de licitaciones saltacompra.gob.ar para FEDAFAR."""

import os, re, json, time, sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pathlib import Path

# Cargar .env si existe (ejecución local)
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from supabase import create_client
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

SUPABASE_URL  = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY  = os.environ.get('SUPABASE_KEY', '')
ANTHROPIC_KEY = os.environ.get('ANTHROPIC_API_KEY', '')

URL_LICITACIONES = 'https://saltacompra.gob.ar/Compras.aspx?qs=iouVZE0yWCs='
SITE_ROOT        = 'https://saltacompra.gob.ar/'
MAX_PAGINAS      = 15

KEYWORDS = [
    'salud', 'hospital', 'medicamento', 'farmacia', 'diabetes',
    'insulina', 'reactivo', 'insumo', 'drogueria', 'droguería',
    'sanitario', 'clinica', 'clínica', 'vacuna', 'jeringa',
    'descartable', 'material medico', 'material médico', 'enfermeria',
    'enfermería', 'ambulancia', 'quirurgico', 'quirúrgico',
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'es-AR,es;q=0.9',
}

# ── Keyword filter ────────────────────────────────────────────────────────────

def contiene_keyword(texto):
    t = texto.lower()
    return any(k in t for k in KEYWORDS)

# ── ASP.NET helpers ───────────────────────────────────────────────────────────

def extraer_viewstate(soup):
    def val(name):
        el = soup.find('input', {'name': name})
        return el['value'] if el else ''
    return {
        '__VIEWSTATE':          val('__VIEWSTATE'),
        '__VIEWSTATEGENERATOR': val('__VIEWSTATEGENERATOR'),
        '__EVENTVALIDATION':    val('__EVENTVALIDATION'),
    }

def extraer_form_data(soup):
    data = extraer_viewstate(soup)
    data['__EVENTTARGET']  = ''
    data['__EVENTARGUMENT'] = ''
    form = soup.find('form')
    if form:
        for inp in form.find_all('input'):
            name = inp.get('name', '')
            val  = inp.get('value', '')
            if name and name not in data and inp.get('type', '').lower() != 'submit':
                data[name] = val
    return data

def get_form_action(soup):
    """Extrae la URL de action del form principal."""
    form = soup.find('form')
    if form and form.get('action'):
        action = form['action']
        if action.startswith('http'):
            return action
        return 'https://saltacompra.gob.ar/' + action.lstrip('/')
    return URL_LICITACIONES

def obtener_evento_pagina(soup, pagina_siguiente):
    """Devuelve (target, arg) para el link de la página siguiente, o (None, None)."""
    patron = re.compile(r"__doPostBack\('([^']+)','([^']+)'\)", re.I)
    for a in soup.find_all('a', href=True):
        href = a['href']
        m = patron.search(href)
        if not m:
            continue
        target, arg = m.group(1), m.group(2)
        txt = a.get_text(strip=True)
        if txt in ('>', '»', 'Siguiente', 'Next', str(pagina_siguiente)):
            return target, arg
        if arg == f'Page${pagina_siguiente}':
            return target, arg
    return None, None

# ── Parsear tabla de licitaciones ─────────────────────────────────────────────

def parsear_tabla(soup):
    filas = []
    # Buscar tabla principal por clase o la tabla con más columnas
    tabla = None
    for t in soup.find_all('table'):
        ths = t.find_all('th')
        tds = t.find('tr') and t.find_all('tr')[0].find_all('td')
        if len(ths) >= 3:
            tabla = t
            break
    if not tabla:
        for t in soup.find_all('table'):
            rows = t.find_all('tr')
            if len(rows) > 2:
                tabla = t
                break
    if not tabla:
        return filas

    rows = tabla.find_all('tr')
    # Detectar índices de columnas desde el encabezado
    header_row = rows[0] if rows else None
    col_idx = {'numero': 0, 'objeto': 1, 'organismo': 2, 'estado': 3, 'fecha': 4}
    if header_row:
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]
        for i, h in enumerate(headers):
            if any(x in h for x in ['nro', 'número', 'numero', 'expediente']) or h == 'número de proceso':
                col_idx['numero'] = i
            elif any(x in h for x in ['objeto', 'descripcion', 'descripción', 'denominacion']):
                col_idx['objeto'] = i
            elif any(x in h for x in ['organismo', 'entidad', 'reparticion', 'repartición']):
                col_idx['organismo'] = i
            elif any(x in h for x in ['estado', 'etapa']):
                col_idx['estado'] = i
            elif any(x in h for x in ['fecha', 'apertura', 'vencimiento']):
                col_idx['fecha'] = i

    for row in rows[1:]:
        # Saltar la fila del paginador del GridView (links "Page$N" del control de páginas)
        links_fila = row.find_all('a', href=True)
        if links_fila and all(re.search(r"__doPostBack\('[^']+','Page\$\d+'\)", a['href']) for a in links_fila):
            continue

        celdas = row.find_all('td')
        if len(celdas) < 2:
            continue
        texts = [c.get_text(strip=True) for c in celdas]

        def get_col(key, default=''):
            idx = col_idx.get(key, -1)
            return texts[idx] if 0 <= idx < len(texts) else default

        # Capturar URL directa o postback target de "Descargar Pliego"
        url = URL_LICITACIONES
        postback_target = ''
        for celda in celdas:
            a = celda.find('a', href=True)
            if not a:
                continue
            href = a['href']
            if not href.startswith('javascript'):
                url = href if href.startswith('http') else SITE_ROOT + href.lstrip('/')
                postback_target = ''
                break
            m = re.search(r"__doPostBack\('([^']+)'", href)
            if m:
                postback_target = m.group(1)

        fila = {
            'numero_proceso':   get_col('numero'),
            'objeto':           get_col('objeto'),
            'organismo':        get_col('organismo'),
            'estado':           get_col('estado'),
            'fecha_apertura':   get_col('fecha'),
            'url':              url,
            'postback_target':  postback_target,
        }
        if fila['numero_proceso'] or fila['objeto']:
            filas.append(fila)

    return filas

# ── Obtener URL real del pliego via postback ──────────────────────────────────

def obtener_url_pliego(session, form_action, form_data, postback_target):
    """Simula el click en 'Descargar Pliego' y devuelve la URL resultante."""
    if not postback_target:
        return None
    try:
        data = dict(form_data)
        data['__EVENTTARGET']   = postback_target
        data['__EVENTARGUMENT'] = ''
        resp = session.post(form_action, data=data, timeout=30, allow_redirects=True)
        # Si hubo una redirección a una URL distinta, esa es la del pliego
        if resp.url and resp.url != form_action:
            return resp.url
        # Buscar en los headers
        loc = resp.headers.get('Location', '')
        if loc:
            return loc if loc.startswith('http') else SITE_ROOT + loc.lstrip('/')
    except Exception as e:
        print(f'    [SC] Error obteniendo URL pliego: {e}')
    return None

# ── Claude clasificador ────────────────────────────────────────────────────────

def clasificar(fila):
    if not ANTHROPIC_KEY:
        return {'clasificacion': 'REVISAR', 'rubro': 'Sin clasificar',
                'analisis': 'ANTHROPIC_API_KEY no configurada'}

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = (
        "Sos experto en licitaciones de salud en Argentina. "
        "FEDAFAR es una droguería mayorista de Salta que vende medicamentos, "
        "insumos médicos, descartables y reactivos a farmacias y hospitales.\n\n"
        f"Licitación:\n"
        f"- Objeto: {fila['objeto']}\n"
        f"- Organismo: {fila['organismo']}\n"
        f"- Estado: {fila['estado']}\n"
        f"- Fecha apertura: {fila['fecha_apertura']}\n\n"
        'Respondé SOLO con este JSON (sin markdown):\n'
        '{"clasificacion":"APLICA","rubro":"...","analisis":"...","productos":["nombre genérico 1","nombre genérico 2"]}\n\n'
        'APLICA = claramente medicamentos, insumos, reactivos, descartables\n'
        'REVISAR = posiblemente relevante (equipamiento sanitario, servicios hospitalarios)\n'
        'NO_APLICA = sin relación con droguería\n'
        'rubro: máx 40 chars | analisis: máx 120 chars\n'
        'productos: lista de nombres genéricos (DCI) de medicamentos/insumos EXPLÍCITAMENTE '
        'mencionados en el objeto. NO inferir ni completar: si el objeto dice "PROVISION DE MEDICAMENTOS" '
        'sin nombrar cuáles, devolvé array vacío. Solo incluir lo que está escrito textualmente. '
        'Máx 10 items, array vacío si no hay nombres concretos.'
    )
    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=400,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = resp.content[0].text.strip()
        # Quitar markdown fences si Claude las agrega
        text = re.sub(r'^```json?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text)
    except Exception as e:
        print(f'      [Claude error] {e}')
        return {'clasificacion': 'REVISAR', 'rubro': 'Error', 'analisis': str(e)[:100]}

# ── Supabase ──────────────────────────────────────────────────────────────────

def ya_existe(sb, numero):
    if not numero:
        return False
    try:
        r = sb.table('licitaciones').select('id').eq('numero_proceso', numero).execute()
        return bool(r.data)
    except:
        return False

def guardar(sb, fila, analisis):
    clasificacion = analisis.get('clasificacion', 'REVISAR')
    record = {
        'numero_proceso': fila['numero_proceso'][:100],
        'objeto':         fila['objeto'][:500],
        'organismo':      fila['organismo'][:200],
        'fecha_apertura': fila['fecha_apertura'][:50],
        'estado':         fila['estado'][:50],
        'clasificacion':        clasificacion,
        'analisis':             f"{analisis.get('rubro','')} — {analisis.get('analisis','')}",
        'productos_detectados': json.dumps(analisis.get('productos', []), ensure_ascii=False),
        'url':            fila['url'][:500],
        'fecha_scraping': datetime.now(timezone.utc).isoformat(),
        'notificado':     False,
    }
    try:
        sb.table('licitaciones').insert(record).execute()
        # NO se agrega al CRM acá: la clasificación es solo por título, sin items.
        # El pase al pipeline lo decide sc_pliego_scraper.py una vez que descargó
        # el pliego, extrajo los items y verificó que matcheen con el catálogo.
        return True
    except Exception as e:
        print(f'  [ERROR guardar] {e}')
        return False

# ── Procesamiento de filas ────────────────────────────────────────────────────

def procesar_pagina(sb, soup, estado, session=None):
    """Procesa todas las filas de una página ya parseada.
    estado: dict con 'guardadas', 'procesadas' y 'vistos' (set de números).
    session: si se pasa (modo requests), intenta resolver la URL del pliego.
    Devuelve False si la página no tenía filas (señal de fin)."""
    filas = parsear_tabla(soup)
    if not filas:
        return False

    for fila in filas:
        numero = fila['numero_proceso']
        if numero in estado['vistos']:
            continue
        estado['vistos'].add(numero)

        texto = f"{fila['objeto']} {fila['organismo']}"
        if not contiene_keyword(texto):
            continue

        estado['procesadas'] += 1

        if ya_existe(sb, numero):
            print(f'  [SKIP] {numero}')
            continue

        print(f'  [+] {numero} — {fila["objeto"][:55]}')

        # Obtener URL real del pliego si hay postback (solo modo requests)
        if session is not None and fila.get('postback_target'):
            url_pliego = obtener_url_pliego(
                session, get_form_action(soup),
                extraer_form_data(soup), fila['postback_target']
            )
            if url_pliego:
                fila['url'] = url_pliego
                print(f'      → Pliego: {url_pliego[:70]}')

        analisis = clasificar(fila)
        print(f'      → {analisis.get("clasificacion")} | {analisis.get("rubro","")}')

        if guardar(sb, fila, analisis):
            estado['guardadas'] += 1

        time.sleep(0.5)

    return True

# ── Estrategia Playwright (local): recorre todas las páginas ──────────────────

def _contenido_estable(page, intentos=4):
    """page.content() puede fallar si el DOM se está actualizando por un
    postback AJAX. Reintenta unas veces con una pausa breve."""
    for _ in range(intentos - 1):
        try:
            return page.content()
        except Exception:
            page.wait_for_timeout(600)
    return page.content()

def _scrape_playwright(sb, estado):
    from playwright.sync_api import sync_playwright
    print('  Modo: Playwright (paginación completa)')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page()
        try:
            page.goto(URL_LICITACIONES, wait_until='networkidle', timeout=30000)
            for pagina in range(1, MAX_PAGINAS + 1):
                print(f'  — Página {pagina} —')
                try:
                    html = _contenido_estable(page)
                except Exception as e:
                    print(f'  [aviso] No se pudo leer la página {pagina}: {e}')
                    break
                soup = BeautifulSoup(html, 'html.parser')
                if not procesar_pagina(sb, soup, estado):
                    print('  Sin datos, fin.')
                    break

                target, arg = obtener_evento_pagina(soup, pagina + 1)
                if not target:
                    print('  Sin más páginas.')
                    break

                link = page.locator(f"a[href*=\"'{arg}'\"]")
                if link.count() == 0:
                    print('  Sin más páginas (link no encontrado).')
                    break
                try:
                    link.first.click()
                    page.wait_for_load_state('networkidle', timeout=30000)
                    page.wait_for_timeout(1000)
                except Exception as e:
                    print(f'  [aviso] Falló el avance a la página {pagina + 1}: {e}')
                    break
        finally:
            browser.close()

# ── Estrategia requests (Render): solo página 1 ───────────────────────────────

def _scrape_requests(sb, estado):
    print('  Modo: requests (solo página 1 — sin Playwright)')
    session = requests.Session()
    session.headers.update(HEADERS)
    print(f'  GET {URL_LICITACIONES}')
    resp = session.get(URL_LICITACIONES, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, 'html.parser')
    print('  — Página 1 —')
    procesar_pagina(sb, soup, estado, session=session)

# ── Main ──────────────────────────────────────────────────────────────────────

def run_scraper():
    print('=== Scraper Licitaciones ===')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('[ERROR] Faltan SUPABASE_URL / SUPABASE_KEY')
        return 0

    sb     = create_client(SUPABASE_URL, SUPABASE_KEY)
    estado = {'guardadas': 0, 'procesadas': 0, 'vistos': set()}

    try:
        import playwright  # noqa: F401
        tiene_playwright = True
    except ImportError:
        tiene_playwright = False

    try:
        if tiene_playwright:
            _scrape_playwright(sb, estado)
        else:
            _scrape_requests(sb, estado)
    except Exception as e:
        print(f'  [ERROR scraping] {e}')
        # Solo caer a requests si Playwright no llegó a procesar nada
        # (p.ej. chromium no instalado). Si ya procesó páginas, conservamos
        # el resultado y no re-escaneamos.
        if tiene_playwright and estado['procesadas'] == 0:
            print('  Playwright no procesó nada; reintentando en modo requests...')
            try:
                _scrape_requests(sb, estado)
            except Exception as e2:
                print(f'  [ERROR requests fallback] {e2}')

    print(f'\n[OK] Filtradas: {estado["procesadas"]} | Guardadas nuevas: {estado["guardadas"]}')
    return estado['guardadas']


if __name__ == '__main__':
    run_scraper()
