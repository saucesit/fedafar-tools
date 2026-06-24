#!/usr/bin/env python3
"""
match_catalogo.py — Matchea items de un pliego contra el catálogo de FEDAFAR.

Se usa para decidir si una licitación es relevante (tiene items que vendemos)
antes de mandarla al pipeline/CRM. El mejor anclaje es el principio activo;
como respaldo se usan los tokens significativos del nombre comercial.
"""

import re
import unicodedata

# Palabras de forma farmacéutica / unidades / color / envase / ruido que NO son
# nombre de droga. Evitan falsos positivos (ej. "polvo", "doble" matcheando cosas).
_STOP = {
    'mg', 'ml', 'mcg', 'gr', 'kg', 'cm', 'mm', 'lt', 'mgml',
    'comp', 'compr', 'comprimido', 'comprimidos', 'caps', 'capsula', 'capsulas',
    'amp', 'ampolla', 'ampollas', 'vial', 'viales', 'frasco', 'fco', 'frascos',
    'caja', 'cajas', 'unidad', 'unidades', 'und', 'blister', 'sobre', 'sobres',
    'marca', 'solucion', 'sol', 'iny', 'inyectable', 'jeringa', 'jeringas',
    'kit', 'tiras', 'crema', 'pomada', 'gotas', 'jarabe', 'aerosol', 'spray',
    'por', 'para', 'con', 'sin', 'del', 'los', 'las', 'una', 'uno',
    'adquisicion', 'provision', 'pcte', 'paciente', 'destino', 'hospital',
    # formas / presentación
    'polvo', 'liquido', 'liquida', 'pasta', 'locion', 'gragea', 'grageas',
    'tableta', 'tabletas', 'granulado', 'suspension', 'emulsion', 'supositorio',
    'supositorios', 'ovulo', 'ovulos', 'parche', 'parches', 'oral', 'externo',
    # envase / packaging
    'envase', 'paquete', 'pote', 'pomo', 'tubo', 'tubos', 'sachet', 'bidon',
    'bolsa', 'bolsas', 'rollo', 'pieza', 'piezas', 'pares', 'tamano',
    # color / cualidad
    'verde', 'azul', 'rojo', 'roja', 'blanco', 'blanca', 'negro', 'negra',
    'amarillo', 'amarilla', 'claro', 'oscuro', 'doble', 'simple', 'tono',
    # genéricos varios
    'aprox', 'varios', 'varias', 'surtido', 'medida', 'medidas', 'color',
    'piedra', 'avio', 'tipo', 'segun', 'detalle', 'refrigerado',
}

_MIN_LEN = 4  # ignorar tokens cortos (mg, x, de...)


def _norm(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode('ascii').lower()
    s = re.sub(r'[^a-z0-9 ]', ' ', s)
    return s


def tokens_significativos(s):
    """Tokens 'tipo droga': largos, sin dígitos (descarta dosis tipo 200mcg,
    500mg) y que no sean formas farmacéuticas/ruido."""
    out = set()
    for t in _norm(s).split():
        if len(t) >= _MIN_LEN and not any(c.isdigit() for c in t) and t not in _STOP:
            out.add(t)
    return out


def cargar_terminos_catalogo():
    """Construye el set de términos del catálogo (principios + nombres comerciales)."""
    from api_app import parse_price_list
    prods = parse_price_list('contado')
    terminos = set()
    for p in prods:
        if p.get('principio'):
            terminos |= tokens_significativos(p['principio'])
        terminos |= tokens_significativos(p.get('name', ''))
    return terminos


def matchear_items(items, terminos):
    """Dado items_detalle (lista de dicts con 'descripcion') y el set de términos
    del catálogo, devuelve (cantidad_items_match, lista_de_terminos_match)."""
    matched = 0
    coincidencias = set()
    for it in items:
        desc = it.get('descripcion', '') if isinstance(it, dict) else str(it)
        toks = tokens_significativos(desc)
        inter = toks & terminos
        if inter:
            matched += 1
            coincidencias |= inter
    return matched, sorted(coincidencias)


# ── Cobertura: item del pliego → mejor(es) producto(s) de nuestro catálogo ────

def _num(v):
    """Parsea una cantidad de texto a número (formato es-AR)."""
    if v is None:
        return 0.0
    s = re.sub(r'[^\d,.]', '', str(v))
    if not s:
        return 0.0
    s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return 0.0

def candidatos_para_item(desc, productos, top=3):
    """Devuelve los productos del catálogo que mejor matchean una descripción,
    ordenados por puntaje (el principio activo pesa el doble que el nombre)."""
    toks = tokens_significativos(desc)
    if not toks:
        return []
    scored = []
    for p in productos:
        pp = tokens_significativos(p['principio']) if p.get('principio') else set()
        nm = tokens_significativos(p.get('name', ''))
        score = len(toks & pp) * 2 + len(toks & nm)
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    return [p for _, p in scored[:top]]

def analizar_cobertura(items, productos):
    """Cruza los items del pliego con el catálogo. Devuelve cobertura, el
    detalle item→producto con precios, y el monto estimado de venta."""
    detalle  = []
    cubiertos = 0
    monto     = 0.0
    for it in items:
        if isinstance(it, dict):
            desc = it.get('descripcion', '')
            cant_txt = it.get('cantidad', '')
            unidad   = it.get('unidad', '')
        else:
            desc, cant_txt, unidad = str(it), '', ''

        cands = candidatos_para_item(desc, productos)
        mejor = cands[0] if cands else None
        cant  = _num(cant_txt)

        if mejor:
            cubiertos += 1
            if cant and mejor.get('price'):
                monto += cant * float(mejor['price'])

        detalle.append({
            'descripcion': desc,
            'cantidad':    cant_txt,
            'unidad':      unidad,
            'match': None if not mejor else {
                'producto':  mejor['name'],
                'precio':    mejor.get('price'),
                'principio': mejor.get('principio'),
            },
            'alternativas': [
                {'producto': c['name'], 'precio': c.get('price')} for c in cands[1:3]
            ],
        })

    total = len(items)
    return {
        'cubiertos':      cubiertos,
        'total':          total,
        'pct':            round(cubiertos / total * 100) if total else 0,
        'monto_estimado': round(monto, 2),
        'items':          detalle,
    }


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / '.env')

    print('Cargando términos del catálogo...')
    terminos = cargar_terminos_catalogo()
    print(f'Términos de catálogo: {len(terminos)}\n')

    casos = [
        ('SOMATOTROFINA 12 MG VIAL – (MARCA SAIZEN)',                    'NO deberia matchear'),
        ('ACICLOVIR 500 MG COMPRIMIDOS X 10',                            'deberia matchear'),
        ('ADRENALINA 0.1% AMPOLLA X 1 ML',                               'deberia matchear'),
        ('ACIDO FOLICO 5MG COMPRIMIDOS',                                 'deberia matchear'),
        ('REPUESTOS VARIOS PARA MOTOVEHICULO INTERNO',                   'NO deberia matchear'),
        ('Budesonide + Formoterol Aerosol 200MCG/6 MCG',                 '?'),
        ('CARTELERIA Y SEÑALETICA PARA ONCOLOGIA',                       'NO deberia matchear'),
        ('GLICLAZIDA 60 MG COMPRIMIDOS DE LIBERACION MODIFICADA',        'deberia matchear'),
    ]
    for desc, esperado in casos:
        n, coinc = matchear_items([{'descripcion': desc}], terminos)
        flag = '✅ MATCH' if n else '⬜ sin match'
        print(f'{flag}  [{esperado}]')
        print(f'     {desc}')
        if coinc:
            print(f'     términos: {coinc}')
        print()
