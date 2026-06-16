#!/usr/bin/env python3
"""Scraper de licitaciones saltacompra.gob.ar para FEDAFAR."""

import os, re, json, time, sys
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
            if any(x in h for x in ['nro', 'número', 'numero', 'proceso', 'expediente']):
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
        celdas = row.find_all('td')
        if len(celdas) < 2:
            continue
        texts = [c.get_text(strip=True) for c in celdas]

        def get_col(key, default=''):
            idx = col_idx.get(key, -1)
            return texts[idx] if 0 <= idx < len(texts) else default

        # Buscar URL de detalle en cualquier celda
        url = URL_LICITACIONES
        for celda in celdas:
            a = celda.find('a', href=True)
            if a and not a['href'].startswith('javascript'):
                href = a['href']
                url = href if href.startswith('http') else SITE_ROOT + href.lstrip('/')
                break

        fila = {
            'numero_proceso': get_col('numero'),
            'objeto':         get_col('objeto'),
            'organismo':      get_col('organismo'),
            'estado':         get_col('estado'),
            'fecha_apertura': get_col('fecha'),
            'url':            url,
        }
        if fila['numero_proceso'] or fila['objeto']:
            filas.append(fila)

    return filas

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
        '{"clasificacion":"APLICA","rubro":"...","analisis":"..."}\n\n'
        'APLICA = claramente medicamentos, insumos, reactivos, descartables\n'
        'REVISAR = posiblemente relevante (equipamiento sanitario, servicios hospitalarios)\n'
        'NO_APLICA = sin relación con droguería\n'
        'rubro: máx 40 chars | analisis: máx 120 chars'
    )
    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=200,
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
    record = {
        'numero_proceso': fila['numero_proceso'][:100],
        'objeto':         fila['objeto'][:500],
        'organismo':      fila['organismo'][:200],
        'fecha_apertura': fila['fecha_apertura'][:50],
        'estado':         fila['estado'][:50],
        'clasificacion':  analisis.get('clasificacion', 'REVISAR'),
        'analisis':       f"{analisis.get('rubro','')} — {analisis.get('analisis','')}",
        'url':            fila['url'][:500],
        'fecha_scraping': datetime.now(timezone.utc).isoformat(),
        'notificado':     False,
    }
    try:
        sb.table('licitaciones').insert(record).execute()
        return True
    except Exception as e:
        print(f'  [ERROR guardar] {e}')
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def run_scraper():
    print('=== Scraper Licitaciones ===')
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('[ERROR] Faltan SUPABASE_URL / SUPABASE_KEY')
        return 0

    sb      = create_client(SUPABASE_URL, SUPABASE_KEY)
    session = requests.Session()
    session.headers.update(HEADERS)

    guardadas  = 0
    procesadas = 0

    try:
        print(f'  GET {URL_LICITACIONES}')
        resp = session.get(URL_LICITACIONES, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, 'html.parser')
    except Exception as e:
        print(f'  [ERROR] No se pudo cargar la página: {e}')
        return 0

    for pagina in range(1, MAX_PAGINAS + 1):
        print(f'  — Página {pagina} —')
        filas = parsear_tabla(soup)

        if not filas:
            print('  Sin datos, fin.')
            break

        for fila in filas:
            texto = f"{fila['objeto']} {fila['organismo']}"
            if not contiene_keyword(texto):
                continue

            procesadas += 1
            numero = fila['numero_proceso']

            if ya_existe(sb, numero):
                print(f'  [SKIP] {numero}')
                continue

            print(f'  [+] {numero} — {fila["objeto"][:55]}')
            analisis = clasificar(fila)
            print(f'      → {analisis.get("clasificacion")} | {analisis.get("rubro","")}')

            if guardar(sb, fila, analisis):
                guardadas += 1

            time.sleep(0.4)

        # Siguiente página
        target, arg = obtener_evento_pagina(soup, pagina + 1)
        if not target:
            print('  Sin más páginas.')
            break

        form_action = get_form_action(soup)
        form_data = extraer_form_data(soup)
        form_data['__EVENTTARGET']   = target
        form_data['__EVENTARGUMENT'] = arg
        try:
            resp = session.post(form_action, data=form_data, timeout=30)
            soup = BeautifulSoup(resp.content, 'html.parser')
        except Exception as e:
            print(f'  [ERROR paginación] {e}')
            break

        time.sleep(1)

    print(f'\n[OK] Filtradas: {procesadas} | Guardadas nuevas: {guardadas}')
    return guardadas


if __name__ == '__main__':
    run_scraper()
