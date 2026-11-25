// Tests: charlas guardadas en agent.tests con lo que se espera de cada turno. Las corre parla/bottests.py
// (POST /api/agents/{id}/tests/run) sin guardar ninguna conversación. Al publicar en Producción corren solas.
let tsResults = {}, tsFor = null, tsEnv = 'draft', tsRunning = false, tsError = '';

document.head.append(h('style', {}, `
  .ts-test.ok { border-color: var(--ok); }
  .ts-test.bad { border-color: var(--warn); }
  .ts-head { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .ts-head .title { flex: 1; min-width: 160px; font-weight: 600; }
  .ts-state { font-size: 12.5px; font-weight: 600; border-radius: 999px; padding: 1px 10px; white-space: nowrap; }
  .ts-state.ok { background: var(--ok); color: var(--surface); }
  .ts-state.bad { background: var(--warn-soft); color: var(--warn); }
  .ts-turn { border-left: 3px solid var(--line); padding: 4px 0 4px 12px; display: flex; flex-direction: column; gap: 6px; }
  .ts-turn.ok { border-left-color: var(--ok); }
  .ts-turn.bad { border-left-color: var(--warn); }
  .ts-user { display: flex; gap: 6px; align-items: center; }
  .ts-user input { flex: 1; }
  .ts-exp { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 6px 10px; }
  .ts-exp input, .ts-exp select { font-size: 14px; padding: 5px 8px; min-width: 0; }
  .ts-exp .ts-check { flex-direction: row; align-items: center; gap: 6px; align-self: end; padding-bottom: 6px; }
  .ts-fails { margin: 0; padding-left: 18px; font-size: 13.5px; color: var(--warn); display: flex; flex-direction: column; gap: 2px; }
  .ts-fails code { color: var(--ink); background: var(--soft); border-radius: 5px; padding: 0 5px; overflow-wrap: anywhere; }
`));

const TS_CHECKS = { intent: 'Intención', says: 'Dice', buttons: 'Botones', slots: 'Slot', flow: 'Flujo', handoff: 'Pasa a una persona', error: 'Falló un paso' };
const tsShow = (v) => v == null || v === '' ? '(nada)' : typeof v === 'string' ? v : JSON.stringify(v);
const tsCsv = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
// ponytail: «slot=valor, otro=valor»: un valor con coma no entra; editarlo en el JSON exportado si hace falta
const tsPairs = (s) => Object.fromEntries(tsCsv(s).map((x) => x.split('=')).filter((p) => p.length > 1 && p[0].trim()).map(([k, ...v]) => [k.trim(), v.join('=').trim()]));
const tsPairsText = (o) => Object.entries(o || {}).map(([k, v]) => k + '=' + (typeof v === 'string' ? v : JSON.stringify(v))).join(', ');
const tsSet = (obj, key, value) => { if (value === '' || value == null || (typeof value === 'object' && !Object.keys(value).length)) delete obj[key]; else obj[key] = value; };

// Las fallas en palabras: las usa también el diálogo de publicar (releases.js).
window.testFailures = (results) => h('ul', { class: 'ts-fails' }, results.tests.filter((t) => !t.passed).map((t) => h('li', {}, h('strong', {}, t.name || '?'), ': ',
  t.error ? 'no se pudo correr (' + t.error + ')' : t.turns.flatMap((turn, k) => turn.failures.map((f) => 'turno ' + (k + 1) + ', ' + (TS_CHECKS[f.check.split('.')[0]] || f.check).toLowerCase()
    + (f.check.includes('.') ? ' ' + f.check.split('.')[1] : '') + ': esperaba «' + tsShow(f.expected) + '», recibió «' + tsShow(f.got) + '»')).join('; '))));

async function tsRun(names) {
  tsRunning = true; tsError = ''; render();
  try {
    await saveNow();
    const r = await api('POST', '/' + agent.id + '/tests/run', { environment: tsEnv, names });
    r.tests.forEach((t) => { tsResults[t.name] = t; });
  } catch (e) { tsError = e.message; }
  tsRunning = false;
  if (section === 'tests') render();
}

// «Guardar como test»: una conversación (su historial) pasa a ser un test con lo que pasó como lo esperado.
window.testFromHistory = (history, slots, name) => {
  const from = svFromStart(history || []);            // sessions.js: desde la última vez que empezó
  const start = from[0]?.from === 'event' && from[0].data ? { ...from[0].data } : {};
  const turns = [];
  let cur = null;
  for (const m of from) {
    if (m.from === 'user') {
      cur = { user: m.text };
      if (m.intent && !m.answer_to && !m.fallback) cur.intent = m.intent;
      turns.push(cur);
    } else if (m.from === 'bot' && !m.text.startsWith('⚠')) {
      if (!cur) turns.push(cur = {});                  // lo que dijo al empezar: un turno sin «user»
      cur.says = m.text;                               // el último mensaje del turno
      if (m.buttons?.length) cur.buttons = m.buttons.map((b) => b.label); else delete cur.buttons;
    }
  }
  const filled = Object.fromEntries(Object.entries(slots || {}).filter(([k, v]) => v != null && v !== '' && agent.slots.some((s) => s.name === k)));
  if (turns.length && Object.keys(filled).length) turns[turns.length - 1].slots = filled;
  if (!turns.some((t) => 'user' in t)) return alert('Esta conversación no tiene mensajes del cliente para guardar como test.');
  agent.tests ||= [];
  const test = { name: uniqueName(agent.tests, name || 'Test'), ...(Object.keys(start).length ? { start } : {}), turns };
  agent.tests.push(test);
  touch(); section = 'tests'; render(); $('#center').scrollTop = $('#center').scrollHeight;
};

window.testsView = () => {
  agent.tests ||= [];
  if (tsFor !== agent.id) { tsResults = {}; tsFor = agent.id; tsEnv = 'draft'; tsError = ''; }
  const ro = !canEdit(), ed = (props) => ro ? { ...props, disabled: true } : props;
  const choose = (...args) => { const el = pick(...args); el.disabled = ro; return el; };
  const envs = agent.environments || {}, ENVS = { draft: 'Borrador', staging: 'Pruebas', production: 'Producción' };
  const choices = Object.keys(ENVS).filter((k) => k === 'draft' || envs[k] != null);
  if (!choices.includes(tsEnv)) tsEnv = 'draft';
  const tests = agent.tests;
  const ran = tests.map((t) => tsResults[t.name]).filter(Boolean), bad = ran.filter((r) => !r.passed).length;
  const changed = (t) => { delete tsResults[t.name]; touch(); };
  const flows = [['', '—'], ...agent.flows.map((f) => [f.name, f.name])], intents = [['', '—'], ...agent.intents.map((i) => [i.name, i.name])];

  const turnRow = (t, turn, k, res) => h('div', { class: 'ts-turn' + (res ? (res.passed ? ' ok' : ' bad') : '') },
    'user' in turn ? h('div', { class: 'ts-user' }, h('input', ed({ value: turn.user, placeholder: 'Lo que escribe el cliente', 'aria-label': 'Turno ' + (k + 1) + ': lo que escribe el cliente',
      oninput: (e) => { turn.user = e.target.value; changed(t); } })),
      ro ? null : iconBtn('trash', 'Borrar este turno', () => { t.turns.splice(k, 1); changed(t); render(); }, t.turns.length <= 1))
      : h('strong', { style: 'font-size:14px' }, 'Al empezar la conversación'),
    h('div', { class: 'ts-exp' },
      lab('Entendió', choose(intents, turn.intent, (v) => { tsSet(turn, 'intent', v); changed(t); }, 'Intención esperada')),
      lab('Dice (texto o /regex/)', h('input', ed({ value: turn.says || '', oninput: (e) => { tsSet(turn, 'says', e.target.value); changed(t); } }))),
      lab('Botones', h('input', ed({ value: (turn.buttons || []).join(', '), placeholder: 'Sí, No', oninput: (e) => { tsSet(turn, 'buttons', tsCsv(e.target.value)); changed(t); } }))),
      lab('Slots', h('input', ed({ value: tsPairsText(turn.slots), placeholder: 'slot=valor, …', oninput: (e) => { tsSet(turn, 'slots', tsPairs(e.target.value)); changed(t); } }))),
      lab('Flujo', choose(flows, turn.flow, (v) => { tsSet(turn, 'flow', v); changed(t); }, 'Flujo esperado')),
      h('label', { class: 'f ts-check' }, h('input', ed({ type: 'checkbox', checked: !!turn.handoff, onchange: (e) => { tsSet(turn, 'handoff', e.target.checked || null); changed(t); } })), 'Pasa a una persona')),
    res && !res.passed ? h('ul', { class: 'ts-fails' }, res.failures.map((f) => h('li', {}, (TS_CHECKS[f.check.split('.')[0]] || f.check) + (f.check.includes('.') ? ' ' + f.check.split('.')[1] : '') + ': esperaba ',
      h('code', {}, tsShow(f.expected)), ', recibió ', h('code', {}, tsShow(f.got))))) : null);

  const card = (t, i) => {
    const res = tsResults[t.name];
    return h('div', { class: 'panel ts-test' + (res ? (res.passed ? ' ok' : ' bad') : '') },
      h('div', { class: 'ts-head' },
        h('input', ed({ class: 'title', value: t.name, 'aria-label': 'Nombre del test', onchange: (e) => {
          const name = e.target.value.trim();
          if (!name || tests.some((x) => x !== t && x.name === name)) { e.target.value = t.name; return; }
          delete tsResults[t.name]; t.name = name; touch(); } })),
        res ? h('span', { class: 'ts-state ' + (res.passed ? 'ok' : 'bad') }, res.passed ? 'Pasó' : 'Falló') : null,
        h('button', { class: 'btn quiet small', disabled: tsRunning, onclick: () => tsRun([t.name]) }, icon('redo'), 'Correr'),
        ro ? null : iconBtn('trash', 'Borrar el test', () => confirmBox('¿Borrar el test?', 'Se borra «' + t.name + '». No se puede deshacer.', 'Borrar test', () => { tests.splice(i, 1); delete tsResults[t.name]; touch(); render(); }))),
      lab('Datos de inicio', h('input', ed({ value: tsPairsText(t.start), placeholder: 'slot=valor, … (como los que llegan de un IVR o CRM)', oninput: (e) => { tsSet(t, 'start', tsPairs(e.target.value)); changed(t); } }))),
      res?.error ? h('p', { class: 'notice warn', role: 'alert' }, 'No se pudo correr: ' + res.error) : null,
      t.turns.map((turn, k) => turnRow(t, turn, k, res?.turns?.[k])),
      ro ? null : h('div', {}, h('button', { class: 'btn quiet small', onclick: () => { t.turns.push({ user: '' }); changed(t); render(); } }, icon('plus'), 'Agregar turno')));
  };

  const add = () => { tests.push({ name: uniqueName(tests, 'Test'), turns: [{ user: '' }] }); touch(); render(); [...document.querySelectorAll('.ts-test .title')].pop()?.select(); };
  return h('div', { class: 'page' },
    h('div', { class: 'row' }, h('h1', { class: 'grow' }, 'Tests'),
      choices.length > 1 ? pick(choices.map((k) => [k, ENVS[k] + (envs[k] != null ? ' (v' + envs[k] + ')' : '')]), tsEnv, (k) => { tsEnv = k; tsResults = {}; render(); }, 'Contra qué versión correr') : null,
      h('button', { class: 'btn', disabled: tsRunning || !tests.length, onclick: () => tsRun() }, icon('check'), tsRunning ? 'Corriendo…' : 'Correr todos')),
    h('p', { class: 'help' }, 'Charlas de ejemplo con lo que esperás que haga el bot en cada turno. Correlas después de cada cambio para ver si algo se rompió. Al publicar en Producción corren solas. No quedan en Conversaciones ni en Reportes, pero las consultas a servicios, las funciones y la IA corren de verdad.'),
    tsError ? h('p', { class: 'notice warn', role: 'alert' }, 'No se pudieron correr: ' + tsError) : null,
    ran.length && !tsRunning ? h('p', { class: 'notice' + (bad ? ' warn' : ''), role: 'status' }, icon(bad ? 'x' : 'check'),
      bad ? 'Fallaron ' + bad + ' de ' + ran.length + (ran.length === 1 ? ' test.' : ' tests.') : ran.length === 1 ? 'Pasó el test.' : 'Pasaron los ' + ran.length + ' tests.') : null,
    tests.length ? tests.map(card) : h('div', { class: 'empty' }, icon('check'), h('strong', {}, 'Todavía no hay tests'),
      h('p', { class: 'help' }, 'La forma más fácil: charlá con el bot en «Probar» o abrí una charla en Conversaciones y tocá «Guardar como test». Queda guardado lo que pasó como lo esperado; después aflojá lo que cambia solo (fechas, nombres).')),
    ro ? null : h('div', {}, h('button', { class: 'btn quiet', onclick: add }, icon('plus'), 'Nuevo test')));
};
