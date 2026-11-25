// Archivos del bot (lista de precios, catálogo, fotos) y el paso «Enviar un archivo». Se suben desde el mismo paso y
// quedan en el servidor (agents/<id>.files/). Son del bot, no de una versión: lo publicado manda los de hoy.
document.head.append(h('style', {}, `
  .badge.file { background: #E3EEFB; color: #1F4F8A; }
  .file-card { display: inline-flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px;
    background: var(--surface); color: var(--ink); text-decoration: none; max-width: 300px; white-space: normal; vertical-align: middle; }
  .file-card:hover { border-color: var(--brand); }
  .file-card .ic { flex: none; color: var(--brand); }
  .file-card span { display: flex; flex-direction: column; min-width: 0; }
  .file-card strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
  .file-card small { color: var(--muted); font-size: 12px; }
  .file-img { display: block; max-width: 220px; max-height: 220px; border-radius: 10px; }
  .msg .file-card, .msg .file-img { margin-top: 6px; }
`));
const FILE_ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,.txt,.csv,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip';
const fileSize = (n) => n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toFixed(1).replace('.', ',') + ' MB';
// la tarjeta del adjunto en el chat de prueba y en Conversaciones (las imágenes se ven directo)
window.fileCard = (f) => f?.mime?.startsWith('image/')
  ? h('a', { href: f.url, target: '_blank', rel: 'noopener', title: 'Abrir ' + f.name }, h('img', { class: 'file-img', src: f.url, alt: f.name }))
  : h('a', { class: 'file-card', href: f.url, target: '_blank', rel: 'noopener', title: 'Abrir o descargar ' + f.name },
    icon('clip'), h('span', {}, h('strong', {}, f.name), h('small', {}, fileSize(f.size || 0) + ' · Abrir o descargar')));

const fl = { agent: null, loaded: false, list: [], busy: false, error: '' };
async function flLoad() {
  Object.assign(fl, { agent: agent.id, loaded: false, list: [], error: '' });
  const id = agent.id;
  try { const r = await api('GET', '/' + id + '/files'); if (fl.agent === id) fl.list = r.files; } catch (e) { fl.error = e.message; }
  if (fl.agent === id) { fl.loaded = true; render(); }
}
function flUpload(file, s) {
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { fl.error = 'El archivo es muy grande (máximo 10 MB).'; return render(); }
  fl.busy = true; fl.error = ''; render();
  const r = new FileReader();
  r.onload = async () => {
    try { const out = await api('POST', '/' + agent.id + '/files', { name: file.name, data: r.result }); fl.list = out.files; s.file = out.id; touch(); }
    catch (e) { fl.error = 'No se pudo subir: ' + e.message; }
    fl.busy = false; render();
  };
  r.onerror = () => { fl.busy = false; fl.error = 'No se pudo leer el archivo.'; render(); };
  r.readAsDataURL(file);
}
function flRemove(f) {
  let used = 0;
  walkSteps((x) => { if (x.type === 'file' && (x.file === f.id || String(x.file || '').toLowerCase() === f.name.toLowerCase())) used++; });
  confirmBox('Borrar el archivo', 'Se borra «' + f.name + '» del bot.' + (used ? ' Lo ' + (used === 1 ? 'usa 1 paso, que va' : 'usan ' + used + ' pasos, que van') +
    ' a dar error, también en las versiones publicadas.' : '') + ' No se puede deshacer.', 'Borrar archivo', async () => {
    try { fl.list = (await api('DELETE', '/' + agent.id + '/files/' + f.id)).files; } catch (e) { fl.error = e.message; }
    render();
  });
}
window.fileStepView = (s) => {
  if (fl.agent !== agent.id) flLoad();
  const ref = String(s.file || '');
  const cur = fl.list.find((f) => f.id === ref) || fl.list.findLast((f) => f.name.toLowerCase() === ref.toLowerCase());
  const input = h('input', { type: 'file', accept: FILE_ACCEPT, hidden: true, 'aria-label': 'Elegir archivo', onchange: (e) => flUpload(e.target.files[0], s) });
  const text = h('textarea', { rows: 1, 'aria-label': 'Texto que acompaña el archivo', ...trBind(s, 'text', 'Por ejemplo: Acá tenés la lista de precios, {{ nombre }}', (e) => grow(e.target)) });
  return [
    h('div', { class: 'row' },
      pick([['', fl.list.length ? 'Elegí un archivo…' : fl.loaded ? 'Todavía no subiste archivos' : 'Cargando…'], ...fl.list.map((f) => [f.id, f.name + ' (' + fileSize(f.size) + ')'])],
        cur?.id ?? '', (v) => { s.file = v; touch(); render(); }, 'Archivo'),
      h('button', { class: 'btn quiet small', type: 'button', disabled: fl.busy, onclick: () => input.click() }, icon('up'), fl.busy ? 'Subiendo…' : 'Subir un archivo'), input),
    ref && !cur && fl.loaded ? h('p', { class: 'help', style: 'font-size:14px;color:var(--warn)' }, '«' + ref + '» ya no está en el bot. Subilo de nuevo o elegí otro.') : null,
    fl.error ? h('p', { class: 'help', style: 'font-size:14px;color:var(--warn)' }, fl.error) : null,
    cur ? h('div', { class: 'row' }, window.fileCard(cur), iconBtn('trash', 'Borrar «' + cur.name + '» del bot', () => flRemove(cur))) : null,
    lab('Texto que acompaña (opcional)', text), slotChips(text),
    h('p', { class: 'help', style: 'font-size:14px' }, 'PDF, imagen, Word, Excel, PowerPoint, CSV, TXT o ZIP, hasta 10 MB. Sin texto, el bot manda solo el archivo. ' +
      'Quien tenga el enlace lo puede abrir, así que no subas nada privado. Los archivos son del bot, no de una versión: si borrás uno, deja de enviarse también en lo publicado.'),
  ];
};
