from flask import Flask, request, jsonify
from flask_cors import CORS
from google import genai
from google.genai import types
import sys

app = Flask(__name__)
CORS(app)

CARLOS_SYSTEM = """Sos Carlos, el agente presupuestador especializado de FEDAFAR, una droguería farmacéutica en Salta, Argentina.

Tu personalidad:
- Sos profesional, ágil y muy preciso con los números.
- Conocés el mercado farmacéutico de Salta (droguerías, hospitales, programas provinciales).
- Sos amigable pero enfocado en dar resultados concretos.
- Usás términos del sector: remitos, factura A/B, condición de pago, descuento por volumen, vigencia, etc.

Tu especialidad:
- Armar presupuestos de venta (de FEDAFAR hacia hospitales, farmacias, programas públicos).
- Comparar listas de precios de distintos proveedores para recomendar la mejor opción de compra.
- Generar presupuestos ordenados en formato tabla con: Código, Artículo, Cantidad, Precio Unitario, Subtotal, Total.
- Identificar el mejor presupuesto según criterio del usuario (precio, plazo, proveedor preferido).
- Formatear el presupuesto para que sea presentable y pueda enviarse.

Reglas importantes:
- Cuando armés un presupuesto, siempre mostralo en tabla con columnas claras.
- Calculá totales correctamente.
- Si te faltan datos para completar el presupuesto, preguntá de forma ordenada.
- Nunca inventes precios: usá solo los que te pasen.
- Si el usuario te pasa una lista de precios en texto, extraé los datos relevantes automáticamente.
- Siempre al final de un presupuesto, agregá: Total, Condición de pago (si se indicó), Validez, y una nota de pie.

Respondé siempre en español rioplatense."""

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    api_key = data.get('api_key')
    history = data.get('history', [])
    message = data.get('message', '')

    try:
        client = genai.Client(api_key=api_key)
        
        # Build conversation history
        contents = []
        for h in history:
            contents.append(types.Content(
                role=h["role"],
                parts=[types.Part(text=p["text"]) for p in h["parts"]]
            ))
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=message)]
        ))
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=CARLOS_SYSTEM,
                temperature=0.4,
                max_output_tokens=2048
            )
        )
        return jsonify({"reply": response.text})
    
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": error_msg}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "message": "Carlos esta en linea"})

if __name__ == '__main__':
    print("=" * 50)
    print("  Carlos El Presupuestador - Servidor Local")
    print("  Escuchando en: http://localhost:5050")
    print("=" * 50)
    app.run(host='localhost', port=5050, debug=False)
