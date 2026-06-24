#!/usr/bin/env python3
"""
agente_analisis.py — Agente de análisis de licitaciones de FEDAFAR (Fase 1).

Para cada item del pliego, el matcher determinístico (match_catalogo) propone
productos candidatos del catálogo por similitud de texto, y Claude CONFIRMA
cuáles realmente sirven (ej: distingue "aguja de biopsia" de "aguja hipodérmica").
Con eso calcula cobertura real, monto estimado y una recomendación.
"""

import os
import re
import json

import anthropic

from match_catalogo import candidatos_para_item, _num

_LETRAS = 'abcdefgh'


def analizar_licitacion(objeto, organismo, items, productos, key=None):
    key = key or os.environ.get('ANTHROPIC_API_KEY', '')

    # 1) Candidatos por item (determinístico, generoso)
    cand_map = []
    bloques  = []
    for idx, it in enumerate(items):
        desc = it.get('descripcion', '') if isinstance(it, dict) else str(it)
        cant = it.get('cantidad', '')   if isinstance(it, dict) else ''
        cands = candidatos_para_item(desc, productos, top=6)
        cand_map.append(cands)

        lineas = [f"[{idx}] {desc[:90]} | cant {cant}"]
        if cands:
            for li, c in enumerate(cands):
                lineas.append(f"    {_LETRAS[li]}) {c['name']}")
        else:
            lineas.append("    (sin candidatos en catálogo)")
        bloques.append("\n".join(lineas))

    # 2) Claude confirma los matches reales
    verdicts, recomendacion, analisis_texto = _confirmar_con_claude(
        objeto, organismo, bloques, key
    )

    # 3) Armar resultado con cobertura y monto reales
    detalle   = []
    cubiertos = 0
    monto     = 0.0
    for idx, it in enumerate(items):
        if isinstance(it, dict):
            desc, cant_txt, unidad = it.get('descripcion', ''), it.get('cantidad', ''), it.get('unidad', '')
        else:
            desc, cant_txt, unidad = str(it), '', ''

        op   = (verdicts.get(idx) or {}).get('opcion')
        prod = None
        if op and op in _LETRAS:
            li = _LETRAS.index(op)
            if li < len(cand_map[idx]):
                prod = cand_map[idx][li]

        if prod:
            cubiertos += 1
            cant = _num(cant_txt)
            if cant and prod.get('price'):
                monto += cant * float(prod['price'])

        otros = [c for c in cand_map[idx] if c is not prod][:2]
        detalle.append({
            'descripcion': desc,
            'cantidad':    cant_txt,
            'unidad':      unidad,
            'match': None if not prod else {
                'producto':  prod['name'],
                'precio':    prod.get('price'),
                'principio': prod.get('principio'),
            },
            'alternativas': [{'producto': c['name'], 'precio': c.get('price')} for c in otros],
        })

    total = len(items)
    return {
        'cubiertos':      cubiertos,
        'total':          total,
        'pct':            round(cubiertos / total * 100) if total else 0,
        'monto_estimado': round(monto, 2),
        'recomendacion':  recomendacion,
        'analisis_texto': analisis_texto,
        'items':          detalle,
    }


def _confirmar_con_claude(objeto, organismo, bloques, key):
    """Devuelve (verdicts{idx:{opcion}}, recomendacion, analisis_texto)."""
    if not key:
        return {}, 'evaluar', 'Sin ANTHROPIC_API_KEY configurada.'

    prompt = (
        "Sos analista de licitaciones de FEDAFAR, droguería mayorista de Salta que vende "
        "medicamentos, insumos médicos, descartables y reactivos. Para cada item de un "
        "pliego te doy productos CANDIDATOS de nuestro catálogo (elegidos por parecido de "
        "texto). Decidí, item por item, si alguno de los candidatos REALMENTE sirve para "
        "cotizar ese item.\n\n"
        "Sé estricto: mismo principio activo o mismo insumo concreto. Ejemplos de lo que NO "
        "sirve: una 'aguja hipodérmica' NO cubre una 'aguja de biopsia'; un antibiótico NO "
        "cubre un cemento dental. Si ningún candidato sirve, opcion=null.\n\n"
        f"Objeto: {objeto}\n"
        f"Organismo: {organismo}\n\n"
        "ITEMS Y CANDIDATOS:\n" + "\n\n".join(bloques) + "\n\n"
        "Respondé SOLO este JSON (sin markdown):\n"
        '{"items":[{"i":0,"opcion":"a"|"b"|null}, ...],'
        '"recomendacion":"cotizar|evaluar|descartar",'
        '"analisis_texto":"2-3 frases: por qué y en qué enfocarse, máx 280 chars"}\n'
        "recomendacion: 'cotizar' si cubrimos buena parte y es nuestro rubro; 'evaluar' si "
        "es parcial o dudoso; 'descartar' si casi no tenemos nada o no es nuestro rubro."
    )
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=800,
            messages=[{'role': 'user', 'content': prompt}]
        )
        text = resp.content[0].text.strip()
        text = re.sub(r'^```json?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        data = json.loads(text)
        verdicts = {v['i']: v for v in data.get('items', []) if 'i' in v}
        return verdicts, data.get('recomendacion', 'evaluar'), data.get('analisis_texto', '')
    except Exception as e:
        return {}, 'evaluar', f'(análisis IA no disponible: {str(e)[:80]})'
