// Corre dentro de la página de WhatsApp Web (world MAIN).
// 1) LECTURA: escucha los mensajes que WhatsApp ya descifró en memoria y los pasa a bridge.js.
// 2) ENVÍO SOLO DE LO APROBADO: bridge.js le pasa respuestas que Facundo aprobó en el panel
//    del Compañero; se escriben en la caja del chat como lo haría una persona y se toca Enviar.
//    Nunca se envía nada que no venga aprobado del panel.
(() => {
  const TAG = '[Compañero]';
  const SKIP_TYPES = new Set(['e2e_notification', 'notification_template', 'gp2', 'protocol', 'ciphertext', 'revoked', 'unknown']);
  const BACKFILL_HORAS = 24;

  function waitCollections(cb, tries = 0) {
    try {
      const C = window.require && window.require('WAWebCollections');
      if (C && C.Msg && C.Chat && C.Msg.getModelsArray().length > 0) return cb(C);
    } catch (_) { /* todavía cargando */ }
    if (tries > 600) return console.warn(TAG, 'no encontré WAWebCollections (¿cambió WhatsApp Web?)');
    setTimeout(() => waitCollections(cb, tries + 1), 1000);
  }

  function serial(x) { return x && (x._serialized || String(x)); }

  function toRecord(C, m) {
    const remote = m.id && m.id.remote;
    const chatId = serial(remote);
    if (!chatId) return null;
    if (chatId.endsWith('@g.us') || chatId === 'status@broadcast' || chatId.endsWith('@broadcast') || chatId.endsWith('@newsletter')) return null;
    if (SKIP_TYPES.has(m.type)) return null;
    const chat = C.Chat.get(remote);
    const contact = C.Contact.get(remote);
    return {
      id: serial(m.id),
      chat_id: chatId,
      chat_nombre: (chat && (chat.formattedTitle || chat.name)) || (contact && (contact.name || contact.pushname)) || null,
      telefono: (contact && contact.phoneNumber && serial(contact.phoneNumber)) || (chatId.endsWith('@c.us') ? chatId : null),
      from_me: !!(m.id && m.id.fromMe),
      t: m.t,
      tipo: m.type,
      texto: m.type === 'chat' ? (m.body || '') : (m.caption || ''),
      mimetype: m.mimetype || null,
      duracion: m.duration ? Number(m.duration) : null,
      cita_id: m.quotedStanzaID || null,
    };
  }

  function send(records) {
    const ok = records.filter(Boolean);
    if (ok.length) window.postMessage({ __companero: true, records: ok }, '*');
  }

  waitCollections((C) => {
    // 1) Backfill: lo que ya está en memoria de las últimas N horas (el backend deduplica por id)
    const desde = Date.now() / 1000 - BACKFILL_HORAS * 3600;
    send(C.Msg.getModelsArray().filter((m) => m.t >= desde).map((m) => toRecord(C, m)));

    // 2) En vivo: cada mensaje que entra o sale (incluye lo que manda el equipo desde otros dispositivos)
    C.Msg.on('add', (m) => {
      if (!m.isNewMsg) return;
      // los mensajes nuevos a veces llegan sin body y se completan un instante después
      setTimeout(() => send([toRecord(C, m)]), 1500);
    });
    console.log(TAG, 'escuchando mensajes');

    window.addEventListener('message', (ev) => {
      if (ev.source !== window || !ev.data || ev.data.__companeroEnviar !== true) return;
      cola = cola.then(() => enviar(C, ev.data.item)).then((r) =>
        window.postMessage(Object.assign({ __companeroResultado: true, id: ev.data.item.id }, r), '*'));
    });
  });

  // ── Envío de respuestas aprobadas ─────────────────────────────────────────
  let cola = Promise.resolve();
  const dormir = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();

  async function esperar(fn, ms = 6000) {
    const fin = Date.now() + ms;
    while (Date.now() < fin) { const v = fn(); if (v) return v; await dormir(150); }
    return null;
  }

  function chatActivo(C) {
    try { if (C.Chat.getActive) return C.Chat.getActive(); } catch (_) {}
    return C.Chat.getModelsArray().find((c) => c.active) || null;
  }

  function cajaTexto() { return document.querySelector('#main footer div[contenteditable="true"]'); }

  function botonEnviar() {
    const b = document.querySelector('#main footer button[aria-label="Enviar"], #main footer button[aria-label="Send"]');
    if (b) return b;
    const ic = document.querySelector('#main footer [data-icon="send"], #main footer [data-icon="wds-ic-send-filled"]');
    return ic ? ic.closest('button') || ic : null;
  }

  async function enviar(C, item) {
    try {
      const chat = C.Chat.get(item.chat_id);
      if (!chat) return { ok: false, error: 'El chat no está cargado en WhatsApp Web' };
      if (item.chat_id.endsWith('@g.us')) return { ok: false, error: 'No envío a grupos' };
      const { Cmd } = window.require('WAWebCmd');
      try { await Cmd.openChatBottom({ chat }); } catch (_) { await Cmd.openChatBottom(chat); }
      const abierto = await esperar(() => { const a = chatActivo(C); return a && serial(a.id) === item.chat_id; });
      if (!abierto) return { ok: false, error: 'No pude abrir el chat' };
      const caja = await esperar(cajaTexto);
      if (!caja) return { ok: false, error: 'No encontré la caja de texto' };
      if (norm(caja.innerText)) return { ok: false, error: 'Había texto escrito a medias en ese chat; no lo pisé' };

      caja.focus();
      const dt = new DataTransfer();
      dt.setData('text/plain', item.texto);
      caja.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      const cargado = await esperar(() => norm(cajaTexto() && cajaTexto().innerText) === norm(item.texto), 3000);
      if (!cargado) {
        document.execCommand('selectAll'); document.execCommand('delete');
        return { ok: false, error: 'No pude cargar el texto en la caja' };
      }
      // última verificación antes de tocar Enviar: seguimos en el chat correcto
      const a = chatActivo(C);
      if (!a || serial(a.id) !== item.chat_id) return { ok: false, error: 'Cambió el chat abierto; no envié' };

      let enviadoId = null;
      const oir = (m) => {
        if (m && m.id && m.id.fromMe && serial(m.id.remote) === item.chat_id && norm(m.body) === norm(item.texto)) enviadoId = serial(m.id);
      };
      C.Msg.on('add', oir);
      try {
        const btn = await esperar(botonEnviar, 2000);
        if (btn) btn.click();
        else cajaTexto().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }));
        await esperar(() => enviadoId, 10000);
      } finally { C.Msg.off('add', oir); }
      if (!enviadoId) return { ok: false, error: 'No se confirmó el envío: revisalo en WhatsApp' };
      console.log(TAG, 'enviado', item.id, enviadoId);
      return { ok: true, wa_msg_id: enviadoId };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  }
})();
