// Conversaciones: lo que la gente habló con el agente (por la API o en el chat de prueba).
// Desde cada una se puede re-ejecutar como prueba (mismos mensajes y datos de inicio) o seguir hablando como ese cliente.
let svSel = null, svQuery = '', svChannel = 'all', svClass = 'all', svEnv = 'all', svDate = 'all';
let svHand = new Map();            // sessionId → handoff activo (lo que muestra la Bandeja)
const svReplays = {};              // sessionId original → { running, step, total } | { result, env, at } | { error }
let svView = 'orig';               // 'orig' o 'cmp' cuando hay una re-ejecución
let svTech = (() => { try { return localStorage.getItem('parla.svTech') === '1'; } catch { return false; } })();

document.head.append(h('style', {}, `
  .sv { max-width: 1120px; margin: 0 auto; display: flex; flex-direction: column; gap: 18px; container: sv / inline-size; }
  .sv-grid { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 20px; align-items: start; }
  .sv-side { display: flex; flex-direction: column; gap: 10px; position: sticky; top: 0; min-width: 0; }
  .sv-filters { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .sv-filters input { grid-column: 1 / -1; }
  .sv-filters select { min-width: 0; font-size: 14px; padding: 6px 8px; }
  .sv-count { font-size: 13px; color: var(--muted); padding: 0 4px; }
  .sv-list { display: flex; flex-direction: column; gap: 2px; max-height: calc(100dvh - 330px); min-height: 200px; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; padding: 2px; min-width: 0; }
  .sv-day { position: sticky; top: 0; z-index: 1; background: var(--bg); font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); padding: 10px 12px 4px; }
  .sv-item { width: 100%; text-align: left; padding: 9px 12px; border-radius: 10px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .sv-item:hover { background: var(--surface); }
  .sv-item[aria-current="true"] { background: var(--surface); box-shadow: inset 3px 0 0 var(--brand), 0 1px 2px rgba(23, 32, 51, .06); }
  .sv-top { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
  .sv-top strong { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
  .sv-top time { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; flex: none; }
  .sv-preview { color: var(--muted); font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sv-meta { display: flex; gap: 4px 6px; flex-wrap: wrap; align-items: center; font-size: 12px; color: var(--muted); min-width: 0; }
  .sv-state { font-size: 12px; font-weight: 600; white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; }
  .sv-state::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
  .sv-state.live { color: var(--ok); }
  .sv-state.done { color: var(--muted); }
  .sv-badge { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; border-radius: 999px; padding: 1px 8px; white-space: nowrap; background: var(--warn-soft); color: var(--warn); }
  .sv-badge .ic { width: 13px; height: 13px; }
  .sv-badge.quiet { background: var(--surface); color: var(--muted); border: 1px solid var(--line); white-space: normal; }
  .sv-tags { display: flex; gap: 4px; flex-wrap: wrap; min-width: 0; }
  .sv-tag { font-size: 12px; font-weight: 600; border-radius: 999px; padding: 1px 8px; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sv-tag.none { background: var(--soft); color: var(--muted); }
  .sv-facts .sv-tag.none { background: var(--surface); }
  .sv-env { font-size: 11.5px; font-weight: 600; border: 1px solid currentColor; border-radius: 6px; padding: 0 6px; white-space: nowrap; color: var(--muted); }
  .sv-env.production { color: var(--ok); }
  .sv-env.staging { color: var(--brand); }

  .sv-detail { min-width: 0; gap: 16px; container: svd / inline-size; }
  .sv-head { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
  .sv-head h2 { font: 700 21px/1.2 var(--display); overflow-wrap: anywhere; }
  .sv-sub { display: flex; gap: 4px 8px; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 13.5px; overflow-wrap: anywhere; }
  .sv-actions { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .sv-note { font-size: 13px; color: var(--muted); display: flex; gap: 6px; align-items: flex-start; margin-top: -8px; max-width: none; }
  .sv-note .ic { width: 15px; height: 15px; margin-top: 2px; color: var(--warn); }
  .sv-facts { background: var(--soft); border-radius: 12px; padding: 12px 14px; }
  .sv .kv { max-height: none; margin: 0; gap: 6px 14px; font-size: 14px; align-items: baseline; }
  .sv-data { display: flex; gap: 4px; flex-wrap: wrap; }
  .sv-data span { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 0 7px; font-size: 13px; overflow-wrap: anywhere; }
  .sv-data b { font-weight: 500; color: var(--muted); }
  .sv-bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; justify-content: space-between; border-bottom: 1px solid var(--line); padding-bottom: 10px; }
  .sv-seg { display: inline-flex; border: 1px solid var(--line); border-radius: 10px; overflow: hidden; }
  .sv-seg button { padding: 5px 12px; font-weight: 600; font-size: 14px; color: var(--muted); }
  .sv-seg button[aria-pressed="true"] { background: var(--brand-soft); color: var(--brand); }
  .sv-toggle[aria-pressed="true"] { border-color: var(--brand); color: var(--brand); background: var(--brand-soft); }
  .sv-log { display: flex; flex-direction: column; gap: 6px; }
  .sv-log .msg.human, .sv-col .msg.human { border: 1px solid var(--brand); color: var(--ink); }
  .sv-at { font-size: 11.5px; color: var(--muted); margin-top: -2px; }
  .sv-at.user { align-self: flex-end; }
  .sv-event { align-self: center; display: inline-flex; gap: 6px; flex-wrap: wrap; justify-content: center; align-items: center; text-align: center; font-size: 13px; color: var(--muted); background: var(--soft); border-radius: 999px; padding: 3px 14px; margin: 6px 0; max-width: 100%; overflow-wrap: anywhere; }
  .sv-tech { display: none; }
  .sv-log.tech .sv-tech { display: block; }
  .sv-miss { align-self: flex-end; font-size: 12.5px; color: var(--warn); font-weight: 500; }
  .sv-log.tech .sv-miss { display: none; }
  .sv-end { font-size: 14px; }
  .sv-end summary { cursor: pointer; color: var(--muted); font-weight: 500; }
  .sv-end[open] summary { margin-bottom: 10px; }

  .sv-cmp { display: flex; flex-direction: column; gap: 12px; }
  .sv-turn { display: flex; flex-direction: column; gap: 8px; padding: 4px 0 14px; border-bottom: 1px solid var(--line); }
  .sv-turn:last-child { border-bottom: 0; }
  .sv-turn .msg.user { align-self: flex-end; }
  .sv-split { align-self: flex-start; display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; font-weight: 700; color: var(--warn); background: var(--warn-soft); border-radius: 999px; padding: 2px 10px; }
  .sv-split .ic { width: 14px; height: 14px; }
  .sv-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .sv-col { display: flex; flex-direction: column; gap: 6px; min-width: 0; padding: 8px 10px; border-radius: 12px; border: 1px solid var(--line); }
  .sv-turn.diff .sv-col.now { border-color: var(--warn); }
  .sv-col .msg { max-width: 100%; font-size: 14px; }
  .sv-col-h { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); }
  .sv-turn.same .sv-col-h::after { content: ${JSON.stringify(t(' · igual'))}; color: var(--ok); text-transform: none; letter-spacing: 0; }
  .msg.sv-imp { background: var(--brand-soft); color: var(--brand); font-weight: 600; border-radius: 10px; padding: 6px 12px; }

  @container sv (max-width: 760px) {
    .sv-grid { grid-template-columns: minmax(0, 1fr); }
    .sv-side { position: static; }
    .sv-list { max-height: 300px; min-height: 0; }
  }
  @container svd (max-width: 520px) { .sv-cols { grid-template-columns: minmax(0, 1fr); } }
`));

const svChannelName = (c) => c === 'api' ? 'API' : c === 'prueba' ? t('Chat de prueba') : c;
const svValue = (v) => typeof v === 'string' ? v : JSON.stringify(v);
const svTime = (iso) => (iso || '').slice(11, 16);
const svDayOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
const svDaysAgo = (iso) => { const d = new Date(iso); return isNaN(d) ? Infinity : Math.round((svDayOf(new Date()) - svDayOf(d)) / 864e5); };
function svDay(iso) {
  const n = svDaysAgo(iso), d = new Date(iso);
  if (n === 0) return t('Hoy');
  if (n === 1) return t('Ayer');
  if (n === Infinity) return t('Sin fecha');
  return d.toLocaleDateString(t.locale, { weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
}
const svWhen = (iso) => svDaysAgo(iso) === Infinity ? '' : svDay(iso).toLowerCase() + ' ' + svTime(iso);
// Quién es el cliente: el dato de inicio que más parece identificarlo (nombre, documento, teléfono…).
const SV_WHO = [/nombre|name/i, /dni|documento|identificaci|c[eé]dula|cuit|cuil|tel[eé]fono|phone|celular|email|correo|cliente|usuario|afiliado/i];
function svWho(data) {
  const e = Object.entries(data || {}).filter(([k, v]) => v != null && v !== '' && typeof v !== 'object' && !/^tipo/i.test(k));
  for (const re of SV_WHO) { const hit = e.find(([k]) => re.test(k)); if (hit) return String(hit[1]); }
  return null;
}
// Una charla puede volver a empezar con el mismo sessionId: lo que se re-ejecuta es la última vez que empezó.
const svFromStart = (hist) => { const i = hist.map((m) => m.from === 'event' && 'data' in m).lastIndexOf(true); return i < 0 ? hist : hist.slice(i); };
const svStartData = (s) => svFromStart(s.history || [])[0]?.data || {};
// Etiqueta de color de una clasificación; si ya no existe en el agente, queda gris.
function svTag(name) {
  const c = (agent.classifications || []).find((x) => x.name === name);
  return h('span', c ? { class: 'sv-tag', style: markStyle(c) } : { class: 'sv-tag none', title: t('Esta clasificación ya no existe en el agente') }, name);
}
const svTags = (names) => names?.length ? h('span', { class: 'sv-tags' }, names.map(svTag)) : null;
// Con qué versión contestó: "Producción · v3", "Pruebas · v2", "Borrador".
const SV_ENVS = { production: t('Producción'), staging: t('Pruebas'), draft: t('Borrador') };
const svEnvOf = (s) => s.environment || 'production';
function svEnvTag(s) {
  const env = svEnvOf(s);
  const label = env === 'draft' ? t('Borrador') : (SV_ENVS[env] || env) + ' · ' + (s.version == null ? t('borrador') : 'v' + s.version);
  return h('span', { class: 'sv-env ' + env, title: s.version == null ? t('Contestó con el borrador (sin publicar)') : t('Contestó con la versión {n}', { n: s.version }) }, label);
}
// la versión elegida en el chat de prueba (testEnv, en index.html)
const svTestEnv = () => testEnv === 'draft' ? t('el borrador') : (SV_ENVS[testEnv] || testEnv) + (agent.environments?.[testEnv] != null ? ' (v' + agent.environments[testEnv] + ')' : '');
const svState = (ended) => h('span', { class: 'sv-state ' + (ended ? 'done' : 'live') }, ended ? t('Terminada') : t('En curso'));
const svHandBadge = (ho) => h('span', { class: 'sv-badge', title: ho.reason ? t('Motivo: {reason}', { reason: ho.reason }) : null }, icon('hand'), ho.by ? t('La atiende {name}', { name: ho.by }) : t('Espera a una persona'));
async function svGet(path, method) {
  const r = await fetch('/api/v1/bots/' + encodeURIComponent(agent.id) + '/sessions' + path, { method });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || t('el servidor respondió {status}', { status: r.status }));
  return data;
}

window.sessionsView = () => {
  const body = h('div', { class: 'empty', role: 'status' }, t('Cargando conversaciones…'));
  const root = h('div', { class: 'sv' },
    h('div', { class: 'stack', style: 'gap:4px' }, h('h1', {}, t('Conversaciones')),
      h('p', { class: 'help' }, t('Lo que la gente habló con este agente. Abrí una para leerla, re-ejecutarla contra el bot o seguir hablando como ese cliente.'))),
    body);
  if (window.sessionsFilter) { if (window.sessionsFilter.classification) { svClass = window.sessionsFilter.classification; svSel = null; } if (window.sessionsFilter.environment) { svEnv = window.sessionsFilter.environment; svSel = null; } delete window.sessionsFilter; }
  const myAgent = agent;
  Promise.all([svGet(''), api('GET', '/' + myAgent.id + '/inbox').catch(() => ({ sessions: [] }))]).then(([{ sessions }, inbox]) => {
    svHand = new Map((inbox.sessions || []).map((s) => [s.sessionId, s.handoff || {}]));
    if (agent === myAgent && root.isConnected) body.replaceWith(svBrowser(sessions));
  }, (e) => body.replaceWith(h('div', { class: 'notice warn', role: 'alert' }, t('No se pudieron cargar las conversaciones: {error}.', { error: e.message }),
    h('button', { class: 'link', onclick: render }, t('Probar de nuevo')))));
  return root;
};

function svBrowser(sessions) {
  if (!sessions.length) return h('div', { class: 'empty' }, icon('history'),
    h('strong', {}, t('Todavía no hay conversaciones')),
    h('p', { class: 'help' }, t('Van a aparecer acá cuando alguien le escriba al agente por la API (mirá la sección API para conectarlo) o cuando lo pruebes en el chat de la derecha.')));

  const list = h('div', { class: 'sv-list', 'aria-label': t('Conversaciones') });
  const count = h('p', { class: 'sv-count', role: 'status' });
  const detail = h('div', { class: 'panel sv-detail' });
  const search = h('input', { type: 'search', placeholder: t('Buscar por cliente, id o mensaje'), 'aria-label': t('Buscar conversaciones'), value: svQuery,
    oninput: (e) => { svQuery = e.target.value; drawList(); } });
  const channel = pick([['all', t('Todos los canales')], ['api', 'API'], ['prueba', t('Chat de prueba')]], svChannel, (v) => { svChannel = v; drawList(); }, t('Canal'));
  const dates = pick([['all', t('Cualquier fecha')], ['0', t('Hoy')], ['7', t('Últimos 7 días')], ['30', t('Últimos 30 días')]], svDate, (v) => { svDate = v; drawList(); }, t('Fecha'));
  const names = (agent.classifications || []).map((c) => c.name);
  if (svClass !== 'all' && svClass !== '__none__' && !names.includes(svClass)) names.push(svClass);  // una que vino de afuera o ya se borró
  const classes = pick([['all', t('Toda clasificación')], ...names.map((n) => [n, n]), ['__none__', t('Sin clasificar')]], svClass,
    (v) => { svClass = v; drawList(); }, t('Clasificación'));
  const envs = pick([['all', t('Todo entorno')], ...Object.entries(SV_ENVS)], svEnv, (v) => { svEnv = v; drawList(); }, t('Entorno'));

  const marks = (s) => s.classifications || [];
  const matches = (s, q) => (svChannel === 'all' || (svChannel === 'prueba') === (s.channel === 'prueba'))
    && (svEnv === 'all' || svEnvOf(s) === svEnv)
    && (svDate === 'all' || svDaysAgo(s.updated) <= +svDate)
    && (svClass === 'all' || (svClass === '__none__' ? !marks(s).length : marks(s).includes(svClass)))
    && (!q || [s.sessionId, s.first_message, s.last_message, ...Object.values(s.data || {}).map(svValue)].some((x) => (x || '').toLowerCase().includes(q)));
  if (!sessions.some((s) => s.sessionId === svSel)) svSel = (sessions.find((s) => matches(s, svQuery.trim().toLowerCase())) || sessions[0]).sessionId;

  const item = (s) => {
    const who = svWho(s.data), ho = svHand.get(s.sessionId);
    return h('button', {
      class: 'sv-item', 'aria-current': String(s.sessionId === svSel), title: who ? s.sessionId : null,
      onclick: () => { svSel = s.sessionId; svView = 'orig'; drawList(); drawDetail(); if (innerWidth <= 900) detail.scrollIntoView({ behavior: 'smooth', block: 'start' }); },
    }, h('span', { class: 'sv-top' }, h('strong', {}, who || s.sessionId), h('time', { datetime: s.updated }, svTime(s.updated))),
      h('span', { class: 'sv-preview' }, s.first_message || t('Sin mensajes del cliente')),
      h('span', { class: 'sv-meta' }, ho ? svHandBadge(ho) : null, s.ended ? null : svState(false), svChannelName(s.channel) + ' · ' + t.plural(s.messages, '{n} mensaje', '{n} mensajes'), svEnvTag(s)),
      svTags(s.classifications));
  };
  function drawList() {
    const q = svQuery.trim().toLowerCase();
    const shown = sessions.filter((s) => matches(s, q));
    count.textContent = shown.length === sessions.length ? t.plural(sessions.length, '{n} conversación', '{n} conversaciones') : t('{shown} de {total} conversaciones', { shown: shown.length, total: sessions.length });
    const groups = [];        // vienen de la más reciente a la más vieja: se agrupan por día
    for (const s of shown) { const d = svDay(s.updated); if (groups[groups.length - 1]?.[0] !== d) groups.push([d, []]); groups[groups.length - 1][1].push(s); }
    list.replaceChildren(...(groups.length ? groups.map(([d, items]) => h('div', { role: 'group', 'aria-label': d }, h('div', { class: 'sv-day', 'aria-hidden': 'true' }, d), items.map(item)))
      : [h('p', { class: 'help', style: 'padding:10px 12px' }, t('Ninguna conversación coincide con el filtro.'))]));
  }

  let current = null;
  async function drawDetail() {
    const id = svSel;
    detail.replaceChildren(h('p', { class: 'help' }, t('Cargando la conversación…')));
    try {
      const s = await svGet('/' + encodeURIComponent(id));
      if (id === svSel) { current = s; redraw(); }
    } catch (e) {
      if (id === svSel) detail.replaceChildren(h('div', { class: 'notice warn', role: 'alert' }, t('No se pudo abrir la conversación: {error}.', { error: e.message })));
    }
  }
  function redraw() { if (current && current.sessionId === svSel && detail.isConnected) detail.replaceChildren(...svDetail(current, redraw).filter(Boolean)); }

  drawList(); drawDetail();
  return h('div', { class: 'sv-grid' }, h('div', { class: 'sv-side' }, h('div', { class: 'sv-filters' }, search, channel, dates, classes, envs), count, list), detail);
}

// ---------- re-ejecutar e impersonar: usan el chat de prueba de index.html (startChat, sendText) ----------
async function svReplay(s, redraw) {
  const users = svFromStart(s.history).filter((m) => m.from === 'user');
  const run = svReplays[s.sessionId] = { running: true, step: 0, total: users.length };
  const myAgent = agent, env = svTestEnv();
  redraw();
  try {
    setChat(true);
    await startChat(svStartData(s));
    const sid = session;
    chat.unshift({ who: 'event sv-imp', text: t('Re-ejecución de «{id}» contra {env}', { id: s.sessionId, env }) });
    renderChat();
    for (const m of users) {
      if (session !== sid || agent !== myAgent) throw new Error(t('se cortó porque empezó otra conversación en el chat de prueba'));
      run.step++; redraw();
      await sendText(m.text);
    }
    const result = await svGet('/' + encodeURIComponent(sid));
    svReplays[s.sessionId] = { result, env, at: new Date().toTimeString().slice(0, 5) };
    svView = 'cmp';
  } catch (e) { svReplays[s.sessionId] = { error: e.message }; }
  if (agent === myAgent) redraw();
}
async function svImpersonate(s, who) {
  const data = svStartData(s);
  startData = Object.fromEntries(Object.entries(data).map(([k, v]) => [k, svValue(v)])); startFor = agent.id;   // quedan cargados en «Empezar con datos» (sin pisar lo guardado)
  setChat(true);
  await startChat(data);
  chat.unshift({ who: 'event sv-imp', text: (Object.keys(data).length ? t('Hablás como {who}, con sus datos de inicio', { who }) : t('Hablás como {who} (esa conversación no trajo datos de inicio)', { who })) });
  renderChat();
  $('#chat form input')?.focus();
}

// Turnos: lo que dijo el bot al empezar y, después, cada mensaje del cliente con lo que se le respondió.
function svTurns(history) {
  const turns = [{ user: null, bots: [] }];
  for (const m of history) {
    if (m.from === 'user') turns.push({ user: m, bots: [] });
    else if (m.from === 'bot' || m.from === 'human') turns[turns.length - 1].bots.push(m);
  }
  return turns;
}
const svBubble = (m) => m.from === 'human' ? h('div', { class: 'msg human' }, h('span', { class: 'who' }, m.by ? t('{name} (persona)', { name: m.by }) : t('Una persona del equipo')), m.text)
  : m.text.startsWith('⚠') ? h('div', { class: 'msg problem' }, t('Error en el flujo: {error}', { error: m.text.replace(/^⚠\s*/, '') })) : h('div', { class: 'msg bot' }, m.file && m.text === m.file.name ? null : m.text, m.file ? window.fileCard(m.file) : null);   // fileCard: /static/files.js
const svUnderstood = (m) => !m ? '' : m.answer_to ? t('respuesta para {slot}', { slot: m.answer_to }) : m.intent || t('no entendió');

function svCompare(orig, run) {
  const a = svTurns(svFromStart(orig.history)), b = svTurns(run.result.history);
  const said = (tn) => (tn?.bots || []).filter((m) => m.from === 'bot').map((m) => m.text.trim()).join('\n');
  const n = Math.max(a.length, b.length);
  let first = -1, diffs = 0;
  const rows = [];
  for (let i = 0; i < n; i++) {
    const same = said(a[i]) === said(b[i]);
    if (!same) { diffs++; if (first < 0) first = i; }
    const u = a[i]?.user || b[i]?.user, was = svUnderstood(a[i]?.user), now = svUnderstood(b[i]?.user);
    const col = (label, tn, cls) => h('div', { class: 'sv-col ' + cls }, h('span', { class: 'sv-col-h' }, label),
      tn?.bots.length ? tn.bots.map(svBubble) : h('p', { class: 'help', style: 'font-size:14px' }, tn ? t('No respondió nada.') : t('No llegó a este punto.')));
    rows.push(h('div', { class: 'sv-turn ' + (same ? 'same' : 'diff') },
      first === i ? h('span', { class: 'sv-split' }, icon('branch'), t('Acá se separó')) : null,
      u ? h('div', { class: 'msg user' }, u.text) : h('span', { class: 'sv-event' }, t('Al empezar')),
      u && was !== now ? h('div', { class: 'read' }, t('Antes: '), h('strong', {}, was), t(' · Ahora: '), h('strong', {}, now)) : null,
      h('div', { class: 'sv-cols' }, col(t('Original'), a[i], 'was'), col(t('Re-ejecución'), b[i], 'now'))));
  }
  return h('div', { class: 'sv-cmp' },
    h('div', { class: 'notice' + (diffs ? ' warn' : ''), role: 'status' }, icon(diffs ? 'branch' : 'check'),
      h('span', { class: 'grow' }, diffs ? t('Respondió distinto en {diffs} de {n} turnos.', { diffs, n }) + ' ' + (first ? t('Se separó en el mensaje {n} del cliente.', { n: first }) : t('Se separó en el saludo inicial.'))
        : n === 1 ? t('Respondió igual.') : t('Respondió igual en los {n} turnos.', { n }), ' ' + t('Contra {env}, a las {time}. Las fechas y horarios que dependen del día pueden cambiar solos.', { env: run.env, time: run.at })),
      h('button', { class: 'link', onclick: () => setChat(true) }, t('Seguir en el chat de prueba'))),
    rows);
}

function svDetail(s, redraw) {
  const data = svStartData(s), who = svWho(data);
  const users = svFromStart(s.history).filter((m) => m.from === 'user').length;
  const run = svReplays[s.sessionId];
  const remove = () => confirmBox(t('¿Borrar esta conversación?'), t('Se borra «{id}» con todos sus mensajes. No se puede deshacer.', { id: s.sessionId }), t('Borrar conversación'), async () => {
    try { await svGet('/' + encodeURIComponent(s.sessionId), 'DELETE'); svSel = null; render(); }
    catch (e) { alert(t('No se pudo borrar: {error}', { error: e.message })); }
  });

  // la charla: burbujas, y debajo de cada mensaje del cliente lo que entendió el bot (se muestra con «Qué entendió el bot»)
  let lastAt = '';
  const stamp = (m, cls) => { const tm = svTime(m.at); if (tm === lastAt) return null; lastAt = tm; return h('div', { class: 'sv-at ' + (cls || '') }, tm); };
  const items = s.history.map((m) => {
    if (m.from === 'event' && m.classification) return h('div', { class: 'sv-event' }, t('Clasificada como'), svTag(m.classification), '· ' + svTime(m.at));
    if (m.from === 'event') return h('div', { class: 'sv-event' }, m.text + ' · ' + svTime(m.at));
    if (m.from === 'user') {
      const ents = (m.entities || []).map((e) => [' ', h('mark', { 'data-entity': e.entity, style: markStyle(entityOf(e.entity)) }, e.value)]);
      const pct = m.confidence != null ? ' (' + Math.round(m.confidence * 100) + '%)' : '';
      const read = m.answer_to ? [t('Lo tomó como respuesta para '), h('strong', {}, m.answer_to)]
        : m.intent ? [m.fallback ? t('No estuvo seguro. Lo más parecido: ') : t('Entendió '), h('strong', {}, m.intent), pct]
        : [t('No entendió qué quería')];
      const where = m.flow ? ' · ' + (m.waiting ? t('en «{flow}», esperando {slot}', { flow: m.flow, slot: m.waiting }) : t('en «{flow}»', { flow: m.flow })) : '';
      const missed = !m.answer_to && (!m.intent || m.fallback);
      return [h('div', { class: 'msg user' }, m.text), stamp(m, 'user'),
        missed ? h('div', { class: 'sv-miss' }, t('No lo entendió')) : null,
        h('div', { class: 'read sv-tech' }, read, ents, where, m.via ? ' · ' + t('respondió {who}', { who: m.via === 'ia' ? t('la IA') : m.via === 'knowledge' ? t('Conocimiento') : m.via }) : '')];
    }
    return [svBubble(m), stamp(m)];
  });
  if (s.ended) items.push(h('div', { class: 'sv-event' }, t('Terminó la conversación') + ' · ' + svTime(s.updated)));
  const log = h('div', { class: 'sv-log' + (svTech ? ' tech' : '') }, items.length ? items : h('p', { class: 'help' }, t('Esta conversación no tiene mensajes.')));
  const tech = h('button', { class: 'btn quiet small sv-toggle', 'aria-pressed': String(svTech), onclick: (e) => {
    svTech = !svTech; try { localStorage.setItem('parla.svTech', svTech ? '1' : '0'); } catch {}
    e.currentTarget.setAttribute('aria-pressed', String(svTech)); log.classList.toggle('tech', svTech);
  } }, icon('sliders'), t('Qué entendió el bot'));

  // resumen arriba: quién, cómo terminó, si pasó a una persona, si algo falló
  const ho = s.handoff || (s.history.some((m) => m.from === 'human') ? {} : null);
  const errors = s.history.filter((m) => m.from === 'bot' && m.text.startsWith('⚠')).length;
  const dataList = Object.entries(data);
  const facts = [
    [t('Datos de inicio'), dataList.length ? h('span', { class: 'sv-data' }, dataList.map(([k, v]) => h('span', {}, h('b', {}, k + ' '), svValue(v)))) : t('No llegaron datos al empezar')],
    [t('Resultado'), svTags(s.classifications) || h('span', { class: 'sv-tag none' }, t('Sin clasificar'))],
    ho ? [t('Persona'), ho.active ? svHandBadge(ho) : h('span', { class: 'sv-badge quiet' }, icon('hand'), t('Pasó a una persona') + (ho.by ? ' (' + ho.by + ')' : '') + (ho.reason ? ': ' + ho.reason : ''))] : null,
    errors ? [t('Errores'), h('span', { style: 'color:var(--warn);font-weight:600' }, t.plural(errors, '{n} paso falló', '{n} pasos fallaron'))] : null,
    !s.ended && s.waiting_for ? [t('Quedó'), [t('esperando '), h('strong', {}, s.waiting_for), s.flow ? t(' en el flujo «{flow}»', { flow: s.flow }) : '']] : null,
  ].filter(Boolean);
  const slots = Object.entries(s.slots || {}).filter(([, v]) => v != null && v !== '');

  const replayBtn = h('button', { class: 'btn small', disabled: !users || !!run?.running, title: users ? t('Manda los mismos mensajes, con los mismos datos de inicio, al bot del chat de prueba') : t('Esta conversación no tiene mensajes del cliente'),
    onclick: () => svReplay(s, redraw) }, icon('redo'), run?.result ? t('Re-ejecutar de nuevo') : t('Re-ejecutar como prueba'));
  const imperBtn = h('button', { class: 'btn quiet small', disabled: !!run?.running, title: t('Empieza una charla nueva en el chat de prueba con los datos de este cliente'),
    onclick: () => svImpersonate(s, who ? t('el cliente {name}', { name: who }) : t('el cliente de «{id}»', { id: s.sessionId })) }, icon('users'), t('Hablar como este cliente'));
  const cmp = run?.result && svView === 'cmp';

  return [
    h('div', { class: 'sv-head' }, h('div', { class: 'grow stack', style: 'gap:4px;min-width:min(240px,100%)' }, h('h2', {}, who ? t('Cliente {name}', { name: who }) : s.sessionId),
      h('span', { class: 'sv-sub' }, svState(s.ended), svEnvTag(s), [who ? s.sessionId : null, svChannelName(s.channel), t('empezó {when}', { when: svWhen(s.started) })].filter(Boolean).join(' · '))),
      h('div', { class: 'sv-actions' }, replayBtn, imperBtn,
        canEdit() && users ? h('button', { class: 'btn quiet small', title: t('Guarda esta charla en Pruebas, con lo que respondió el bot como lo esperado'),
          onclick: () => window.testFromHistory(s.history, s.slots, who ? t('Cliente {name}', { name: who }) : s.sessionId) }, icon('check'), t('Guardar como test')) : null,
        iconBtn('trash', t('Borrar conversación'), remove))),
    h('p', { class: 'sv-note' }, icon('globe'), h('span', {}, t('Re-ejecutar y hablar como el cliente usan el chat de prueba con {env} (se elige arriba del chat) y llaman de verdad a las integraciones del bot: APIs, reservas.', { env: svTestEnv() }))),
    run?.running ? h('div', { class: 'notice', role: 'status' }, t('Re-ejecutando: mensaje {step} de {total}. Lo ves en vivo en el chat de prueba.', { step: run.step, total: run.total })) : null,
    run?.error ? h('div', { class: 'notice warn', role: 'alert' }, t('No se pudo re-ejecutar: {error}.', { error: run.error })) : null,
    h('div', { class: 'sv-facts' }, h('dl', { class: 'kv' }, facts.map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))),
    h('div', { class: 'sv-bar' },
      run?.result ? h('div', { class: 'sv-seg', role: 'group', 'aria-label': t('Qué ver') }, [['orig', t('Conversación')], ['cmp', t('Comparar con la re-ejecución')]].map(([k, txt]) =>
        h('button', { 'aria-pressed': String(svView === k), onclick: () => { svView = k; redraw(); } }, txt))) : h('h2', {}, t('Conversación')),
      cmp ? null : tech),
    cmp ? svCompare(s, run) : log,
    h('details', { class: 'sv-end' }, h('summary', {}, t.plural(slots.length, 'Qué quedó anotado al final ({n} dato)', 'Qué quedó anotado al final ({n} datos)')),
      slots.length ? h('dl', { class: 'kv' }, slots.map(([k, v]) => [h('dt', {}, k), h('dd', {}, svValue(v))])) : h('p', { class: 'help' }, t('No quedó ningún dato anotado.'))),
  ];
}
