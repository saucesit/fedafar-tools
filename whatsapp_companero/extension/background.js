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

// ── Salida: respuestas que Facundo aprobó en el panel ─────────────────────
function urlSalida(apiUrl) { return apiUrl.replace(/\/ingest\/?$/, '/salida'); }

async function pollSalida() {
  const s = await chrome.storage.local.get({ apiUrl: 'https://fedafar-tools.onrender.com/api/wa/ingest', apiToken: '', envioActivo: true, entregados: [] });
  if (!s.envioActivo || !s.apiUrl || !s.apiToken) return { enviar: [] };
  const r = await fetch(urlSalida(s.apiUrl), { headers: { Authorization: 'Bearer ' + s.apiToken } });
  if (!r.ok) return { enviar: [] };
  const j = await r.json();
  // red de seguridad: nunca entregar dos veces el mismo id a la página
  const vistos = new Set(s.entregados);
  const enviar = (j.enviar || []).filter((x) => x && x.id && !vistos.has(x.id));
  if (enviar.length) await chrome.storage.local.set({ entregados: [...s.entregados, ...enviar.map((x) => x.id)].slice(-500) });
  return { enviar };
}

async function resultadoSalida(msg) {
  const s = await chrome.storage.local.get({ apiUrl: 'https://fedafar-tools.onrender.com/api/wa/ingest', apiToken: '', log: [] });
  await fetch(urlSalida(s.apiUrl) + '/' + msg.id, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + s.apiToken },
    body: JSON.stringify({ ok: !!msg.ok, wa_msg_id: msg.wa_msg_id || null, error: msg.error || null }),
  }).catch(() => {});
  const log = [{ id: msg.id, ok: !!msg.ok, error: msg.error || null, cuando: Date.now() }, ...s.log].slice(0, 30);
  await chrome.storage.local.set({ log });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.kind === 'poll_salida') { pollSalida().then(reply).catch(() => reply({ enviar: [] })); return true; }
  if (msg.kind === 'resultado_salida') { resultadoSalida(msg); return; }
  if (msg.kind === 'records') enCola(() => procesar(msg.records));
  if (msg.kind === 'flush') { enCola(() => procesar([])).then(() => reply({ ok: true })); return true; }
});

chrome.runtime.onInstalled.addListener(() => chrome.alarms.create('flush', { periodInMinutes: 1 }));
chrome.runtime.onStartup.addListener(() => chrome.alarms.create('flush', { periodInMinutes: 1 }));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === 'flush') enCola(() => procesar([])); });
