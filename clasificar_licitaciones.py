#!/usr/bin/env python3
"""
clasificar_licitaciones.py — Filtro de relevancia (lista blanca) para no
inundar la bandeja con licitaciones que no cotizamos (prótesis, cirugía,
ortopedia, etc.).

Regla: una licitación queda en la bandeja (REVISAR) solo si:
  a) alguno de sus items matchea el catálogo de precios, O
  b) su título/items contienen una "palabra de interés" (rubros_interes.json),
     ej: diabetes, glucosa, Dexcom — cosas que cotizamos pero no están en el
     catálogo como para matchear.
Si no cumple ninguna (y no es lista negra), se marca NO_APLICA "sin
coincidencia con catálogo" → va a Descartadas (recuperable, se limpia sola).

Nunca toca:
  - Las que están en el CRM/pipeline.
  - Las APLICA (decisión humana/agente) — solo re-clasifica las REVISAR.

Corre en el sync (post-scrapers) y se puede correr suelto para limpiar lo viejo.
"""

import os, re, json, sys, unicodedata
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from supabase import create_client
from match_catalogo import cargar_terminos_catalogo, matchear_items
from filtro_descarte import motivo_descarte

_INTERES_PATH = Path(__file__).parent / 'rubros_interes.json'


def _norm(s):
    t = unicodedata.normalize('NFKD', str(s or ''))
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def cargar_palabras_interes():
    try:
        data = json.loads(_INTERES_PATH.read_text(encoding='utf-8'))
        return [_norm(p) for p in data.get('palabras_interes', []) if p]
    except Exception:
        return []


def es_relevante(objeto, items, terminos, palabras_interes):
    """True si matchea el catálogo O contiene una palabra de interés."""
    # a) match de catálogo
    if items:
        n, _ = matchear_items(items, terminos)
        if n > 0:
            return True
    # b) palabra de interés en título o items
    blob = _norm(objeto) + ' ' + _norm(' '.join(
        i.get('descripcion', '') for i in items if isinstance(i, dict)))
    return any(p in blob for p in palabras_interes)


def clasificar(sb=None):
    sb = sb or create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
    terminos = cargar_terminos_catalogo()
    interes  = cargar_palabras_interes()

    crm    = sb.table('licitaciones_crm').select('licitacion_id').execute().data or []
    en_crm = {str(c['licitacion_id']) for c in crm}
    # Solo las REVISAR (el default de scraping); APLICA y NO_APLICA no se tocan
    rows = sb.table('licitaciones').select('id,objeto,items_detalle,clasificacion') \
             .eq('clasificacion', 'REVISAR').limit(3000).execute().data or []

    descartadas = 0
    for r in rows:
        if str(r['id']) in en_crm:
            continue
        try:
            items = json.loads(r.get('items_detalle') or '[]')
        except Exception:
            items = []
        objeto = r.get('objeto') or ''
        items_txt = [i.get('descripcion', '') for i in items if isinstance(i, dict)]

        # Lista negra primero (rubros que nunca cotizamos) — mira título Y items,
        # porque cosas como "aguja trucut" vienen en los items, no en el título.
        mot = motivo_descarte(objeto, *items_txt)
        if mot:
            razon = f'Descartada automáticamente (regla: {mot})'
        elif es_relevante(objeto, items, terminos, interes):
            continue   # relevante → queda en la bandeja
        else:
            razon = 'Sin coincidencia con catálogo ni rubros de interés'

        sb.table('licitaciones').update({
            'clasificacion': 'NO_APLICA', 'analisis': razon,
        }).eq('id', r['id']).execute()
        descartadas += 1

    print(f'[OK] Licitaciones descartadas por relevancia: {descartadas}')
    return descartadas


if __name__ == '__main__':
    print('=== Clasificación de relevancia de licitaciones ===')
    clasificar()
