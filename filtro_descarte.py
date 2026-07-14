#!/usr/bin/env python3
"""
filtro_descarte.py — Filtro automático de licitaciones que NUNCA cotizamos.

Lee la lista de palabras de `reglas_descarte.json`. Si alguna aparece en el
título/objeto de una licitación, `es_descartable()` devuelve True y el scraper
la guarda directo como NO_APLICA (no llega a la bandeja ni se procesa el pliego).

Match tolerante: sin distinguir mayúsculas ni acentos (audífono == audifono).
Editar la lista NO requiere tocar este archivo: solo `reglas_descarte.json`.
"""

import json
import unicodedata
from pathlib import Path

_REGLAS_PATH = Path(__file__).parent / 'reglas_descarte.json'
_cache = None  # (mtime, [palabras_normalizadas])


def _normalizar(texto):
    """minúsculas + sin acentos, para comparar sin sorpresas."""
    if not texto:
        return ''
    t = unicodedata.normalize('NFKD', str(texto))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def cargar_palabras():
    """Devuelve la lista de palabras de descarte ya normalizadas. Se recarga
    sola si el JSON cambió (compara mtime), así el sync toma cambios en caliente."""
    global _cache
    try:
        mtime = _REGLAS_PATH.stat().st_mtime
    except OSError:
        return []
    if _cache is not None and _cache[0] == mtime:
        return _cache[1]
    try:
        data = json.loads(_REGLAS_PATH.read_text(encoding='utf-8'))
        palabras = [_normalizar(p) for p in data.get('palabras_descarte', []) if p]
    except Exception:
        palabras = []
    _cache = (mtime, palabras)
    return palabras


def es_descartable(*textos):
    """True si alguno de los textos (título, rubro, etc.) contiene una palabra
    de descarte. Se le pueden pasar varios: es_descartable(objeto, rubro)."""
    palabras = cargar_palabras()
    if not palabras:
        return False
    blob = _normalizar(' '.join(t for t in textos if t))
    return any(p in blob for p in palabras)


def motivo_descarte(*textos):
    """Devuelve la primera palabra que gatilló el descarte (para el análisis), o ''."""
    palabras = cargar_palabras()
    if not palabras:
        return ''
    blob = _normalizar(' '.join(t for t in textos if t))
    for p in palabras:
        if p in blob:
            return p
    return ''


if __name__ == '__main__':
    # Prueba rápida
    for t in ['AUDIFONO - AFILIADO: PEREZ JUAN', 'AMOXICILINA 500', 'Audífonos x 2', 'protesis de cadera']:
        print(f'{es_descartable(t)!s:5}  {motivo_descarte(t)!r:12}  <- {t}')
