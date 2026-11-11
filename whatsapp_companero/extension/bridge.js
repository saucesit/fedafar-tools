// Mundo aislado de la extensión: recibe lo que manda inject.js y lo pasa al background.
window.addEventListener('message', (ev) => {
  if (ev.source !== window || !ev.data || ev.data.__companero !== true) return;
  chrome.runtime.sendMessage({ kind: 'records', records: ev.data.records });
});

// Respuestas aprobadas en el panel: el background las pide a la API y acá se
// le pasan a inject.js. El resultado vuelve a la API.
let enCurso = false;
window.addEventListener('message', (ev) => {
  if (ev.source !== window || !ev.data || ev.data.__companeroResultado !== true) return;
  const { id, ok, wa_msg_id, error } = ev.data;
  chrome.runtime.sendMessage({ kind: 'resultado_salida', id, ok, wa_msg_id, error });
});

async function buscarSalida() {
  if (enCurso) return;
  enCurso = true;
  try {
    const r = await chrome.runtime.sendMessage({ kind: 'poll_salida' });
    for (const item of (r && r.enviar) || []) window.postMessage({ __companeroEnviar: true, item }, '*');
  } catch (_) { /* extensión recargada o sin red: se reintenta */ }
  enCurso = false;
}
setInterval(buscarSalida, 8000);
