// Registro del último entrenamiento: se abre tocando "Entrenado HH:MM" arriba a la derecha.
(() => {
  document.head.append(h('style', {}, `
    .tl { width: min(640px, calc(100vw - 32px)); max-height: min(86vh, 900px); padding: 0; }
    .tl[open] { display: flex; flex-direction: column; }
    .tl-head { display: flex; align-items: flex-start; gap: 12px; padding: 20px 24px 12px; border-bottom: 1px solid var(--line); }
    .tl-head h2 { font: 700 22px/1.2 var(--display); }
    .tl-head p { color: var(--muted); font-size: 14px; margin-top: 4px; }
    .tl-body { overflow-y: auto; overscroll-behavior: contain; padding: 16px 24px 24px; display: flex; flex-direction: column; gap: 20px; }
    .tl-body h3 { font-size: 15px; margin: 0 0 8px; }
    .tl-score { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .tl-score strong { font: 700 40px/1 var(--display); }
    .tl-score.good strong { color: var(--ok); }
    .tl-score.meh strong { color: #8A5A00; }
    .tl-score.bad strong { color: var(--warn); }
    .tl-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .tl-steps li { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; gap: 8px; align-items: start; font-size: 14px; }
    .tl-steps li .ic { color: var(--ok); margin-top: 1px; }
    .tl-steps small { display: block; color: var(--muted); }
    .tl-ms { color: var(--muted); font-size: 13px; font-variant-numeric: tabular-nums; }
    .tl-rows { display: flex; flex-direction: column; }
    .tl-row { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(80px, 1fr) 70px; gap: 10px; align-items: center; padding: 7px 0; border-bottom: 1px solid var(--line); font-size: 14px; }
    .tl-row:last-child { border-bottom: 0; }
    .tl-row .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tl-bar { height: 8px; border-radius: 999px; background: var(--soft); overflow: hidden; }
    .tl-bar span { display: block; height: 100%; background: var(--ok); border-radius: 999px; }
    .tl-bar.low span { background: var(--warn); }
    .tl-num { text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }
    .tl-mistake { padding: 10px 12px; border-radius: 10px; background: var(--soft); font-size: 14px; display: flex; flex-direction: column; gap: 4px; }
    .tl-mistake q { font-size: 15px; color: var(--ink); }
    .tl-mistake span { color: var(--muted); }
    .tl-tips { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
    .tl-foot { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 24px; border-top: 1px solid var(--line); }
    .tl-cm { overflow-x: auto; overscroll-behavior-x: contain; border: 1px solid var(--line); border-radius: 10px; max-width: 100%; }
    .tl-cm table { border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
    .tl-cm th, .tl-cm td { padding: 6px 8px; border-bottom: 1px solid var(--line); text-align: center; white-space: nowrap; }
    .tl-cm thead th { color: var(--muted); font-weight: 600; max-width: 110px; overflow: hidden; text-overflow: ellipsis; }
    .tl-cm tbody th { text-align: left; font-weight: 500; position: sticky; left: 0; background: var(--surface); max-width: 150px; overflow: hidden; text-overflow: ellipsis; }
    .tl-cm td.hit { color: var(--ok); font-weight: 700; }
    .tl-cm td.miss { background: var(--warn-soft); color: var(--warn); font-weight: 700; }
    .tl-cm td.zero { color: var(--line); }
    @media (max-width: 520px) { .tl-row { grid-template-columns: minmax(0, 1fr) 70px; } .tl-row .tl-bar { display: none; } }
  `));

  const pct = (x) => Math.round(x * 100) + '%';
  const goIntent = (name, dialog) => {
    const i = agent.intents.findIndex((x) => x.name === name);
    if (i < 0) return;
    dialog.close(); section = 'intents'; sel.intents = i; render(); $('#center').scrollTop = 0;
  };

  // filas = la intención de la frase, columnas = a cuál la mandó; fuera de la diagonal = se confundió
  function matrix(confusion) {
    const real = (n) => !n.startsWith('__');
    const rows = Object.keys(confusion || {}).filter(real);
    if (rows.length < 2) return null;
    const cols = [...new Set([...rows, ...rows.flatMap((r) => Object.keys(confusion[r]))])].filter(real);
    return h('section', {}, h('h3', {}, 'Con qué intenciones se confunde'),
      h('p', { class: 'help', style: 'font-size:13px;margin-bottom:8px' }, 'Cada fila es una intención y muestra a cuál mandó sus frases: lo verde está bien, lo marcado en rojo son frases que se confunden con otra.'),
      h('div', { class: 'tl-cm', role: 'region', 'aria-label': 'Tabla de confusiones', tabindex: '0' }, h('table', {},
        h('thead', {}, h('tr', {}, h('th', { scope: 'col' }, 'Es de ↓ / la mandó a →'), cols.map((c) => h('th', { scope: 'col', title: c }, c)))),
        h('tbody', {}, rows.map((r) => h('tr', {}, h('th', { scope: 'row', title: r }, r), cols.map((c) => {
          const n = confusion[r][c] || 0;
          return h('td', { class: n ? (c === r ? 'hit' : 'miss') : 'zero', title: n ? n + (n === 1 ? ' frase de «' : ' frases de «') + r + '» fueron a «' + c + '»' : null }, n || '·');
        })))))));
  }

  function body(log, dialog) {
    const check = log.self_check || {};
    const level = check.accuracy == null ? '' : check.accuracy >= 0.85 ? 'good' : check.accuracy >= 0.6 ? 'meh' : 'bad';
    const verdict = check.accuracy == null ? 'Sumá al menos 2 frases por intención para que pueda evaluarse.'
      : check.accuracy >= 0.85 ? 'Distingue bien tus intenciones.'
      : check.accuracy >= 0.6 ? 'Se confunde a veces: mirá las frases de abajo y sumá ejemplos más distintos.'
      : 'Se confunde seguido: las intenciones se parecen mucho entre sí o tienen pocas frases.';
    return [
      h('section', {},
        h('h3', {}, 'Qué tan bien entiende'),
        h('div', { class: 'tl-score ' + level }, check.accuracy == null ? null : h('strong', {}, pct(check.accuracy)), h('span', { class: 'help' }, verdict)),
        check.checked ? h('p', { class: 'help', style: 'font-size:13px;margin-top:6px' },
          'Probó cada frase de ejemplo como si no la conociera y se fijó a qué intención la mandaría: acertó ' + check.right + ' de ' + check.checked + '.') : null),
      check.intents?.length ? h('section', {}, h('h3', {}, 'Por intención'),
        h('div', { class: 'tl-rows' }, check.intents.map((i) => h('div', { class: 'tl-row' },
          h('button', { class: 'name link', style: 'text-align:left;font-weight:500', onclick: () => goIntent(i.name, dialog) }, i.name),
          i.accuracy == null ? h('span', { class: 'help', style: 'font-size:13px' }, 'necesita 2 frases o más')
            : h('div', { class: 'tl-bar' + (i.accuracy < 0.6 ? ' low' : ''), title: pct(i.accuracy) }, h('span', { style: 'width:' + pct(i.accuracy) })),
          h('span', { class: 'tl-num' }, (i.accuracy == null ? '' : pct(i.accuracy) + ' · ') + i.phrases + ' fr.'))))) : null,
      matrix(check.confusion),
      check.mistakes?.length ? h('section', {}, h('h3', {}, 'Frases que confunde'),
        h('div', { class: 'stack' }, check.mistakes.map((m) => h('div', { class: 'tl-mistake' },
          h('q', {}, m.phrase),
          h('span', {}, 'Es de ', h('strong', {}, m.expected), ' pero se parece más a ', h('strong', {}, m.got), ' («' + m.closest + '»).'),
          h('div', {}, h('button', { class: 'link', style: 'font-size:13px', onclick: () => goIntent(m.expected, dialog) }, 'Ver ' + m.expected)))))) : null,
      log.warnings?.length ? h('section', {}, h('h3', {}, 'Para mejorar'), h('ul', { class: 'tl-tips' }, log.warnings.map((w) => h('li', {}, w)))) : null,
      log.entities?.length ? h('section', {}, h('h3', {}, 'Entidades'),
        h('div', { class: 'tl-rows' }, log.entities.map((e) => h('div', { class: 'tl-row', style: 'grid-template-columns:minmax(0,1fr) auto' },
          h('span', { class: 'name' }, h('span', { class: 'dot', style: markStyle(entityOf(e.name)) + ';margin-right:8px;vertical-align:-2px' }), e.name),
          h('span', { class: 'tl-num' }, e.kind + (e.marked ? ' · marcada ' + e.marked + (e.marked === 1 ? ' vez' : ' veces') : '')))))) : null,
      h('section', {}, h('h3', {}, 'Pasos'),
        h('ol', { class: 'tl-steps' }, (log.steps || []).map((s) => h('li', {}, icon('check'), h('span', {}, s.name, h('small', {}, s.detail)), h('span', { class: 'tl-ms' }, s.ms + ' ms'))))),
    ];
  }

  window.trainLogView = () => {
    const t = agent?.trained;
    const log = t?.log;
    const dialog = h('dialog', { class: 'tl', 'aria-labelledby': 'tl-title' });
    const close = () => dialog.close();
    dialog.append(
      h('div', { class: 'tl-head' },
        h('div', { class: 'grow' }, h('h2', { id: 'tl-title' }, 'Último entrenamiento'),
          h('p', {}, t ? t.at.replace(' ', ' a las ') + (log ? ' · tardó ' + (log.duration_ms / 1000).toFixed(1) + ' s' : '') + ' · ' + t.phrases + ' frases, ' + t.marked + ' datos marcados' : 'Todavía no se entrenó.')),
        iconBtn('x', 'Cerrar', close)),
      h('div', { class: 'tl-body' }, log ? body(log, dialog)
        : h('p', { class: 'help' }, 'Este entrenamiento es de antes de que Parla guardara el detalle. Entrená de nuevo para verlo.')),
      h('div', { class: 'tl-foot' },
        untrained() ? h('span', { class: 'help grow', style: 'font-size:13px;align-self:center' }, 'Hay cambios que todavía no están en este entrenamiento.') : null,
        h('button', { class: 'btn quiet', onclick: close }, 'Cerrar'),
        h('button', { class: 'btn', onclick: async () => { close(); await trainNow(); window.trainLogView(); } }, icon('spark'), 'Entrenar de nuevo')));
    dialog.onclose = () => dialog.remove();
    dialog.addEventListener('click', (e) => { if (e.target === dialog) close(); });   // clic afuera
    document.body.append(dialog);
    dialog.showModal();
  };
})();
