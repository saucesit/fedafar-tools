#!/usr/bin/env python3
"""
voz_intercambios.py — Carga de préstamos/devoluciones por audio.

Dos etapas:
  1) transcribir(audio) -> texto      (Groq Whisper, español)
  2) interpretar(texto) -> dict       (Claude saca tipo/entidad/producto/cantidad)

El resultado PRE-LLENA el formulario de Intercambios; NUNCA guarda solo. El
usuario (Agustín, perfil jefe) revisa, corrige y confirma con el botón de siempre.
"""

import os, re, json
import requests

GROQ_URL   = 'https://api.groq.com/openai/v1/audio/transcriptions'
GROQ_MODEL = 'whisper-large-v3-turbo'   # rápido y barato; español muy bueno


def transcribir(audio_bytes, filename='audio.m4a'):
    """Audio -> texto con Groq Whisper. Devuelve '' si falla."""
    key = os.environ.get('GROQ_API_KEY', '')
    if not key:
        raise RuntimeError('Falta GROQ_API_KEY en el entorno')
    resp = requests.post(
        GROQ_URL,
        headers={'Authorization': f'Bearer {key}'},
        files={'file': (filename, audio_bytes)},
        data={'model': GROQ_MODEL, 'language': 'es',
              'prompt': 'Préstamo o devolución de medicamentos entre farmacias y droguerías.'},
        timeout=60,
    )
    resp.raise_for_status()
    return (resp.json().get('text') or '').strip()


_PROMPT = """Sos un asistente de una droguería. El usuario dictó por voz un
préstamo o devolución de mercadería entre la droguería y otra farmacia/entidad.
Extraé los datos del texto y devolvé SOLO un JSON (sin explicaciones) con:

{{
  "tipo": "prestamos_a" | "nos_prestaron" | "",
  "entidad": "nombre de la farmacia/persona/entidad, o ''",
  "producto": "qué producto, texto libre, o ''",
  "cantidad": número (o null si no se dice),
  "notas": "cualquier detalle extra relevante, o ''"
}}

Reglas:
- "le prestamos / le dimos / le pasamos a X" => tipo "prestamos_a" (nosotros prestamos).
- "nos prestó / nos dio / me prestaron / nos pasó X" => tipo "nos_prestaron".
- Si no queda claro el tipo, dejá "tipo": "".
- La cantidad es solo el número (ej: "10 cajas" => cantidad 10, y "cajas" puede ir en producto o notas).
- No inventes datos: si algo no se dice, dejalo vacío o null.
- Respondé en español.

Texto dictado:
\"\"\"{texto}\"\"\""""


def interpretar(texto, key=None):
    """Texto -> dict con los campos del intercambio. Campos vacíos si no se dicen."""
    import anthropic
    key = key or os.environ.get('ANTHROPIC_API_KEY', '')
    vacio = {'tipo': '', 'entidad': '', 'producto': '', 'cantidad': None, 'notas': ''}
    if not key or not texto:
        return vacio
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=400,
            messages=[{'role': 'user', 'content': _PROMPT.format(texto=texto)}],
        )
        t = resp.content[0].text.strip()
        t = re.sub(r'^```json?\s*', '', t)
        t = re.sub(r'\s*```$', '', t)
        data = json.loads(t)
        # Normalizar / validar
        out = dict(vacio)
        if data.get('tipo') in ('prestamos_a', 'nos_prestaron'):
            out['tipo'] = data['tipo']
        out['entidad']  = str(data.get('entidad') or '').strip()
        out['producto'] = str(data.get('producto') or '').strip()
        out['notas']    = str(data.get('notas') or '').strip()
        c = data.get('cantidad')
        try:
            out['cantidad'] = float(c) if c is not None and str(c).strip() != '' else None
        except (ValueError, TypeError):
            out['cantidad'] = None
        return out
    except Exception as e:
        print(f'[voz_intercambios] interpretar falló: {str(e)[:100]}')
        return vacio


if __name__ == '__main__':
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / '.env')
    ejemplos = [
        'le presté diez cajas de amoxicilina a la farmacia San Martín',
        'nos prestaron 5 ampollas de dexametasona de la farmacia del centro',
        'le dimos veinte comprimidos de ibuprofeno a Farmacia Nueva España',
        'devolvimos las 3 cajas de amoxidal que nos había prestado San Bernardo',
    ]
    for e in ejemplos:
        print(f'\n> {e}')
        print(' ', interpretar(e))
