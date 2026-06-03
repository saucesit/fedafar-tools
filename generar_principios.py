"""
generar_principios.py — Genera/actualiza el archivo principios_activos.json
usando Claude Sonnet para identificar el principio activo de cada producto.

Uso:
    python generar_principios.py          # procesa todos los productos
    python generar_principios.py --test   # solo los primeros 30 (prueba)

El JSON generado se usa en la app para busqueda por principio activo.
"""

import os
import re
import json
import time
import sys
import anthropic
import pandas as pd
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
PRICE_LIST   = os.path.join(BASE_DIR, 'price_list.xlsx')
OUTPUT_JSON  = os.path.join(BASE_DIR, 'principios_activos.json')
BATCH_SIZE   = 15  # productos por llamada a la API

client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))


def leer_productos():
    df = pd.read_excel(PRICE_LIST, skiprows=2, header=0)
    df.columns = ['codigo', 'articulo', 'laboratorio', 'costo']
    df['nombre'] = df['articulo'].apply(
        lambda x: re.sub(r'\s*-\s*\d+\s*$', '', str(x)).strip()
    )
    df = df[df['costo'] > 0].reset_index(drop=True)
    return df[['nombre', 'laboratorio']].drop_duplicates(subset='nombre')


def consultar_principios(productos: list[dict]) -> dict:
    """
    Recibe una lista de {nombre, laboratorio} y devuelve
    un dict {nombre: principio_activo}.
    """
    lista_txt = "\n".join(
        f'{i+1}. {p["nombre"]} ({p["laboratorio"]})'
        for i, p in enumerate(productos)
    )

    prompt = f"""Sos un experto en farmacología argentina.
Para cada medicamento de la siguiente lista, indicá el principio activo (droga) en español.

Reglas:
- Si el producto tiene principio activo conocido, respondé SOLO con el nombre genérico (ej: "diclofenac", "amoxicilina", "ibuprofeno")
- Si tiene varios principios activos, separarlos con " + " (ej: "amoxicilina + ácido clavulánico")
- Si es un insumo, descartable o dispositivo médico (agujas, gasas, jeringas, algodón, etc.), respondé "insumo"
- Si no estás seguro, respondé "desconocido"
- Respondé SOLO en formato JSON con el número como clave

Lista:
{lista_txt}

Respondé ÚNICAMENTE con el JSON, sin texto adicional. Ejemplo:
{{"1": "diclofenac", "2": "insumo", "3": "amoxicilina"}}"""

    msg = client.messages.create(
        model='claude-sonnet-4-5',
        max_tokens=1000,
        messages=[{'role': 'user', 'content': prompt}]
    )

    texto = msg.content[0].text.strip()
    # Extraer el JSON de la respuesta
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if not match:
        print(f'    [AVISO] Respuesta inesperada: {texto[:100]}')
        return {}

    resultado = json.loads(match.group())
    return {
        productos[int(k) - 1]['nombre']: v.lower().strip()
        for k, v in resultado.items()
        if int(k) - 1 < len(productos)
    }


def main():
    test_mode = '--test' in sys.argv
    print(f'=== Generando principios activos {"(PRUEBA 30 productos)" if test_mode else ""} ===')

    # Cargar productos
    df = leer_productos()
    if test_mode:
        df = df.head(30)
    productos = df.to_dict('records')
    total = len(productos)
    print(f'Productos a procesar: {total}')

    # Cargar JSON existente para no reprocesar
    existentes = {}
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON, 'r', encoding='utf-8') as f:
            existentes = json.load(f)
        print(f'Ya procesados anteriormente: {len(existentes)}')

    # Filtrar los que ya tienen principio activo
    pendientes = [p for p in productos if p['nombre'] not in existentes]
    print(f'Pendientes: {len(pendientes)}')

    if not pendientes:
        print('Nada nuevo para procesar.')
        return

    # Procesar en batches
    resultados = dict(existentes)
    errores = []

    for i in range(0, len(pendientes), BATCH_SIZE):
        batch = pendientes[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(pendientes) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f'  Batch {batch_num}/{total_batches}: {len(batch)} productos...')

        try:
            res = consultar_principios(batch)
            resultados.update(res)
            print(f'    [OK] {len(res)} procesados.')

            # Mostrar resultados del batch
            for nombre, principio in res.items():
                print(f'       {nombre[:45]:45} -> {principio}')

        except Exception as e:
            print(f'    [ERROR] Batch {batch_num}: {e}')
            errores.extend([p['nombre'] for p in batch])

        # Guardar progreso después de cada batch
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(resultados, f, ensure_ascii=False, indent=2)

        # Pausa entre batches para no saturar la API
        if i + BATCH_SIZE < len(pendientes):
            time.sleep(1)

    # Resumen
    print(f'\n=== Resumen ===')
    print(f'Total procesados: {len(resultados)}')
    print(f'Insumos: {sum(1 for v in resultados.values() if v == "insumo")}')
    print(f'Desconocidos: {sum(1 for v in resultados.values() if v == "desconocido")}')
    print(f'Con principio activo: {sum(1 for v in resultados.values() if v not in ("insumo", "desconocido"))}')
    if errores:
        print(f'Errores: {len(errores)} productos no procesados')
    print(f'Guardado en: {OUTPUT_JSON}')


if __name__ == '__main__':
    main()
