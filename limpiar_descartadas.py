#!/usr/bin/env python3
"""
limpiar_descartadas.py — Borra las licitaciones descartadas (NO_APLICA) viejas.

Corre en el sync de licitaciones y también lo usa el botón "Limpiar" del admin.
Borra las NO_APLICA con fecha_scraping de más de `dias` (default 15), SIN tocar
el pipeline (CRM). El umbral evita borrar algo que siga abierto en la fuente
(las ventanas de IPS cierran en pocos días, así que a los 15 ya están muertas).
"""

import os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DIAS_DEFAULT = 15


def limpiar(sb, dias=DIAS_DEFAULT):
    """Borra las NO_APLICA de más de `dias`, excluyendo las del CRM.
    Devuelve la cantidad borrada."""
    corte = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    rows = sb.table('licitaciones').select('id') \
             .eq('clasificacion', 'NO_APLICA').lt('fecha_scraping', corte).execute().data or []
    crm    = sb.table('licitaciones_crm').select('licitacion_id').execute().data or []
    en_crm = {str(c['licitacion_id']) for c in crm}
    ids = [r['id'] for r in rows if str(r['id']) not in en_crm]
    for lid in ids:
        sb.table('licitaciones').delete().eq('id', lid).execute()
    return len(ids)


def run():
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / '.env')
    from supabase import create_client
    sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    print('=== Limpieza de descartadas viejas ===')
    n = limpiar(sb, DIAS_DEFAULT)
    print(f'[OK] Descartadas borradas (+{DIAS_DEFAULT} días): {n}')
    return n


if __name__ == '__main__':
    run()
