"""Charla con el Compañero: Facundo le escribe (o le habla) y el Compañero
contesta usando lo que pasó por el WhatsApp Business y el catálogo.

Puede redactar respuestas para los clientes, pero NUNCA las manda: el borrador
vuelve al panel y Facundo decide si lo copia/abre en WhatsApp y lo envía.

Las herramientas que tocan la base o el catálogo las implementa api_app y se
pasan en `herramientas` (dict nombre -> función). Acá solo vive el prompt,
los esquemas y el loop con Claude.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

MODELO = os.getenv('COMPANERO_MODELO_CHARLA', 'claude-opus-5-5')
# sugerencias automáticas: corren por cada mensaje que espera respuesta → modelo más barato
MODELO_SUG = os.getenv('COMPANERO_MODELO_SUGERENCIA', 'claude-sonnet-5-5')
MAX_VUELTAS = 8
PLAZO_SEG = 90          # gunicorn corta a los 120 s
_AR = timezone(timedelta(hours=-3))

SYSTEM = """Sos el Compañero de Facundo: un compañero de trabajo que lee todo lo que entra y sale por el WhatsApp Business de FEDAFAR, una droguería (distribuidora de medicamentos) de Salta, Argentina. Le escriben farmacias clientes, centros de salud, médicos, pacientes y proveedores.

Facundo te habla como a un compañero: te pregunta qué pasó, qué quedó pendiente, qué pidió tal cliente, o te encarga tareas como "respondele a X".

Cómo trabajás:
- Antes de afirmar algo sobre una conversación, buscalo con las herramientas. No inventes mensajes, productos, precios ni stock.
- Para saber qué hay pendiente usá resumen_chats. Para ver una conversación, leer_chat. Para encontrar algo puntual, buscar_mensajes.
- Para precio o stock de un producto usá buscar_producto. Si no hay dato de stock, decilo; no lo supongas.
- Respuestas a Facundo: cortas, directas, en castellano rioplatense. Listas breves cuando haya varias cosas. Nombrá al cliente y cuánto hace que espera cuando importe.

Redactar respuestas a clientes:
- Cuando Facundo te pida responder, contestar o "decile que...", leé primero la conversación y redactá con redactar_respuesta. Un borrador por chat.
- Vos no podés mandar mensajes. El borrador le aparece a Facundo con botones para copiarlo o abrirlo en WhatsApp; él lo revisa y lo manda. Nunca digas que lo enviaste.
- Tono del borrador: como escribe FEDAFAR en ese chat (mirá sus mensajes anteriores). Cordial, breve, sin firmas largas, sin emojis de más.
- Precios: hay precio contado y precio cuenta corriente. Si no sabés cuál corresponde al cliente, poné el que corresponda según la conversación o avisale a Facundo en tu respuesta que confirme cuál usar.
- Si falta un dato para responder bien (precio, si hay stock, fecha de entrega), redactá igual dejando el hueco marcado entre corchetes, por ejemplo [confirmar fecha], y avisale a Facundo qué falta."""

TOOLS = [
    {
        'name': 'resumen_chats',
        'description': 'Lista los chats con actividad en los últimos días: nombre, chat_id, teléfono, si está sin responder y hace cuántos minutos espera, último mensaje (resumido) y categorías (pedido, reclamo, pago, consulta, proveedor...). Usala para "qué hay pendiente", "qué pasó hoy", "quién escribió".',
        'input_schema': {
            'type': 'object',
            'properties': {
                'dias': {'type': 'integer', 'description': 'Cuántos días hacia atrás (1 = desde ayer a esta hora). Default 1.'},
                'solo_sin_responder': {'type': 'boolean', 'description': 'Solo los que esperan respuesta de FEDAFAR.'},
            },
        },
    },
    {
        'name': 'leer_chat',
        'description': 'Trae los últimos mensajes de una conversación, en orden, con fecha/hora y quién escribió (CLIENTE o FEDAFAR). Pasá chat_id si lo tenés; si no, el nombre o parte del nombre/teléfono del contacto.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'chat_id': {'type': 'string'},
                'nombre': {'type': 'string', 'description': 'Nombre o parte del nombre o teléfono, si no tenés chat_id.'},
                'cantidad': {'type': 'integer', 'description': 'Cuántos mensajes (default 40, máx 150).'},
            },
        },
    },
    {
        'name': 'buscar_mensajes',
        'description': 'Busca un texto en todos los mensajes (contenido, nombre del chat o teléfono). Devuelve los más recientes que coinciden, con chat, fecha y quién lo escribió.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'texto': {'type': 'string'},
                'dias': {'type': 'integer', 'description': 'Hasta cuántos días atrás (default 30).'},
            },
            'required': ['texto'],
        },
    },
    {
        'name': 'buscar_producto',
        'description': 'Busca en el catálogo de FEDAFAR por nombre o principio activo. Devuelve nombre, laboratorio, precio contado, precio cuenta corriente y stock si se conoce.',
        'input_schema': {
            'type': 'object',
            'properties': {'texto': {'type': 'string', 'description': 'Ej: "aciclovir 800", "guantes nitrilo".'}},
            'required': ['texto'],
        },
    },
    {
        'name': 'redactar_respuesta',
        'description': 'Deja un borrador de respuesta para un chat de cliente. NO lo envía: le aparece a Facundo para que lo revise y lo mande él. Usalo una vez por chat al que haya que responder.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'chat_id': {'type': 'string'},
                'texto': {'type': 'string', 'description': 'El mensaje tal como se mandaría por WhatsApp.'},
            },
            'required': ['chat_id', 'texto'],
        },
    },
]


def _sistema():
    ahora = datetime.now(_AR)
    dias = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    return SYSTEM + f"\n\nAhora es {dias[ahora.weekday()]} {ahora.strftime('%d/%m/%Y %H:%M')} (hora de Salta)."


def charlar(historial, herramientas, foco=None, log=print, modelo=None, tools=None, system=None):
    """historial: [{'role': 'user'|'assistant', 'content': str}], el último es de Facundo.
    herramientas: {nombre: función(**input) -> dict|list}. 'redactar_respuesta' debe
    devolver la ficha del borrador (con chat_id, nombre, telefono, texto) o {'error': ...}.
    foco: chat_id que Facundo tiene abierto en el panel, si hay.
    Devuelve {'texto', 'borradores', 'herramientas'}."""
    import anthropic
    key = os.getenv('ANTHROPIC_API_KEY')
    if not key:
        return {'texto': 'Falta configurar ANTHROPIC_API_KEY en el servidor.', 'borradores': [], 'herramientas': []}
    client = anthropic.Anthropic(api_key=key)

    mensajes = [{'role': m['role'], 'content': m['content']} for m in historial if m.get('content')]
    if foco:
        mensajes[-1] = {'role': 'user', 'content': f"(Tengo abierto el chat {foco} en el panel.)\n\n{mensajes[-1]['content']}"}

    borradores, usadas = [], []
    inicio = time.monotonic()
    resp = None
    for _ in range(MAX_VUELTAS):
        resp = client.messages.create(
            model=modelo or MODELO,
            max_tokens=6000,
            system=system or _sistema(),
            tools=tools or TOOLS,
            messages=mensajes,
            thinking={'type': 'adaptive'},
            output_config={'effort': 'low'},
        )
        if resp.stop_reason == 'pause_turn':
            mensajes.append({'role': 'assistant', 'content': resp.content})
            continue
        if resp.stop_reason != 'tool_use':
            break
        mensajes.append({'role': 'assistant', 'content': resp.content})
        resultados = []
        for b in resp.content:
            if b.type != 'tool_use':
                continue
            usadas.append(b.name)
            fn = herramientas.get(b.name)
            try:
                out = fn(**(b.input or {})) if fn else {'error': f'herramienta desconocida {b.name}'}
            except Exception as e:
                log(f'[charla] {b.name} falló: {type(e).__name__}: {e}')
                out = {'error': f'{type(e).__name__}: {e}'}
            if b.name == 'redactar_respuesta' and isinstance(out, dict) and not out.get('error'):
                borradores.append(out)
                out = {'ok': True, 'nota': 'Borrador listo en el panel. Facundo lo revisa y lo manda él.'}
            resultados.append({'type': 'tool_result', 'tool_use_id': b.id,
                               'content': json.dumps(out, ensure_ascii=False, default=str)[:60000],
                               **({'is_error': True} if isinstance(out, dict) and out.get('error') else {})})
        mensajes.append({'role': 'user', 'content': resultados})
        if time.monotonic() - inicio > PLAZO_SEG:
            break

    texto = ''
    if resp is not None:
        if resp.stop_reason == 'refusal':
            texto = 'No puedo ayudar con eso.'
        else:
            texto = '\n'.join(b.text for b in resp.content if b.type == 'text').strip()
        if resp.stop_reason == 'tool_use':
            texto = (texto + '\n\n' if texto else '') + '(Me quedé sin tiempo a mitad de camino; pedímelo de nuevo o más acotado.)'
    if not texto and borradores:
        texto = 'Te dejé el borrador abajo.' if len(borradores) == 1 else f'Te dejé {len(borradores)} borradores abajo.'
    return {'texto': texto, 'borradores': borradores, 'herramientas': usadas}


# ── Sugerencias automáticas ──────────────────────────────────────────────────

SYSTEM_SUG = """

MODO SUGERENCIA: acaba de entrar un mensaje de un cliente y nadie de FEDAFAR contestó todavía. Tu trabajo es dejarle a Facundo la respuesta lista para que él la apruebe y se envíe tal cual. Escribila como la mandaría FEDAFAR, sin notas internas dentro del texto.
- Una sola respuesta con redactar_respuesta, para ese chat.
- Si hay que dar precio o stock, buscalo con buscar_producto. Si el precio depende de si el cliente es contado o cuenta corriente y la conversación no lo aclara, poné el de contado y avisalo en la nota.
- Si falta un dato que no podés saber (fecha de entrega, algo del depósito), dejá el hueco entre corchetes, ej. [confirmar fecha].
- NO redactes si no corresponde responder: ya se le contestó, es solo un saludo/gracias/ok, es un audio o imagen que hay que ver para entender, o es personal. En ese caso no llames a redactar_respuesta.
- Al final escribí UNA línea para Facundo: qué tiene que confirmar antes de enviar, o "OK" si está todo; si no redactaste, por qué."""

_TOOLS_SUG = [t for t in TOOLS if t['name'] in ('buscar_producto', 'buscar_mensajes', 'redactar_respuesta')]


def sugerir(chat, herramientas, log=print):
    """chat: salida de leer_chat (chat_id, nombre, mensajes[]). Devuelve {'texto', 'borradores'}."""
    lineas = []
    for m in chat['mensajes']:
        t = m.get('texto') or ''
        if m.get('tipo') and m['tipo'] != 'chat':
            t = f"[{m['tipo']}] " + t + (f" (resumen: {m['resumen']})" if m.get('resumen') else '')
        lineas.append(f"{m['hora']} {m['quien']}: {t.strip()}")
    prompt = (f"Chat con {chat['nombre']} (chat_id {chat['chat_id']}). Conversación reciente:\n\n"
              + '\n'.join(lineas)
              + "\n\nRedactá la respuesta que debería mandar FEDAFAR al último mensaje del cliente.")
    return charlar([{'role': 'user', 'content': prompt}], herramientas, log=log,
                   modelo=MODELO_SUG, tools=_TOOLS_SUG, system=_sistema() + SYSTEM_SUG)
