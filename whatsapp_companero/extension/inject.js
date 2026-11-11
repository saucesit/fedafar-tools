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
  // WhatsApp cambia el formato al pegar (*negritas*, viñetas, saltos de línea):
  // para verificar alcanza con que coincidan letras y números.
  const esencia = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]/g, '');

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
    const zona = document.querySelector('#main footer') || document.querySelector('#main') || document;
    const clicable = (el) => el && (el.closest('button,[role="button"]') || el);
    // 1) por etiqueta accesible
    for (const el of zona.querySelectorAll('button,[role="button"]')) {
      const l = (el.getAttribute('aria-label') || el.getAttribute('title') || '').toLowerCase();
      if (l === 'enviar' || l === 'send') return el;
    }
    // 2) por ícono
    const ic = zona.querySelector('[data-icon="send"],[data-icon="wds-ic-send-filled"],[data-icon*="send"]');
    if (ic) return clicable(ic);
    // 3) el último botón de la barra de escritura (el de enviar está a la derecha)
    const bs = zona.querySelectorAll('button,[role="button"]');
    return bs.length ? bs[bs.length - 1] : null;
  }

  function vaciarCaja() {
    const c = cajaTexto();
    if (!c) return;
    c.focus();
    const sel = window.getSelection(), r = document.createRange();
    r.selectNodeContents(c); sel.removeAllRanges(); sel.addRange(r);
    document.execCommand('delete');
  }

  function describirBarra() {
    const zona = document.querySelector('#main footer');
    if (!zona) return 'sin footer';
    return [...zona.querySelectorAll('button,[role="button"],[data-icon]')].slice(0, 12)
      .map((e) => e.tagName.toLowerCase() + '[' + (e.getAttribute('aria-label') || e.getAttribute('data-icon') || '') + ']').join(' ');
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
      if (esencia(caja.innerText)) return { ok: false, error: 'Había texto escrito a medias en ese chat; no lo pisé' };

      caja.focus();
      const dt = new DataTransfer();
      dt.setData('text/plain', item.texto);
      caja.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
      const quiero = esencia(item.texto);
      const cargado = await esperar(() => esencia(cajaTexto() && cajaTexto().innerText) === quiero, 3000);
      if (!cargado) {
        const hay = esencia(cajaTexto() && cajaTexto().innerText);
        vaciarCaja();
        return { ok: false, error: `No pude cargar el texto en la caja (esperaba ${quiero.length} letras, quedaron ${hay.length})` };
      }
      // última verificación antes de tocar Enviar: seguimos en el chat correcto
      const a = chatActivo(C);
      if (!a || serial(a.id) !== item.chat_id) return { ok: false, error: 'Cambió el chat abierto; no envié' };

      let enviadoId = null;
      const oir = (m) => {
        if (m && m.id && m.id.fromMe && serial(m.id.remote) === item.chat_id && esencia(m.body) === quiero) enviadoId = serial(m.id);
      };
      C.Msg.on('add', oir);
      try {
        const btn = await esperar(botonEnviar, 2000);
        if (btn) btn.click();
        await esperar(() => enviadoId, 4000);
        if (!enviadoId && esencia(cajaTexto() && cajaTexto().innerText)) {
          // el clic no anduvo: probar con Enter, como haría una persona
          const caja2 = cajaTexto(); caja2.focus();
          for (const tipo of ['keydown', 'keypress', 'keyup']) {
            caja2.dispatchEvent(new KeyboardEvent(tipo, { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true }));
          }
          await esperar(() => enviadoId, 6000);
        }
      } finally { C.Msg.off('add', oir); }
      if (!enviadoId) {
        const quedo = esencia(cajaTexto() && cajaTexto().innerText);
        if (quedo) {   // no salió: no dejar el texto colgado en la caja
          vaciarCaja();
          return { ok: false, error: 'No pude tocar Enviar. Barra: ' + describirBarra() };
        }
        return { ok: false, error: 'La caja se vació pero no vi el mensaje enviado: revisalo en WhatsApp' };
      }
      console.log(TAG, 'enviado', item.id, enviadoId);
      return { ok: true, wa_msg_id: enviadoId };
    } catch (e) {
      return { ok: false, error: String((e && e.message) || e) };
    }
  }
})();
