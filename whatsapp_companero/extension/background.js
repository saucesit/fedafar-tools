// Guarda los mensajes localmente y los manda a la API del Compañero.
// Lo que no se pudo enviar queda en "pendientes" y se reintenta en el próximo
// mensaje, con la alarma de cada minuto o al guardar la configuración.
const MAX_LOCAL = 2000;
const LOTE = 500;

async function getState() {
  return chrome.storage.local.get({
    msgs: [], seen: [], pendientes: [],
    stats: { total: 0, entrantes: 0, salientes: 0, ultimo: null },
    apiUrl: 'https://fedafar-tools.onrender.com/api/wa/ingest', apiToken: '',
    envio: { ok: null, cuando: null, detalle: '' },
  });
}

async function postLote(apiUrl, apiToken, batch) {
  const r = await fetch(apiUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + apiToken },
    body: JSON.stringify({ mensajes: batch }),
  });
  if (!r.ok) throw new Error('HTTP ' + r.status);
}

// Envía los pendientes en lotes. Devuelve los que quedaron sin enviar.
async function flush(s) {
  let pend = s.pendientes;
  if (!s.apiUrl || !s.apiToken || !pend.length) return { pend, envio: s.envio };
  try {
    while (pend.length) {
      await postLote(s.apiUrl, s.apiToken, pend.slice(0, LOTE));
      pend = pend.slice(LOTE);
    }
    return { pend, envio: { ok: true, cuando: Date.now(), detalle: '' } };
  } catch (e) {
    return { pend, envio: { ok: false, cuando: Date.now(), detalle: String(e.message || e) } };
  }
}

let chain = Promise.resolve();
function enCola(fn) { chain = chain.then(fn).catch((e) => console.warn('[Compañero]', e)); return chain; }

async function procesar(records) {
  const s = await getState();
  const seen = new Set(s.seen);
  const nuevos = (records || []).filter((r) => r && r.id && !seen.has(r.id));
  nuevos.forEach((r) => {
    seen.add(r.id);
    s.stats.total++;
    r.from_me ? s.stats.salientes++ : s.stats.entrantes++;
  });
  if (nuevos.length) {
    s.stats.ultimo = Date.now();
    s.msgs = s.msgs.concat(nuevos).slice(-MAX_LOCAL);
    s.pendientes = s.pendientes.concat(nuevos).slice(-MAX_LOCAL * 5);
  }
  const { pend, envio } = await flush(s);
  await chrome.storage.local.set({
    msgs: s.msgs,
    seen: [...seen].slice(-MAX_LOCAL * 5),
    stats: s.stats,
    pendientes: pend,
    envio,
  });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.kind === 'records') enCola(() => procesar(msg.records));
  if (msg.kind === 'flush') { enCola(() => procesar([])).then(() => reply({ ok: true })); return true; }
});

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create('flush', { periodInMinutes: 1 }));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create('flush', { periodInMinutes: 1 }));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === 'flush') enCola(() => procesar([])); });
