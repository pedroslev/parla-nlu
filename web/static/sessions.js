// Conversaciones: lo que la gente habló con el agente (por la API o en el chat de prueba).
let svSel = null, svQuery = '', svChannel = 'all', svClass = 'all', svEnv = 'all';

document.head.append(h('style', {}, `
  .sv { max-width: 1040px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; }
  .sv-grid { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 24px; align-items: start; }
  .sv-filters { display: flex; gap: 8px; flex-wrap: wrap; }
  .sv-filters input { flex: 1; min-width: 180px; }
  .sv-list { display: flex; flex-direction: column; gap: 4px; position: sticky; top: 0; max-height: calc(100vh - 160px); overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; padding: 2px; min-width: 0; }
  .sv-item { text-align: left; padding: 10px 12px; border-radius: 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .sv-item:hover { background: var(--surface); }
  .sv-item[aria-current="true"] { background: var(--surface); box-shadow: inset 3px 0 0 var(--brand); }
  .sv-item .sv-top { display: flex; gap: 8px; align-items: baseline; }
  .sv-item strong { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
  .sv-item small { color: var(--muted); font-size: 13px; }
  .sv-preview { color: var(--muted); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sv-state { font-size: 12px; font-weight: 600; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }
  .sv-state::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .sv-state.live { color: var(--ok); }
  .sv-state.done { color: var(--muted); }
  .sv-head { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .sv-head h2 { font: 700 20px/1.2 var(--display); overflow-wrap: anywhere; }
  .sv-log { display: flex; flex-direction: column; gap: 6px; }
  .sv-at { font-size: 11.5px; color: var(--muted); margin-top: -2px; }
  .sv-at.user { align-self: flex-end; }
  .sv-event { align-self: center; text-align: center; font-size: 13px; color: var(--muted); background: var(--soft); border-radius: 999px; padding: 4px 14px; margin: 6px 0; max-width: 100%; overflow-wrap: anywhere; }
  .sv-event b { color: var(--ink); font-weight: 600; }
  .sv .kv { max-height: none; margin: 0; }
  .sv-tags { display: flex; gap: 4px; flex-wrap: wrap; min-width: 0; }
  .sv-tag { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 1px 8px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sv-tag.none { background: var(--soft); color: var(--muted); }
  .sv-env { font-size: 11.5px; font-weight: 600; border: 1px solid currentColor; border-radius: 6px; padding: 0 6px; white-space: nowrap; color: var(--muted); }
  .sv-env.production { color: var(--ok); }
  .sv-env.staging { color: var(--brand); }
  @media (max-width: 900px) {
    .sv-grid { grid-template-columns: 1fr; }
    .sv-list { position: static; max-height: 320px; }
  }
`));

const svChannelName = (c) => c === 'api' ? 'API' : c === 'prueba' ? 'Chat de prueba' : c;
const svValue = (v) => typeof v === 'string' ? v : JSON.stringify(v);
const svTime = (iso) => (iso || '').slice(11, 16);
function svWhen(iso) {
  const d = new Date(iso), today = new Date();
  if (isNaN(d)) return '';
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(today) - day(d)) / 864e5);
  if (diff === 0) return 'hoy ' + svTime(iso);
  if (diff === 1) return 'ayer ' + svTime(iso);
  return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short', year: d.getFullYear() === today.getFullYear() ? undefined : 'numeric' }) + ' ' + svTime(iso);
}
// Etiqueta de color de una clasificación; si ya no existe en el agente, queda gris.
function svTag(name) {
  const c = (agent.classifications || []).find((x) => x.name === name);
  return h('span', c ? { class: 'sv-tag', style: markStyle(c) } : { class: 'sv-tag none', title: 'Esta clasificación ya no existe en el agente' }, name);
}
const svTags = (names) => names?.length ? h('span', { class: 'sv-tags' }, names.map(svTag)) : null;
// Con qué versión contestó: "Producción · v3", "Pruebas · v2", "Borrador".
const SV_ENVS = { production: 'Producción', staging: 'Pruebas', draft: 'Borrador' };
const svEnvOf = (s) => s.environment || 'production';
function svEnvTag(s) {
  const env = svEnvOf(s);
  const label = env === 'draft' ? 'Borrador' : (SV_ENVS[env] || env) + ' · ' + (s.version == null ? 'borrador' : 'v' + s.version);
  return h('span', { class: 'sv-env ' + env, title: s.version == null ? 'Contestó con el borrador (sin publicar)' : 'Contestó con la versión ' + s.version }, label);
}
const svState = (ended) => h('span', { class: 'sv-state ' + (ended ? 'done' : 'live') }, ended ? 'Terminada' : 'En curso');
async function svGet(path, method) {
  const r = await fetch('/api/v1/bots/' + encodeURIComponent(agent.id) + '/sessions' + path, { method });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || 'el servidor respondió ' + r.status);
  return data;
}

window.sessionsView = () => {
  const body = h('div', { class: 'empty', role: 'status' }, 'Cargando conversaciones…');
  const root = h('div', { class: 'sv' },
    h('h1', {}, 'Conversaciones'),
    h('p', { class: 'help' }, 'Acá ves lo que la gente habló con este agente y qué entendió el bot en cada mensaje.'),
    body);
  if (window.sessionsFilter) { if (window.sessionsFilter.classification) { svClass = window.sessionsFilter.classification; svSel = null; } if (window.sessionsFilter.environment) { svEnv = window.sessionsFilter.environment; svSel = null; } delete window.sessionsFilter; }
  const myAgent = agent;
  svGet('').then(({ sessions }) => { if (agent === myAgent && root.isConnected) body.replaceWith(svBrowser(sessions)); },
    (e) => body.replaceWith(h('div', { class: 'notice warn', role: 'alert' }, 'No se pudieron cargar las conversaciones: ' + e.message + '.',
      h('button', { class: 'link', onclick: render }, 'Probar de nuevo'))));
  return root;
};

function svBrowser(sessions) {
  if (!sessions.length) return h('div', { class: 'empty' }, icon('history'),
    h('strong', {}, 'Todavía no hay conversaciones'),
    h('p', { class: 'help' }, 'Van a aparecer acá cuando alguien le escriba al agente por la API (mirá la sección API para conectarlo) o cuando lo pruebes en el chat de la derecha.'));

  const list = h('div', { class: 'sv-list', role: 'list', 'aria-label': 'Conversaciones' });
  const detail = h('div', { class: 'panel', 'aria-live': 'polite' });
  const search = h('input', { type: 'search', placeholder: 'Buscar por id o mensaje', 'aria-label': 'Buscar conversaciones', value: svQuery,
    oninput: (e) => { svQuery = e.target.value; drawList(); } });
  const channel = pick([['all', 'Todas'], ['api', 'API'], ['prueba', 'Chat de prueba']], svChannel, (v) => { svChannel = v; drawList(); }, 'Canal');
  const names = (agent.classifications || []).map((c) => c.name);
  if (svClass !== 'all' && svClass !== '__none__' && !names.includes(svClass)) names.push(svClass);  // una que vino de afuera o ya se borró
  const classes = pick([['all', 'Todas las clasificaciones'], ...names.map((n) => [n, n]), ['__none__', 'Sin clasificar']], svClass,
    (v) => { svClass = v; drawList(); }, 'Clasificación');
  const envs = pick([['all', 'Todos los entornos'], ...Object.entries(SV_ENVS)], svEnv, (v) => { svEnv = v; drawList(); }, 'Entorno');

  const marks = (s) => s.classifications || [];
  const matches = (s, q) => (svChannel === 'all' || (svChannel === 'prueba') === (s.channel === 'prueba'))
    && (svEnv === 'all' || svEnvOf(s) === svEnv)
    && (svClass === 'all' || (svClass === '__none__' ? !marks(s).length : marks(s).includes(svClass)))
    && (!q || [s.sessionId, s.first_message, s.last_message].some((t) => (t || '').toLowerCase().includes(q)));
  if (!sessions.some((s) => s.sessionId === svSel)) svSel = (sessions.find((s) => matches(s, svQuery.trim().toLowerCase())) || sessions[0]).sessionId;

  function drawList() {
    const q = svQuery.trim().toLowerCase();
    const shown = sessions.filter((s) => matches(s, q));
    list.replaceChildren(...(shown.length ? shown.map((s) => h('div', { role: 'listitem' }, h('button', {
      class: 'sv-item', 'aria-current': String(s.sessionId === svSel),
      onclick: () => { svSel = s.sessionId; drawList(); drawDetail(); if (innerWidth <= 900) detail.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
    }, h('span', { class: 'sv-top' }, h('strong', {}, s.sessionId), svEnvTag(s), svState(s.ended)),
      h('span', { class: 'sv-preview' }, s.first_message ? '«' + s.first_message + '»' : 'Sin mensajes todavía'),
      svTags(s.classifications),
      h('small', {}, svChannelName(s.channel) + ' · ' + svWhen(s.updated) + ' · ' + s.messages + (s.messages === 1 ? ' mensaje' : ' mensajes')))))
      : [h('p', { class: 'help', style: 'padding:10px 12px' }, 'Ninguna conversación coincide con el filtro.')]));
  }

  async function drawDetail() {
    const id = svSel;
    detail.replaceChildren(h('p', { class: 'help' }, 'Cargando la conversación…'));
    try {
      const s = await svGet('/' + encodeURIComponent(id));
      if (id === svSel) detail.replaceChildren(...svTranscript(s).filter(Boolean));
    } catch (e) {
      if (id === svSel) detail.replaceChildren(h('div', { class: 'notice warn', role: 'alert' }, 'No se pudo abrir la conversación: ' + e.message + '.'));
    }
  }

  drawList(); drawDetail();
  return h('div', { class: 'sv-grid' }, h('div', { class: 'stack' }, h('div', { class: 'sv-filters' }, search, channel, envs, classes), list), detail);
}

function svTranscript(s) {
  const remove = () => confirmBox('¿Borrar esta conversación?', 'Se borra «' + s.sessionId + '» con todos sus mensajes. No se puede deshacer.', 'Borrar conversación', async () => {
    try { await svGet('/' + encodeURIComponent(s.sessionId), 'DELETE'); svSel = null; render(); }
    catch (e) { alert('No se pudo borrar: ' + e.message); }
  });
  const items = s.history.map((m) => {
    if (m.from === 'event' && m.classification) return h('div', { class: 'sv-event row', style: 'gap:6px;flex-wrap:wrap;justify-content:center' },
      'Clasificada como', svTag(m.classification), '· ' + svTime(m.at));
    if (m.from === 'event') {
      const data = Object.entries(m.data || {});
      return h('div', { class: 'sv-event' }, m.text + ' · ' + svTime(m.at),
        data.length ? [h('br'), 'Llegó con datos: ', data.map(([k, v], i) => [i ? ', ' : '', h('b', {}, k), ' = ' + svValue(v)])] : null);
    }
    if (m.from === 'user') {
      const ents = (m.entities || []).map((e) => [' ', h('mark', { 'data-entity': e.entity, style: markStyle(entityOf(e.entity)) }, e.value)]);
      const read = m.answer_to ? ['Lo tomó como respuesta para ', h('strong', {}, m.answer_to)]
        : m.intent ? ['Entendió ', h('strong', {}, m.intent), m.confidence != null ? ' (' + Math.round(m.confidence * 100) + '%)' : '']
        : ['No entendió qué quería'];
      return [h('div', { class: 'msg user' }, m.text), h('div', { class: 'read' }, svTime(m.at) + ' · ', read, ents)];
    }
    const problem = m.text.startsWith('⚠');
    return [h('div', { class: 'msg ' + (problem ? 'problem' : 'bot') }, problem ? 'Error en el flujo: ' + m.text.replace(/^⚠\s*/, '') : m.text),
      h('div', { class: 'sv-at' }, svTime(m.at))];
  });
  if (s.ended) items.push(h('div', { class: 'sv-event' }, 'Terminó la conversación · ' + svTime(s.updated)));
  const slots = Object.entries(s.slots || {}).filter(([, v]) => v != null && v !== '');
  return [
    h('div', { class: 'sv-head' }, h('div', { class: 'grow stack', style: 'gap:4px;min-width:0' }, h('h2', {}, s.sessionId),
      h('span', { class: 'row', style: 'gap:8px;color:var(--muted);font-size:14px' }, svState(s.ended), svEnvTag(s), svChannelName(s.channel) + ' · empezó ' + svWhen(s.started)), svTags(s.classifications)),
      h('button', { class: 'btn danger small', onclick: remove }, icon('trash'), 'Borrar conversación')),
    h('div', { class: 'sv-log' }, items.length ? items : h('p', { class: 'help' }, 'Esta conversación no tiene mensajes.')),
    h('h2', { style: 'margin-top:8px' }, 'Qué quedó anotado'),
    slots.length ? h('dl', { class: 'kv' }, slots.map(([k, v]) => [h('dt', {}, k), h('dd', {}, svValue(v))]))
      : h('p', { class: 'help' }, 'No quedó ningún dato anotado.'),
    !s.ended && s.waiting_for ? h('p', { class: 'help' }, 'Está esperando que le respondan ', h('strong', {}, s.waiting_for), s.flow ? ' (en el flujo «' + s.flow + '»).' : '.') : null,
  ];
}
