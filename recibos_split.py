#!/usr/bin/env python3
"""
recibos_split.py — Divide el PDF único de recibos de sueldo (una hoja por
empleado) y asigna cada recibo a su cuenta en la app por CUIL (llave única).

Nunca matchea por nombre: el CUIL es un número único, imposible de confundir
(hay 3 "Federico" y 3 "Farjat" distintos). Los CUIL que no están en el mapa
`empleados_cuil.json` quedan SIN ASOCIAR (no se publican).

Uso: `analizar(pdf_bytes)` -> plan de reparto (para previsualizar, no publica).
     `partir_pagina(pdf_bytes, page_index)` -> bytes del recibo de 1 hoja.
"""

import re, json, io
from pathlib import Path

_MAPA_PATH = Path(__file__).parent / 'empleados_cuil.json'

_RE_ID = re.compile(
    r'APELLIDO Y NOMBRE:\s*(.+?)\s*N[^ ]*\s*LEGAJO:\s*(\d+)\s*'
    r'C\.?U\.?I\.?L\.?[^:]*:\s*([\d\-]+)', re.IGNORECASE)
_RE_FECHA = re.compile(r'\b\d{2}/(\d{2})/(\d{4})\b')


def cargar_mapa():
    """Devuelve {cuil: username}. Vacío si el archivo falta o está mal."""
    try:
        data = json.loads(_MAPA_PATH.read_text(encoding='utf-8'))
        return data.get('cuil_a_username', {}) or {}
    except Exception:
        return {}


def _periodo(texto):
    """Extrae MM/YYYY de la fecha de pago del recibo (ej: 30/06/2026 -> 06/2026)."""
    m = _RE_FECHA.search(texto or '')
    return f'{m.group(1)}/{m.group(2)}' if m else ''


def analizar(pdf_bytes):
    """Lee el PDF y devuelve el plan de reparto (sin publicar nada):
    lista de dicts con page_index, cuil, nombre_recibo, legajo, periodo,
    username (o None si no está en el mapa). Deduplica original+duplicado
    (misma llave = mismo CUIL): se queda con la primera aparición.
    """
    import pdfplumber
    mapa = cargar_mapa()
    plan, vistos = [], set()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, pg in enumerate(pdf.pages):
            t = pg.extract_text() or ''
            m = _RE_ID.search(t)
            if not m:
                plan.append({'page_index': i, 'cuil': '', 'nombre_recibo': '',
                             'legajo': '', 'periodo': '', 'username': None,
                             'error': 'No se pudo leer el CUIL de esta hoja'})
                continue
            nombre, legajo, cuil = m.group(1).strip(), m.group(2), m.group(3)
            if cuil in vistos:
                continue  # duplicado (copia) del mismo recibo
            vistos.add(cuil)
            plan.append({
                'page_index':    i,
                'cuil':          cuil,
                'nombre_recibo': nombre,
                'legajo':        legajo,
                'periodo':       _periodo(t),
                'username':      mapa.get(cuil),   # None => sin cuenta => sin asociar
            })
    return plan


def partir_pagina(pdf_bytes, page_index):
    """Devuelve los bytes de un PDF de 1 hoja (la página `page_index`)."""
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.add_page(reader.pages[page_index])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


if __name__ == '__main__':
    import sys
    pdf = Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else b''
    for r in analizar(pdf):
        dest = r['username'] or 'SIN ASOCIAR'
        print(f"  hoja {r['page_index']+1:2} | CUIL {r.get('cuil',''):14} | "
              f"{r.get('nombre_recibo',''):26} | {r.get('periodo',''):8} -> {dest}")
