#!/usr/bin/env python3
"""Scraper de solicitudes IPS Salta para FEDAFAR."""

import os, re, time, json
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from pathlib import Path

env_path = Path(__file__).parent / '.env'
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from supabase import create_client
from filtro_descarte import motivo_descarte

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
IPS_USER     = os.environ.get('IPS_USER', '')
IPS_PASS     = os.environ.get('IPS_PASS', '')

LOGIN_URL = ('https://www.ipssalta.gov.ar/Cotizaciones/login.aspx'
             '?ReturnUrl=%2fCotizaciones%2fProveedor%2fwfPanelControl.aspx')
PANEL_URL = 'https://www.ipssalta.gov.ar/Cotizaciones/Proveedor/wfPanelControl.aspx'
BASE_URL  = 'https://www.ipssalta.gov.ar/Cotizaciones/Proveedor/'
LISTA_URL = BASE_URL + 'wfCotizaciones.aspx'   # lista COMPLETA (las 3 plataformas)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def extraer_numero(solicitud_txt):
    """Extrae N°XXXX/YYYY del texto de solicitud."""
    m = re.search(r'N[°ºº]\s*(\d+/\d+)', solicitud_txt)
    return f"N°{m.group(1)}" if m else solicitud_txt[:50]

def limpiar(txt):
    return txt.encode('latin-1', errors='replace').decode('latin-1').strip()

# ── Login ─────────────────────────────────────────────────────────────────────

def hacer_login():
    s = requests.Session()
    s.headers.update(HEADERS)

    r = s.get(LOGIN_URL, timeout=20)
    soup = BeautifulSoup(r.content, 'html.parser')

    def val(name):
        el = soup.find('input', {'name': name})
        return el['value'] if el else ''

    data = {
        '__EVENTTARGET':    '',
        '__EVENTARGUMENT':  '',
        '__VIEWSTATE':      val('__VIEWSTATE'),
        '__EVENTVALIDATION': val('__EVENTVALIDATION'),
        'txtUserName':      IPS_USER,
        'txtPassword':      IPS_PASS,
        'btnLogin':         'Entrar',
    }
    r2 = s.post(LOGIN_URL, data=data, timeout=20)
    if 'wfPanelControl' not in r2.url and 'PanelControl' not in r2.text:
        raise RuntimeError(f'Login IPS fallido. URL: {r2.url}')
    return s, r2

# ── Parsear solicitudes ───────────────────────────────────────────────────────

def _tabla_solicitudes(soup):
    """Encuentra la tabla de solicitudes (header Solicitud/Título/Rubro), o la
    de más filas como respaldo. Sirve tanto para el panel como para la lista."""
    candidatas = soup.find_all('table')
    for t in candidatas:
        filas = t.find_all('tr')
        if not filas:
            continue
        head = ' '.join(c.get_text(strip=True).lower() for c in filas[0].find_all(['th', 'td']))
        if 'solicitud' in head and ('rubro' in head or 'tulo' in head):
            return t
    return max(candidatas, key=lambda t: len(t.find_all('tr'))) if candidatas else None

def parsear_solicitudes(html_content):
    soup  = BeautifulSoup(html_content, 'html.parser')
    tabla = _tabla_solicitudes(soup)
    if not tabla:
        return []

    solicitudes = []
    for row in tabla.find_all('tr')[1:]:  # saltar header
        # Solo filas cotizables: tienen un link a un formulario de cotización
        a = row.find('a', href=re.compile(r'wfNuevaCotizacion', re.I))
        if not a:
            continue
        cells = row.find_all('td')
        if len(cells) < 3:
            continue

        solicitud_txt = cells[0].get_text(strip=True)
        titulo        = cells[1].get_text(strip=True)
        rubro         = cells[2].get_text(strip=True) if len(cells) > 2 else ''
        fecha_ap      = cells[3].get_text(strip=True) if len(cells) > 3 else ''
        hora_ap       = cells[4].get_text(strip=True) if len(cells) > 4 else ''

        href = a['href']
        link = href if href.startswith('http') else BASE_URL + href.lstrip('/')

        solicitudes.append({
            'numero_proceso': extraer_numero(solicitud_txt),
            'objeto':         titulo,
            'organismo':      'IPS Salta',
            'rubro':          rubro,
            'fecha_apertura': f"{fecha_ap} {hora_ap}".strip(),
            'estado':         'Abierta',
            'url':            link,
        })

    return solicitudes

# ── Scraping de ítems del pliego ─────────────────────────────────────────────

def scrape_items(session, url):
    """Entra al pliego de cada solicitud y extrae la lista de productos.
    Retorna (items, no_encontrada) donde no_encontrada=True si IPS dice que
    la solicitud no existe para este usuario (proveedor no habilitado)."""
    if not url:
        return [], False
    try:
        r    = session.get(url, timeout=20)
        soup = BeautifulSoup(r.content, 'html.parser')

        # IPS avisa en JS cuando el proveedor no tiene acceso a esa solicitud
        for script in soup.find_all('script'):
            if 'solicitud no fue encontrada' in script.get_text().lower():
                print('    [IPS] Solicitud no accesible para este proveedor')
                return [], True

        items = []

        # Buscar tabla de detalle (id contiene gvDetSolicitud, o la siguiente a h3 "Detalle de Productos")
        tabla = soup.find('table', id=lambda x: x and 'gvDetSolicitud' in x)
        if not tabla:
            for tag in soup.find_all(string=lambda t: t and 'detalle de producto' in t.lower()):
                tabla = tag.find_parent().find_next('table')
                if tabla:
                    break

        if tabla:
            for row in tabla.find_all('tr')[1:]:
                tds = row.find_all('td')
                if len(tds) < 2:
                    continue

                # Columna "Producto": nombre en div siguiente al div "Nombre:"
                td_prod = tds[1]
                nombre = ''
                divs = td_prod.find_all('div')
                for i, d in enumerate(divs):
                    if d.get_text(strip=True).lower() == 'nombre:' and i + 1 < len(divs):
                        nombre = divs[i + 1].get_text(strip=True)
                        break
                if not nombre:
                    nombre = td_prod.get_text(' ', strip=True)
                if not nombre or len(nombre) < 3:
                    continue

                # Columna "Cantidad": puede estar en input[value] o texto del td
                cantidad = ''
                if len(tds) > 2:
                    inp = tds[2].find('input')
                    cantidad = inp['value'].strip() if inp and inp.get('value') else tds[2].get_text(strip=True)

                items.append({'descripcion': nombre, 'cantidad': cantidad, 'unidad': ''})

        print(f'    Ítems encontrados: {len(items)}')
        return items[:50], False
    except Exception as e:
        print(f'    [IPS] Error ítems: {e}')
        return [], False

# ── Supabase ──────────────────────────────────────────────────────────────────

def ya_existe(sb, numero):
    if not numero:
        return False
    try:
        r = sb.table('licitaciones').select('id').eq('numero_proceso', numero).eq('fuente', 'ips').execute()
        return bool(r.data)
    except:
        return False

def guardar(sb, sol, clasificacion='REVISAR', analisis=None):
    items = sol.get('items', [])
    nombres = [i['descripcion'] for i in items if i.get('descripcion')]
    record = {
        'numero_proceso':      sol['numero_proceso'][:100],
        'objeto':              sol['objeto'][:500],
        'organismo':           sol['organismo'],
        'fecha_apertura':      sol['fecha_apertura'][:50],
        'estado':              sol['estado'],
        'clasificacion':       clasificacion,
        'analisis':            analisis if analisis is not None else f"IPS — {sol['rubro']}",
        'url':                 sol['url'][:500],
        'fecha_scraping':      datetime.now(timezone.utc).isoformat(),
        'notificado':          False,
        'fuente':              'ips',
        'productos_detectados': json.dumps(nombres,   ensure_ascii=False),
        'items_detalle':        json.dumps(items,     ensure_ascii=False),
    }
    try:
        sb.table('licitaciones').insert(record).execute()
        return True
    except Exception as e:
        print(f'  [ERROR guardar] {e}')
        return False

# ── Limpieza de solicitudes cerradas ──────────────────────────────────────────

def limpiar_cerradas(sb, session):
    """Marca NO_APLICA las solicitudes IPS de la BANDEJA cuyo acceso ya cerró
    IPS (ventana vencida). NUNCA toca las que están en el pipeline (CRM): esas
    el usuario las está trabajando y son sólo suyas."""
    rows = sb.table('licitaciones').select('id,url,clasificacion') \
             .eq('fuente', 'ips').neq('clasificacion', 'NO_APLICA').execute().data or []
    # Excluir las que están en el CRM: no se tocan bajo ningún concepto.
    crm    = sb.table('licitaciones_crm').select('licitacion_id').execute().data or []
    en_crm = {str(c['licitacion_id']) for c in crm}
    cerradas = 0
    for r in rows:
        if str(r['id']) in en_crm:
            continue  # en el pipeline → intocable
        url = r.get('url', '')
        if not url:
            continue
        try:
            resp = session.get(url, timeout=20)
            if 'solicitud no fue encontrada' in resp.text.lower():
                sb.table('licitaciones').update({
                    'clasificacion': 'NO_APLICA',
                    'analisis':      'IPS cerró el acceso (ventana de cotización vencida)',
                }).eq('id', r['id']).execute()
                cerradas += 1
        except Exception as e:
            print(f'    [IPS limpieza] Error en {url}: {e}')
        time.sleep(0.3)
    print(f'  Licitaciones IPS cerradas/descartadas: {cerradas}')
    return cerradas

# ── Main ──────────────────────────────────────────────────────────────────────

def run_scraper():
    print('=== Scraper IPS Salta ===')
    if not all([SUPABASE_URL, SUPABASE_KEY, IPS_USER, IPS_PASS]):
        print('[ERROR] Faltan variables de entorno (SUPABASE_URL/KEY o IPS_USER/PASS)')
        return 0

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    try:
        print(f'  Login como {IPS_USER}...')
        session, resp = hacer_login()
        print(f'  Login OK')
    except Exception as e:
        print(f'  [ERROR login] {e}')
        return 0

    # Leer la LISTA COMPLETA (las 3 plataformas: Insumos/Prótesis, Audífonos,
    # Medicamentos), no solo el panel (que mostraba un subconjunto chico).
    try:
        lista = session.get(LISTA_URL, timeout=30)
        solicitudes = parsear_solicitudes(lista.content)
    except Exception as e:
        print(f'  [aviso] No se pudo leer la lista completa ({e}); uso el panel')
        solicitudes = parsear_solicitudes(resp.content)
    print(f'  Solicitudes abiertas encontradas: {len(solicitudes)}')

    guardadas = 0
    descartadas = 0
    for sol in solicitudes:
        numero = sol['numero_proceso']
        if ya_existe(sb, numero):
            print(f'  [SKIP] {numero}')
            continue

        # Filtro de descarte automático (audífonos, etc.): si el título matchea
        # una regla, se guarda NO_APLICA sin entrar al pliego (ahorra tiempo).
        motivo = motivo_descarte(sol['objeto'], sol.get('rubro', ''))
        if motivo:
            sol['items'] = []
            guardar(sb, sol, clasificacion='NO_APLICA',
                    analisis=f'Descartada automáticamente (regla: {motivo})')
            print(f'  [–] {numero} — descartada por filtro «{motivo}»')
            descartadas += 1
            continue

        print(f'  [+] {numero} — {sol["objeto"][:60]}')
        items, no_encontrada = scrape_items(session, sol['url'])
        if no_encontrada:
            print(f'  [SKIP] {numero} — proveedor sin acceso, se omite')
            time.sleep(0.5)
            continue
        sol['items'] = items
        time.sleep(0.5)
        if guardar(sb, sol):
            guardadas += 1

    print('\n  Revisando licitaciones IPS ya guardadas (limpieza de cerradas)...')
    limpiar_cerradas(sb, session)

    print(f'\n[OK] Guardadas nuevas: {guardadas} | Descartadas por filtro: {descartadas}')
    return guardadas


if __name__ == '__main__':
    run_scraper()
