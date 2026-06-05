import os
import re
import json
import pandas as pd
from flask import Flask, jsonify, render_template, send_from_directory, request, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', os.urandom(24))
CORS(app, supports_credentials=True)

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
    login_user(user, remember=True)
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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
    if tipo not in ('contado', 'cta-cte', 'empleado', 'jefe', 'admin'):
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
        return jsonify({'error': str(e)}), 500

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
    es_empleado = tipo in ('empleado', 'jefe', 'admin')

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
            price_val = round(price_val * 1.21, 2)

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

# ── Documentos de empleados ────────────────────────────────────────────────────

DOCS_TIPOS = {
    'recibo_sueldo': 'Recibo de Sueldo',
    'art_tarjeta':   'Tarjeta ART',
    'otro':          'Otro',
}

def _es_empleado_interno():
    """True si el usuario logueado tiene rol interno (empleado/jefe/admin)."""
    return current_user.is_authenticated and \
           current_user.tipo_precio in ('empleado', 'jefe', 'admin')

@app.route('/api/docs', methods=['GET'])
@login_required
def api_get_docs():
    if not _es_empleado_interno():
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb   = get_sb()
        tipo = current_user.tipo_precio
        if tipo in ('jefe', 'admin'):
            emp_id = request.args.get('empleado_id')
            q = sb.table('documentos_empleados') \
                  .select('id,tipo,nombre_archivo,periodo,estado,firma_timestamp,firma_nombre,created_at,empleado_id') \
                  .order('created_at', desc=True)
            if emp_id:
                q = q.eq('empleado_id', emp_id)
        else:
            q = sb.table('documentos_empleados') \
                  .select('id,tipo,nombre_archivo,periodo,estado,firma_timestamp,firma_nombre,created_at,empleado_id') \
                  .eq('empleado_id', current_user.id) \
                  .order('created_at', desc=True)
        return jsonify(q.execute().data or [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/docs/empleados-lista', methods=['GET'])
@login_required
def api_docs_empleados_lista():
    if current_user.tipo_precio not in ('jefe', 'admin'):
        return jsonify({'error': 'No autorizado'}), 403
    try:
        sb  = get_sb()
        res = sb.table('clientes') \
                .select('id,nombre,tipo_precio') \
                .in_('tipo_precio', ['empleado', 'jefe', 'admin']) \
                .eq('activo', True) \
                .order('nombre') \
                .execute()
        return jsonify(res.data or [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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
        return jsonify({'error': str(e)}), 500

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Iniciando API FEDAFAR en puerto {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
