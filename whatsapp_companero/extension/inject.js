// Corre dentro de la página de WhatsApp Web (world MAIN).
// SOLO LECTURA: escucha los mensajes que WhatsApp ya descifró en memoria
// y los pasa a bridge.js. No llama a ninguna función que envíe o modifique nada.
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
    console.log(TAG, 'escuchando mensajes (solo lectura)');
  });
})();
