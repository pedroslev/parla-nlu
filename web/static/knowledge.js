// Conocimiento: textos, preguntas frecuentes, páginas web y PDFs con los que el bot responde cuando ningún flujo cubre la pregunta.
// Los documentos viven en agent.knowledge (se exportan y versionan con el agente). La búsqueda la hace knowledge.py.
document.head.append(h('style', {}, `
  .kn-doc { text-align: left; display: flex; flex-direction: column; gap: 4px; width: 100%; }
  .kn-doc small, .kn-meta { color: var(--muted); font-size: 13px; }
  .kn-doc .kn-snip { color: var(--muted); font-size: 14px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .kn-doc:hover strong { color: var(--brand); }
  .kn-text { min-height: 220px; max-height: 60vh; overflow-y: auto !important; font-size: 14.5px; line-height: 1.55; }
  .kn-pair { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
  .kn-hit { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; background: var(--soft); }
  .kn-hit p { white-space: pre-wrap; font-size: 14px; overflow-wrap: anywhere; }
  .kn-hit.off { opacity: .6; }
  .kn-score { font-weight: 700; color: var(--ok); }
  .kn-hit.off .kn-score { color: var(--muted); }
  .kn-err { color: var(--warn); font-size: 14px; }
`));

// draft: lo que se está escribiendo en «Nuevo…» (sobrevive a los redibujos); edit: preguntas del documento abierto, con las vacías recién agregadas
const kn = { open: null, adding: null, busy: false, error: '', test: '', results: null, draft: {}, edit: null };
query.knowledge ??= '';
const knDocs = () => (agent.knowledge ||= []);
const knSource = (d) => ({ url: 'Página web', pdf: 'PDF' }[d.source] || 'Texto');
const knId = () => 'k' + Math.random().toString(36).slice(2, 8);
const knFlat = (t) => String(t || '').replace(/^#+\s*/gm, '').replace(/\s+/g, ' ').trim();

// «P: … / R: …» ↔ [{q, a}]. Si el texto no es solo preguntas y respuestas, devuelve null (se edita como texto).
function knParse(text) {
  const blocks = String(text || '').trim().split(/\n\s*\n(?=\s*P:)/);
  const pairs = blocks.map((b) => b.match(/^\s*P:\s*([\s\S]*?)\n\s*R:\s*([\s\S]*)$/)).map((m) => m && { q: m[1].trim(), a: m[2].trim() });
  return text?.trim() && pairs.every(Boolean) ? pairs : null;
}
const knJoin = (pairs) => pairs.filter((p) => p.q.trim() || p.a.trim()).map((p) => 'P: ' + p.q.trim() + '\nR: ' + p.a.trim()).join('\n\n');

function knAdd(doc) {
  doc = { id: knId(), title: '', source: 'texto', url: '', text: '', ...doc };
  doc.title = (doc.title || '').trim() || 'Documento sin título';
  knDocs().push(doc);
  Object.assign(kn, { adding: null, open: doc.id, error: '', draft: {}, edit: null });
  touch(); render();
}
function knRemove(d) {
  confirmBox('Borrar el documento', 'Se borra «' + d.title + '». El bot ya no va a poder responder con lo que dice. No se puede deshacer.', 'Borrar documento', () => {
    agent.knowledge = knDocs().filter((x) => x !== d);
    if (kn.open === d.id) kn.open = null;
    touch(); render();
  });
}
async function knExtract(kind, body, extra) {        // le pide al servidor el texto de una web o un archivo
  kn.busy = true; kn.error = ''; render();
  try { const out = await api('POST', '/' + agent.id + '/knowledge/extract', { kind, ...body }); kn.busy = false; knAdd({ ...out, ...extra(out) }); }
  catch (e) { kn.busy = false; kn.error = e.message; render(); }
}
function knFile(file) {
  if (!file) return;
  if (file.size > 15 * 1024 * 1024) { kn.error = 'El archivo es muy grande (máximo 15 MB).'; return render(); }
  const name = file.name.replace(/\.[^.]+$/, '');
  if (/\.pdf$/i.test(file.name) || file.type === 'application/pdf') {
    const r = new FileReader();
    r.onload = () => knExtract('pdf', { data: r.result }, (o) => ({ source: 'pdf', title: o.title || name }));
    r.readAsDataURL(file);
  } else file.text().then((t) => knExtract(/\.html?$/i.test(file.name) ? 'html' : 'text', { data: t }, (o) => ({ source: 'texto', title: /\.html?$/i.test(file.name) && o.title ? o.title : name })));
}

function knMenu(e) {
  const pick = (kind) => { closePop(); Object.assign(kn, { adding: kind, open: null, error: '', draft: { title: kind === 'faq' ? 'Preguntas frecuentes' : '', text: '', pairs: [{ q: '', a: '' }] } }); render(); $('#center').scrollTop = 0; $('.kn-first')?.focus(); };
  const item = (ic, kind, title, sub) => h('button', { class: 'item', style: 'display:flex;gap:10px;align-items:flex-start;text-align:left;padding:8px 10px;border-radius:8px', onclick: () => pick(kind) },
    icon(ic), h('span', { style: 'display:flex;flex-direction:column' }, h('strong', {}, title), h('small', { style: 'color:var(--muted)' }, sub)));
  openPop(e.currentTarget.getBoundingClientRect(), h('div', { class: 'stack', style: 'gap:2px;max-width:320px' },
    item('pencil', 'text', 'Pegar un texto', 'Información de tu negocio, políticas, precios…'),
    item('question', 'faq', 'Preguntas frecuentes', 'Escribí cada pregunta con su respuesta'),
    item('globe', 'url', 'Desde una página web', 'Traemos el texto de una dirección'),
    item('up', 'file', 'Subir un archivo', 'PDF, TXT o Markdown')));
}

function knPairsEditor(pairs, onchange) {        // lista de preguntas y respuestas
  const up = () => onchange(pairs);
  return h('div', { class: 'stack', style: 'gap:14px' },
    pairs.map((p, i) => h('div', { class: 'kn-pair' },
      h('div', { class: 'row', style: 'flex-wrap:nowrap' },
        h('input', { class: 'grow' + (i === 0 ? ' kn-first' : ''), value: p.q, placeholder: 'Pregunta, por ejemplo: ¿Qué días abren?', 'aria-label': 'Pregunta ' + (i + 1), oninput: (e) => { p.q = e.target.value; up(); } }),
        iconBtn('trash', 'Quitar esta pregunta', () => { pairs.splice(i, 1); if (!pairs.length) pairs.push({ q: '', a: '' }); up(); render(); })),
      h('textarea', { rows: 2, value: p.a, placeholder: 'Respuesta, por ejemplo: De lunes a viernes de 9 a 18.', 'aria-label': 'Respuesta ' + (i + 1), oninput: (e) => { p.a = e.target.value; grow(e.target); up(); } }))),
    h('div', {}, h('button', { class: 'link', onclick: () => { pairs.push({ q: '', a: '' }); up(); render(); [...document.querySelectorAll('.kn-pair input')].pop()?.focus(); } }, 'Agregar otra pregunta')));
}

function knAddPanel() {
  const draft = (key) => ({ value: kn.draft[key] ?? '', oninput: (e) => { kn.draft[key] = e.target.value; } });
  const cancel = h('button', { class: 'btn quiet', onclick: () => { kn.adding = null; kn.error = ''; render(); } }, 'Cancelar');
  const err = kn.error ? h('p', { class: 'kn-err', role: 'alert' }, kn.error) : null;
  const busy = kn.busy ? h('p', { class: 'help' }, 'Leyendo…') : null;
  if (kn.adding === 'text') {
    const title = h('input', { class: 'kn-first', ...draft('title'), placeholder: 'Por ejemplo: Política de cambios', 'aria-label': 'Título' });
    const text = h('textarea', { class: 'kn-text', ...draft('text'), placeholder: 'Pegá acá el texto. Podés usar «# Título» para separar secciones.', 'aria-label': 'Texto' });
    return h('div', { class: 'panel' }, h('h2', {}, 'Pegar un texto'), lab('Título', title), lab('Texto', text), err,
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => { if (!text.value.trim()) { kn.error = 'Escribí o pegá algún texto.'; return render(); } knAdd({ title: title.value || text.value.trim().split('\n')[0].slice(0, 60), text: text.value.trim() }); } }, 'Guardar'), cancel));
  }
  if (kn.adding === 'faq') {
    const title = h('input', { ...draft('title'), 'aria-label': 'Título' });
    return h('div', { class: 'panel' }, h('h2', {}, 'Preguntas frecuentes'), lab('Título', title),
      h('p', { class: 'help', style: 'font-size:14px' }, 'No hace falta que la gente pregunte con las mismas palabras: el bot entiende preguntas parecidas.'),
      knPairsEditor(kn.draft.pairs, () => {}), err,
      h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => { const text = knJoin(kn.draft.pairs); if (!text) { kn.error = 'Escribí al menos una pregunta con su respuesta.'; return render(); } knAdd({ title: title.value, text }); } }, 'Guardar'), cancel));
  }
  if (kn.adding === 'url') {
    const url = h('input', { class: 'grow kn-first', ...draft('url'), type: 'url', placeholder: 'https://misitio.com/preguntas', 'aria-label': 'Dirección de la página' });
    const go = (e) => { e.preventDefault(); const u = url.value.trim(); if (u) knExtract('url', { url: /^https?:\/\//i.test(u) ? u : 'https://' + u }, () => ({ source: 'url', url: /^https?:\/\//i.test(u) ? u : 'https://' + u })); };
    return h('div', { class: 'panel' }, h('h2', {}, 'Desde una página web'),
      h('p', { class: 'help', style: 'font-size:14px' }, 'Traemos el texto de la página una vez. Si la página cambia, volvé a traerla o editá el texto acá.'),
      h('form', { class: 'row', onsubmit: go }, url, h('button', { class: 'btn', disabled: kn.busy }, 'Traer texto')), busy, err, h('div', {}, cancel));
  }
  return h('div', { class: 'panel' }, h('h2', {}, 'Subir un archivo'),
    h('p', { class: 'help', style: 'font-size:14px' }, 'PDF, TXT o Markdown. Los PDF escaneados (fotos de papel) no tienen texto para leer.'),
    h('input', { class: 'kn-first', type: 'file', accept: '.pdf,.txt,.md,.markdown,.html,.htm,application/pdf,text/plain,text/markdown,text/html', 'aria-label': 'Elegir archivo', disabled: kn.busy, onchange: (e) => knFile(e.target.files[0]) }),
    busy, err, h('div', {}, cancel));
}

function knEditor(d) {
  if (kn.edit?.id !== d.id) kn.edit = { id: d.id, pairs: knParse(d.text) };
  const pairs = kn.edit.pairs;
  const meta = [knSource(d), /^https?:\/\//i.test(d.url || '') ? h('a', { class: 'link', href: d.url, target: '_blank', rel: 'noopener' }, d.url) : null, d.text ? d.text.length.toLocaleString('es') + ' letras' : null].filter(Boolean);
  return h('div', { class: 'page' },
    h('div', {}, h('button', { class: 'link', onclick: () => { kn.open = null; render(); } }, '← Todos los documentos')),
    h('div', { class: 'row', style: 'flex-wrap:nowrap' }, h('input', { class: 'title', ...bind(d, 'title'), 'aria-label': 'Título del documento' }), iconBtn('trash', 'Borrar documento', () => knRemove(d))),
    h('div', { class: 'row kn-meta' }, meta.flatMap((m, i) => i ? [' · ', m] : [m])),
    pairs
      ? h('div', { class: 'panel' }, knPairsEditor(pairs, (p) => { d.text = knJoin(p); touch(); }),
        h('div', {}, h('button', { class: 'link', style: 'font-size:14px', onclick: () => { kn.edit.pairs = null; render(); } }, 'Editar como texto')))
      : h('div', { class: 'panel' }, lab('Texto', h('textarea', { class: 'kn-text', ...bind(d, 'text'), 'aria-label': 'Texto del documento' })),
        h('p', { class: 'help', style: 'font-size:13px' }, 'Consejo: dejá una línea en blanco entre temas, y usá «# Título» para separar secciones o «P:» / «R:» para preguntas y respuestas.')));
}

function knTester() {
  const th = agent.knowledge_threshold ?? 0.75;
  const input = h('input', { class: 'grow', value: kn.test, placeholder: 'Por ejemplo: ¿hacen envíos al interior?', 'aria-label': 'Pregunta de prueba', oninput: (e) => { kn.test = e.target.value; } });
  const go = async (e) => {
    e.preventDefault(); if (!kn.test.trim()) return;
    kn.results = 'loading'; render();
    try { await saveNow(); kn.results = (await api('POST', '/' + agent.id + '/knowledge/search', { query: kn.test, k: 3 })).results; }
    catch (err) { kn.results = err.message; }
    render(); $('#kn-test input')?.focus();
  };
  const res = kn.results;
  return h('div', { class: 'panel', id: 'kn-test' }, h('h2', {}, 'Probar una pregunta'),
    h('p', { class: 'help', style: 'font-size:14px' }, 'Escribí algo que preguntaría un cliente y mirá qué partes de tus documentos encuentra el bot.'),
    h('form', { class: 'row', onsubmit: go }, input, h('button', { class: 'btn quiet', disabled: res === 'loading' }, 'Buscar')),
    res === 'loading' ? h('p', { class: 'help' }, 'Buscando…')
      : typeof res === 'string' ? h('p', { class: 'kn-err' }, 'No se pudo buscar: ' + res)
        : Array.isArray(res) ? (res.length ? res.map((r) => h('div', { class: 'kn-hit' + (r.score < th ? ' off' : '') },
          h('div', { class: 'row', style: 'gap:8px' }, h('span', { class: 'kn-score' }, Math.round(r.score * 100) + '% parecido'), h('small', { class: 'kn-meta' }, r.title),
            h('small', { class: 'kn-meta', style: 'margin-left:auto' }, r.score >= th ? 'lo usaría para responder' : 'no alcanza el mínimo')),
          h('p', {}, r.text))) : h('p', { class: 'help' }, 'No hay documentos para buscar todavía.')) : null);
}

function knThreshold() {
  const th = agent.knowledge_threshold ?? 0.75, pct = h('strong', {}, Math.round(th * 100) + '%');
  return h('div', { class: 'panel' }, h('h2', {}, 'Qué tan parecido tiene que ser'),
    h('div', { class: 'row' }, 'Flexible', h('input', { class: 'grow', type: 'range', min: 0.3, max: 0.9, step: 0.05, value: th, 'aria-label': 'Parecido mínimo', style: 'padding:0',
      oninput: (e) => { agent.knowledge_threshold = Number(e.target.value); pct.textContent = Math.round(agent.knowledge_threshold * 100) + '%'; touch(); } }), 'Estricto', pct),
    h('p', { class: 'help', style: 'font-size:14px' }, 'El bot solo usa un texto si se parece a la pregunta al menos este porcentaje. Si responde con cosas que no tienen que ver, subilo. Si dice «no entendí» aunque la respuesta está en tus documentos, bajalo. Probalo abajo.'));
}

window.knowledgeView = function () {
  const docs = knDocs(), open = docs.find((d) => d.id === kn.open);
  if (open) return knEditor(open);
  kn.edit = null;
  const rows = docs.map((d) => {
    const n = knParse(d.text)?.length;
    const el = h('div', { class: 'panel', style: 'padding:14px 16px' }, h('div', { class: 'row', style: 'flex-wrap:nowrap;align-items:flex-start' },
      h('button', { class: 'kn-doc', onclick: () => { kn.open = d.id; render(); $('#center').scrollTop = 0; } },
        h('strong', {}, d.title || 'Sin título'), h('small', {}, knSource(d) + (n ? ' · ' + n + (n === 1 ? ' pregunta' : ' preguntas') : ' · ' + (d.text || '').length.toLocaleString('es') + ' letras')),
        h('span', { class: 'kn-snip' }, knFlat(d.text).slice(0, 220))),
      iconBtn('trash', 'Borrar documento', () => knRemove(d))));
    return [el, d.title + ' ' + d.text];
  });
  const [search, none] = docs.length ? searchBox('knowledge', 'Buscar en los documentos', rows) : [null, null];
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, 'Conocimiento'), search, h('button', { class: 'btn', onclick: knMenu }, icon('plus'), 'Nuevo…')),
    h('p', { class: 'help' }, 'Acá guardás lo que el bot tiene que saber: horarios, precios, políticas, preguntas frecuentes. El bot responde con esto cuando no hay un flujo para la pregunta. ',
      h('button', { class: 'link', onclick: () => { section = 'ai'; render(); } }, 'Ver ajustes de IA')),
    kn.adding ? knAddPanel() : null,
    docs.length ? [rows.map(([el]) => el), none]
      : kn.adding ? null : h('div', { class: 'empty' }, h('h2', {}, 'Todavía no hay documentos'), h('p', {}, 'Empezá con tus preguntas frecuentes o pegá un texto con la información de tu negocio.'),
        h('button', { class: 'btn', onclick: knMenu }, icon('plus'), 'Nuevo…')),
    docs.length ? [knThreshold(), knTester()] : null);
};
