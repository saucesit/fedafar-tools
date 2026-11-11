"""Clasificador del Compañero WhatsApp.

Toma los mensajes sin clasificar de wa_mensajes, los agrupa por chat y le pide
a Claude, con la conversación reciente como contexto, la categoría, prioridad,
si espera respuesta y un resumen corto de cada uno.

Se dispara solo después de cada ingesta (hilo en api_app) y también se puede
correr a mano:  python -m whatsapp_companero.clasificador
"""
import json
import os
import threading
from datetime import datetime, timedelta, timezone

MODELO = os.getenv('COMPANERO_MODELO', 'claude-opus-5-5')
CATEGORIAS = ['pedido', 'reclamo', 'pago', 'consulta', 'proveedor', 'licitacion', 'personal', 'ruido', 'otro']
CONTEXTO_MSGS = 25      # mensajes de la conversación que ve Claude
MAX_CHATS_POR_CORRIDA = 40
_AR = timezone(timedelta(hours=-3))

SYSTEM = """Sos el asistente de Facundo, que trabaja en FEDAFAR, una droguería (distribuidora de medicamentos) de Salta, Argentina.
Leés las conversaciones del WhatsApp Business de la empresa y clasificás cada mensaje marcado con * para que Facundo vea rápido lo importante.

Quiénes escriben: farmacias clientes, centros de salud y hospitales, médicos, pacientes, proveedores/laboratorios y, a veces, gente del equipo. "FEDAFAR" son los mensajes que manda la empresa.

Categorías:
- pedido: el cliente pide mercadería o agrega/cambia algo de un pedido.
- reclamo: faltante, error en una entrega o factura, demora, producto vencido o dañado, queja.
- pago: comprobantes, transferencias, recibos, saldos, cuenta corriente, facturas para pagar.
- consulta: pregunta precio, stock, disponibilidad, horarios o información.
- proveedor: un proveedor/laboratorio ofrece listas, precios, promociones o coordina una compra de FEDAFAR.
- licitacion: licitaciones, pliegos, compras públicas.
- personal: temas personales o del equipo, no de clientes.
- ruido: saludos sueltos, "gracias", "ok", stickers, emojis, confirmaciones sin contenido.
- otro: lo que no encaja.

Prioridad (para mensajes de FEDAFAR usá siempre 1):
- 3 urgente: reclamos, un paciente o servicio de salud esperando, faltantes en una entrega, algo con plazo hoy, montos grandes con problema.
- 2 importante: pedidos, consultas de precio/stock de clientes, pagos informados, proveedores con algo concreto.
- 1 normal: el resto.

espera_respuesta: true si el mensaje pide, pregunta o reclama algo y le corresponde a FEDAFAR contestar. false para "gracias", "ok", saludos de cierre, mensajes de FEDAFAR, o si en la conversación ya se le respondió después.

resumen: en español, máximo 12 palabras, concreto (qué pide/reclama, producto, cantidad, monto). Para audios, imágenes o documentos sin texto, deducilo del contexto si se puede (ej: "Comprobante de pago (imagen)"); si no, describí el tipo.

Usá solo lo que dice la conversación; no inventes productos ni montos."""

SCHEMA = {
    'type': 'object',
    'properties': {
        'mensajes': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'n': {'type': 'integer'},
                    'categoria': {'type': 'string', 'enum': CATEGORIAS},
                    'prioridad': {'type': 'integer', 'enum': [1, 2, 3]},
                    'espera_respuesta': {'type': 'boolean'},
                    'resumen': {'type': 'string'},
                },
                'required': ['n', 'categoria', 'prioridad', 'espera_respuesta', 'resumen'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['mensajes'],
    'additionalProperties': False,
}

_TIPOS = {'ptt': 'audio', 'audio': 'audio', 'image': 'imagen', 'document': 'documento', 'video': 'video',
          'sticker': 'sticker', 'call_log': 'llamada', 'location': 'ubicación', 'vcard': 'contacto'}


def _linea(n, m, pendiente):
    hora = datetime.fromisoformat(m['t']).astimezone(_AR).strftime('%d/%m %H:%M')
    quien = 'FEDAFAR' if m['from_me'] else 'CLIENTE'
    texto = (m.get('texto') or '').strip().replace('\n', ' / ')
    if m['tipo'] != 'chat':
        adj = '[' + _TIPOS.get(m['tipo'], m['tipo']) + ']'
        texto = adj + (' ' + texto if texto else '')
    return f"{'*' if pendiente else ' '}[{n}] {hora} {quien}: {texto[:1500]}"


def _clasificar_chat(client, nombre, contexto, pendientes_ids):
    """contexto: mensajes del chat en orden cronológico. Devuelve {id: clasificación}."""
    indice = {}
    lineas = []
    for n, m in enumerate(contexto, 1):
        pend = m['id'] in pendientes_ids
        if pend:
            indice[n] = m['id']
        lineas.append(_linea(n, m, pend))
    prompt = (f"Conversación con: {nombre}\n\n" + '\n'.join(lineas) +
              f"\n\nClasificá los {len(indice)} mensajes marcados con * (devolvé uno por cada número marcado).")
    resp = client.beta.messages.create(
        model=MODELO,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{'role': 'user', 'content': prompt}],
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}},
        betas=['server-side-fallback-2026-07-01'],
        extra_body={'fallbacks': 'default'},
    )
    if resp.stop_reason == 'refusal':
        return {}
    texto = next((b.text for b in resp.content if b.type == 'text'), '')
    datos = json.loads(texto)
    out = {}
    for c in datos.get('mensajes', []):
        mid = indice.get(c.get('n'))
        if mid:
            out[mid] = c
    return out


_lock = threading.Lock()


def clasificar_pendientes(sb, max_chats=MAX_CHATS_POR_CORRIDA, log=print):
    """Clasifica lo pendiente. Si ya hay una corrida en curso, no hace nada."""
    if not _lock.acquire(blocking=False):
        return {'ocupado': True}
    try:
        import anthropic
        key = os.getenv('ANTHROPIC_API_KEY')
        if not key:
            log('[clasificador] falta ANTHROPIC_API_KEY')
            return {'error': 'sin api key'}
        client = anthropic.Anthropic(api_key=key)
        desde = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        pend = (sb.table('wa_mensajes').select('id,chat_id,chat_nombre,t')
                .is_('clasificado_en', 'null').gte('t', desde)
                .order('t').limit(1000).execute().data or [])
        por_chat = {}
        for m in pend:
            por_chat.setdefault(m['chat_id'], []).append(m)
        hechos, chats, errores = 0, 0, 0
        for chat_id, ms in list(por_chat.items())[:max_chats]:
            ultimo_t = ms[-1]['t']
            ctx = (sb.table('wa_mensajes').select('id,t,from_me,tipo,texto')
                   .eq('chat_id', chat_id).lte('t', ultimo_t)
                   .order('t', desc=True).limit(max(CONTEXTO_MSGS, len(ms) + 5)).execute().data or [])
            ctx.reverse()
            ids = {m['id'] for m in ms}
            try:
                res = _clasificar_chat(client, ms[-1].get('chat_nombre') or chat_id, ctx, ids)
            except Exception as e:  # un chat que falla no frena a los demás; se reintenta en la próxima corrida
                errores += 1
                log(f'[clasificador] error en chat {chat_id}: {type(e).__name__}: {e}')
                continue
            ahora = datetime.now(timezone.utc).isoformat()
            for mid in ids:
                c = res.get(mid) or {'categoria': 'otro', 'prioridad': 1, 'espera_respuesta': None, 'resumen': None}
                sb.table('wa_mensajes').update({
                    'categoria': c['categoria'], 'prioridad': c['prioridad'],
                    'espera_respuesta': c['espera_respuesta'], 'resumen': (c['resumen'] or None),
                    'clasificado_en': ahora,
                }).eq('id', mid).execute()
                hechos += 1
            chats += 1
        quedan = len(pend) - hechos
        log(f'[clasificador] {hechos} mensajes en {chats} chats · errores {errores} · quedan {quedan}')
        return {'clasificados': hechos, 'chats': chats, 'errores': errores, 'quedan': quedan}
    finally:
        _lock.release()


def clasificar_en_segundo_plano(sb):
    threading.Thread(target=clasificar_pendientes, args=(sb,), daemon=True).start()


if __name__ == '__main__':
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dotenv import load_dotenv
    load_dotenv()
    from supabase import create_client
    sb = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))
    while True:
        r = clasificar_pendientes(sb)
        if not r.get('clasificados') or not r.get('quedan'):
            break
