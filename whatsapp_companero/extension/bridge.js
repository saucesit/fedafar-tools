// Mundo aislado de la extensión: recibe lo que manda inject.js y lo pasa al background.
window.addEventListener('message', (ev) => {
  if (ev.source !== window || !ev.data || ev.data.__companero !== true) return;
  chrome.runtime.sendMessage({ kind: 'records', records: ev.data.records });
});
