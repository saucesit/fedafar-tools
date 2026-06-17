#!/usr/bin/env python3
"""Rellena items_detalle para licitaciones IPS sin items.
Las que IPS marca como 'no encontrada' se marcan NO_APLICA."""

import os, json, time
from pathlib import Path

env_path = Path(__file__).parent / '.env'
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from supabase import create_client
from ips_scraper import hacer_login, scrape_items

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

def run():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = sb.table('licitaciones').select('id,numero_proceso,url,items_detalle') \
             .eq('fuente', 'ips').execute().data or []

    pendientes = [r for r in rows if not r.get('items_detalle') or r['items_detalle'] in ('[]', 'null', '')]
    print(f'Licitaciones IPS sin items: {len(pendientes)} de {len(rows)}')
    if not pendientes:
        print('Nada que procesar.')
        return

    print('Haciendo login en IPS...')
    session, _ = hacer_login()
    print('Login OK\n')

    ok = sin_acceso = 0
    for r in pendientes:
        print(f'  {r["numero_proceso"]}')
        items, no_encontrada = scrape_items(session, r['url'])

        if no_encontrada:
            sb.table('licitaciones').update({'clasificacion': 'NO_APLICA'}).eq('id', r['id']).execute()
            print(f'    => sin acceso, marcada NO_APLICA')
            sin_acceso += 1
        else:
            nombres = [i['descripcion'] for i in items if i.get('descripcion')]
            sb.table('licitaciones').update({
                'items_detalle':        json.dumps(items,   ensure_ascii=False),
                'productos_detectados': json.dumps(nombres, ensure_ascii=False),
            }).eq('id', r['id']).execute()
            print(f'    => {len(items)} items guardados')
            ok += 1

        time.sleep(0.8)

    print(f'\n[OK] Con items: {ok} | Sin acceso (NO_APLICA): {sin_acceso}')

if __name__ == '__main__':
    run()
