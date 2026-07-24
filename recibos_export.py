#!/usr/bin/env python3
"""
recibos_export.py — Arma un PDF consolidado del mes con todos los recibos y la
firma de cada empleado estampada sobre la hoja.

Para cada recibo: toma la hoja original, le superpone (overlay) la imagen de la
firma en el área de firma del empleado + una línea "Firmado digitalmente por X
el FECHA (IP)", y junta todo en un único PDF.

Usa fpdf2 (ya en requirements) para el overlay y pypdf para fusionar/combinar.
"""

import io, base64
from fpdf import FPDF
from pypdf import PdfReader, PdfWriter


def _overlay_firma(w, h, firma_png, nombre, fecha, ip):
    """Crea una hoja (mismo tamaño w×h en pt) transparente con la firma y el
    texto en el área de firma del empleado. Devuelve bytes PDF."""
    pdf = FPDF(unit='pt', format=(w, h))
    pdf.set_auto_page_break(False)
    pdf.add_page()

    # Área de firma del empleado: banda izquierda LIBRE, entre el renglón de
    # "Obra Social" (~y=597) y la tabla de contribuciones (~y=666). Coords desde
    # arriba (fpdf pt). Ajustado para no pisar ningún texto del recibo.
    x0, y_linea = 48, 634
    # Imagen de la firma (PNG), apenas por encima de la línea.
    if firma_png:
        try:
            img = io.BytesIO(firma_png)
            pdf.image(img, x=x0, y=y_linea - 34, w=100, h=32)
        except Exception:
            pass
    # Línea y textos
    pdf.set_draw_color(60, 60, 60)
    pdf.line(x0, y_linea, x0 + 200, y_linea)
    pdf.set_font('Helvetica', 'B', 6.5)
    pdf.set_text_color(20, 20, 20)
    pdf.text(x0, y_linea + 8, 'FIRMA DEL EMPLEADO (DIGITAL)')
    pdf.set_font('Helvetica', '', 6)
    pdf.set_text_color(90, 90, 90)
    linea2 = f'{nombre} - {fecha}'
    if ip:
        linea2 += f'  (IP {ip})'
    pdf.text(x0, y_linea + 16, linea2)

    return bytes(pdf.output())


def estampar(recibo_pdf, firma_data_url, nombre, fecha, ip=''):
    """Devuelve la hoja del recibo con la firma estampada (1 página, bytes)."""
    firma_png = b''
    if firma_data_url and ',' in firma_data_url:
        try:
            firma_png = base64.b64decode(firma_data_url.split(',', 1)[1])
        except Exception:
            firma_png = b''

    base = PdfReader(io.BytesIO(recibo_pdf))
    page = base.pages[0]
    w = float(page.mediabox.width)
    h = float(page.mediabox.height)

    overlay_bytes = _overlay_firma(w, h, firma_png, nombre, fecha, ip)
    overlay = PdfReader(io.BytesIO(overlay_bytes)).pages[0]
    page.merge_page(overlay)

    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def combinar(hojas):
    """Une varias hojas (lista de bytes de PDFs de 1 página) en un solo PDF."""
    writer = PdfWriter()
    for b in hojas:
        for pg in PdfReader(io.BytesIO(b)).pages:
            writer.add_page(pg)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
