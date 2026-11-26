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
const fileSize = (n) => n < 1024 ? n + ' B' : n < 1048576 ? Math.round(n / 1024) + ' KB' : (n / 1048576).toLocaleString(t.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' MB';
// la tarjeta del adjunto en el chat de prueba y en Conversaciones (las imágenes se ven directo)
window.fileCard = (f) => f?.mime?.startsWith('image/')
  ? h('a', { href: f.url, target: '_blank', rel: 'noopener', title: t('Abrir {name}', { name: f.name }) }, h('img', { class: 'file-img', src: f.url, alt: f.name }))
  : h('a', { class: 'file-card', href: f.url, target: '_blank', rel: 'noopener', title: t('Abrir o descargar {name}', { name: f.name }) },
    icon('clip'), h('span', {}, h('strong', {}, f.name), h('small', {}, fileSize(f.size || 0) + ' · ' + t('Abrir o descargar'))));

// lo que mandó el cliente por WhatsApp o Telegram (history[].media): foto, audio, video, documento o ubicación
window.mediaView = (m) => !m ? null
  : m.error && !m.url ? h('small', { class: 'help', style: 'display:block;font-size:12px' }, t('El archivo no se guardó: {error}', { error: m.error }))
  : m.type === 'location' && m.lat != null ? h('a', { class: 'file-card', href: 'https://www.openstreetmap.org/?mlat=' + m.lat + '&mlon=' + m.lng + '#map=17/' + m.lat + '/' + m.lng, target: '_blank', rel: 'noopener' },
    icon('globe'), h('span', {}, h('strong', {}, m.name || t('Ubicación')), h('small', {}, t('Ver en el mapa'))))
  : !m.url ? null
  : m.type === 'audio' ? h('span', { style: 'display:block;margin-top:6px' }, h('audio', { controls: '', preload: 'none', src: m.url, 'aria-label': t('Audio del cliente') }),
    m.transcript ? h('small', { style: 'display:block;font-size:12px;opacity:.8' }, t('Transcripción del audio')) : null)
  : m.type === 'video' ? h('video', { class: 'file-img', controls: '', preload: 'none', src: m.url, 'aria-label': t('Video del cliente') })
  : window.fileCard({ url: m.url, name: m.name || m.type, mime: m.mime, size: m.size });

const fl = { agent: null, loaded: false, list: [], busy: false, error: '' };
async function flLoad() {
  Object.assign(fl, { agent: agent.id, loaded: false, list: [], error: '' });
  const id = agent.id;
  try { const r = await api('GET', '/' + id + '/files'); if (fl.agent === id) fl.list = r.files; } catch (e) { fl.error = e.message; }
  if (fl.agent === id) { fl.loaded = true; render(); }
}
function flUpload(file, s) {
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) { fl.error = t('El archivo es muy grande (máximo 10 MB).'); return render(); }
  fl.busy = true; fl.error = ''; render();
  const r = new FileReader();
  r.onload = async () => {
    try { const out = await api('POST', '/' + agent.id + '/files', { name: file.name, data: r.result }); fl.list = out.files; s.file = out.id; touch(); }
    catch (e) { fl.error = t('No se pudo subir: {error}', { error: e.message }); }
    fl.busy = false; render();
  };
  r.onerror = () => { fl.busy = false; fl.error = t('No se pudo leer el archivo.'); render(); };
  r.readAsDataURL(file);
}
function flRemove(f) {
  let used = 0;
  walkSteps((x) => { if (x.type === 'file' && (x.file === f.id || String(x.file || '').toLowerCase() === f.name.toLowerCase())) used++; });
  confirmBox(t('Borrar el archivo'), t('Se borra «{name}» del bot.', { name: f.name }) + (used ? ' ' + t.plural(used, 'Lo usa 1 paso, que va a dar error, también en las versiones publicadas.',
    'Lo usan {n} pasos, que van a dar error, también en las versiones publicadas.') : '') + ' ' + t('No se puede deshacer.'), t('Borrar archivo'), async () => {
    try { fl.list = (await api('DELETE', '/' + agent.id + '/files/' + f.id)).files; } catch (e) { fl.error = e.message; }
    render();
  });
}
window.fileStepView = (s) => {
  if (fl.agent !== agent.id) flLoad();
  const ref = String(s.file || '');
  const cur = fl.list.find((f) => f.id === ref) || fl.list.findLast((f) => f.name.toLowerCase() === ref.toLowerCase());
  const input = h('input', { type: 'file', accept: FILE_ACCEPT, hidden: true, 'aria-label': t('Elegir archivo'), onchange: (e) => flUpload(e.target.files[0], s) });
  const text = h('textarea', { rows: 1, 'aria-label': t('Texto que acompaña el archivo'), ...trBind(s, 'text', t('Por ejemplo: Acá tenés la lista de precios, {{ nombre }}'), (e) => grow(e.target)) });
  return [
    h('div', { class: 'row' },
      pick([['', fl.list.length ? t('Elegí un archivo…') : fl.loaded ? t('Todavía no subiste archivos') : t('Cargando…')], ...fl.list.map((f) => [f.id, f.name + ' (' + fileSize(f.size) + ')'])],
        cur?.id ?? '', (v) => { s.file = v; touch(); render(); }, t('Archivo')),
      h('button', { class: 'btn quiet small', type: 'button', disabled: fl.busy, onclick: () => input.click() }, icon('up'), fl.busy ? t('Subiendo…') : t('Subir un archivo')), input),
    ref && !cur && fl.loaded ? h('p', { class: 'help', style: 'font-size:14px;color:var(--warn)' }, t('«{name}» ya no está en el bot. Subilo de nuevo o elegí otro.', { name: ref })) : null,
    fl.error ? h('p', { class: 'help', style: 'font-size:14px;color:var(--warn)' }, fl.error) : null,
    cur ? h('div', { class: 'row' }, window.fileCard(cur), iconBtn('trash', t('Borrar «{name}» del bot', { name: cur.name }), () => flRemove(cur))) : null,
    lab(t('Texto que acompaña (opcional)'), text), slotChips(text),
    h('p', { class: 'help', style: 'font-size:14px' }, t('PDF, imagen, Word, Excel, PowerPoint, CSV, TXT o ZIP, hasta 10 MB. Sin texto, el bot manda solo el archivo. Quien tenga el enlace lo puede abrir, así que no subas nada privado. Los archivos son del bot, no de una versión: si borrás uno, deja de enviarse también en lo publicado.')),
  ];
};
