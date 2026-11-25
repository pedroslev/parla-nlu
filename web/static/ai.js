// IA: un modelo de lenguaje chico que corre en esta compu (Ollama o un servidor compatible) y ayuda al bot cuando
// no entiende, cuando duda entre dos intenciones o para contestar con la base de conocimiento.
const AI_DEFAULTS = { enabled: false, provider: 'ollama', url: 'http://127.0.0.1:11434', model: 'qwen2.5:0.5b', temperature: 0.2,
  generative_fallback: true, rescue_intents: true, use_knowledge: true, persona: '' };
let aiStatus = null, aiKey = '', aiProgress = {}, aiPoll = null, aiTest = { text: 'Hola, ¿qué podés hacer?', reply: null, busy: false };

document.head.append(h('style', {}, `
  .ai-state { display: flex; align-items: center; gap: 10px; font-size: 14px; }
  .ai-state .dot { width: 10px; height: 10px; background: var(--muted); }
  .ai-state.ok .dot { background: var(--ok); }
  .ai-state.bad .dot { background: var(--warn); }
  .ai-hint { color: var(--warn); font-size: 14px; max-width: 62ch; }
  .ai-models { display: grid; gap: 6px; }
  .ai-model { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 4px 10px; align-items: center; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); cursor: pointer; }
  .ai-model.on { border-color: var(--brand); background: var(--brand-soft); }
  .ai-model small { color: var(--muted); font-size: 13px; grid-column: 2 / -1; }
  .ai-model b { font-weight: 600; overflow-wrap: anywhere; }
  .ai-model span { color: var(--muted); font-size: 13px; white-space: nowrap; }
  .ai-bar { height: 8px; border-radius: 999px; background: var(--soft); overflow: hidden; }
  .ai-bar span { display: block; height: 100%; background: var(--brand); transform-origin: left; transition: transform .3s; }
  .ai-reply { background: var(--soft); border-radius: 10px; padding: 10px 12px; white-space: pre-wrap; }
  .ai-toggles { display: flex; flex-direction: column; gap: 12px; }
  .ai-toggles small { display: block; color: var(--muted); font-size: 13px; margin-left: 48px; margin-top: -8px; }
`));

const aiCfg = () => ({ ...AI_DEFAULTS, ...(agent.ai || {}) });
function aiSet(key, value, again) {
  agent.ai = { ...aiCfg(), [key]: value };
  touch();
  if (again) aiKey = '';               // cambió dónde buscar el modelo: volver a preguntar
  render();
}
const aiSize = (n) => !n ? '' : n >= 1e9 ? (n / 1e9).toFixed(1).replace('.', ',') + ' GB' : Math.round(n / 1e6) + ' MB';
async function aiPost(path, body) {
  const r = await fetch('/api/ai/' + path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && window.showLogin) { await window.showLogin(); return aiPost(path, body); }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}
async function aiRefresh() {
  const c = aiCfg();
  aiKey = c.provider + ' ' + c.url + ' ' + c.model;
  try { aiStatus = await aiPost('status', { ai: c }); }
  catch (e) { aiStatus = { ok: false, models: [], error: e.message, hint: 'No pude preguntarle a Parla por la IA.' }; }
  if (section === 'ai') render();
}
async function aiPull(model) {
  try {
    const r = await aiPost('pull', { ai: aiCfg(), model });
    if (!r.ok) throw new Error(r.error);
    aiProgress[model] = { status: 'empezando', done: false };
  } catch (e) { aiProgress[model] = { status: 'error', error: e.message, done: true }; }
  aiWatch(); render();
}
function aiWatch() {
  clearInterval(aiPoll);
  aiPoll = setInterval(async () => {
    try { aiProgress = await aiPost('progress'); } catch { return; }
    const running = Object.values(aiProgress).some((p) => !p.done);
    if (!running) { clearInterval(aiPoll); aiPoll = null; aiKey = ''; }
    if (section === 'ai') render();
  }, 1000);
}
async function aiTry() {
  aiTest.busy = true; aiTest.reply = null; render();
  try { aiTest.reply = await aiPost('status', { ai: { ...aiCfg(), prompt: aiTest.text } }); }
  catch (e) { aiTest.reply = { ok: false, error: e.message }; }
  aiTest.busy = false; render();
}

function aiStateLine(c) {
  if (!aiStatus) return h('div', { class: 'ai-state' }, h('span', { class: 'dot' }), 'Buscando el modelo en esta compu…');
  const ok = aiStatus.ok && aiStatus.model_ready;
  return h('div', {},
    h('div', { class: 'ai-state ' + (ok ? 'ok' : 'bad') }, h('span', { class: 'dot' }),
      ok ? 'Listo: «' + c.model + '» está en esta compu.' : aiStatus.ok ? 'Conectado, pero falta descargar el modelo.' : 'No me puedo conectar.',
      h('button', { class: 'link', onclick: aiRefresh }, 'Volver a mirar')),
    aiStatus.hint ? h('p', { class: 'ai-hint' }, aiStatus.hint) : null);
}

function aiModels(c) {
  const installed = (aiStatus?.models || []);
  const names = new Set(installed.map((m) => m.name));
  const recommended = (aiStatus?.recommended || [{ name: AI_DEFAULTS.model, size: 4e8, note: 'El más liviano.' }]);
  const rows = [...recommended.map((m) => ({ ...m, here: names.has(m.name) })),
    ...installed.filter((m) => !recommended.some((r) => r.name === m.name)).map((m) => ({ ...m, here: true,
      note: m.size > 3e9 ? 'Ya está en esta compu, pero es pesado: puede andar lento sin placa de video.' : 'Ya está en esta compu.' }))];
  const card = (m) => {
    const p = aiProgress[m.name], pulling = p && !p.done;
    return h('div', { class: 'ai-model' + (m.name === c.model ? ' on' : ''), onclick: (e) => { if (e.target.tagName !== 'BUTTON' && m.name !== c.model) aiSet('model', m.name, true); } },
      h('input', { type: 'radio', name: 'ai-model', checked: m.name === c.model, 'aria-label': m.name }),
      h('b', {}, m.name),
      c.provider === 'ollama' && !m.here
        ? h('button', { class: 'btn small quiet', disabled: pulling, onclick: () => aiPull(m.name) }, icon('down'), pulling ? 'Descargando…' : 'Descargar' + (m.size ? ' (' + aiSize(m.size) + ')' : ''))
        : h('span', {}, (m.here ? 'En esta compu' : '') + (m.size ? ' · ' + aiSize(m.size) : '')),
      h('small', {}, m.note || ''),
      pulling || p?.error ? h('small', {}, p.error ? h('span', { class: 'ai-hint' }, 'No se pudo descargar: ' + p.error) : [
        h('div', { class: 'ai-bar' }, h('span', { style: 'transform:scaleX(' + (p.total ? p.completed / p.total : 0.02).toFixed(3) + ')' })),
        p.total ? aiSize(p.completed) + ' de ' + aiSize(p.total) : p.status]) : null);
  };
  if (c.provider !== 'ollama') return h('div', { class: 'ai-models' },
    lab('Nombre del modelo', h('input', { value: c.model, placeholder: 'el que cargaste en LM Studio o llama.cpp', onchange: (e) => aiSet('model', e.target.value.trim(), true) })),
    installed.length ? h('p', { class: 'help' }, 'El servidor ofrece: ' + installed.map((m) => m.name).join(', ')) : null);
  return h('div', { class: 'ai-models' }, rows.map(card));
}

function aiToggle(c, key, title, help) {
  return h('div', {},
    h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!c[key], onchange: (e) => aiSet(key, e.target.checked) }), title),
    h('small', {}, help));
}

window.aiView = () => {
  const c = aiCfg();
  if (aiKey !== c.provider + ' ' + c.url + ' ' + c.model) { aiKey = c.provider + ' ' + c.url + ' ' + c.model; aiStatus = null; aiRefresh(); }
  if (!aiPoll && Object.values(aiProgress).some((p) => !p.done)) aiWatch();
  const persona = { persona: c.persona };
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, 'IA'),
      h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!c.enabled, onchange: (e) => aiSet('enabled', e.target.checked) }),
        c.enabled ? 'Activada' : 'Apagada')),
    h('p', { class: 'help' }, 'Un modelo de lenguaje chico ayuda al bot a entender mejor y a contestar con tu base de conocimiento. ',
      h('strong', {}, 'Todo corre en esta compu:'), ' las conversaciones no salen a internet y no hay que pagar nada. Con la IA apagada el bot funciona igual que siempre.'),
    h('div', { class: 'panel' }, h('h2', {}, 'Dónde corre'),
      h('div', { class: 'row' },
        lab('Programa', pick([['ollama', 'Ollama (recomendado)'], ['openai', 'Servidor compatible (LM Studio, llama.cpp)']], c.provider, (v) => {
          agent.ai = { ...c, provider: v, url: v === 'ollama' ? AI_DEFAULTS.url : 'http://127.0.0.1:1234' }; touch(); aiKey = ''; render();
        }, 'Programa')),
        lab('Dirección', h('input', { value: c.url, onchange: (e) => aiSet('url', e.target.value.trim(), true) }), 'grow')),
      aiStateLine(c)),
    h('div', { class: 'panel' }, h('h2', {}, 'Modelo'),
      h('p', { class: 'help' }, 'Los más chicos contestan más rápido y usan menos memoria; los un poco más grandes se equivocan menos. Para empezar alcanza con el primero.'),
      aiModels(c)),
    h('div', { class: 'panel' }, h('h2', {}, 'Qué hace la IA'),
      h('div', { class: 'ai-toggles' },
        aiToggle(c, 'generative_fallback', 'Responder cuando no entiende', 'En vez del «no entendí» de siempre, pide que lo digan de otra forma y cuenta en qué puede ayudar.'),
        aiToggle(c, 'rescue_intents', 'Ayudar cuando duda', 'Si el bot no está seguro de qué intención es, la IA elige entre las más parecidas.'),
        aiToggle(c, 'use_knowledge', 'Usar la base de conocimiento', 'Arma la respuesta con lo que cargaste en Conocimiento, sin inventar. Apagada, el bot muestra el texto tal cual.'))),
    h('div', { class: 'panel' }, h('h2', {}, 'Cómo habla'),
      area(persona, 'persona', { placeholder: 'Por ejemplo: Sos Lula, de la Veterinaria Patitas. Hablás de vos, con calidez y frases cortas.', 'aria-label': 'Cómo habla',
        oninput: (e) => { agent.ai = { ...aiCfg(), persona: e.target.value }; touch(); grow(e.target); } })),
    h('div', { class: 'panel' }, h('h2', {}, 'Probar'),
      h('div', { class: 'row' },
        h('input', { class: 'grow', value: aiTest.text, 'aria-label': 'Mensaje de prueba', oninput: (e) => { aiTest.text = e.target.value; },
          onkeydown: (e) => { if (e.key === 'Enter' && !aiTest.busy && aiTest.text.trim()) aiTry(); } }),
        h('button', { class: 'btn', disabled: aiTest.busy, onclick: aiTry }, icon('spark'), aiTest.busy ? 'Pensando…' : 'Probar')),
      aiTest.reply ? (aiTest.reply.reply != null
        ? [h('div', { class: 'ai-reply' }, aiTest.reply.reply || '(respuesta vacía)'),
           h('p', { class: 'help' }, 'Tardó ' + (aiTest.reply.ms / 1000).toFixed(1).replace('.', ',') + ' s. La primera vez tarda más porque carga el modelo.')]
        : h('p', { class: 'ai-hint' }, aiTest.reply.hint || aiTest.reply.error || 'No contestó.')) : null));
};
