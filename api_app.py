import os
import re
import json
import pandas as pd
from flask import Flask, jsonify, render_template, send_from_directory, request, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
CORS(app, supports_credentials=True, origins=[
    "https://fedafar-tools.onrender.com",
    "http://localhost:5001",
    "http://127.0.0.1:5001",
])

limiter = Limiter(get_remote_address, app=app, default_limits=[])

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
FEDAFAR_APP_DIR = os.path.join(BASE_DIR, 'fedafar-app')
PRICE_LIST_PATH   = os.path.join(BASE_DIR, 'price_list.xlsx')
PRINCIPIOS_PATH   = os.path.join(BASE_DIR, 'principios_activos.json')

def get_principios():
    try:
        with open(PRINCIPIOS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}
STOCK_URL       = 'http://192.168.0.35/fedafar/ALM_ArticulosPorDepositoExport-.xlsx'

SUPABASE_URL   = os.getenv('SUPABASE_URL')
SUPABASE_KEY   = os.getenv('SUPABASE_KEY')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', '')

# ── Supabase ───────────────────────────────────────────────────────────────────

def get_sb():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── Flask-Login ────────────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)

class ClientUser(UserMixin):
    def __init__(self, data):
        self.id              = str(data['id'])
        self.username        = data['username']
        self.nombre          = data['nombre']
        self.tipo_precio     = data['tipo_precio']
        self.genexus_client_id = data.get('genexus_client_id')

@login_manager.user_loader
def load_user(user_id):
    try:
        sb  = get_sb()
        res = sb.table('clientes').select('*').eq('id', user_id).single().execute()
        if res.data:
            return ClientUser(res.data)
    except Exception:
        pass
    return None

# ── Auth endpoints ─────────────────────────────────────────────────────────────

@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    data     = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Usuario y contraseña requeridos'}), 400

    try:
        sb       = get_sb()
        res      = sb.table('clientes') \
                     .select('*') \
                     .eq('username', username) \
                     .eq('activo', True) \
                     .single() \
                     .execute()
        user_data = res.data
    except Exception:
        return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401

    if not user_data:
        return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401

    if not check_password_hash(user_data['password_hash'], password):
        return jsonify({'error': 'Usuario o contraseña incorrectos'}), 401

    user = ClientUser(user_data)
    from datetime import datetime, timedelta, timezone
    login_user(user, remember=True, duration=timedelta(days=30))
    try:
        sb.table('clientes').update({'ultimo_acceso': datetime.now(timezone.utc).isoformat()}).eq('id', user_data['id']).execute()
    except Exception:
        pass
    return jsonify({
        'ok':          True,
        'nombre':      user.nombre,
        'tipo_precio': user.tipo_precio,
    })

@app.route('/api/logout', methods=['POST'])
def api_logout():
    logout_user()
    return jsonify({'ok': True})

@app.route('/api/me', methods=['GET'])
def api_me():
    if not current_user.is_authenticated:
        return jsonify({'authenticated': False}), 401
    return jsonify({
        'authenticated':      True,
        'id':                 current_user.id,
        'nombre':             current_user.nombre,
        'tipo_precio':        current_user.tipo_precio,
        'genexus_client_id':  current_user.genexus_client_id,
    })

@app.route('/api/cta-cte', methods=['GET'])
def api_cta_cte():
    if not current_user.is_authenticated:
        return jsonify({'error': 'No autenticado'}), 401
    if not current_user.genexus_client_id:
        return jsonify([])
    try:
        sb  = get_sb()
        res = sb.table('cuenta_corriente') \
                .select('fecha_comprobante,comprobante,fecha_vencimiento,importe,saldo,actualizado_en') \
                .eq('genexus_client_id', current_user.genexus_client_id) \
                .gt('saldo', 0) \
                .order('fecha_comprobante', desc=False) \
                .execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/todas-cuentas', methods=['GET'])
def api_todas_cuentas():
    if not current_user.is_authenticated:
        return jsonify({'error': 'No autenticado'}), 401
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb = get_sb()
        # Obtener todos los clientes activos con código Genexus
        clientes_res = sb.table('clientes') \
            .select('id,nombre,genexus_client_id,tipo_precio') \
            .eq('activo', True) \
            .not_.is_('genexus_client_id', 'null') \
            .order('nombre') \
            .execute()
        clientes = clientes_res.data or []

        # Para cada cliente, calcular saldo total pendiente
        ctas_res = sb.table('cuenta_corriente') \
            .select('genexus_client_id,saldo') \
            .gt('saldo', 0) \
            .execute()
        ctas = ctas_res.data or []

        # Agrupar saldos por cliente
        from collections import defaultdict
        saldos = defaultdict(float)
        conteos = defaultdict(int)
        for row in ctas:
            gx_id = row['genexus_client_id']
            saldos[gx_id]  += float(row['saldo'] or 0)
            conteos[gx_id] += 1

        resultado = []
        for c in clientes:
            gx_id = c['genexus_client_id']
            resultado.append({
                'nombre':                  c['nombre'],
                'genexus_client_id':       gx_id,
                'tipo_precio':             c['tipo_precio'],
                'saldo_total':             round(saldos.get(gx_id, 0), 2),
                'comprobantes_pendientes': conteos.get(gx_id, 0),
            })

        # Ordenar por mayor saldo primero
        resultado.sort(key=lambda x: x['saldo_total'], reverse=True)
        return jsonify(resultado)
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/cliente/<int:gx_id>/comprobantes', methods=['GET'])
def api_cliente_comprobantes(gx_id):
    """Comprobantes pendientes de una farmacia puntual (solo jefe/admin)."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'No autenticado'}), 401
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        cli = sb.table('clientes').select('nombre') \
                .eq('genexus_client_id', gx_id).limit(1).execute()
        nombre = cli.data[0]['nombre'] if cli.data else f'Cliente {gx_id}'

        res = sb.table('cuenta_corriente') \
                .select('fecha_comprobante,comprobante,fecha_vencimiento,importe,saldo,genexus_factura_id,iva_total,total_factura') \
                .eq('genexus_client_id', gx_id) \
                .gt('saldo', 0) \
                .order('fecha_comprobante', desc=False) \
                .execute()
        comps = res.data or []

        # Marcar cuáles tienen ítems sincronizados
        if comps:
            fac_ids = [c['genexus_factura_id'] for c in comps if c.get('genexus_factura_id')]
            if fac_ids:
                items_res = sb.table('comprobante_items') \
                              .select('genexus_factura_id') \
                              .in_('genexus_factura_id', fac_ids) \
                              .execute()
                con_items = {str(r['genexus_factura_id']) for r in (items_res.data or [])}
                for c in comps:
                    c['tiene_items'] = str(c.get('genexus_factura_id', '')) in con_items

        return jsonify({'nombre': nombre, 'comprobantes': comps})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Generación de comprobante PDF ─────────────────────────────────────────────

def _fmt_money(v):
    try:
        v = float(v)
    except (ValueError, TypeError):
        v = 0.0
    s = f"{v:,.2f}"
    return s.replace(',', 'X').replace('.', ',').replace('X', '.')  # → 1.234,56

def _latin1(s):
    """fpdf2 con fuentes core usa latin-1; reemplazamos caracteres no soportados."""
    return str(s if s is not None else '').encode('latin-1', 'replace').decode('latin-1')

def _build_comprobante_pdf(cliente_nombre, gx_id, comp, items=None):
    """
    Genera PDF del comprobante.
    Si items (list) está presente, incluye la tabla de renglones con totales.
    """
    from fpdf import FPDF
    from datetime import datetime

    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()

    AZUL  = (0, 74, 153)
    GRIS  = (90, 90, 90)
    NEGRO = (30, 30, 30)

    # ── Logo + encabezado ──────────────────────────────────────────────────────
    logo_path = os.path.join(BASE_DIR, 'static', 'logo fedafar antiguo.jpeg')
    try:
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=15, y=12, h=22)
    except Exception:
        pass

    pdf.set_xy(42, 14)
    pdf.set_text_color(*AZUL)
    pdf.set_font('Helvetica', 'B', 22)
    pdf.cell(0, 9, 'FEDAFAR', ln=True)
    pdf.set_x(42)
    pdf.set_text_color(*GRIS)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 6, _latin1('Droguería Integral'), ln=True)
    pdf.ln(12)

    # ── Título ─────────────────────────────────────────────────────────────────
    pdf.set_text_color(*AZUL)
    pdf.set_font('Helvetica', 'B', 13)
    pdf.cell(0, 7, 'COMPROBANTE DE CUENTA CORRIENTE', ln=True, align='C')
    pdf.ln(2)

    # ── Aviso informativo ──────────────────────────────────────────────────────
    pdf.set_fill_color(255, 247, 224)
    pdf.set_draw_color(230, 180, 60)
    pdf.set_text_color(140, 90, 0)
    pdf.set_font('Helvetica', 'I', 8)
    pdf.multi_cell(0, 4.5,
        _latin1('Documento informativo generado por la app FEDAFAR. '
                'NO valido como factura fiscal. La factura oficial es la emitida por el sistema de gestion.'),
        border=1, fill=True, align='C')
    pdf.ln(5)

    # ── Datos del comprobante (encabezado) ─────────────────────────────────────
    pdf.set_draw_color(210, 210, 210)
    pdf.set_text_color(*NEGRO)

    # Bloque izquierdo: cliente / bloque derecho: número y fechas
    y_bloque = pdf.get_y()
    ancho    = (pdf.w - 30) / 2   # mitad del ancho útil

    # Columna izquierda — cliente
    pdf.set_xy(15, y_bloque)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*AZUL)
    pdf.cell(ancho, 6, 'CLIENTE', ln=False)
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*AZUL)
    pdf.cell(ancho, 6, 'COMPROBANTE', ln=True)

    pdf.set_x(15)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.set_text_color(*NEGRO)
    pdf.cell(ancho, 6, _latin1(cliente_nombre[:40]), ln=False)
    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(ancho, 6, _latin1(comp.get('comprobante', '')), ln=True)

    pdf.set_x(15)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(*GRIS)
    pdf.cell(ancho, 5, _latin1(f'Codigo {gx_id}'), ln=False)
    pdf.cell(ancho, 5,
             _latin1(f"Emision: {(comp.get('fecha_comprobante') or '')[:10]}   "
                     f"Vence: {(comp.get('fecha_vencimiento') or '')[:10]}"),
             ln=True)
    pdf.ln(4)

    # ── Tabla de renglones (si hay ítems sincronizados) ────────────────────────
    if items:
        # Encabezados de columna
        # Anchos (mm): Articulo=80, Lab=30, Cant=15, P.Unit=22, IVA=13, Total=25
        cols = [
            ('Articulo',    80, 'L'),
            ('Laboratorio', 30, 'L'),
            ('Cant.',       15, 'C'),
            ('P. Unit.',    22, 'R'),
            ('IVA',         13, 'C'),
            ('Total',       25, 'R'),
        ]
        H = 7   # altura de fila

        pdf.set_fill_color(*AZUL)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_draw_color(255, 255, 255)
        for label, w, _ in cols:
            pdf.cell(w, H, _latin1(label), border=1, fill=True, align='C')
        pdf.ln()

        pdf.set_draw_color(210, 210, 210)
        pdf.set_text_color(*NEGRO)
        pdf.set_font('Helvetica', '', 8)

        for i, it in enumerate(items):
            pdf.set_fill_color(245, 248, 252) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)

            # Artículo puede ser largo → truncar con elipsis si es necesario
            art = _latin1(str(it.get('articulo', ''))[:46])
            lab = _latin1(str(it.get('laboratorio', ''))[:14])
            cant = f"{float(it.get('cantidad', 0)):g}"
            punit = '$ ' + _fmt_money(it.get('precio', 0))
            iva_label = _latin1(str(it.get('iva_label', '')).replace('I.V.A. ', '').replace('IVA ', ''))
            linea = '$ ' + _fmt_money(it.get('linea', 0))

            datos = [
                (art,       80, 'L'),
                (lab,       30, 'L'),
                (cant,      15, 'C'),
                (punit,     22, 'R'),
                (iva_label, 13, 'C'),
                (linea,     25, 'R'),
            ]
            for val, w, align in datos:
                pdf.cell(w, H, val, border=1, fill=True, align=align)
            pdf.ln()

        # ── Totales ──────────────────────────────────────────────────────────
        pdf.ln(2)
        pdf.set_draw_color(0, 74, 153)

        def fila_total(etiqueta, valor, bold=False, highlight=False):
            pdf.set_x(15 + 80 + 30 + 15)   # alineado a la derecha
            ancho_et = 35
            ancho_val = 25
            pdf.set_fill_color(*(AZUL if highlight else (240, 244, 250)))
            pdf.set_text_color(*(255, 255, 255) if highlight else NEGRO)
            pdf.set_font('Helvetica', 'B' if bold else '', 9)
            pdf.cell(ancho_et,  7, _latin1(etiqueta), border=1, fill=True, align='R')
            pdf.set_font('Helvetica', 'B' if bold else '', 9)
            pdf.cell(ancho_val, 7, _latin1('$ ' + _fmt_money(valor)), border=1, fill=True, align='R')
            pdf.ln()

        # Calcular totales desde los ítems si los de Genexus no están
        total_neto = sum(float(it.get('subtotal', 0)) for it in items)
        total_iva  = sum(float(it.get('impuesto', 0)) for it in items)
        total_tot  = sum(float(it.get('linea', 0))    for it in items)

        # Usar los del comprobante si están (vienen de la solapa General de Genexus)
        if comp.get('iva_total'):    total_iva = float(comp['iva_total'])
        if comp.get('total_factura'): total_tot = float(comp['total_factura'])

        fila_total('Neto sin IVA', total_neto)
        fila_total('IVA',          total_iva)
        fila_total('TOTAL',        total_tot,  bold=True, highlight=True)

    else:
        # Sin ítems: mostrar solo los datos del encabezado
        filas_hdrs = [
            ('Importe',         comp.get('importe', 0)),
            ('Saldo pendiente', comp.get('saldo',   0)),
        ]
        pdf.set_draw_color(210, 210, 210)
        for i, (et, val) in enumerate(filas_hdrs):
            es_saldo = et == 'Saldo pendiente'
            pdf.set_fill_color(245, 248, 252) if i % 2 == 0 else pdf.set_fill_color(255, 255, 255)
            pdf.set_font('Helvetica', 'B', 11)
            pdf.set_text_color(60, 60, 60)
            pdf.cell(60, 9, _latin1(et), border=1, fill=True)
            pdf.set_font('Helvetica', 'B' if es_saldo else '', 11)
            pdf.set_text_color(*(AZUL if es_saldo else NEGRO))
            pdf.cell(0, 9, _latin1('$ ' + _fmt_money(val)), border=1, fill=True, ln=True)

        pdf.ln(4)
        pdf.set_text_color(*GRIS)
        pdf.set_font('Helvetica', 'I', 8)
        pdf.cell(0, 5, _latin1('Los items detallados estaran disponibles tras el proximo sync nocturno.'), ln=True, align='C')

    # ── Pie ───────────────────────────────────────────────────────────────────
    pdf.ln(8)
    pdf.set_text_color(160, 160, 160)
    pdf.set_font('Helvetica', '', 7)
    emitido = datetime.now().strftime('%d/%m/%Y %H:%M')
    pdf.cell(0, 4,
             _latin1(f'Emitido el {emitido} - FEDAFAR Drogueria Integral, Salta, Argentina.'),
             ln=True, align='C')

    return bytes(pdf.output())

@app.route('/api/factura-pdf', methods=['GET'])
def api_factura_pdf():
    """Descarga el comprobante PDF de una factura puntual (solo jefe/admin)."""
    if not current_user.is_authenticated:
        return jsonify({'error': 'No autenticado'}), 401
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403

    gx_id       = request.args.get('cliente', '').strip()
    comprobante = request.args.get('comprobante', '').strip()
    if not gx_id or not comprobante:
        return jsonify({'error': 'Faltan parámetros cliente/comprobante'}), 400

    try:
        sb  = get_sb()
        cli = sb.table('clientes').select('nombre') \
                .eq('genexus_client_id', gx_id).limit(1).execute()
        nombre = cli.data[0]['nombre'] if cli.data else f'Cliente {gx_id}'

        res = sb.table('cuenta_corriente') \
                .select('fecha_comprobante,comprobante,fecha_vencimiento,importe,saldo,'
                        'genexus_factura_id,iva_total,total_factura') \
                .eq('genexus_client_id', gx_id) \
                .eq('comprobante', comprobante) \
                .limit(1).execute()
        if not res.data:
            return jsonify({'error': 'Comprobante no encontrado'}), 404

        comp_row = res.data[0]

        # Intentar traer ítems desde comprobante_items
        items = []
        fac_id = comp_row.get('genexus_factura_id')
        if fac_id:
            items_res = sb.table('comprobante_items') \
                          .select('*') \
                          .eq('genexus_factura_id', fac_id) \
                          .order('item_num') \
                          .execute()
            items = items_res.data or []

        pdf_bytes = _build_comprobante_pdf(nombre, gx_id, comp_row, items=items)

        from flask import Response
        safe = re.sub(r'[^A-Za-z0-9_-]+', '-', comprobante).strip('-') or 'comprobante'
        return Response(pdf_bytes, mimetype='application/pdf', headers={
            'Content-Disposition': f'attachment; filename="comprobante_{safe}.pdf"'
        })
    except Exception as e:
        print(f"[ERROR factura-pdf] {e}")
        return jsonify({'error': 'No se pudo generar el PDF'}), 500

# ── Admin Auth ────────────────────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('is_admin'):
            return jsonify({'error': 'No autorizado'}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/admin')
@app.route('/admin/')
def serve_admin():
    return render_template('admin.html')

@app.route('/api/admin/auto-auth', methods=['POST'])
def admin_auto_auth():
    """Autentica automáticamente al panel admin si el usuario logueado es de tipo admin."""
    if not current_user.is_authenticated or current_user.tipo_precio != 'admin':
        return jsonify({'error': 'No autorizado'}), 403
    session['is_admin'] = True
    return jsonify({'ok': True})

@app.route('/api/admin/login', methods=['POST'])
@limiter.limit("5 per minute")
def admin_login():
    data     = request.get_json() or {}
    password = data.get('password', '')
    if not ADMIN_PASSWORD or password != ADMIN_PASSWORD:
        return jsonify({'error': 'Contraseña incorrecta'}), 401
    session['is_admin'] = True
    return jsonify({'ok': True})

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.pop('is_admin', None)
    return jsonify({'ok': True})

@app.route('/api/admin/me', methods=['GET'])
def admin_me():
    return jsonify({'authenticated': bool(session.get('is_admin'))})

# ── Admin CRUD de clientes ─────────────────────────────────────────────────────

@app.route('/api/admin/clientes', methods=['GET'])
@admin_required
def admin_get_clientes():
    try:
        sb  = get_sb()
        res = sb.table('clientes') \
                .select('id,username,nombre,tipo_precio,genexus_client_id,activo,created_at') \
                .order('nombre') \
                .execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/clientes', methods=['POST'])
@admin_required
def admin_create_cliente():
    data     = request.get_json() or {}
    nombre   = data.get('nombre', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    tipo     = data.get('tipo_precio', 'contado')
    gx_id    = data.get('genexus_client_id')

    if not nombre or not username or not password:
        return jsonify({'error': 'Nombre, usuario y contraseña son obligatorios'}), 400
    if tipo not in ('contado', 'cta-cte', 'empleado', 'jefe', 'admin', 'jefe_deposito', 'farmaceutico'):
        return jsonify({'error': 'tipo_precio inválido'}), 400

    try:
        sb  = get_sb()
        res = sb.table('clientes').insert({
            'username':          username,
            'password_hash':     generate_password_hash(password),
            'nombre':            nombre,
            'tipo_precio':       tipo,
            'genexus_client_id': int(gx_id) if gx_id else None,
            'activo':            True,
        }).execute()
        return jsonify({'ok': True, 'cliente': res.data[0]}), 201
    except Exception as e:
        err = str(e)
        if 'unique' in err.lower():
            return jsonify({'error': f'El usuario "{username}" ya existe'}), 409
        return jsonify({'error': err}), 500

@app.route('/api/admin/clientes/<cliente_id>', methods=['PUT'])
@admin_required
def admin_update_cliente(cliente_id):
    data = request.get_json() or {}
    update = {}

    if 'nombre'            in data: update['nombre']            = data['nombre'].strip()
    if 'username'          in data: update['username']          = data['username'].strip()
    if 'tipo_precio'       in data: update['tipo_precio']       = data['tipo_precio']
    if 'genexus_client_id' in data: update['genexus_client_id'] = int(data['genexus_client_id']) if data['genexus_client_id'] else None
    if 'activo'            in data: update['activo']            = bool(data['activo'])
    if data.get('password'):
        update['password_hash'] = generate_password_hash(data['password'])

    if not update:
        return jsonify({'error': 'Sin datos para actualizar'}), 400

    try:
        sb  = get_sb()
        res = sb.table('clientes').update(update).eq('id', cliente_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Stock ──────────────────────────────────────────────────────────────────────

STOCK_JSON_PATH = os.path.join(BASE_DIR, 'stock_data.json')

def get_stock_data():
    stock_dict = {}

    # 1. Intentar desde la red interna (tiempo real, solo en red local)
    try:
        import requests
        from io import BytesIO
        r = requests.get(STOCK_URL, timeout=5)
        r.raise_for_status()
        df = pd.read_excel(BytesIO(r.content), skiprows=5, header=None,
            names=['Articulo','Descripcion','Tranzable','Existencia','Lote','FechaVenc','Serie','Cantidad'])
        df['Existencia'] = pd.to_numeric(df['Existencia'], errors='coerce').fillna(0)
        grouped = df.groupby('Descripcion')['Existencia'].sum()
        for nombre, stock in grouped.items():
            stock_dict[str(nombre).strip().upper()] = float(stock)
        print(f"Stock cargado: {len(stock_dict)} productos desde red interna.")
        return stock_dict
    except Exception:
        pass

    # 2. Fallback: usar stock_data.json generado por el sync diario
    try:
        with open(STOCK_JSON_PATH, 'r', encoding='utf-8') as f:
            stock_dict = json.load(f)
        print(f"Stock cargado: {len(stock_dict)} productos desde stock_data.json.")
    except Exception as e:
        print(f"Stock no disponible: {e}")

    return stock_dict

def clean_name_for_matching(name):
    name = name.upper()
    name = re.sub(r'\s+', ' ', name)
    name = name.replace("COMPR", "COMP")
    name = name.replace(" X ", "X")
    name = name.replace(" MG", "MG")
    return name.strip()

def fuzzy_stock_match(price_name, stock_dict):
    price_name_clean = clean_name_for_matching(price_name)
    if price_name_clean in stock_dict:
        return stock_dict[price_name_clean]
    parts = price_name_clean.split()
    for stock_name, stock_val in stock_dict.items():
        stock_parts = clean_name_for_matching(stock_name).split()
        match_count = sum(1 for part in parts if part in stock_parts)
        if match_count >= len(parts) - 1 and len(parts) > 1:
            return stock_val
    return None

def parse_price_list(tipo='contado'):
    products   = []
    stock_dict = get_stock_data()
    principios = get_principios()
    es_empleado = tipo in ('empleado', 'jefe', 'admin', 'farmaceutico', 'jefe_deposito')

    try:
        df = pd.read_excel(PRICE_LIST_PATH, skiprows=2, header=0)
        df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        MARKUP_C  = 1.195
        MARKUP_CC = 1.26

        # Columna de costo base (siempre existe)
        col_costo = 'precio_costo' if 'precio_costo' in df.columns else df.columns[3]
        df[col_costo] = pd.to_numeric(df[col_costo], errors='coerce').fillna(0)

        # Columnas explícitas de precio (opcionales en el Excel)
        tiene_contado = 'contado' in df.columns
        tiene_ctacte  = 'cta_cte'  in df.columns
        if tiene_contado:
            df['contado'] = pd.to_numeric(df['contado'], errors='coerce').fillna(0)
        if tiene_ctacte:
            df['cta_cte'] = pd.to_numeric(df['cta_cte'], errors='coerce').fillna(0)

        # Filtrar productos sin costo
        df = df[df[col_costo] > 0].reset_index(drop=True)

    except Exception as e:
        print(f"Error leyendo lista de precios: {e}")
        return []

    for id_counter, (_, row) in enumerate(df.iterrows(), start=1):
        costo = float(row[col_costo])

        # Usar precios explícitos si el Excel los tiene, sino aplicar markup
        price_contado = round(float(row['contado']), 2) if tiene_contado and row['contado'] > 0 \
                        else round(costo * MARKUP_C, 2)
        price_ctacte  = round(float(row['cta_cte']),  2) if tiene_ctacte  and row['cta_cte']  > 0 \
                        else round(costo * MARKUP_CC, 2)

        # price_val = precio principal de referencia (para IVA y clientes normales)
        price_val = price_ctacte if tipo == 'cta-cte' else price_contado

        # Quitar el código al final del nombre: "NOMBRE - 000000001" → "NOMBRE"
        col_art = 'artículo' if 'artículo' in df.columns else 'articulo'
        col_lab = 'laboratorio'
        articulo = str(row.get(col_art, row.iloc[1])).strip()
        name     = re.sub(r'\s*-\s*\d+\s*$', '', articulo).strip()
        lab      = str(row.get(col_lab, 'GENERICO')).strip() if pd.notna(row.get(col_lab, None)) else 'GENERICO'

        # Categoría
        category = "Otros"
        n = name.upper()
        if any(x in n for x in ["AMOX", "CEFA", "CLARITRO", "AZITRO"]):
            category = "Antibióticos"
        elif any(x in n for x in ["PARACETAMOL", "IBU", "DICLO", "NAPRO"]):
            category = "Analgésicos"
        elif any(x in n for x in ["DEXA", "MEPRED", "BETAME"]):
            category = "Corticoides"
        elif any(x in n for x in ["VALSAR", "ENALAPRIL", "ATORVA"]):
            category = "Cardiovascular"
        elif any(x in n for x in [
            "JERINGA", "AGUJA", "APOSI", "BAJALENGUA", "BARBIJO",
            "CATETER", "GASA", "GUANTE", "CUBRECAMILLA", "RECOLECT",
            "SONDA", "MICROPORE", "TELA ADHESIVA", "TERMOMETRO",
            "TUBO ENDOT", "TIRAS REAC", "ALCOHOL AL 70"
        ]):
            category = "Descartables"

        # IVA 21% para descartables
        if category == "Descartables":
            price_val     = round(price_val     * 1.21, 2)
            price_contado = round(price_contado * 1.21, 2)
            price_ctacte  = round(price_ctacte  * 1.21, 2)

        # Filtrar por stock (solo si hay datos disponibles)
        stock_val = None
        if len(stock_dict) > 0:
            stock_val = fuzzy_stock_match(name, stock_dict)
            if stock_val is None or stock_val <= 0:
                continue

        # Promos ACCU-CHEK
        promo   = None
        n_upper = name.upper()
        if "ACCU-CHEK GUIDE KIT" in n_upper:
            promo     = "🎁 Gratis con la compra de 4 cajas de Tiras Reactivas x50"
            price_val = 0
        elif "ACCU-CHEK GUIDE TIRAS" in n_upper and "50" in n_upper:
            promo = "🎁 Comprando 4 cajas, el equipo medidor va de regalo"

        principio = principios.get(name, '')
        if principio in ('insumo', 'desconocido'):
            principio = ''

        producto = {
            "id": id_counter, "name": name, "lab": lab,
            "price": price_val, "category": category, "promo": promo,
            "principio": principio
        }
        if es_empleado:
            producto["price_contado"] = price_contado
            producto["price_ctacte"]  = price_ctacte
        if tipo in ('jefe', 'admin') and stock_val is not None:
            producto["stock"] = int(stock_val)

        products.append(producto)

    return products

# ── Préstamos internos ────────────────────────────────────────────────────────

@app.route('/api/prestamos', methods=['GET'])
@login_required
def api_prestamos_list():
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        rol = current_user.tipo_precio
        if rol in ('jefe', 'admin'):
            # Traer préstamos y enriquecer con nombre del empleado manualmente
            res = sb.table('prestamos') \
                    .select('*') \
                    .order('created_at', desc=True) \
                    .execute()
            prestamos = res.data or []

            # Obtener nombres de empleados en una sola consulta
            if prestamos:
                emp_ids = list({p['empleado_id'] for p in prestamos})
                emp_res = sb.table('clientes') \
                             .select('id,nombre') \
                             .in_('id', emp_ids) \
                             .execute()
                nombres = {str(e['id']): e['nombre'] for e in (emp_res.data or [])}
                for p in prestamos:
                    p['clientes'] = {'nombre': nombres.get(str(p['empleado_id']), '?')}
        else:
            res = sb.table('prestamos') \
                    .select('*') \
                    .eq('empleado_id', current_user.id) \
                    .order('created_at', desc=True) \
                    .execute()
            prestamos = res.data or []
        return jsonify(prestamos)
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/pendientes-count', methods=['GET'])
@login_required
def api_prestamos_pendientes_count():
    """Cantidad de items que requieren acción del jefe/admin."""
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'count': 0})
    try:
        sb = get_sb()
        solicitudes = sb.table('prestamos') \
                        .select('id', count='exact') \
                        .eq('estado', 'pendiente') \
                        .execute()
        pagos_pend  = sb.table('prestamo_pagos') \
                        .select('id', count='exact') \
                        .eq('estado', 'informado') \
                        .execute()
        total = (solicitudes.count or 0) + (pagos_pend.count or 0)
        return jsonify({'count': total})
    except Exception as e:
        return jsonify({'count': 0})

@app.route('/api/prestamos', methods=['POST'])
@login_required
def api_prestamos_solicitar():
    """Solo jefe/admin pueden crear préstamos directamente (aprobados)."""
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'La creación de préstamos está deshabilitada para empleados. Consultá con tu jefe.'}), 403
    try:
        from datetime import datetime, timezone
        data           = request.get_json() or {}
        empleado_id    = data.get('empleado_id')
        monto          = float(data.get('monto', 0))
        cuotas         = int(data.get('cuotas', 1))
        monto_cuota    = float(data.get('monto_cuota') or 0)
        condiciones    = (data.get('condiciones_nota') or '').strip()

        if not empleado_id:
            return jsonify({'error': 'Seleccioná un empleado'}), 400
        if monto <= 0:
            return jsonify({'error': 'El monto debe ser mayor a 0'}), 400
        if cuotas < 1:
            return jsonify({'error': 'Las cuotas deben ser al menos 1'}), 400

        sb       = get_sb()
        existing = sb.table('prestamos') \
                     .select('id') \
                     .eq('empleado_id', empleado_id) \
                     .in_('estado', ['pendiente', 'aprobado']) \
                     .execute()
        if existing.data:
            return jsonify({'error': 'Este empleado ya tiene un préstamo activo'}), 400

        now = datetime.now(timezone.utc).isoformat()
        res = sb.table('prestamos').insert({
            'empleado_id':      empleado_id,
            'monto_solicitado': monto,
            'monto_aprobado':   monto,
            'cuotas_total':     cuotas,
            'monto_cuota':      monto_cuota if monto_cuota > 0 else None,
            'condiciones_nota': condiciones or None,
            'saldo_pendiente':  monto,
            'estado':           'aprobado',
            'aprobado_por':     current_user.id,
            'fecha_aprobacion': now,
        }).execute()
        return jsonify({'ok': True, 'prestamo': res.data[0]}), 201
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/<prestamo_id>/aprobar', methods=['POST'])
@login_required
def api_prestamos_aprobar(prestamo_id):
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data           = request.get_json() or {}
        monto_aprobado = float(data.get('monto_aprobado', 0))
        cuotas         = int(data.get('cuotas', 1))
        monto_cuota    = float(data.get('monto_cuota', 0))
        condiciones    = data.get('condiciones_nota', '').strip()
        if monto_aprobado <= 0:
            return jsonify({'error': 'Monto aprobado inválido'}), 400

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        sb  = get_sb()
        sb.table('prestamos').update({
            'estado':           'aprobado',
            'monto_aprobado':   monto_aprobado,
            'cuotas_total':     cuotas,
            'monto_cuota':      monto_cuota if monto_cuota > 0 else round(monto_aprobado / cuotas, 2),
            'condiciones_nota': condiciones or None,
            'saldo_pendiente':  monto_aprobado,
            'aprobado_por':     current_user.id,
            'fecha_aprobacion': now,
        }).eq('id', prestamo_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/<prestamo_id>/rechazar', methods=['POST'])
@login_required
def api_prestamos_rechazar(prestamo_id):
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data = request.get_json() or {}
        nota = data.get('nota', '').strip()
        sb   = get_sb()
        sb.table('prestamos').update({
            'estado':       'rechazado',
            'nota_rechazo': nota or None,
        }).eq('id', prestamo_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/<prestamo_id>/pago-directo', methods=['POST'])
@login_required
def api_prestamos_pago_directo(prestamo_id):
    """Jefe/admin registra un pago confirmado directamente (sin paso de informar)."""
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        from datetime import datetime, timezone
        data  = request.get_json() or {}
        monto = float(data.get('monto', 0))
        nota  = (data.get('nota') or '').strip()

        if monto <= 0:
            return jsonify({'error': 'El monto debe ser mayor a 0'}), 400

        sb = get_sb()
        pr = sb.table('prestamos').select('*').eq('id', prestamo_id).single().execute()
        if not pr.data or pr.data['estado'] != 'aprobado':
            return jsonify({'error': 'Préstamo no válido o no activo'}), 400

        now = datetime.now(timezone.utc).isoformat()

        # Insertar pago ya confirmado
        sb.table('prestamo_pagos').insert({
            'prestamo_id':     prestamo_id,
            'monto':           monto,
            'estado':          'confirmado',
            'nota_jefe':       nota or None,
            'informado_por':   current_user.id,
            'confirmado_por':  current_user.id,
            'fecha_informado': now,
            'fecha_confirmado': now,
        }).execute()

        # Actualizar saldo y estado del préstamo
        nuevo_saldo  = max(0, float(pr.data.get('saldo_pendiente') or 0) - monto)
        nuevo_estado = 'saldado' if nuevo_saldo == 0 else 'aprobado'
        sb.table('prestamos').update({
            'saldo_pendiente': nuevo_saldo,
            'estado':          nuevo_estado,
        }).eq('id', prestamo_id).execute()

        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/<prestamo_id>/pagos', methods=['GET'])
@login_required
def api_prestamos_get_pagos(prestamo_id):
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        pr  = sb.table('prestamos').select('empleado_id').eq('id', prestamo_id).single().execute()
        if not pr.data:
            return jsonify({'error': 'Préstamo no encontrado'}), 404
        if current_user.tipo_precio == 'empleado' and str(pr.data['empleado_id']) != str(current_user.id):
            return jsonify({'error': 'No autorizado'}), 403
        res = sb.table('prestamo_pagos') \
                .select('*') \
                .eq('prestamo_id', prestamo_id) \
                .order('created_at', desc=False) \
                .execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/<prestamo_id>/pagos', methods=['POST'])
@login_required
def api_prestamos_informar_pago(prestamo_id):
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data  = request.get_json() or {}
        monto = float(data.get('monto', 0))
        nota  = data.get('nota', '').strip()
        if monto <= 0:
            return jsonify({'error': 'El monto debe ser mayor a 0'}), 400

        sb   = get_sb()
        pr   = sb.table('prestamos').select('empleado_id,estado,saldo_pendiente').eq('id', prestamo_id).single().execute()
        if not pr.data:
            return jsonify({'error': 'Préstamo no encontrado'}), 404
        if current_user.tipo_precio == 'empleado' and str(pr.data['empleado_id']) != str(current_user.id):
            return jsonify({'error': 'No autorizado'}), 403
        if pr.data['estado'] != 'aprobado':
            return jsonify({'error': 'El préstamo no está activo'}), 400

        # Verificar que no haya ya un pago informado sin confirmar
        pend = sb.table('prestamo_pagos') \
                 .select('id') \
                 .eq('prestamo_id', prestamo_id) \
                 .eq('estado', 'informado') \
                 .execute()
        if pend.data:
            return jsonify({'error': 'Ya hay un pago pendiente de confirmación'}), 400

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        res = sb.table('prestamo_pagos').insert({
            'prestamo_id':    prestamo_id,
            'monto':          monto,
            'estado':         'informado',
            'nota_empleado':  nota or None,
            'informado_por':  current_user.id,
            'fecha_informado': now,
        }).execute()
        return jsonify({'ok': True, 'pago': res.data[0]}), 201
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/pagos/<pago_id>/confirmar', methods=['POST'])
@login_required
def api_prestamos_confirmar_pago(pago_id):
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data   = request.get_json() or {}
        nota   = data.get('nota', '').strip()
        sb     = get_sb()
        pago_r = sb.table('prestamo_pagos').select('*').eq('id', pago_id).single().execute()
        pago   = pago_r.data
        if not pago:
            return jsonify({'error': 'Pago no encontrado'}), 404
        if pago['estado'] != 'informado':
            return jsonify({'error': 'El pago ya fue procesado'}), 400

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        sb.table('prestamo_pagos').update({
            'estado':           'confirmado',
            'nota_jefe':        nota or None,
            'confirmado_por':   current_user.id,
            'fecha_confirmado': now,
        }).eq('id', pago_id).execute()

        # Descontar del saldo
        pr_r         = sb.table('prestamos').select('saldo_pendiente').eq('id', pago['prestamo_id']).single().execute()
        saldo_actual = float(pr_r.data['saldo_pendiente'] or 0)
        nuevo_saldo  = round(max(0, saldo_actual - float(pago['monto'])), 2)
        nuevo_estado = 'saldado' if nuevo_saldo == 0 else 'aprobado'
        sb.table('prestamos').update({
            'saldo_pendiente': nuevo_saldo,
            'estado':          nuevo_estado,
        }).eq('id', pago['prestamo_id']).execute()

        return jsonify({'ok': True, 'nuevo_saldo': nuevo_saldo, 'estado_prestamo': nuevo_estado})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/prestamos/pagos/<pago_id>/rechazar', methods=['POST'])
@login_required
def api_prestamos_rechazar_pago(pago_id):
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data   = request.get_json() or {}
        nota   = data.get('nota', '').strip()
        sb     = get_sb()
        pago_r = sb.table('prestamo_pagos').select('estado').eq('id', pago_id).single().execute()
        if not pago_r.data or pago_r.data['estado'] != 'informado':
            return jsonify({'error': 'Pago no encontrado o ya procesado'}), 400
        sb.table('prestamo_pagos').update({
            'estado':    'rechazado',
            'nota_jefe': nota or None,
        }).eq('id', pago_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Documentos de empleados ────────────────────────────────────────────────────

DOCS_TIPOS = {
    'recibo_sueldo':   'Recibo de Sueldo',
    'credencial_art':  'Credencial ART',
    'seguro_vehiculo': 'Seguro Vehículo',
    'carnet_conducir': 'Carnet de Conducir',
}
DOCS_RECIBOS        = {'recibo_sueldo'}
DOCS_DOCUMENTACION  = {'credencial_art', 'seguro_vehiculo', 'carnet_conducir'}

def _es_empleado_interno():
    """True si el usuario logueado tiene rol interno (empleado/jefe/admin/farmaceutico/jefe_deposito)."""
    return current_user.is_authenticated and \
           current_user.tipo_precio in ('empleado', 'jefe', 'admin', 'farmaceutico', 'jefe_deposito')

@app.route('/api/docs', methods=['GET'])
@login_required
def api_get_docs():
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb        = get_sb()
        rol       = current_user.tipo_precio
        categoria = request.args.get('categoria')  # 'recibos' | 'documentacion'

        # Determinar qué tipos mostrar según categoría solicitada
        if categoria == 'recibos':
            tipos_filtro = list(DOCS_RECIBOS)
        elif categoria == 'documentacion':
            tipos_filtro = list(DOCS_DOCUMENTACION)
        else:
            tipos_filtro = list(DOCS_TIPOS.keys())

        if rol in ('jefe', 'admin'):
            emp_id = request.args.get('empleado_id')
            q = sb.table('documentos_empleados') \
                  .select('id,tipo,nombre_archivo,periodo,estado,firma_timestamp,firma_nombre,created_at,empleado_id') \
                  .in_('tipo', tipos_filtro) \
                  .order('created_at', desc=True)
            if emp_id:
                q = q.eq('empleado_id', emp_id)
        else:
            q = sb.table('documentos_empleados') \
                  .select('id,tipo,nombre_archivo,periodo,estado,firma_timestamp,firma_nombre,created_at,empleado_id') \
                  .eq('empleado_id', current_user.id) \
                  .in_('tipo', tipos_filtro) \
                  .order('created_at', desc=True)
        return jsonify(q.execute().data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/docs/empleados-lista', methods=['GET'])
@login_required
def api_docs_empleados_lista():
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        res = sb.table('clientes') \
                .select('id,nombre,tipo_precio') \
                .in_('tipo_precio', ['empleado', 'jefe', 'admin', 'farmaceutico', 'jefe_deposito']) \
                .eq('activo', True) \
                .order('nombre') \
                .execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/docs/subir', methods=['POST'])
@login_required
def api_docs_subir():
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        empleado_id = request.form.get('empleado_id', '').strip()
        tipo        = request.form.get('tipo', 'recibo_sueldo')
        periodo     = request.form.get('periodo', '').strip()
        archivo     = request.files.get('archivo')

        if not empleado_id or not archivo:
            return jsonify({'error': 'empleado_id y archivo son requeridos'}), 400
        if tipo not in DOCS_TIPOS:
            return jsonify({'error': 'Tipo de documento inválido'}), 400

        nombre = secure_filename(archivo.filename)
        if not nombre.lower().endswith('.pdf'):
            return jsonify({'error': 'Solo se permiten archivos PDF'}), 400

        file_bytes   = archivo.read()
        safe_periodo = periodo.replace(' ', '_') if periodo else ''
        storage_path = f"{empleado_id}/{tipo}/{safe_periodo}_{nombre}" if safe_periodo \
                       else f"{empleado_id}/{tipo}/{nombre}"

        sb = get_sb()
        # Subir a Supabase Storage
        try:
            sb.storage.from_('documentos').upload(
                path=storage_path,
                file=file_bytes,
                file_options={'content-type': 'application/pdf', 'upsert': 'true'}
            )
        except Exception as se:
            err = str(se)
            if 'already exists' in err.lower() or '409' in err:
                sb.storage.from_('documentos').update(
                    path=storage_path,
                    file=file_bytes,
                    file_options={'content-type': 'application/pdf'}
                )
            else:
                raise

        # Guardar metadatos en DB
        res = sb.table('documentos_empleados').insert({
            'empleado_id':    empleado_id,
            'tipo':           tipo,
            'nombre_archivo': nombre,
            'periodo':        periodo or None,
            'storage_path':   storage_path,
            'estado':         'pendiente',
            'subido_por':     current_user.id,
        }).execute()
        return jsonify({'ok': True, 'doc': res.data[0]}), 201
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/docs/firmar/<doc_id>', methods=['POST'])
@login_required
def api_docs_firmar(doc_id):
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        data       = request.get_json() or {}
        firma_data = data.get('firma_data', '')
        if not firma_data:
            return jsonify({'error': 'firma_data requerido'}), 400

        sb      = get_sb()
        doc_res = sb.table('documentos_empleados').select('*').eq('id', doc_id).single().execute()
        doc     = doc_res.data
        if not doc:
            return jsonify({'error': 'Documento no encontrado'}), 404
        if str(doc['empleado_id']) != str(current_user.id):
            return jsonify({'error': 'No autorizado para firmar este documento'}), 403
        if doc['estado'] == 'firmado':
            return jsonify({'error': 'El documento ya fue firmado anteriormente'}), 400

        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ',' in ip:
            ip = ip.split(',')[0].strip()

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        sb.table('documentos_empleados').update({
            'estado':          'firmado',
            'firma_data':      firma_data,
            'firma_timestamp': now,
            'firma_ip':        ip,
            'firma_nombre':    current_user.nombre,
        }).eq('id', doc_id).execute()

        return jsonify({'ok': True, 'timestamp': now})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/docs/descargar/<doc_id>', methods=['GET'])
@login_required
def api_docs_descargar(doc_id):
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb      = get_sb()
        doc_res = sb.table('documentos_empleados').select('*').eq('id', doc_id).single().execute()
        doc     = doc_res.data
        if not doc:
            return jsonify({'error': 'Documento no encontrado'}), 404
        if current_user.tipo_precio == 'empleado' and str(doc['empleado_id']) != str(current_user.id):
            return jsonify({'error': 'No autorizado'}), 403

        signed = sb.storage.from_('documentos').create_signed_url(doc['storage_path'], 3600)
        # supabase-py v2 devuelve objeto con .signed_url
        if hasattr(signed, 'signed_url'):
            url = signed.signed_url
        elif isinstance(signed, dict):
            url = signed.get('signedURL') or signed.get('signed_url') or signed.get('signedUrl')
        else:
            url = None

        if not url:
            return jsonify({'error': 'No se pudo generar URL de descarga'}), 500
        return jsonify({'url': url})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Faltantes ─────────────────────────────────────────────────────────────────

ROLES_VER_FALTANTES       = ('jefe_deposito', 'farmaceutico', 'jefe', 'admin')
ROLES_GESTIONAR_FALTANTES = ('farmaceutico', 'jefe', 'admin')

@app.route('/api/faltantes', methods=['GET'])
@login_required
def api_faltantes_list():
    if current_user.tipo_precio not in ROLES_VER_FALTANTES:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        # Solo tickets activos (no confirmados por jefe_deposito)
        res = sb.table('faltantes').select('*').is_('confirmado_en', 'null').order('creado_en', desc=True).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/faltantes', methods=['POST'])
@login_required
def api_faltantes_create():
    if current_user.tipo_precio != 'jefe_deposito':
        return jsonify({'error': 'Solo el Jefe de Depósito puede cargar faltantes'}), 403
    data     = request.get_json() or {}
    producto = data.get('producto', '').strip()
    nota     = data.get('nota', '').strip()
    if not producto:
        return jsonify({'error': 'El producto es obligatorio'}), 400
    try:
        sb  = get_sb()
        res = sb.table('faltantes').insert({
            'producto':          producto,
            'nota':              nota or None,
            'estado':            'faltante',
            'creado_por_nombre': current_user.nombre,
        }).execute()
        return jsonify(res.data[0] if res.data else {}), 201
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/faltantes/<int:faltante_id>', methods=['PATCH'])
@login_required
def api_faltantes_update(faltante_id):
    if current_user.tipo_precio not in ROLES_GESTIONAR_FALTANTES:
        return jsonify({'error': 'No autorizado para gestionar faltantes'}), 403
    data   = request.get_json() or {}
    estado = data.get('estado', '').strip()
    if estado not in ('faltante', 'en_gestion', 'resuelto'):
        return jsonify({'error': 'Estado inválido'}), 400
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    update = {
        'estado':                 estado,
        'actualizado_por_nombre': current_user.nombre,
        'actualizado_en':         now,
    }
    if estado == 'en_gestion':
        update['gestion_por_nombre'] = current_user.nombre
        update['gestion_en']         = now
        nota_g = (data.get('nota_gestion') or '').strip()
        if nota_g:
            update['nota_gestion'] = nota_g
    if estado == 'resuelto':
        dias = data.get('dias_entrega')
        if dias is not None:
            try:
                update['dias_entrega'] = int(dias)
            except (ValueError, TypeError):
                pass
    try:
        sb  = get_sb()
        res = sb.table('faltantes').update(update).eq('id', faltante_id).execute()
        return jsonify(res.data[0] if res.data else {})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/faltantes/<int:faltante_id>/confirmar', methods=['PATCH'])
@login_required
def api_faltantes_confirmar(faltante_id):
    if current_user.tipo_precio != 'jefe_deposito':
        return jsonify({'error': 'Solo el Jefe de Depósito puede confirmar la recepción'}), 403
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        sb  = get_sb()
        res = sb.table('faltantes').update({'confirmado_en': now}).eq('id', faltante_id).execute()
        return jsonify(res.data[0] if res.data else {})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/faltantes', methods=['GET'])
@admin_required
def api_admin_faltantes_list():
    try:
        sb  = get_sb()
        res = sb.table('faltantes').select('*').order('creado_en', desc=True).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/faltantes/<int:faltante_id>', methods=['DELETE'])
@login_required
def api_faltantes_delete(faltante_id):
    if current_user.tipo_precio not in ('jefe_deposito', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb = get_sb()
        sb.table('faltantes').delete().eq('id', faltante_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Balance de Stock ───────────────────────────────────────────────────────────

BALANCE_ROLES = ('empleado', 'jefe', 'jefe_deposito', 'admin')

@app.route('/api/balance-stock/buscar', methods=['GET'])
@login_required
def balance_stock_buscar():
    if current_user.tipo_precio not in BALANCE_ROLES:
        return jsonify({'error': 'No autorizado'}), 403
    q = request.args.get('q', '').strip().upper()
    if len(q) < 2:
        return jsonify([])
    stock_dict = get_stock_data()
    results = [{'name': k, 'stock': int(v)} for k, v in stock_dict.items() if q in k][:12]
    return jsonify(results)

@app.route('/api/balance-stock', methods=['POST'])
@login_required
def api_balance_stock_crear():
    if current_user.tipo_precio not in BALANCE_ROLES:
        return jsonify({'error': 'No autorizado'}), 403
    data       = request.get_json() or {}
    producto   = (data.get('producto') or '').strip()
    stock_real = data.get('stock_real')
    if not producto or stock_real is None:
        return jsonify({'error': 'Datos incompletos'}), 400
    try:
        s_sistema = float(data.get('stock_sistema') or 0)
        s_real    = float(stock_real)
        from datetime import datetime, timezone
        sb = get_sb()
        sb.table('balance_stock').insert({
            'producto':           producto,
            'stock_sistema':      s_sistema,
            'stock_real':         s_real,
            'diferencia':         s_real - s_sistema,
            'reportado_por':      current_user.nombre,
            'reportado_por_tipo': current_user.tipo_precio,
            'estado':             'pendiente',
            'creado_en':          datetime.now(timezone.utc).isoformat(),
        }).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR balance-stock POST] {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/balance-stock', methods=['GET'])
@login_required
def api_balance_stock_list():
    if current_user.tipo_precio not in BALANCE_ROLES:
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        res = sb.table('balance_stock').select('*').eq('estado', 'pendiente').order('creado_en', desc=True).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/balance-stock', methods=['GET'])
@admin_required
def api_admin_balance_stock_list():
    try:
        sb  = get_sb()
        res = sb.table('balance_stock').select('*').order('creado_en', desc=True).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/balance-stock/<int:ticket_id>/cerrar', methods=['PATCH'])
@admin_required
def api_admin_balance_stock_cerrar(ticket_id):
    from datetime import datetime, timezone
    data = request.get_json() or {}
    nota = (data.get('nota') or '').strip()
    now  = datetime.now(timezone.utc).isoformat()
    try:
        sb     = get_sb()
        update = {'estado': 'cerrado', 'cerrado_en': now}
        if nota:
            update['nota_cierre'] = nota
        sb.table('balance_stock').update(update).eq('id', ticket_id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Pedidos ────────────────────────────────────────────────────────────────────

@app.route('/api/pedidos', methods=['POST'])
@login_required
def api_crear_pedido():
    try:
        data = request.get_json()
        sb = get_sb()
        from datetime import datetime, timezone
        sb.table('pedidos').insert({
            'cliente_nombre':    current_user.nombre,
            'genexus_client_id': str(current_user.genexus_client_id) if current_user.genexus_client_id else None,
            'tipo_precio':       data.get('tipo_precio'),
            'items':             data.get('items'),
            'total_estimado':    data.get('total_estimado'),
            'creado_en':         datetime.now(timezone.utc).isoformat(),
        }).execute()
        return jsonify({'ok': True})
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/clientes/actividad', methods=['GET'])
@admin_required
def api_admin_clientes_actividad():
    try:
        sb = get_sb()
        res = sb.table('clientes').select('id,nombre,username,tipo_precio,activo,ultimo_acceso').execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/admin/pedidos', methods=['GET'])
@admin_required
def api_admin_pedidos():
    try:
        sb = get_sb()
        res = sb.table('pedidos').select('*').order('creado_en', desc=True).limit(500).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': 'Error interno del servidor'}), 500

# ── Rutas estáticas ────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
def serve_app():
    return render_template('index.html')

@app.route('/tienda/')
def serve_tienda():
    return send_from_directory(FEDAFAR_APP_DIR, 'index.html')

@app.route('/tienda/<path:path>')
def serve_tienda_static(path):
    return send_from_directory(FEDAFAR_APP_DIR, path)

@app.route('/api/productos', methods=['GET'])
def get_productos():
    tipo = request.args.get('tipo', 'contado')
    if current_user.is_authenticated:
        tipo = current_user.tipo_precio
    prods = parse_price_list(tipo)
    return jsonify(prods)

# ── Licitaciones ──────────────────────────────────────────────────────────────

@app.route('/api/admin/licitaciones', methods=['GET'])
@admin_required
def api_admin_licitaciones_list():
    try:
        sb  = get_sb()
        res = sb.table('licitaciones').select('*').order('fecha_scraping', desc=True).limit(300).execute()
        return jsonify(res.data or [])
    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/licitaciones/marcar-vistas', methods=['PATCH'])
@admin_required
def api_admin_licitaciones_marcar_vistas():
    try:
        sb = get_sb()
        sb.table('licitaciones').update({'notificado': True}).eq('notificado', False).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/licitaciones/sync', methods=['POST'])
@admin_required
def api_admin_licitaciones_sync():
    try:
        import sys
        for mod in ('licitaciones_scraper', 'ips_scraper'):
            if mod in sys.modules:
                del sys.modules[mod]
        from licitaciones_scraper import run_scraper as run_saltacompra
        from ips_scraper import run_scraper as run_ips
        total = run_saltacompra() + run_ips()
        return jsonify({'ok': True, 'guardadas': total})
    except Exception as e:
        print(f"[ERROR sync licitaciones] {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/licitaciones/<id>/clasificar', methods=['PATCH'])
@admin_required
def api_admin_licitaciones_clasificar(id):
    data = request.get_json() or {}
    clasificacion = data.get('clasificacion')
    if clasificacion not in ('APLICA', 'REVISAR', 'NO_APLICA'):
        return jsonify({'error': 'Clasificación inválida'}), 400
    try:
        sb = get_sb()
        sb.table('licitaciones').update({'clasificacion': clasificacion}).eq('id', id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── Intercambios de mercadería ─────────────────────────────────────────────────

def _jefe_o_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({'error': 'No autenticado'}), 401
        if current_user.tipo_precio not in ('jefe', 'jefe_deposito', 'farmaceutico', 'admin'):
            return jsonify({'error': 'Sin permiso'}), 403
        return f(*args, **kwargs)
    return decorated

@app.route('/api/intercambios', methods=['GET'])
@_jefe_o_admin_required
def api_intercambios_list():
    try:
        sb  = get_sb()
        res = sb.table('prestamos_externos').select('*').order('creado_en', desc=True).limit(200).execute()
        return jsonify(res.data or [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/intercambios/pendientes-count', methods=['GET'])
@_jefe_o_admin_required
def api_intercambios_count():
    try:
        sb  = get_sb()
        res = sb.table('prestamos_externos').select('id').eq('devuelto', False).execute()
        return jsonify({'count': len(res.data or [])})
    except Exception as e:
        return jsonify({'count': 0})

@app.route('/api/intercambios', methods=['POST'])
@_jefe_o_admin_required
def api_intercambios_crear():
    data    = request.get_json() or {}
    tipo    = data.get('tipo', '').strip()
    entidad = data.get('entidad', '').strip()
    producto= data.get('producto', '').strip()
    cantidad= data.get('cantidad', '').strip()
    notas   = data.get('notas', '').strip()

    if not tipo or not entidad or not producto or not cantidad:
        return jsonify({'error': 'Faltan campos obligatorios'}), 400
    if tipo not in ('prestamos_a', 'nos_prestaron'):
        return jsonify({'error': 'Tipo inválido'}), 400

    try:
        from datetime import datetime, timezone, date
        sb = get_sb()
        sb.table('prestamos_externos').insert({
            'tipo':       tipo,
            'entidad':    entidad,
            'producto':   producto,
            'cantidad':   cantidad,
            'notas':      notas or None,
            'creado_por': current_user.nombre,
            'fecha':      date.today().isoformat(),
            'devuelto':   False,
            'creado_en':  datetime.now(timezone.utc).isoformat(),
        }).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/intercambios/<id>/devolver', methods=['PATCH'])
@_jefe_o_admin_required
def api_intercambios_devolver(id):
    try:
        from datetime import datetime, timezone
        sb = get_sb()
        sb.table('prestamos_externos').update({
            'devuelto':         True,
            'fecha_devolucion': datetime.now(timezone.utc).isoformat(),
        }).eq('id', id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/intercambios/<id>', methods=['DELETE'])
@admin_required
def api_intercambios_borrar(id):
    try:
        sb = get_sb()
        sb.table('prestamos_externos').delete().eq('id', id).execute()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando API FEDAFAR en puerto {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
