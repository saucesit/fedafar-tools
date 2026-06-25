#!/usr/bin/env python3
"""
email_scraper.py — Ingesta de licitaciones que llegan por email, de MÚLTIPLES
remitentes (hospitales y organismos de Salta y Jujuy).

Reemplaza a jujuy_mail_scraper.py: misma mecánica (IMAP Mail2World, 2 fases para
no tener IMAP ocioso durante Claude, reconexión, throttle por rate limit), pero
recorre la lista SENDERS. Cada remitente tiene una 'fuente' (slug estable, para
dedup) y un 'organismo' (etiqueta visible, se puede corregir sin romper nada).

Corre localmente en el sync de licitaciones. Usa BODY.PEEK (no marca leídos).
"""

import os, sys, re, time, imaplib, email, json
from email.header import decode_header
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

from datetime import datetime, timezone, timedelta
from supabase import create_client

# Reuso de piezas ya probadas
from sc_pliego_scraper import (parsear_pliego, get_storage_client, asegurar_bucket,
                               subir_pliego, evaluar_crm)
from match_catalogo import cargar_terminos_catalogo

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_KEY = os.environ['SUPABASE_KEY']
EMAIL_HOST   = os.environ.get('EMAIL_HOST', 'imap.mail2world.com')
EMAIL_USER   = os.environ.get('EMAIL_USER', '')
EMAIL_PASS   = os.environ.get('EMAIL_PASS', '')

TMP_DIR      = Path(__file__).parent / 'tmp_email'
VENTANA_DIAS = 3
_MESES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
_EXTS  = ('.pdf', '.docx', '.xlsx', '.xls')

# Remitentes de licitaciones. 'token' = texto para buscar (TEXT, Mail2World es
# quisquilloso con FROM). 'fuente' = slug estable (dedup). 'organismo' = etiqueta.
SENDERS = [
    {'token': 'hncomprasjujuy2023',        'fuente': 'jujuy',        'organismo': 'Hospital Materno Infantil - Jujuy'},
    {'token': 'patriciacomprashpmise',     'fuente': 'hpmi_salta',   'organismo': 'Hospital Público Materno Infantil S.E. - Salta'},
    {'token': 'licabiertasmsp',            'fuente': 'msp_salta',    'organismo': 'Ministerio de Salud Pública - Salta'},
    {'token': 'compras.ugpsalta',          'fuente': 'ugp_salta',    'organismo': 'UGP - Salta'},
    {'token': 'compras.honativia',         'fuente': 'onativia',     'organismo': 'Hospital Dr. Arturo Oñativia - Salta'},
    {'token': 'comprasfarmacia@ipssalta',  'fuente': 'ips_farmacia', 'organismo': 'IPS Salta - Farmacia'},
    {'token': 'comprashospitalpablosoria', 'fuente': 'pablo_soria',  'organismo': 'Hospital Pablo Soria - Jujuy'},
    {'token': 'compras@hospitalsanbernardo','fuente': 'san_bernardo','organismo': 'Hospital San Bernardo - Salta'},
    {'token': 'comprashsrjujuy',           'fuente': 'hsr_jujuy',    'organismo': 'Hospital San Roque - Jujuy'},
    {'token': 'crhj.compras',              'fuente': 'crhj',         'organismo': 'CRHJ - Jujuy'},
    {'token': 'hospitalpalpalacompras',    'fuente': 'palpala',      'organismo': 'Hospital de Palpalá - Jujuy'},
    {'token': 'comprasnopek',              'fuente': 'snopek',       'organismo': 'Hospital Snopek - Jujuy'},
    {'token': 'csdivisioncompras',         'fuente': 'cs_division',  'organismo': 'Centro de Salud - División Compras'},
    {'token': 'comprasspps',               'fuente': 'spps',         'organismo': 'SPPS'},
    {'token': 'comprasdirectasministerio', 'fuente': 'min_jujuy',    'organismo': 'Ministerio de Salud - Jujuy (Compras Directas)'},
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def dec(s):
    if not s:
        return ''
    out = []
    for txt, enc in decode_header(s):
        out.append(txt.decode(enc or 'utf-8', 'replace') if isinstance(txt, bytes) else txt)
    return ''.join(out)

def _fecha_since(dias):
    d = datetime.now() - timedelta(days=dias)
    return f'{d.day:02d}-{_MESES[d.month - 1]}-{d.year}'

def extraer_numero(subject):
    s = subject.upper()
    m = re.search(r'N[°ºO]?\s*(\d+(?:[-/]\d+)?)', s)
    if m:
        return f'N°{m.group(1)}'
    return re.sub(r'\s+', ' ', subject).strip()[:80] or 'sin-asunto'

def primer_adjunto(msg):
    """Devuelve (bytes, nombre) del primer adjunto PDF/Word/Excel, o (None, None)."""
    for part in msg.walk():
        fn = part.get_filename()
        if fn:
            fn = dec(fn)
            if fn.lower().endswith(_EXTS):
                try:
                    return part.get_payload(decode=True), fn
                except Exception:
                    pass
    return None, None

def ya_existe(sb, numero, fuente):
    try:
        r = sb.table('licitaciones').select('id').eq('numero_proceso', numero).eq('fuente', fuente).execute()
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
    print('=== Scraper Licitaciones por Email (multi-remitente) ===')
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

    since = _fecha_since(VENTANA_DIAS)
    print(f'  Ventana: desde {since} ({VENTANA_DIAS} días)\n')

    # ── FASE 1 (IMAP): bajar headers + adjuntos de los nuevos y CERRAR conexión.
    nuevos = []  # (fuente, organismo, numero, subj, ext, adj_bytes)
    for snd in SENDERS:
        token, fuente, organismo = snd['token'], snd['fuente'], snd['organismo']
        try:
            typ, data = M.uid('SEARCH', 'SINCE', since, 'TEXT', token)
        except Exception:
            M = _conectar()
            try:
                typ, data = M.uid('SEARCH', 'SINCE', since, 'TEXT', token)
            except Exception as e:
                print(f'  [{organismo}] error de búsqueda: {str(e)[:50]}')
                continue
        uids = data[0].split() if data and data[0] else []
        if not uids:
            continue
        print(f'  [{organismo}]: {len(uids)} mails en la ventana')

        for uid in uids:
            M, hdata = _fetch_uid(M, uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
            if not hdata or not isinstance(hdata[0], tuple):
                continue
            subj = dec(email.message_from_bytes(hdata[0][1]).get('Subject', ''))
            if 'ORDEN DE COMPRA' in subj.upper():
                continue  # post-adjudicación, no es licitación a cotizar
            numero = extraer_numero(subj)
            if ya_existe(sb, numero, fuente):
                continue
            M, bdata = _fetch_uid(M, uid, '(BODY.PEEK[])')
            if not bdata or not isinstance(bdata[0], tuple):
                continue
            full = email.message_from_bytes(bdata[0][1])
            adj_bytes, adj_name = primer_adjunto(full)
            if not adj_bytes:
                print(f'    [skip] {numero}: sin adjunto (PDF/Word/Excel)')
                continue
            ext = '.' + adj_name.lower().rsplit('.', 1)[-1]
            nuevos.append((fuente, organismo, numero, subj, ext, adj_bytes))

    try:
        M.logout()
    except Exception:
        pass

    print(f'\n  Nuevas con adjunto a procesar: {len(nuevos)}')
    if not nuevos:
        print('[OK] Nada nuevo.')
        return 0

    # ── FASE 2 (Claude + DB): sin IMAP. Throttle por el rate limit.
    terminos = cargar_terminos_catalogo()
    guardadas = 0
    THROTTLE  = 22

    for i, (fuente, organismo, numero, subj, ext, adj_bytes) in enumerate(nuevos):
        if i > 0:
            time.sleep(THROTTLE)
        print(f'  [+] [{organismo[:30]}] {numero} — {subj[:45]}')

        tmp = TMP_DIR / f'tmp{i}{ext}'
        tmp.write_bytes(adj_bytes)
        items = parsear_pliego(tmp, subj)
        if items is None:   # rate limit persistente: no guardar, se reintenta luego
            print('      items pendientes (rate limit), se reintenta luego')
            tmp.unlink(missing_ok=True)
            continue
        nombres = [it['descripcion'] for it in items if it.get('descripcion')]
        print(f'      {len(items)} items extraídos')

        record = {
            'numero_proceso':       numero[:100],
            'objeto':               subj[:500],
            'organismo':            organismo,
            'fecha_apertura':       '',
            'estado':               'Por cotizar',
            'clasificacion':        'REVISAR',
            'analisis':             f'Email — {organismo}',
            'productos_detectados': json.dumps(nombres, ensure_ascii=False),
            'items_detalle':        json.dumps(items,   ensure_ascii=False),
            'url':                  'email',
            'fuente':               fuente,
            'fecha_scraping':       datetime.now(timezone.utc).isoformat(),
            'notificado':           False,
        }
        try:
            res    = sb.table('licitaciones').insert(record).execute()
            lic_id = res.data[0]['id']
        except Exception as e:
            print(f'      [ERROR guardar] {e}')
            tmp.unlink(missing_ok=True)
            continue

        # Subir el adjunto a Storage para el botón Pliego
        try:
            dest = TMP_DIR / f'{lic_id}{ext}'
            tmp.rename(dest)
            url = subir_pliego(sb_admin, lic_id, dest)
            if url:
                sb.table('licitaciones').update({'url': url}).eq('id', lic_id).execute()
            dest.unlink(missing_ok=True)
        except Exception as e:
            print(f'      [aviso] no se pudo subir el pliego: {e}')
            tmp.unlink(missing_ok=True)

        if items:
            evaluar_crm(sb, lic_id, items, terminos)
        guardadas += 1

    print(f'\n[OK] Guardadas nuevas: {guardadas}')
    return guardadas


if __name__ == '__main__':
    run()
