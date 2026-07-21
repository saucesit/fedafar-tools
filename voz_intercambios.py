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
Primero detectá QUÉ quiere hacer (la acción), y después extraé los datos.
Devolvé SOLO un JSON (sin explicaciones) con:

{{
  "accion": "crear" | "devolver" | "corregir" | "borrar",
  "tipo": "prestamos_a" | "nos_prestaron" | "",
  "entidad": "nombre de la farmacia/persona/entidad, o ''",
  "producto": "qué producto, texto libre, o ''",
  "cantidad": número (o null si no se dice),
  "notas": "cualquier detalle extra relevante, o ''"
}}

Cómo detectar la ACCIÓN:
- "crear": anotar un préstamo o algo nuevo. Ej: "le presté 10 cajas a San Martín", "anotá que nos prestaron...".
- "devolver": registrar una devolución sobre algo ya prestado. Ej: "San Bernardo me devolvió 3 amoxidal", "devolvimos las 2 cajas a...". Acá la cantidad es lo que se devolvió.
- "corregir": arreglar un error de carga de un registro que ya existe. Ej: "corregí el préstamo de amoxicilina a San Martín, eran 15 no 10", "cambiá la cantidad de...". Poné en cantidad/producto/etc. el valor CORREGIDO.
- "borrar": eliminar un registro cargado por error. Ej: "borrá el préstamo a San Martín", "eliminá lo de...".
- Si no queda claro, usá "crear".

Reglas de los datos:
- entidad y producto sirven para IDENTIFICAR el registro (en devolver/corregir/borrar) o para el nuevo (en crear).
- "le prestamos / le dimos / le pasamos a X" => tipo "prestamos_a". "nos prestó / me prestaron / nos dio" => "nos_prestaron". Si no está claro, "".
- La cantidad es solo el número (ej: "10 cajas" => 10; "cajas" va en producto o notas).
- No inventes datos: lo que no se dice va vacío o null.
- Respondé en español.

Texto dictado:
\"\"\"{texto}\"\"\""""


def interpretar(texto, key=None):
    """Texto -> dict con los campos del intercambio. Campos vacíos si no se dicen."""
    import anthropic
    key = key or os.environ.get('ANTHROPIC_API_KEY', '')
    vacio = {'accion': 'crear', 'tipo': '', 'entidad': '', 'producto': '', 'cantidad': None, 'notas': ''}
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
        out['accion'] = data.get('accion') if data.get('accion') in ('crear', 'devolver', 'corregir', 'borrar') else 'crear'
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


def _norm(s):
    import unicodedata
    if not s:
        return ''
    t = unicodedata.normalize('NFKD', str(s))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def _tokens(s):
    return [w for w in re.split(r'\W+', _norm(s)) if len(w) >= 3]


def buscar_candidatos(sb, entidad, producto, solo_activos=False, limite=5):
    """Busca en prestamos_externos los registros que mejor matchean con la
    entidad y el producto dictados. Devuelve una lista ordenada por relevancia,
    cada uno con 'pendiente' (cantidad - devoluciones). Para 'devolver' conviene
    solo_activos=True (los que todavía tienen algo por devolver)."""
    rows = sb.table('prestamos_externos').select('*').order('creado_en', desc=True).limit(200).execute().data or []
    if not rows:
        return []
    # Devoluciones para calcular lo pendiente
    ids = [r['id'] for r in rows]
    devs = sb.table('intercambios_devoluciones').select('intercambio_id,cantidad').in_('intercambio_id', ids).execute().data or []
    dev_por_id = {}
    for d in devs:
        dev_por_id[d['intercambio_id']] = dev_por_id.get(d['intercambio_id'], 0) + float(d['cantidad'] or 0)

    te, tp = set(_tokens(entidad)), set(_tokens(producto))
    scored = []
    for r in rows:
        se, sp = set(_tokens(r.get('entidad'))), set(_tokens(r.get('producto')))
        # Puntaje: coincidencia de entidad pesa más que producto
        score = 2 * len(te & se) + len(tp & sp)
        # Si dijo entidad pero no matchea NADA de la entidad, descartar
        if te and not (te & se):
            continue
        if score == 0:
            continue
        total = float(r.get('cantidad') or 0)
        pend = total - dev_por_id.get(r['id'], 0)
        if solo_activos and pend <= 0.001:
            continue
        scored.append((score, r, pend))
    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for score, r, pend in scored[:limite]:
        out.append({
            'id':        r['id'],
            'tipo':      r.get('tipo'),
            'entidad':   r.get('entidad'),
            'producto':  r.get('producto'),
            'cantidad':  float(r.get('cantidad') or 0),
            'pendiente': pend,
            'estado':    r.get('estado'),
            'fecha':     r.get('fecha') or '',
            'notas':     r.get('notas') or '',
        })
    return out


if __name__ == '__main__':
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / '.env')
    ejemplos = [
        'le presté diez cajas de amoxicilina a la farmacia San Martín',
        'nos prestaron 5 ampollas de dexametasona de la farmacia del centro',
        'San Bernardo me devolvió 3 cajas de amoxidal',
        'corregí el préstamo de amoxicilina a San Martín, eran quince cajas no diez',
        'borrá el préstamo a la farmacia Nueva España',
        'devolvimos las 2 cajas de ibuprofeno que le habíamos prestado a San Roque',
    ]
    for e in ejemplos:
        print(f'\n> {e}')
        print(' ', interpretar(e))
