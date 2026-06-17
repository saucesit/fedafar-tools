"""Re-analiza con Claude las licitaciones SaltaCompra que tienen productos_detectados
pero cuyo objeto es genérico (sin nombres concretos de medicamentos)."""

import os, json, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path('.env'))

from supabase import create_client
from licitaciones_scraper import clasificar

sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])

rows = sb.table('licitaciones') \
         .select('id,numero_proceso,objeto,organismo,estado,fecha_apertura,productos_detectados') \
         .eq('fuente', 'saltacompra').execute().data or []

con_productos = [r for r in rows if r.get('productos_detectados') and r['productos_detectados'] not in ('[]','null','')]
print(f'Licitaciones SC con productos: {len(con_productos)} de {len(rows)}')

actualizadas = 0
for r in con_productos:
    prods_antes = json.loads(r['productos_detectados'])
    print(f'\n  {r["numero_proceso"] or r["objeto"][:40]}')
    print(f'    Antes: {prods_antes}')

    fila = {
        'objeto':         r['objeto'],
        'organismo':      r['organismo'],
        'estado':         r['estado'],
        'fecha_apertura': r['fecha_apertura'],
    }
    analisis = clasificar(fila)
    prods_despues = analisis.get('productos', [])
    print(f'    Despues: {prods_despues}')

    sb.table('licitaciones').update({
        'productos_detectados': json.dumps(prods_despues, ensure_ascii=False),
    }).eq('id', r['id']).execute()
    actualizadas += 1
    time.sleep(0.3)

print(f'\n[OK] Actualizadas: {actualizadas}')
