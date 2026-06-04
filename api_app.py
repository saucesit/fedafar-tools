import os
import re
import json
import pandas as pd
from flask import Flask, jsonify, render_template, send_from_directory, request, session
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
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
    if tipo not in ('contado', 'cta-cte', 'empleado'):
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

def get_stock_data():
    stock_dict = {}
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
    except Exception as e:
        print(f"Stock no disponible (red interna no accesible): {e}")
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
    es_empleado = (tipo == 'empleado')

    try:
        df = pd.read_excel(PRICE_LIST_PATH, skiprows=2, header=0)
        df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

        # Para empleado usamos contado como referencia para filtrar > 0
        col_ref = 'contado' if 'contado' in df.columns else 'precio_costo'
        if col_ref not in df.columns:
            col_ref = df.columns[3]

        # Columnas de precio para clientes normales
        col_contado = 'contado' if 'contado' in df.columns else col_ref
        col_ctacte  = 'cta_cte' if 'cta_cte' in df.columns else col_ref

        MARKUP_C  = 1.195
        MARKUP_CC = 1.26

        for col in [col_contado, col_ctacte]:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Filtrar productos sin precio
        df = df[df[col_ref] > 0].reset_index(drop=True)

    except Exception as e:
        print(f"Error leyendo lista de precios: {e}")
        return []

    for id_counter, (_, row) in enumerate(df.iterrows(), start=1):
        price_contado = round(float(row[col_contado]) if row[col_contado] > 0
                              else float(row.get('precio_costo', 0)) * MARKUP_C, 2)
        price_ctacte  = round(float(row[col_ctacte]) if row[col_ctacte] > 0
                              else float(row.get('precio_costo', 0)) * MARKUP_CC, 2)

        if es_empleado:
            price_val = price_contado  # referencia para IVA
        elif tipo == 'cta-cte':
            price_val = price_ctacte
        else:
            price_val = price_contado

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

        # Filtrar por stock (solo si la red interna está disponible)
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

        products.append(producto)

    return products

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
