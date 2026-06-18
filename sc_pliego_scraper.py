#!/usr/bin/env python3
"""
sc_pliego_scraper.py — Descarga y parsea pliegos de SaltaCompra con Playwright.
Corre localmente (no en Render). Requiere: playwright install chromium

Busca licitaciones SaltaCompra sin items_detalle, descarga el pliego PDF
de cada una, extrae los renglones con Claude y los guarda en Supabase.
"""

import os, json, re, time, base64
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from playwright.sync_api import sync_playwright
from supabase import create_client
import anthropic

SUPABASE_URL  = os.environ['SUPABASE_URL']
SUPABASE_KEY  = os.environ['SUPABASE_KEY']
ANTHROPIC_KEY = os.environ['ANTHROPIC_API_KEY']
SC_USER       = os.environ['SC_USER']
SC_PASS       = os.environ['SC_PASS']

URL_LISTA = 'https://saltacompra.gob.ar/Compras.aspx?qs=iouVZE0yWCs='
TMP_DIR   = Path(__file__).parent / 'tmp_sc_pliegos'

# ── Parsear PDF con Claude ────────────────────────────────────────────────────

def parsear_pdf(pdf_bytes, objeto):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode('utf-8')
    prompt = (
        f'Este es el pliego de una licitacion publica argentina. Objeto: {objeto}\n\n'
        'Extraé la tabla de renglones/items que se solicitan comprar. '
        'Para cada item incluí descripcion, cantidad y unidad (si existe). '
        'Respondi SOLO con un JSON array sin markdown:\n'
        '[{"descripcion":"...","cantidad":"...","unidad":"..."},...]\n'
        'Si no hay tabla de items, respondi [].'
    )
    try:
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': [
                {'type': 'document', 'source': {
                    'type': 'base64', 'media_type': 'application/pdf', 'data': pdf_b64
                }},
                {'type': 'text', 'text': prompt}
            ]}]
        )
        text = resp.content[0].text.strip()
        text = re.sub(r'^```json?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        return json.loads(text)
    except Exception as e:
        print(f'    [Claude] Error: {e}')
        return []

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    TMP_DIR.mkdir(exist_ok=True)

    rows = sb.table('licitaciones').select('id,numero_proceso,objeto,items_detalle') \
             .eq('fuente', 'saltacompra') \
             .in_('clasificacion', ['APLICA', 'REVISAR']).execute().data or []

    pendientes = [r for r in rows
                  if not r.get('items_detalle') or r['items_detalle'] in ('[]', 'null', '')]
    print(f'Licitaciones SC sin items: {len(pendientes)}')
    if not pendientes:
        print('Nada que procesar.')
        return

    with sync_playwright() as p:
        browser  = p.chromium.launch(headless=True)
        context  = browser.new_context(accept_downloads=True)
        page     = context.new_page()

        # Login
        print('Abriendo SaltaCompra...')
        page.goto(URL_LISTA, wait_until='networkidle', timeout=30000)
        page.locator('a:has-text("Ingresar")').click()
        page.locator('input[id*="txtUsername_txtTextBox"]').fill(SC_USER)
        page.locator('input[id*="txtPassword_txtTextBox"]').fill(SC_PASS)
        page.locator('input[id*="btnIngresar"]').click()
        page.wait_for_timeout(2500)

        # Verificar login
        if page.locator('a:has-text("Ingresar")').count() > 0:
            print('[ERROR] Login fallo — verificar credenciales SC_USER/SC_PASS')
            browser.close()
            return
        print('Login OK\n')

        ok = sin_pliego = 0
        for lic in pendientes:
            numero = lic['numero_proceso']
            objeto = lic['objeto']
            print(f'  {numero} — {objeto[:55]}')

            # Ir a la lista y buscar la fila
            page.goto(URL_LISTA, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(1000)

            fila = page.locator(f'tr:has-text("{numero}")').first
            if fila.count() == 0:
                # Intentar por primeras palabras del objeto
                palabras = ' '.join(objeto.split()[:4])
                fila = page.locator(f'tr:has-text("{palabras}")').first

            if fila.count() == 0:
                print(f'    No encontrado en la lista (puede haber vencido)')
                sb.table('licitaciones').update({'items_detalle': '[]'}).eq('id', lic['id']).execute()
                sin_pliego += 1
                continue

            btn = fila.locator('a:has-text("Pliego"), a:has-text("Descargar")')
            if btn.count() == 0:
                print(f'    Sin boton de descarga')
                sin_pliego += 1
                continue

            try:
                with page.expect_download(timeout=15000) as dl_info:
                    btn.first.click()
                dl = dl_info.value
                tmp = TMP_DIR / dl.suggested_filename
                dl.save_as(str(tmp))
                size = tmp.stat().st_size
                print(f'    Descargado: {tmp.name} ({size:,} bytes)')

                if tmp.suffix.lower() == '.pdf':
                    items = parsear_pdf(tmp.read_bytes(), objeto)
                else:
                    print(f'    Formato {tmp.suffix} no soportado aun')
                    items = []

                nombres = [i['descripcion'] for i in items if i.get('descripcion')]
                sb.table('licitaciones').update({
                    'items_detalle':        json.dumps(items,   ensure_ascii=False),
                    'productos_detectados': json.dumps(nombres, ensure_ascii=False),
                }).eq('id', lic['id']).execute()
                print(f'    => {len(items)} items guardados')
                ok += 1
                tmp.unlink(missing_ok=True)

            except Exception as e:
                print(f'    [ERROR] {e}')
                sin_pliego += 1

            time.sleep(1)

        browser.close()

    print(f'\n[OK] Con items: {ok} | Sin pliego: {sin_pliego}')


if __name__ == '__main__':
    run()
