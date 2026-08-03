#!/usr/bin/env python3
"""
camara_captura.py — Guarda el histórico de temperaturas de la cámara de frío
(ESPDesign) en nuestra base, para retención permanente (más allá de los 3 meses
que guarda ESP). Cada corrida trae desde la última lectura guardada hasta ahora
(backfill): se puede correr pocas veces al día sin perder datos.

Dedup por el `id` único de cada lectura de ESP (columna lectura_id UNIQUE).
Tabla: camara_lecturas (ver SQL en el repo / crear con RLS deshabilitado).
"""

import os, re, sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase import create_client
from espdesign import historico, machines

SUPABASE_URL = os.environ['SUPABASE_URL']
# Corre local: usa la service key (bypassea RLS) si está; si no, la anon.
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ['SUPABASE_KEY']
DIAS_BACKFILL_INICIAL = 15   # si la tabla está vacía, hasta cuántos días atrás backfillear
SOLAPE_MIN = 15              # re-pedir un poco de más para no dejar huecos
MAX_PAGINAS = 60            # tope de seguridad (cada página ~3000 filas / ~16h)


def _valor(v):
    """'20.56 °C' -> 20.56 ; '' / 'Sin datos' -> None."""
    if not v:
        return None
    m = re.search(r'-?\d+[.,]?\d*', v)
    return float(m.group().replace(',', '.')) if m else None


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def capturar():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Hasta dónde retroceder: última fecha guardada (con solape) o backfill inicial
    ult = sb.table('camara_lecturas').select('fecha').order('fecha', desc=True).limit(1).execute().data
    if ult and ult[0].get('fecha'):
        tope = datetime.fromisoformat(str(ult[0]['fecha']).replace('Z', '')) - timedelta(minutes=SOLAPE_MIN)
    else:
        tope = datetime.now() - timedelta(days=DIAS_BACKFILL_INICIAL)
    tope_str = tope.strftime('%Y-%m-%d %H:%M:%S')

    mid = (machines() or [{}])[0].get('_id')   # machine es obligatorio pero no filtra
    if mid is None:
        print('[ERROR] No se pudo obtener un equipo de ESP')
        return 0

    print(f'=== Captura cámara de frío ===')
    print(f'  Backfill hacia atrás hasta {tope_str} (paginando por hasta)')

    hasta = datetime.now()
    guardadas = 0
    for pag in range(MAX_PAGINAS):
        try:
            filas = historico((hasta - timedelta(days=40)).isoformat(), hasta.isoformat(), mid)
        except Exception as e:
            print(f'  [aviso] página {pag+1} falló: {str(e)[:60]}')
            break
        if not filas:
            break
        fechas = [x.get('fecha') for x in filas if x.get('fecha')]
        mas_vieja = min(fechas) if fechas else None

        recs = []
        for x in filas:
            lid = x.get('id')
            if not lid:
                continue
            recs.append({
                'lectura_id':    str(lid),
                'dispositivo':   (x.get('dispositivo') or '').strip(),
                'sensor_nombre': (x.get('nombre') or '').strip(),
                'sensor_key':    (x.get('sensor') or '').strip(),
                'valor':         _valor(x.get('valor')),
                'fecha':         x.get('fecha'),
            })
        for chunk in _chunks(recs, 500):
            try:
                sb.table('camara_lecturas').upsert(chunk, on_conflict='lectura_id',
                                                   ignore_duplicates=True).execute()
                guardadas += len(chunk)
            except Exception as e:
                print(f'  [aviso] chunk falló: {str(e)[:80]}')
        print(f'  pág {pag+1}: {len(filas)} filas ({mas_vieja} .. )')

        # ¿Llegamos al tope o la página ya no avanza?
        if not mas_vieja or mas_vieja <= tope_str:
            break
        nueva_hasta = datetime.fromisoformat(mas_vieja)
        if nueva_hasta >= hasta:   # no avanzó: cortar para no colgarse
            break
        hasta = nueva_hasta - timedelta(seconds=1)

    print(f'[OK] Procesadas (upsert, dedup por lectura_id): {guardadas}')
    return guardadas


if __name__ == '__main__':
    capturar()
