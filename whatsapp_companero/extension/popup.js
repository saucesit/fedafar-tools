const DEF = {
  msgs: [], pendientes: [],
  stats: { total: 0, entrantes: 0, salientes: 0, ultimo: null },
  apiUrl: 'https://fedafar-tools.onrender.com/api/wa/ingest', apiToken: '',
  envio: { ok: null, cuando: null, detalle: '' },
  envioActivo: true, log: [],
};
const $ = (id) => document.getElementById(id);
const fecha = (ms) => new Date(ms).toLocaleString('es-AR');

function render() {
  chrome.storage.local.get(DEF, (s) => {
    $('total').textContent = s.stats.total;
    $('in').textContent = s.stats.entrantes;
    $('out').textContent = s.stats.salientes;
    $('ultimo').textContent = s.stats.ultimo ? 'Último capturado: ' + fecha(s.stats.ultimo) : 'Todavía no capturó nada. Abrí o recargá WhatsApp Web.';
    if (document.activeElement.tagName !== 'INPUT') { $('apiUrl').value = s.apiUrl; $('apiToken').value = s.apiToken; }

    const env = $('envio');
    if (!s.apiToken) { env.className = 'envio err'; env.textContent = 'Sin conexión configurada: los mensajes quedan solo en esta PC.'; $('conf').open = true; }
    else if (s.envio.ok === false) { env.className = 'envio err'; env.textContent = 'Error al enviar (' + s.envio.detalle + '). Pendientes: ' + s.pendientes.length; }
    else if (s.envio.ok) { env.className = 'envio ok'; env.textContent = 'Enviando a la API · último envío ' + fecha(s.envio.cuando) + ' · pendientes: ' + s.pendientes.length; }
    else { env.className = 'envio'; env.textContent = 'Pendientes de enviar: ' + s.pendientes.length; }

    $('envioActivo').checked = s.envioActivo;
    const env2 = s.log.filter((x) => x.ok).length, err2 = s.log.filter((x) => !x.ok);
    $('salidas').textContent = s.log.length
      ? 'Respuestas enviadas: ' + env2 + (err2.length ? ' · con error: ' + err2.length + ' (último: ' + err2[0].error + ')' : '') + ' · última ' + fecha(s.log[0].cuando)
      : 'Todavía no envió ninguna respuesta aprobada.';

    const ul = $('lista');
    ul.replaceChildren();
    s.msgs.slice(-30).reverse().forEach((m) => {
      const li = document.createElement('li');
      const who = document.createElement('div');
      who.className = 'who' + (m.from_me ? ' me' : '');
      who.textContent = (m.from_me ? 'FEDAFAR → ' : '') + (m.chat_nombre || m.telefono || m.chat_id);
      const txt = document.createElement('div');
      txt.textContent = m.texto || '[' + m.tipo + ']';
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = fecha(m.t * 1000) + ' · ' + m.tipo;
      li.append(who, txt, meta);
      ul.append(li);
    });
  });
}

$('guardar').addEventListener('click', () => {
  chrome.storage.local.set({ apiUrl: $('apiUrl').value.trim(), apiToken: $('apiToken').value.trim() }, () => {
    $('envio').textContent = 'Enviando…';
    chrome.runtime.sendMessage({ kind: 'flush' }, () => render());
  });
});

$('envioActivo').addEventListener('change', (e) => chrome.storage.local.set({ envioActivo: e.target.checked }));

render();
