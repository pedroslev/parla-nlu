// Widget web: el chat que el negocio pega en su propia página. Acá se configura (agent.widget) y se ve en vivo.
document.head.append(h('style', {}, `
  .wg-snippet { background: var(--soft); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin: 0;
    font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; user-select: all; }
  .wg-error { color: var(--warn); font-size: 14px; }
  .wg-check { display: flex; gap: 10px; align-items: flex-start; font-size: 15px; }
  .wg-check input { margin-top: 2px; }
  .wg-check small { display: block; color: var(--muted); font-size: 13px; }
`));

const WG_DEFAULT = { enabled: false, origins: [], title: 'Hablá con nosotros', color: '#2f6bff', greeting: '', position: 'right', voice: false };
// el título de fábrica va en el idioma del bot (lo ve quien visita el sitio), no en el de la interfaz
const wgConf = () => (agent.widget = { ...WG_DEFAULT, ...({ en: { title: 'Chat with us' }, pt: { title: 'Fale com a gente' } }[String(agent.languages?.[0] || 'es').slice(0, 2)] || {}), ...(agent.widget || {}) });
let wgPreview = true, wgError = '', wgTimer = null;

// «https://www.misitio.com/contacto» → «https://www.misitio.com». null si no es una dirección web.
function wgOrigin(raw) {
  const t = raw.trim();
  if (!t) return null;
  try {
    const u = new URL(/^[a-z]+:\/\//i.test(t) ? t : 'https://' + t);
    return /^https?:$/.test(u.protocol) && /^[a-z0-9.-]+$/i.test(u.hostname) && u.hostname.includes('.') || u.hostname === 'localhost' ? u.origin : null;
  } catch { return null; }
}

function wgAttrs(w) {                       // los data-* del <script>, en el orden en que se leen mejor
  return [['data-bot', agent.id], ['data-title', w.title], ['data-color', w.color], ['data-greeting', w.greeting],
    ['data-position', w.position], ['data-voice', String(!!w.voice)], ['data-lang', agent.languages?.[0] || 'es']].filter(([, v]) => v !== '' && v != null);
}
const wgEsc = (v) => String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const wgSnippet = (w) => '<script src="' + location.origin + '/static/widget.js"\n' +
  wgAttrs(w).map(([k, v]) => '  ' + k + '="' + wgEsc(v) + '"').join('\n') + ' async></script>';

function wgRemovePreview() {
  document.querySelectorAll('[data-parla-widget]').forEach((el) => el.parlaDestroy ? el.parlaDestroy() : el.remove());
  document.getElementById('wg-preview-script')?.remove();
}
function wgInject() {                       // la vista previa es el widget real, cargado en esta misma página
  wgRemovePreview();
  if (!wgPreview || section !== 'widget') return;
  const s = h('script', { id: 'wg-preview-script', src: '/static/widget.js', async: true, 'data-channel': 'prueba-widget' });
  wgAttrs(wgConf()).forEach(([k, v]) => s.setAttribute(k, v));
  document.body.append(s);
}
const wgRefresh = () => { clearTimeout(wgTimer); wgTimer = setTimeout(wgInject, 500); };
const wgChanged = () => { touch(); wgRefresh(); };
// al salir de la sección, la vista previa se va sola
new MutationObserver(() => { if (section !== 'widget' && document.querySelector('[data-parla-widget]')) wgRemovePreview(); })
  .observe(document.body, { childList: true, subtree: true });

function wgOrigins(w) {
  const add = (input) => {
    const o = wgOrigin(input.value);
    if (!o) { wgError = t('Eso no parece una dirección web. Escribila como aparece arriba en el navegador, por ejemplo https://www.misitio.com'); return render(); }
    wgError = '';
    if (!w.origins.includes(o)) { w.origins.push(o); touch(); }
    render();
  };
  const input = h('input', { class: 'grow', placeholder: 'https://www.misitio.com', 'aria-label': t('Dirección del sitio'), onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); add(e.target); } } });
  return h('div', { class: 'panel' },
    h('h2', {}, t('Sitios autorizados')),
    h('p', { class: 'help' }, t('Solo las páginas de estas direcciones pueden mostrar tu chat. Así nadie lo copia en otro sitio y lo usa a tu nombre. '),
      t('Escribí la dirección tal como aparece arriba en el navegador, sin nada después del dominio: «https://www.misitio.com». '),
      t('Si tu sitio se abre con y sin «www», agregá las dos.')),
    w.origins.length ? h('div', { class: 'values' }, w.origins.map((o) => h('span', { class: 'value' }, o,
      h('button', { type: 'button', 'aria-label': t('Quitar {site}', { site: o }), title: t('Quitar'), onclick: () => { w.origins.splice(w.origins.indexOf(o), 1); touch(); render(); } }, icon('x')))))
      : h('p', { class: 'help' }, t('Todavía no autorizaste ningún sitio.')),
    h('div', { class: 'row' }, input, h('button', { class: 'btn quiet small', type: 'button', onclick: () => add(input) }, icon('plus'), t('Agregar'))),
    wgError ? h('p', { class: 'wg-error', role: 'alert' }, wgError) : null);
}

function wgCopy(text, btn) {
  const done = () => {           // la tilde aparece solo cuando se copió de verdad
    const mark = icon('check'); btn.prepend(mark); btn.lastChild.textContent = t('¡Copiado!');
    setTimeout(() => { mark.remove(); btn.lastChild.textContent = t('Copiar'); }, 1500);
  };
  navigator.clipboard?.writeText(text).then(done, () => {}) ?? (() => {
    const sel = getSelection(), r = document.createRange(); r.selectNodeContents($('.wg-snippet')); sel.removeAllRanges(); sel.addRange(r);
    if (document.execCommand('copy')) done();
  })();
}

window.widgetView = () => {
  const w = wgConf();
  wgRefresh();
  const check = (key, text, sub, after) => h('label', { class: 'wg-check' },
    h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!w[key], onchange: (e) => { w[key] = e.target.checked; wgChanged(); after?.(); } }),
    h('span', {}, text, sub ? h('small', {}, sub) : null));
  const snippet = wgSnippet(w);
  const copyBtn = h('button', { class: 'btn small', type: 'button', onclick: (e) => wgCopy(snippet, e.currentTarget) }, h('span', {}, t('Copiar')));
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, t('Widget web'))),
    h('p', { class: 'help' }, t('Un botón de chat para tu página web: tus clientes hablan con este bot sin salir de tu sitio. Lo configurás acá y pegás un pedacito de código en tu página.')),
    h('div', { class: 'notice warn' }, icon('globe'),
      h('span', {}, t('Hoy Parla corre en esta computadora, así que solo la ven las páginas abiertas acá mismo. Para usarlo en tu sitio real, Parla tiene que estar publicado en internet (en un servidor o con un túnel) y el código de abajo tiene que apuntar a esa dirección.'))),
    h('div', { class: 'panel' },
      check('enabled', t('Activar el chat en mi sitio'), w.enabled ? t('Prendido: los sitios autorizados ya pueden usarlo.') : t('Apagado: ningún sitio externo puede usarlo todavía.'), render)),
    w.enabled && !w.origins.length ? h('div', { class: 'notice warn' }, t('Está prendido pero sin sitios autorizados: agregá la dirección de tu página abajo.')) : null,
    wgOrigins(w),
    h('div', { class: 'panel' },
      h('h2', {}, t('Cómo se ve')),
      lab(t('Título'), h('input', bind(w, 'title', wgRefresh))),
      lab(t('Saludo (opcional, aparece apenas se abre)'), h('input', { ...bind(w, 'greeting', wgRefresh), placeholder: t('¡Hola! ¿En qué te ayudo?') })),
      h('div', { class: 'row' },
        h('div', { class: 'row', style: 'gap:8px' }, h('span', {}, t('Color')),
          colorField(w, t('Color del chat'), { hex: true, live: wgChanged, done: () => { wgChanged(); render(); } })),
        lab(t('Lugar en la pantalla'), pick([['right', t('Abajo a la derecha')], ['left', t('Abajo a la izquierda')]], w.position, (v) => { w.position = v; wgChanged(); }, t('Lugar en la pantalla')))),
      check('voice', t('Dejar que hablen por micrófono'), t('El bot escucha y contesta también con voz. Se oculta solo si el navegador no lo permite.'))),
    h('div', { class: 'panel' },
      h('div', { class: 'row' }, h('h2', { class: 'grow' }, t('Código para tu página')), copyBtn),
      h('p', { class: 'help' }, t('Copialo y pegalo en tu sitio, antes de «</body>». Si usás un armador de páginas (WordPress, Wix, Tiendanube…), buscá la opción «agregar código» o «HTML personalizado».')),
      h('pre', { class: 'wg-snippet' }, snippet)),
    h('div', { class: 'panel' }, h('label', { class: 'wg-check' },
      h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: wgPreview, onchange: (e) => { wgPreview = e.target.checked; wgInject(); } }),
      h('span', {}, t('Ver la vista previa en esta pantalla'),
        h('small', {}, t('Es el chat de verdad, abajo en la esquina. Las charlas de prueba quedan en Conversaciones con el canal «prueba-widget».'))))));
};
