#!/usr/bin/env python3
"""
venta_inf_reporte.py — Hojas y reportes de VENTA INF (ventas informales +
consumo personal). La HOJA de venta NO lleva logo ni identificación: solo
producto, cantidad, precio y total (pedido de Facundo).
"""

import io
from datetime import datetime
from fpdf import FPDF


def _fmt(n):
    try:
        return f'{float(n):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return str(n)


def generar_hoja(venta):
    """PDF simple de una venta/consumo: sin logo, solo detalle y total.
    `venta`: dict con items [{name, cantidad, precio_unit, subtotal}], total,
    creado_en, tipo."""
    items = venta.get('items') or []
    pdf = FPDF(unit='mm', format='A4')
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    fecha = str(venta.get('creado_en') or '')[:16].replace('T', ' ')
    pdf.set_font('Helvetica', 'B', 13)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 8, 'Detalle', ln=1)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, f'Fecha: {fecha}', ln=1)
    pdf.ln(3)

    # Encabezado tabla
    cols = [('Producto', 100), ('Cant.', 18), ('P. Unit', 30), ('Subtotal', 32)]
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(20, 20, 20)
    pdf.set_draw_color(180, 180, 180)
    for t, w in cols:
        al = 'L' if t == 'Producto' else 'R'
        pdf.cell(w, 7, t, border='B', align=al)
    pdf.ln()

    pdf.set_font('Helvetica', '', 9)
    for it in items:
        nombre = str(it.get('name', ''))[:58]
        pdf.cell(cols[0][1], 6, nombre, border='B')
        pdf.cell(cols[1][1], 6, _fmt(it.get('cantidad')), border='B', align='R')
        pdf.cell(cols[2][1], 6, '$ ' + _fmt(it.get('precio_unit')), border='B', align='R')
        pdf.cell(cols[3][1], 6, '$ ' + _fmt(it.get('subtotal')), border='B', align='R')
        pdf.ln()

    pdf.ln(2)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(cols[0][1] + cols[1][1] + cols[2][1], 8, 'TOTAL', align='R')
    pdf.cell(cols[3][1], 8, '$ ' + _fmt(venta.get('total')), align='R')
    return bytes(pdf.output())


def generar_reporte_dia(fecha, ventas):
    """PDF del reporte diario: todas las ventas + consumos del día, agrupado por
    tipo y empleado, con totales. `ventas`: lista de filas de ventas_inf."""
    pdf = FPDF(unit='mm', format='A4')
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(0, 74, 153)
    pdf.cell(0, 9, 'Reporte VENTA INF', ln=1)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, f'Dia: {fecha}', ln=1)
    pdf.ln(2)

    for tipo, titulo in (('venta', 'Ventas'), ('consumo', 'Consumo personal')):
        grupo = [v for v in ventas if v.get('tipo') == tipo]
        subtotal = sum(float(v.get('total') or 0) for v in grupo)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(20, 20, 20)
        pdf.cell(0, 7, f'{titulo}  ({len(grupo)})   -   Total: $ {_fmt(subtotal)}', ln=1)
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(60, 60, 60)
        for v in grupo:
            hora = str(v.get('creado_en') or '')[11:16]
            n_items = len(v.get('items') or [])
            pdf.cell(0, 5, f'   {hora}  -  {v.get("empleado_nombre","")}  -  {n_items} items  -  $ {_fmt(v.get("total"))}', ln=1)
        pdf.ln(3)

    total_gral = sum(float(v.get('total') or 0) for v in ventas)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f'TOTAL DEL DIA: $ {_fmt(total_gral)}', ln=1)
    return bytes(pdf.output())
