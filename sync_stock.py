"""
sync_stock.py - Descarga el stock desde el servidor interno y guarda stock_data.json

El archivo generado es usado por la app en Render (que no tiene acceso
a la red interna) para filtrar productos sin stock.

Uso:
    python sync_stock.py

Requisitos:
    - Red interna de Fedafar (192.168.0.35 accesible)
"""

import os
import json
import requests
import pandas as pd
from io import BytesIO

STOCK_URL   = 'http://192.168.0.35/fedafar/ALM_ArticulosPorDepositoExport-.xlsx'
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(BASE_DIR, 'stock_data.json')


def sync_stock():
    print("=== Sync Stock ===")
    print("  Descargando stock desde red interna...")

    try:
        r = requests.get(STOCK_URL, timeout=10)
        r.raise_for_status()

        df = pd.read_excel(
            BytesIO(r.content), skiprows=5, header=None,
            names=['Articulo', 'Descripcion', 'Tranzable', 'Existencia',
                   'Lote', 'FechaVenc', 'Serie', 'Cantidad']
        )
        df['Existencia'] = pd.to_numeric(df['Existencia'], errors='coerce').fillna(0)
        grouped = df.groupby('Descripcion')['Existencia'].sum()

        stock_dict = {
            str(nombre).strip().upper(): float(stock)
            for nombre, stock in grouped.items()
        }

        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(stock_dict, f, ensure_ascii=False)

        print(f"  [OK] {len(stock_dict)} productos guardados en stock_data.json")
        return True

    except Exception as e:
        print(f"  ERROR: {e}")
        print("  Verificar que estas en la red de Fedafar.")
        return False


if __name__ == '__main__':
    ok = sync_stock()
    exit(0 if ok else 1)
