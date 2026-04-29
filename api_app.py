import json
import pandas as pd
import glob
from flask import Flask, jsonify, render_template
from flask_cors import CORS
import re

app = Flask(__name__)
CORS(app)

def get_stock_data():
    stock_dict = {}
    # Buscar el último archivo ALM_ArticulosWWExport en la carpeta Descargas
    files = glob.glob(r"C:\Users\FEDAFAR\Downloads\ALM_ArticulosWWExport*.xlsx")
    if not files:
        return stock_dict
    
    # Use the most recent one by name or just the first one found
    latest_file = sorted(files)[-1]
    
    try:
        df = pd.read_excel(latest_file, skiprows=2)
        # Drop the first row which is the header names
        df = df.iloc[1:]
        
        for index, row in df.iterrows():
            name = str(row['Unnamed: 1']).strip().upper()
            stock = row['Unnamed: 2']
            try:
                stock_val = float(stock)
                stock_dict[name] = stock_val
            except (ValueError, TypeError):
                continue
    except Exception as e:
        print(f"Error reading stock file: {e}")
        
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
    
    # Exact match first
    if price_name_clean in stock_dict:
        return stock_dict[price_name_clean]
        
    # Try partial matching - if all parts of price_name are in a stock name
    # Or viceversa
    parts = price_name_clean.split()
    
    best_stock = 0
    found = False
    
    for stock_name, stock_val in stock_dict.items():
        stock_name_clean = clean_name_for_matching(stock_name)
        # Calculate overlap
        stock_parts = stock_name_clean.split()
        match_count = sum(1 for part in parts if part in stock_parts)
        
        if match_count >= len(parts) - 1 and len(parts) > 1:
            best_stock = stock_val
            found = True
            break
            
    if found:
        return best_stock
        
    return None # Not found in stock file

def parse_price_list():
    products = []
    try:
        with open("full_price_list.txt", "r", encoding="utf-16") as f:
            lines = f.readlines()
    except UnicodeError:
        with open("full_price_list.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()

    id_counter = 1
    stock_dict = get_stock_data()
    print(f"Loaded {len(stock_dict)} stock entries.")

    for line in lines:
        line = line.strip()
        if not line or "Articulo" in line or "LISTA DE PRECIO" in line:
            continue
            
        parts = line.split()
        if len(parts) >= 3:
            p2_str = parts[-1]
            p1_str = parts[-2]
            
            try:
                p1_val = float(p1_str.replace('.', '').replace(',', '.'))
                if p1_val <= 0: continue
                
                full_desc = " ".join(parts[:-2])
                lab = "GENERICO"
                if " - " in full_desc:
                    desc_parts = full_desc.split(" - ")
                    name = desc_parts[0]
                    after_dash = desc_parts[1].split()
                    if len(after_dash) > 1:
                        lab = after_dash[1]
                else:
                    name = full_desc
                
                category = "Otros"
                n = name.upper()
                if any(x in n for x in ["AMOX", "CEFA", "CLARITRO", "AZITRO"]): category = "Antibióticos"
                elif any(x in n for x in ["PARACETAMOL", "IBU", "DICLO", "NAPRO"]): category = "Analgésicos"
                elif any(x in n for x in ["DEXA", "MEPRED", "BETAME"]): category = "Corticoides"
                elif any(x in n for x in ["VALSAR", "ENALAPRIL", "ATORVA"]): category = "Cardiovascular"
                elif any(x in n for x in ["JERINGA", "AGUJA"]): category = "Descartables"
                
                # IVA para descartables (+21%)
                if category == "Descartables":
                    p1_val = round(p1_val * 1.21, 2)

                # Check Stock
                if len(stock_dict) > 0:
                    stock_val = fuzzy_stock_match(name, stock_dict)
                    if stock_val is None or stock_val <= 0:
                        continue # Skip products with 0 stock
                
                products.append({
                    "id": id_counter,
                    "name": name,
                    "lab": lab,
                    "price": p1_val,
                    "category": category
                })
                id_counter += 1
            except ValueError:
                continue
                
    return products

@app.route('/', methods=['GET'])
def serve_app():
    return render_template('index.html')

@app.route('/api/productos', methods=['GET'])
def get_productos():
    prods = parse_price_list()
    return jsonify(prods)

if __name__ == '__main__':
    print("Iniciando API de Stock de FEDAFAR en puerto 5001...")
    app.run(host='0.0.0.0', port=5001, debug=False)
