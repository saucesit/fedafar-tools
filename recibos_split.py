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

# CUIL del empleado: prefijos personales (20/23/24/27), NO el CUIT de la empresa (30).
# Funciona en cualquier formato de recibo, esté donde esté el CUIL en la hoja.
_RE_CUIL_EMP = re.compile(r'\b((?:20|23|24|27)[-\s]?\d{8}[-\s]?\d)\b')
# Formato MENSUAL ("RECIBO"): "APELLIDO Y NOMBRE: X  N° LEGAJO: N ..."
_RE_ID_MENSUAL = re.compile(r'APELLIDO Y NOMBRE:\s*(.+?)\s*N[^ ]*\s*LEGAJO:\s*(\d+)', re.IGNORECASE)
# Formato QUINCENAL ("RECIBO DE HABERES"): "Primera Julio 2026 NOMBRE LEGAJO SUELDO..."
_RE_ID_QUINC = re.compile(r'(Primera|Segunda)\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})\s+(.+?)\s+(\d{1,4})\s+\d+[.,]\d+', re.IGNORECASE)
_RE_FECHA = re.compile(r'\b\d{2}/(\d{2})/(\d{4})\b')

_MESES = {'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04', 'mayo': '05',
          'junio': '06', 'julio': '07', 'agosto': '08', 'septiembre': '09', 'setiembre': '09',
          'octubre': '10', 'noviembre': '11', 'diciembre': '12'}


def _norm_cuil(s):
    """Normaliza a 'XX-XXXXXXXX-X'. Devuelve '' si no son 11 dígitos."""
    d = re.sub(r'\D', '', s or '')
    return f'{d[:2]}-{d[2:10]}-{d[10]}' if len(d) == 11 else ''


def _parse_pagina(t):
    """Extrae (cuil, nombre, legajo, periodo) de una hoja, sea cual sea el formato."""
    mc   = _RE_CUIL_EMP.search(t)
    cuil = _norm_cuil(mc.group(1)) if mc else ''
    nombre, legajo, periodo = '', '', ''
    m1 = _RE_ID_MENSUAL.search(t)
    if m1:
        nombre, legajo = m1.group(1).strip(), m1.group(2)
        mf = _RE_FECHA.search(t)
        periodo = f'{mf.group(1)}/{mf.group(2)}' if mf else ''
    else:
        m2 = _RE_ID_QUINC.search(t)
        if m2:
            quincena, mes, anio = m2.group(1), m2.group(2).lower(), m2.group(3)
            nombre, legajo = m2.group(4).strip(), m2.group(5)
            mm = _MESES.get(mes, '')
            periodo = (f'{mm}/{anio} ({quincena.capitalize()} quinc.)' if mm
                       else f'{mes} {anio} ({quincena})')
    return cuil, nombre, legajo, periodo


def cargar_mapa():
    """Devuelve (cuil_a_username, legajo_a_username). El legajo es respaldo por si
    algún formato de recibo no trae el CUIL."""
    try:
        data = json.loads(_MAPA_PATH.read_text(encoding='utf-8'))
        return (data.get('cuil_a_username', {}) or {},
                {str(k): v for k, v in (data.get('legajo_a_username', {}) or {}).items()})
    except Exception:
        return {}, {}


def analizar(pdf_bytes):
    """Lee el PDF y devuelve el plan de reparto (sin publicar nada):
    lista de dicts con page_index, cuil, nombre_recibo, legajo, periodo, username
    (o None si no está en el mapa). Matchea por CUIL y, si no hay, por legajo.
    Deduplica original+duplicado por (llave del empleado + período).
    """
    import pdfplumber
    por_cuil, por_legajo = cargar_mapa()
    plan, vistos = [], set()
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, pg in enumerate(pdf.pages):
            t = pg.extract_text() or ''
            cuil, nombre, legajo, periodo = _parse_pagina(t)
            if not cuil and not legajo:
                plan.append({'page_index': i, 'cuil': '', 'nombre_recibo': '',
                             'legajo': '', 'periodo': '', 'username': None,
                             'error': 'No se pudo identificar al empleado en esta hoja'})
                continue
            # Dedup: misma persona + mismo período = copia (original/duplicado)
            clave = f'{cuil or legajo}|{periodo}'
            if clave in vistos:
                continue
            vistos.add(clave)
            username = por_cuil.get(cuil) or por_legajo.get(str(legajo))
            plan.append({
                'page_index':    i,
                'cuil':          cuil,
                'nombre_recibo': nombre,
                'legajo':        legajo,
                'periodo':       periodo,
                'username':      username,   # None => sin cuenta => sin asociar
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
