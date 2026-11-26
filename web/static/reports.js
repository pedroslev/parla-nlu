// Reportes: cómo terminaron las conversaciones, según las clasificaciones que aplican los flujos.
let rpRange = '30', rpFrom = '', rpTo = '', rpChannel = '', rpCampaign = '', rpCampaigns = null, rpCampFor = null;   // rpCampaigns: las de /campaigns, para el filtro

document.head.append(h('style', {}, `
  .rp-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
  .rp-filters input[type="date"] { min-width: 140px; }
  .rp-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
  .rp-stat { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .rp-stat small { color: var(--muted); font-size: 13px; }
  .rp-stat b { font: 700 28px/1.1 var(--display); color: var(--ink); overflow-wrap: anywhere; }
  .rp-stat b.rp-text { font-size: 19px; display: flex; align-items: center; gap: 8px; }
  .rp-bars { display: flex; flex-direction: column; gap: 2px; }
  .rp-bar { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; align-items: center; text-align: left; padding: 8px 10px; border-radius: 10px; color: var(--ink); }
  .rp-bar:hover { background: var(--soft); }
  .rp-name { display: flex; align-items: center; gap: 8px; font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
  .rp-num { font-variant-numeric: tabular-nums; color: var(--muted); font-size: 14px; white-space: nowrap; }
  .rp-num b { color: var(--ink); font-size: 15px; }
  .rp-track { grid-column: 1 / -1; height: 10px; border-radius: 999px; background: var(--soft); overflow: hidden; display: flex; }
  .rp-track span { display: block; height: 100%; min-width: 0; }
  :root[data-theme="dark"] .rp-track span { filter: brightness(.86) saturate(.9); }
  .rp-days { display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
  .rp-day { display: grid; grid-template-columns: 64px minmax(0, 1fr) 32px; gap: 10px; align-items: center; }
  .rp-day > small { color: var(--muted); font-variant-numeric: tabular-nums; }
  .rp-day > b { text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--ink); }
  .rp-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; color: var(--muted); }
  .rp-legend span { display: inline-flex; align-items: center; gap: 6px; }
  .rp-legend .dot { width: 10px; height: 10px; }
  .rp-error { color: var(--warn); }
  .rp-sub { color: var(--muted); font-size: 13px; }
  .rp-stat.warn b { color: var(--warn); }
  .rp-stat.good b { color: var(--ok); }
  .rp-csat { display: flex; flex-direction: column; gap: 4px; }
  .rp-csat .rp-day { grid-template-columns: 64px minmax(0, 1fr) 32px; }
`));

const RP_NONE = 'var(--line)';        // "Sin clasificar"
const RP_GONE = 'var(--muted)';       // clasificaciones que ya no están en el agente
const rpDay = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const rpAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return rpDay(d); };
const rpShort = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d).toLocaleDateString(t.locale, { day: 'numeric', month: 'numeric' }); };
const rpColor = (name) => { const c = agent.classifications.find((x) => x.name === name); return c ? colorOf(c)[0] : RP_GONE; };   // como el resto: paleta o libre
const rpOpenSessions = (classification) => { window.sessionsFilter = { classification }; section = 'sessions'; render(); $('#center').scrollTop = 0; };
const rpGoClassifications = () => { section = 'classifications'; render(); $('#center').scrollTop = 0; };

function rpDates() {                    // [desde, hasta] según el atajo elegido
  if (rpRange === '7') return [rpAgo(6), rpDay(new Date())];
  if (rpRange === '30') return [rpAgo(29), rpDay(new Date())];
  if (rpRange === 'all') return ['', ''];
  return [rpFrom, rpTo];
}

function rpResults(data) {
  if (!data.sessions) return [h('div', { class: 'empty' }, h('h2', {}, t('No hay conversaciones en este período')),
    h('p', {}, t('Las conversaciones llegan cuando alguien habla con el bot por la API, o cuando lo probás en el chat de la derecha. Probá con otro período o con otro canal.')))];
  const n = data.sessions, pct = (x) => Math.round((x / n) * 100) + '%';
  const rows = [...data.classifications].sort((a, b) => b.count - a.count || Number(b.configured) - Number(a.configured));
  const top = rows[0] && rows[0].count ? rows[0] : null;
  const stat = (label, value, cls) => h('div', { class: 'rp-stat' }, h('small', {}, label), h('b', { class: cls || null }, value));
  const bar = (label, count, fill, value, note) => h('button', { class: 'rp-bar', title: t('Ver estas conversaciones'), onclick: () => rpOpenSessions(value) },
    h('span', { class: 'rp-name' }, h('span', { class: 'dot', style: 'background:' + fill }), label, note ? h('small', { class: 'help', style: 'font-weight:400;font-size:13px' }, note) : null),
    h('span', { class: 'rp-num' }, h('b', {}, count), ' · ', pct(count)),
    h('span', { class: 'rp-track' }, h('span', { style: 'width:' + (count / n) * 100 + '%;background:' + fill })));
  const days = [...data.by_day].reverse();
  const most = Math.max(...days.map((d) => d.unclassified + Object.values(d.counts).reduce((a, b) => a + b, 0)));
  return [
    h('div', { class: 'rp-stats' },
      stat(t.plural(n, 'Conversación', 'Conversaciones'), n),
      stat(t('Clasificadas'), pct(n - data.unclassified)),
      stat(t('La más común'), top ? [h('span', { class: 'dot', style: 'background:' + rpColor(top.name) }), top.name] : '—', 'rp-text')),
    h('div', { class: 'panel' }, h('h2', {}, t('Cómo terminaron')),
      rows.some((c) => c.count) ? null : h('p', { class: 'help', style: 'font-size:14px' }, t('Ninguna conversación fue clasificada en este período. Sumá el paso «Clasificar la conversación» en tus flujos.')),
      h('div', { class: 'rp-bars' },
        rows.map((c) => bar(c.name, c.count, rpColor(c.name), c.name, c.configured ? null : t('(ya no está en el agente)'))),
        bar(t('Sin clasificar'), data.unclassified, RP_NONE, '__none__')),
      h('p', { class: 'help', style: 'font-size:13px' }, t('Tocá una fila para ver esas conversaciones. Una conversación puede tener más de una clasificación, por eso los porcentajes pueden sumar más de 100%.'))),
    h('div', { class: 'panel' }, h('h2', {}, t('Por día')),
      h('div', { class: 'rp-legend' }, rows.map((c) => h('span', {}, h('span', { class: 'dot', style: 'background:' + rpColor(c.name) }), c.name)),
        h('span', {}, h('span', { class: 'dot', style: 'background:' + RP_NONE }), t('Sin clasificar'))),
      h('div', { class: 'rp-days' }, days.map((d) => {
        const parts = [...rows.map((c) => [c.name, d.counts[c.name] || 0, rpColor(c.name)]), [t('Sin clasificar'), d.unclassified, RP_NONE]].filter((p) => p[1]);
        return h('div', { class: 'rp-day', title: parts.map(([name, k]) => name + ': ' + k).join(', ') },
          h('small', {}, rpShort(d.date)),
          h('span', { class: 'rp-track', style: 'grid-column:auto;height:14px' }, parts.map(([, k, fill]) => h('span', { style: 'width:' + (k / most) * 100 + '%;background:' + fill }))),
          h('b', {}, d.sessions));
      }))),
  ];
}

// Lo que importa al negocio: cuántas resolvió el bot, cuántas pasaron a una persona, cuánto no entendió, satisfacción y abandono.
function rpAnalytics(a) {
  if (!a.sessions) return [h('p', { class: 'help' }, t('Todavía no hay conversaciones en este período.'))];
  const pct = (x) => x == null ? '—' : Math.round(x * 100) + '%';
  const stat = (label, value, sub, cls) => h('div', { class: 'rp-stat ' + (cls || '') }, h('small', {}, label), h('b', {}, value), sub ? h('span', { class: 'rp-sub' }, sub) : null);
  const c = a.csat || {};
  const goImprove = () => { section = 'improve'; render(); $('#center').scrollTop = 0; };
  const asked = (q) => q ? t('en la pregunta «{question}»', { question: q }) : t('esperando una respuesta');
  const drops = a.drop_off || [], flows = (a.flows || []).filter((f) => f.started);
  const most = Math.max(1, ...drops.map((d) => d.count));
  const csatMost = Math.max(1, ...Object.values(c.distribution || {}));
  return [
    h('div', { class: 'rp-stats' },
      stat(t('Las resolvió el bot'), pct(a.contained_rate), t('{done} de {total} sin ayuda de una persona', { done: a.contained, total: a.sessions }), a.contained_rate >= 0.8 ? 'good' : null),
      stat(t('Pasaron a una persona'), pct(a.handoff_rate), t.plural(a.handoff, '{n} conversación', '{n} conversaciones')),
      stat(t('No entendió'), pct(a.fallback_rate), a.user_messages ? t('{done} de {total} mensajes', { done: a.fallbacks, total: a.user_messages }) : t('sin mensajes'), a.fallback_rate > 0.2 ? 'warn' : null),
      stat(t('Satisfacción'), c.average == null ? '—' : c.average.toLocaleString(t.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' / 5', c.answered ? t.plural(c.answered, '{n} respuesta', '{n} respuestas') : t('nadie contestó la encuesta')),
      stat(t('Se fueron a mitad de camino'), a.abandoned, t('dejaron de contestar más de 30 min'), a.abandoned ? 'warn' : null)),
    a.fallbacks ? h('div', { class: 'notice' }, icon('lightbulb'), h('span', { class: 'grow' }, t('Hay mensajes que el bot no entendió. Enseñale qué quisieron decir.')),
      h('button', { class: 'btn small', onclick: goImprove }, t('Ir a Para enseñar'))) : null,
    h('div', { class: 'panel' }, h('h2', {}, t('Dónde se van')),
      drops.length ? h('div', { class: 'rp-bars' }, drops.map((d) => h('div', { class: 'rp-bar' },
        h('span', { class: 'rp-name' }, d.flow, h('small', { class: 'help', style: 'font-weight:400;font-size:13px' }, asked(d.question))),
        h('span', { class: 'rp-num' }, h('b', {}, d.count), t.plural(d.count, ' persona', ' personas')),
        h('span', { class: 'rp-track' }, h('span', { style: 'width:' + (d.count / most) * 100 + '%;background:var(--warn)' })))))
        : h('p', { class: 'help', style: 'font-size:14px' }, t('Nadie dejó una conversación a medias en este período.')),
      flows.length ? h('div', { class: 'rp-bars' }, h('h3', { style: 'font-size:14px;margin-top:6px' }, t('Por flujo')),
        flows.map((f) => h('div', { class: 'rp-bar' }, h('span', { class: 'rp-name' }, f.flow),
          h('span', { class: 'rp-num' }, h('b', {}, f.started), t(' empezaron') + ' · ', h('b', {}, f.dropped), t(' se fueron')),
          h('span', { class: 'rp-track' }, h('span', { style: 'width:' + (1 - f.dropped / f.started) * 100 + '%;background:var(--ok)' }),
            h('span', { style: 'width:' + (f.dropped / f.started) * 100 + '%;background:var(--warn)' }))))) : null,
      h('p', { class: 'help', style: 'font-size:13px' }, t('Conversaciones que quedaron esperando una respuesta del cliente y no volvió en más de 30 minutos.'))),
    c.answered ? h('div', { class: 'panel' }, h('h2', {}, t('Cómo calificaron la atención')),
      h('div', { class: 'rp-days rp-csat' }, [5, 4, 3, 2, 1].map((n) => h('div', { class: 'rp-day' },
        h('small', {}, t.plural(n, '{n} estrella', '{n} estrellas')),
        h('span', { class: 'rp-track', style: 'grid-column:auto;height:14px' }, h('span', { style: 'width:' + ((c.distribution[n] || 0) / csatMost) * 100 + '%;background:' + (n >= 4 ? 'var(--ok)' : n === 3 ? 'var(--muted)' : 'var(--warn)') })),
        h('b', {}, c.distribution[n] || 0))))) : null,
  ];
}

function rpReport() {
  if (rpCampFor !== agent.id) {          // una vez por agente; si todavía no hay campañas (o el servidor no las tiene) no aparece el filtro
    rpCampFor = agent.id; rpCampaigns = null; rpCampaign = '';
    api('GET', '/' + agent.id + '/campaigns').then((r) => { rpCampaigns = r.campaigns || []; if (rpCampaigns.length && section === 'reports') render(); }, () => {});
  }
  const [from, to] = rpDates();
  const setDate = (which) => (e) => { [rpFrom, rpTo] = rpDates(); if (which === 'from') rpFrom = e.target.value; else rpTo = e.target.value; rpRange = 'custom'; render(); };
  const filters = h('div', { class: 'rp-filters' },
    lab(t('Período'), pick([['7', t('Últimos 7 días')], ['30', t('Últimos 30 días')], ['all', t('Todo')], ['custom', t('Elegir fechas')]], rpRange, (v) => { if (v === 'custom') [rpFrom, rpTo] = rpDates(); rpRange = v; render(); })),
    lab(t('Desde'), h('input', { type: 'date', value: from, max: to || null, onchange: setDate('from') })),
    lab(t('Hasta'), h('input', { type: 'date', value: to, min: from || null, onchange: setDate('to') })),
    lab(t('Canal'), pick([['', t('Todos')], ['api', 'API'], ['prueba', t('Chat de prueba')]], rpChannel, (v) => { rpChannel = v; render(); })),
    rpCampaigns?.length ? lab(t('Campaña'), pick([['', t('Todas las conversaciones')], ...rpCampaigns.map((c) => [c.id, c.name])], rpCampaign, (v) => { rpCampaign = v; render(); })) : null);
  const q = new URLSearchParams(Object.entries({ from, to, channel: rpChannel, campaign: rpCampaign }).filter(([, v]) => v));
  const stats = h('div', { class: 'stack', style: 'gap:18px', 'aria-live': 'polite' }, h('p', { class: 'help' }, t('Cargando los números…')));
  api('GET', '/' + agent.id + '/insights/analytics?' + q).then((a) => { if (stats.isConnected) stats.replaceChildren(...rpAnalytics(a).filter(Boolean)); },
    (e) => stats.replaceChildren(h('p', { class: 'rp-error' }, t('No se pudieron cargar los números: {error}.', { error: e.message }))));
  if (!agent.classifications.length) return [filters, stats,
    h('div', { class: 'empty' }, h('h2', {}, t('Todavía no hay clasificaciones')),
      h('p', {}, t('Para ver cómo terminaron las conversaciones, creá clasificaciones (por ejemplo «Turno agendado» o «Cancelación») y aplicalas desde un flujo.')),
      h('button', { class: 'btn', onclick: rpGoClassifications }, t('Ir a Clasificaciones')))];
  const box = h('div', { class: 'panel', 'aria-live': 'polite' }, h('p', { class: 'help' }, t('Cargando el reporte…')));
  (async () => {
    try {
      await saveNow();                    // así cuenta las clasificaciones recién creadas o renombradas
      const r = await fetch('/api/v1/bots/' + encodeURIComponent(agent.id) + '/report?' + q);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || r.status);
      if (box.isConnected) box.replaceWith(...rpResults(data));
    } catch (e) {
      box.replaceChildren(h('p', { class: 'rp-error' }, t('No se pudo cargar el reporte: {error}.', { error: e.message })),
        h('div', {}, h('button', { class: 'btn quiet small', onclick: () => render() }, t('Probar de nuevo'))));
    }
  })();
  return [filters, stats, box];
}

window.reportsView = () => h('div', { class: 'page' }, h('h1', {}, t('Reportes')),
  h('p', { class: 'help' }, t('Cuántas conversaciones resolvió el bot solo, dónde se traba la gente y cómo terminaron, según las clasificaciones que aplican tus flujos.')),
  rpReport());
