#!/usr/bin/env python3
"""
jujuy_mail_scraper.py — Ingesta licitaciones de Jujuy que llegan por email.

El Hospital Materno Infantil de Jujuy (hncomprasjujuy2023@gmail.com) manda
"Contrataciones Directas" y "Pedidos de Provisión" con el pliego en PDF adjunto.
Este script lee la casilla por IMAP, baja los PDF, extrae los items con Claude
(reusa el parser de SaltaCompra), sube el pliego a Storage y guarda en Supabase.

Corre localmente en el sync nocturno. No marca los mails como leídos (BODY.PEEK).
"""

import os, sys, re, time, imaplib, email, json
from email.header import decode_header
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from datetime import datetime, timezone
from supabase import create_client

# Reuso de piezas ya probadas
from sc_pliego_scraper import (parsear_pdf, get_storage_client, asegurar_bucket,
                               subir_pliego, evaluar_crm)
from match_catalogo import cargar_terminos_catalogo

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']
EMAIL_HOST   = os.environ.get('EMAIL_HOST', 'imap.mail2world.com')
EMAIL_USER   = os.environ.get('EMAIL_USER', '')
EMAIL_PASS   = os.environ.get('EMAIL_PASS', '')

REMITENTE = 'hncomprasjujuy2023'
ORGANISMO = 'Hospital Materno Infantil - Jujuy'
TMP_DIR   = Path(__file__).parent / 'tmp_jujuy'

# ── Helpers ───────────────────────────────────────────────────────────────────

def dec(s):
    if not s:
        return ''
    out = []
    for txt, enc in decode_header(s):
        out.append(txt.decode(enc or 'utf-8', 'replace') if isinstance(txt, bytes) else txt)
    return ''.join(out)

def extraer_numero(subject):
    s = subject.upper()
    if 'ORDEN DE COMPRA' in s:
        tipo = 'OC'
    elif 'PEDIDO DE PROVISION' in s or 'PED DE PROV' in s or 'PED. DE PROV' in s:
        tipo = 'PP'
    elif 'CONTRATACION DIRECTA' in s or s.strip().startswith('CD'):
        tipo = 'CD'
    else:
        tipo = ''
    m = re.search(r'N[°ºO]?\s*([\d]+(?:[-/]\d+)?)', s)
    num = m.group(1) if m else ''
    if not num:
        m2 = re.search(r'\b(\d{2,6})\b', s)
        num = m2.group(1) if m2 else ''
    return (f'{tipo} {num}').strip() or subject.strip()[:60]

def primer_pdf(msg):
    """Devuelve (bytes, nombre) del primer adjunto PDF, o (None, None)."""
    for part in msg.walk():
        fn = part.get_filename()
        if fn and part.get_content_type() == 'application/pdf':
            try:
                return part.get_payload(decode=True), dec(fn)
            except Exception:
                pass
    return None, None

def ya_existe(sb, numero):
    try:
        r = sb.table('licitaciones').select('id').eq('numero_proceso', numero).eq('fuente', 'jujuy').execute()
        return bool(r.data)
    except Exception:
        return False

# ── IMAP con reconexión (Mail2World corta seguido) ────────────────────────────

def _conectar():
    M = imaplib.IMAP4_SSL(EMAIL_HOST, 993)
    M.login(EMAIL_USER, EMAIL_PASS)
    M.select('INBOX')
    return M

def _fetch_uid(M, uid, parts):
    """Fetch por UID con reconexión ante caída de socket. Devuelve (M, data)."""
    for _ in range(3):
        try:
            typ, data = M.uid('FETCH', uid, parts)
            if typ == 'OK' and data and data[0]:
                return M, data
        except (imaplib.IMAP4.abort, imaplib.IMAP4.error, OSError):
            pass
        try:
            M.logout()
        except Exception:
            pass
        time.sleep(1)
        M = _conectar()
    return M, [None]

# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    print('=== Scraper Licitaciones Jujuy (email) ===')
    if not EMAIL_USER or not EMAIL_PASS:
        print('[ERROR] Faltan EMAIL_USER / EMAIL_PASS en .env')
        return 0

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    TMP_DIR.mkdir(exist_ok=True)
    sb_admin = get_storage_client()
    asegurar_bucket(sb_admin)

    try:
        M = _conectar()
        print(f'  Login OK ({EMAIL_USER})')
    except Exception as e:
        print(f'  [ERROR login IMAP] {e}')
        return 0

    typ, data = M.uid('SEARCH', 'TEXT', REMITENTE)
    uids = data[0].split() if data and data[0] else []
    print(f'  Mails de Jujuy en bandeja: {len(uids)}')

    # ── FASE 1 (IMAP): bajar headers + PDF de los nuevos, y CERRAR la conexión.
    # Así no queda IMAP inactivo durante las llamadas lentas a Claude (Mail2World
    # corta las conexiones ociosas).
    nuevos = []  # (numero, subj, pdf_bytes)
    for uid in uids:
        M, hdata = _fetch_uid(M, uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
        if not hdata or not isinstance(hdata[0], tuple):
            continue
        msg  = email.message_from_bytes(hdata[0][1])
        frm  = dec(msg.get('From', ''))
        subj = dec(msg.get('Subject', ''))
        if REMITENTE not in frm.lower():
            continue
        if 'ORDEN DE COMPRA' in subj.upper():
            continue  # es una orden (post-adjudicación), no una licitación a cotizar
        numero = extraer_numero(subj)
        if ya_existe(sb, numero):
            continue
        M, bdata = _fetch_uid(M, uid, '(BODY.PEEK[])')
        if not bdata or not isinstance(bdata[0], tuple):
            print(f'      [aviso] no se pudo bajar {numero}')
            continue
        full = email.message_from_bytes(bdata[0][1])
        pdf_bytes, _ = primer_pdf(full)
        if not pdf_bytes:
            print(f'  [skip] {numero}: sin PDF adjunto')
            continue
        nuevos.append((numero, subj, pdf_bytes))

    try:
        M.logout()
    except Exception:
        pass

    print(f'  Nuevas con PDF a procesar: {len(nuevos)}')
    if not nuevos:
        print('[OK] Nada nuevo.')
        return 0

    # ── FASE 2 (Claude + DB): sin IMAP. Throttle entre PDFs por el rate limit.
    terminos = cargar_terminos_catalogo()
    guardadas = 0
    THROTTLE = 22  # seg entre PDFs (tier 1: 50k tokens/min)

    for i, (numero, subj, pdf_bytes) in enumerate(nuevos):
        if i > 0:
            time.sleep(THROTTLE)
        print(f'  [+] {numero} — {subj[:55]}')

        items = parsear_pdf(pdf_bytes, subj)
        if items is None:   # rate limit persistente: no guardar, se reintenta otra corrida
            print('      items pendientes (rate limit), se reintenta luego')
            continue
        nombres = [it['descripcion'] for it in items if it.get('descripcion')]
        print(f'      {len(items)} items extraídos')

        record = {
            'numero_proceso':       numero[:100],
            'objeto':               subj[:500],
            'organismo':            ORGANISMO,
            'fecha_apertura':       '',
            'estado':               'Por cotizar',
            'clasificacion':        'REVISAR',
            'analisis':             'Jujuy (email) — Hospital Materno Infantil',
            'productos_detectados': json.dumps(nombres, ensure_ascii=False),
            'items_detalle':        json.dumps(items,   ensure_ascii=False),
            'url':                  'email',
            'fuente':               'jujuy',
            'fecha_scraping':       datetime.now(timezone.utc).isoformat(),
            'notificado':           False,
        }
        try:
            res    = sb.table('licitaciones').insert(record).execute()
            lic_id = res.data[0]['id']
        except Exception as e:
            print(f'      [ERROR guardar] {e}')
            continue

        # Subir el PDF a Storage para el botón Pliego
        try:
            tmp = TMP_DIR / f'{lic_id}.pdf'
            tmp.write_bytes(pdf_bytes)
            url = subir_pliego(sb_admin, lic_id, tmp)
            if url:
                sb.table('licitaciones').update({'url': url}).eq('id', lic_id).execute()
            tmp.unlink(missing_ok=True)
        except Exception as e:
            print(f'      [aviso] no se pudo subir el pliego: {e}')

        if items:
            evaluar_crm(sb, lic_id, items, terminos)
        guardadas += 1

    print(f'\n[OK] Guardadas nuevas: {guardadas}')
    return guardadas


if __name__ == '__main__':
    run()
