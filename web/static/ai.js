// IA: un modelo de lenguaje (chico y local con Ollama, o cualquier servidor compatible con OpenAI) que ayuda al bot
// cuando no entiende, cuando duda entre dos intenciones o para contestar con la base de conocimiento.
const AI_DEFAULTS = { enabled: false, provider: 'ollama', url: 'http://127.0.0.1:11434', model: 'qwen2.5:0.5b', temperature: 0.2,
  generative_fallback: true, rescue_intents: true, use_knowledge: true, persona: '' };
let aiStatus = null, aiKey = '', aiProgress = {}, aiPoll = null, aiTest = { text: t('Hola, ¿qué podés hacer?'), reply: null, busy: false, where: '' };
let aiKeyMsg = '';                    // resultado de guardar la API key en Claves

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
const aiSize = (n) => !n ? '' : n >= 1e9 ? (n / 1e9).toLocaleString(t.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + ' GB' : Math.round(n / 1e6) + ' MB';
const aiFrac = (p) => (p.total ? p.completed / p.total : 0.02).toFixed(3);
const aiPullText = (p) => p.total ? t('{done} de {total}', { done: aiSize(p.completed), total: aiSize(p.total) }) : p.status === 'empezando' ? t('empezando') : p.status;
async function aiPost(path, body) {
  const r = await fetch('/api/ai/' + path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401 && window.showLogin) { await window.showLogin(); return aiPost(path, body); }
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.status);
  return data;
}
const aiWhere = (c) => [c.provider, c.url, c.model, c.api_key_secret || '', c.azure ? 'azure' : ''].join(' ');
async function aiRefresh() {
  const c = aiCfg();
  aiKey = aiWhere(c);
  try { aiStatus = await aiPost('status', { ai: c, agent: agent.id }); }
  catch (e) { aiStatus = { ok: false, models: [], error: e.message, hint: t('No pude preguntarle a Parla por la IA.') }; }
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
    if (section !== 'ai') return;
    const live = Object.entries(aiProgress).filter(([, p]) => !p.done);
    const els = live.map(([name]) => [...document.querySelectorAll('[data-pull]')].find((e) => e.dataset.pull === name));
    if (!running || els.some((e) => !e)) return render();      // terminó o empezó una descarga: redibujar todo
    live.forEach(([, p], i) => {                                 // solo avanza la barra: tocar nada más que eso
      els[i].querySelector('.ai-bar span').style.transform = 'scaleX(' + aiFrac(p) + ')';
      els[i].lastChild.textContent = aiPullText(p);
    });
  }, 1000);
}
async function aiTry(where) {
  aiTest.busy = true; aiTest.reply = null; aiTest.where = where || 'test'; render();
  try { aiTest.reply = await aiPost('status', { ai: { ...aiCfg(), prompt: aiTest.text || t('Hola') }, agent: agent.id }); }
  catch (e) { aiTest.reply = { ok: false, error: e.message }; }
  aiTest.busy = false; render();
}

function aiReply(where) {
  const r = aiTest.where === where && aiTest.reply;
  if (!r) return null;
  return r.reply != null
    ? [h('div', { class: 'ai-reply' }, r.reply || t('(respuesta vacía)')),
       h('p', { class: 'help' }, t('Tardó {s} s.', { s: (r.ms / 1000).toLocaleString(t.locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) }) + (aiCfg().provider === 'ollama' ? ' ' + t('La primera vez tarda más porque carga el modelo.') : ''))]
    : h('p', { class: 'ai-hint' }, r.hint || r.error || t('No contestó.'));
}

function aiStateLine(c) {
  const ollama = c.provider === 'ollama';
  if (!aiStatus) return h('div', { class: 'ai-state' }, h('span', { class: 'dot' }), ollama ? t('Buscando el modelo en esta compu…') : t('Conectando…'));
  const ok = aiStatus.ok && aiStatus.model_ready;
  return h('div', {},
    h('div', { class: 'ai-state ' + (ok ? 'ok' : 'bad') }, h('span', { class: 'dot' }),
      !ok ? (aiStatus.ok ? (ollama ? t('Conectado, pero falta descargar el modelo.') : t('Conectado, pero el servidor no ofrece ese modelo.')) : t('No me puedo conectar.'))
        : ollama ? t('Listo: «{model}» está en esta compu.', { model: c.model })
        : aiStatus.models_unknown ? t('Conectado. El servidor no dice qué modelos tiene: probá la conexión.') : t('Conectado: el servidor ofrece «{model}».', { model: c.model }),
      h('button', { class: 'link', onclick: aiRefresh }, t('Volver a mirar')),
      ollama ? null : h('button', { class: 'btn small quiet', disabled: aiTest.busy, onclick: () => aiTry('conn') }, aiTest.busy && aiTest.where === 'conn' ? t('Probando…') : t('Probar conexión'))),
    aiStatus.hint ? h('p', { class: 'ai-hint' }, aiStatus.hint) : null,
    aiReply('conn'));
}

async function aiSaveKey(c, input) {       // la key va a Claves (vault); en el agente solo queda el nombre
  const name = c.api_key_secret || 'AI_API_KEY';
  try {
    await api('PUT', '/' + agent.id + '/secrets', { name, value: input.value.trim() });
    aiKeyMsg = t('Guardada en Claves como {name}.', { name });
    input.value = '';
    if (c.api_key_secret !== name) return aiSet('api_key_secret', name, true);
    aiKey = '';
  } catch (e) { aiKeyMsg = t('No se pudo guardar: {error}', { error: e.message }); }
  render();
}

function aiRemote(c) {
  const key = h('input', { type: 'password', autocomplete: 'new-password', placeholder: c.api_key_secret ? t('•••••••• (escribí una nueva para cambiarla)') : 'sk-…', 'aria-label': 'API key' });
  return [
    h('div', { class: 'row' },
      lab('API key', key, 'grow'),
      h('button', { class: 'btn small', onclick: () => key.value.trim() && aiSaveKey(c, key) }, t('Guardar key'))),
    h('p', { class: 'help' }, c.api_key_secret
      ? [t('Se usa la clave '), h('code', {}, c.api_key_secret), t(' de «Claves»: no se guarda en el agente ni se vuelve a mostrar.') + ' ']
      : t('Si el servidor no pide key (vLLM, llama.cpp o LM Studio en tu red), dejalo vacío.') + ' ', aiKeyMsg),
    h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!c.azure, onchange: (e) => aiSet('azure', e.target.checked, true) }),
      t('Azure OpenAI (la key va en el encabezado api-key y se agrega api-version)'))];
}

function aiModels(c) {
  const installed = (aiStatus?.models || []);
  const names = new Set(installed.map((m) => m.name));
  const recommended = (aiStatus?.recommended || [{ name: AI_DEFAULTS.model, size: 4e8, note: t('El más liviano.') }]);
  const rows = [...recommended.map((m) => ({ ...m, here: names.has(m.name) })),
    ...installed.filter((m) => !recommended.some((r) => r.name === m.name)).map((m) => ({ ...m, here: true,
      note: m.size > 3e9 ? t('Ya está en esta compu, pero es pesado: puede andar lento sin placa de video.') : t('Ya está en esta compu.') }))];
  const card = (m) => {
    const p = aiProgress[m.name], pulling = p && !p.done;
    return h('div', { class: 'ai-model' + (m.name === c.model ? ' on' : ''), onclick: (e) => { if (e.target.tagName !== 'BUTTON' && m.name !== c.model) aiSet('model', m.name, true); } },
      h('input', { type: 'radio', name: 'ai-model', checked: m.name === c.model, 'aria-label': m.name }),
      h('b', {}, m.name),
      c.provider === 'ollama' && !m.here
        ? h('button', { class: 'btn small quiet', disabled: pulling, onclick: () => aiPull(m.name) }, icon('down'), pulling ? t('Descargando…') : t('Descargar') + (m.size ? ' (' + aiSize(m.size) + ')' : ''))
        : h('span', {}, (m.here ? t('En esta compu') : '') + (m.size ? ' · ' + aiSize(m.size) : '')),
      h('small', {}, m.note || ''),
      pulling || p?.error ? h('small', { 'data-pull': pulling ? m.name : null }, p.error ? h('span', { class: 'ai-hint' }, t('No se pudo descargar: {error}', { error: p.error })) : [
        h('div', { class: 'ai-bar' }, h('span', { style: 'transform:scaleX(' + aiFrac(p) + ')' })),
        h('span', {}, aiPullText(p))]) : null);
  };
  if (c.provider !== 'ollama') return h('div', { class: 'ai-models' },
    lab(t('Nombre del modelo'), h('input', { value: c.model, list: 'ai-model-list', placeholder: t('por ejemplo gpt-4o-mini, o el que cargaste en el servidor'), onchange: (e) => aiSet('model', e.target.value.trim(), true) })),
    h('datalist', { id: 'ai-model-list' }, installed.slice(0, 300).map((m) => h('option', { value: m.name }))),
    installed.length ? h('p', { class: 'help' }, t.plural(installed.length, 'El servidor ofrece {n} modelo: escribí para ver sugerencias.', 'El servidor ofrece {n} modelos: escribí para ver sugerencias.')) : null);
  return h('div', { class: 'ai-models' }, rows.map(card));
}

function aiToggle(c, key, title, help) {
  return h('div', {},
    h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!c[key], onchange: (e) => aiSet(key, e.target.checked) }), title),
    h('small', {}, help));
}

function aiMcp() {                       // agent.mcp_servers: [{name, url, headers_secret?}]; el secreto es el nombre de una clave de «Claves»
  const list = agent.mcp_servers || [];
  const upd = () => { touch(); render(); };
  return h('div', { class: 'panel' }, h('h2', {}, t('Servidores MCP')),
    h('p', { class: 'help' }, t('Parla se conecta a estos servidores MCP (HTTP) para que el paso «Conversar con IA» use sus herramientas. Solo se llaman las herramientas que habilites en cada paso.')),
    list.map((x, i) => h('div', { class: 'row' },
      lab(t('Nombre'), h('input', { ...bind(x, 'name'), placeholder: 'crm', spellcheck: 'false' })),
      lab(t('Dirección'), h('input', { ...bind(x, 'url'), placeholder: 'https://mcp.example.com/mcp', spellcheck: 'false' }), 'grow'),
      lab(t('Clave para Authorization (opcional)'), h('input', { value: x.headers_secret || '', placeholder: 'CRM_TOKEN', spellcheck: 'false',
        oninput: (e) => { const v = e.target.value.trim(); if (v) x.headers_secret = v; else delete x.headers_secret; touch(); } })),
      iconBtn('x', t('Quitar servidor'), () => { list.splice(i, 1); upd(); }))),
    h('div', {}, h('button', { class: 'link', onclick: () => { (agent.mcp_servers ||= []).push({ name: '', url: '' }); upd(); } }, t('Agregar servidor MCP'))));
}

window.aiView = () => {
  const c = aiCfg();
  if (aiKey !== aiWhere(c)) { aiKey = aiWhere(c); aiStatus = null; aiRefresh(); }
  if (!aiPoll && Object.values(aiProgress).some((p) => !p.done)) aiWatch();
  const persona = { persona: c.persona };
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, t('IA')),
      h('label', { class: 'toggle' }, h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!c.enabled, onchange: (e) => aiSet('enabled', e.target.checked) }),
        c.enabled ? t('Activada') : t('Apagada'))),
    h('p', { class: 'help' }, t('Un modelo de lenguaje ayuda al bot a entender mejor y a contestar con tu base de conocimiento.') + ' ',
      c.provider === 'ollama' ? [h('strong', {}, t('Con Ollama todo corre en esta compu:')), ' ' + t('las conversaciones no salen a internet y no hay que pagar nada.') + ' '] : null,
      t('Con la IA apagada el bot funciona igual que siempre.')),
    h('div', { class: 'panel' }, h('h2', {}, t('Dónde corre')),
      h('div', { class: 'row' },
        lab(t('Programa'), pick([['ollama', t('Local (Ollama)')], ['openai', t('Compatible con OpenAI')]], c.provider, (v) => {
          agent.ai = { ...c, provider: v, url: v === 'ollama' ? AI_DEFAULTS.url : 'http://127.0.0.1:1234/v1' }; touch(); aiKey = ''; render();
        }, t('Programa'))),
        lab(t('Dirección'), h('input', { value: c.url, placeholder: c.provider === 'ollama' ? AI_DEFAULTS.url : t('http://localhost:8000/v1 o https://api.openai.com/v1'),
          onchange: (e) => aiSet('url', e.target.value.trim(), true) }), 'grow')),
      c.provider === 'ollama' ? null : aiRemote(c),
      aiStatus && aiStatus.local === false ? h('p', { class: 'notice warn' }, h('strong', {}, t('Esta dirección no es de esta compu ni de tu red:') + ' '),
        t('el texto de las conversaciones (y lo que se use de la base de conocimiento) se manda a ese proveedor. Revisá sus condiciones de privacidad y de uso de datos.')) : null,
      aiStateLine(c)),
    h('div', { class: 'panel' }, h('h2', {}, t('Modelo')),
      h('p', { class: 'help' }, t('Los más chicos contestan más rápido y usan menos memoria; los un poco más grandes se equivocan menos. Para empezar alcanza con el primero.')),
      aiModels(c)),
    h('div', { class: 'panel' }, h('h2', {}, t('Qué hace la IA')),
      h('div', { class: 'ai-toggles' },
        aiToggle(c, 'generative_fallback', t('Responder cuando no entiende'), t('En vez del «no entendí» de siempre, pide que lo digan de otra forma y cuenta en qué puede ayudar.')),
        aiToggle(c, 'rescue_intents', t('Ayudar cuando duda'), t('Si el bot no está seguro de qué intención es, la IA elige entre las más parecidas.')),
        aiToggle(c, 'use_knowledge', t('Usar la base de conocimiento'), t('Arma la respuesta con lo que cargaste en Conocimiento, sin inventar. Apagada, el bot muestra el texto tal cual.')))),
    h('div', { class: 'panel' }, h('h2', {}, t('Cómo habla')),
      area(persona, 'persona', { placeholder: t('Por ejemplo: Sos Lula, de la Veterinaria Patitas. Hablás de vos, con calidez y frases cortas.'), 'aria-label': t('Cómo habla'),
        oninput: (e) => { agent.ai = { ...aiCfg(), persona: e.target.value }; touch(); grow(e.target); } })),
    aiMcp(),
    h('div', { class: 'panel' }, h('h2', {}, t('Probar')),
      h('div', { class: 'row' },
        h('input', { class: 'grow', value: aiTest.text, 'aria-label': t('Mensaje de prueba'), oninput: (e) => { aiTest.text = e.target.value; },
          onkeydown: (e) => { if (e.key === 'Enter' && !aiTest.busy && aiTest.text.trim()) aiTry('test'); } }),
        h('button', { class: 'btn', disabled: aiTest.busy, onclick: () => aiTry('test') }, icon('spark'), aiTest.busy && aiTest.where === 'test' ? t('Pensando…') : t('Probar'))),
      aiReply('test')));
};
