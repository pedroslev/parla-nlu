// Sección API: documentación de /api/v1 con ejemplos armados con el agente actual y botón «Probar».
(() => {
  const SID_RE = /^[A-Za-z0-9_@+-][A-Za-z0-9_.@+-]{0,99}$/;   // igual que SESSION_ID en parla/server.py
  let sid = 'doc-' + Math.random().toString(36).slice(2, 8);   // sobrevive a los re-render
  let msgText = null;                                          // texto del ejemplo de mensaje (null = sugerido)
  const results = {};                                          // última respuesta de cada «Probar»

  if (!document.getElementById('ad-style')) {
    document.head.append(h('style', { id: 'ad-style' }, `
      .ad-code { position: relative; background: var(--ink); color: #E8ECF5; border-radius: 10px; min-width: 0; }
      .ad-code pre { margin: 0; padding: 12px 14px; overflow-x: auto; font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre; tab-size: 2; }
      .ad-code pre.ad-res { max-height: 380px; overflow: auto; }
      .ad-code .ad-copy { position: absolute; top: 6px; right: 6px; background: rgba(255,255,255,.12); color: #fff; border-radius: 6px; padding: 3px 9px; font-size: 12px; font-weight: 600; }
      .ad-code .ad-copy:hover { background: rgba(255,255,255,.22); }
      .ad-code.light { background: var(--soft); color: var(--ink); border: 1px solid var(--line); }
      .ad-code.light .ad-copy { background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
      .ad-inline { font: 13px ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--soft); border: 1px solid var(--line); border-radius: 5px; padding: 0 5px; overflow-wrap: anywhere; }
      .ad-ep { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; min-width: 0; }
      .ad-ep code { font: 600 14px ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; min-width: 0; }
      .ad-m { font: 700 12px ui-monospace, monospace; padding: 2px 8px; border-radius: 6px; background: var(--brand-soft); color: var(--brand); }
      .ad-m.POST { background: #DDF3E6; color: var(--ok); }
      .ad-m.DELETE { background: var(--warn-soft); color: var(--warn); }
      .ad-step { font: 700 13px var(--display); color: var(--brand); }
      .ad-scroll { overflow-x: auto; }
      .ad-table { border-collapse: collapse; width: 100%; font-size: 14px; }
      .ad-table th { text-align: left; color: var(--muted); font-weight: 500; font-size: 13px; padding: 4px 10px 4px 0; border-bottom: 1px solid var(--line); }
      .ad-table td { padding: 6px 10px 6px 0; border-bottom: 1px solid var(--line); vertical-align: top; }
      .ad-table tr:last-child td { border-bottom: 0; }
      .ad-table td:first-child { white-space: nowrap; }
      .ad-status { font-size: 13px; font-weight: 600; }
      .ad-status.ok { color: var(--ok); } .ad-status.bad { color: var(--warn); }
      .ad-panel { min-width: 0; }
      .ad-panel h2 { font: 700 18px/1.25 var(--display); }
      .ad-sid input { font: 14px ui-monospace, monospace; width: 100%; max-width: 320px; }
      .ad-sid input[aria-invalid="true"] { border-color: var(--warn); }
      .ad-err { color: var(--warn); font-size: 13px; }
    `));
  }

  const BASE = () => location.origin + '/api/v1';
  const botSlug = () => String(agent.name || '').normalize('NFD').replace(/[^\x00-\x7f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const ref = () => encodeURIComponent(botSlug() || agent.id);
  const startFlow = () => agent.flows.find((f) => f.trigger === '__start__');
  const firstClass = () => (agent.classifications || [])[0]?.name;
  const day = (d) => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  const monthRange = () => { const d = new Date(); return 'from=' + day(new Date(d.getFullYear(), d.getMonth(), 1)) + '&to=' + day(d); };

  const SAMPLE = { nombre: 'Olivia', apellido: 'Gómez', dni: '30123456', documento: '30123456', telefono: '+5491122334455',
    celular: '+5491122334455', email: 'olivia@ejemplo.com', mail: 'olivia@ejemplo.com', direccion: 'Av. Corrientes 1234',
    cliente: 'C-1042', cantidad: 2, edad: 34, ciudad: 'Rosario' };
  function sampleData() {
    const slots = agent.slots.map((s) => s.name);
    if (!slots.length) return { dni: '30123456' };
    const known = Object.keys(SAMPLE).filter((n) => slots.includes(n));
    return Object.fromEntries((known.length ? known : slots).slice(0, 3).map((n) => [n, SAMPLE[n] ?? 'ejemplo']));
  }
  function suggestedText() {                     // una frase que dispare el primer flujo, si se puede
    for (const f of agent.flows) {
      const it = agent.intents.find((i) => i.name === f.trigger);
      const ex = it?.examples?.find((e) => e.trim());
      if (ex) return plain(ex);
    }
    const ex = agent.intents.flatMap((i) => i.examples || []).find((e) => e.trim());
    return ex ? plain(ex) : 'hola';
  }
  const text = () => msgText ?? suggestedText();

  // Cada ejemplo: cómo se arma el pedido con el agente y el sessionId del momento.
  const EX = {
    bots: () => ({ method: 'GET', path: '/bots' }),
    bot: () => ({ method: 'GET', path: '/bots/' + ref() }),
    start: () => ({ method: 'POST', path: '/bots/' + ref() + '/events', body: { type: 'start', sessionId: sid, channel: 'api', data: sampleData() } }),
    message: () => ({ method: 'POST', path: '/bots/' + ref() + '/events', body: { type: 'message', sessionId: sid, text: text() } }),
    read: () => ({ method: 'GET', path: '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) }),
    list: () => ({ method: 'GET', path: '/bots/' + ref() + '/sessions?channel=api' }),
    report: () => ({ method: 'GET', path: '/bots/' + ref() + '/report?' + monthRange() }),
    end: () => ({ method: 'POST', path: '/bots/' + ref() + '/events', body: { type: 'end', sessionId: sid } }),
    del: () => ({ method: 'DELETE', path: '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) }),
    messages: () => ({ method: 'GET', path: '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) + '/messages?after=0' }),
    audio: () => ({ method: 'POST', path: '/bots/' + ref() + '/audio', body: { sessionId: sid, audio: '<la grabación en base64>', mime: 'audio/webm', speak: true } }),
  };

  // Qué hace cada dirección: lo usan la página y los archivos exportados.
  const PURPOSE = {
    bots: 'Lista todos los agentes de este Parla con su id, su nombre para la URL, cuándo se entrenaron, sus intenciones y qué versión tiene cada entorno (environments).',
    start: 'Abre (o reinicia) la conversación. Si ya existía, arranca con la memoria en blanco pero conserva lo charlado en el historial. "online" funciona igual que "start".',
    message: 'Un mensaje del usuario. Te devuelve las respuestas del bot en messages y qué entendió en understood. Repetilo por cada mensaje.',
    read: 'La conversación completa: datos anotados, en qué flujo está, sus clasificaciones y el historial (from: "event", "user" o "bot"; los mensajes del usuario traen lo que se entendió; cada clasificación aparece como un event con classification).',
    end: 'Cierra la conversación y borra lo que el bot tenía en memoria. Queda en el historial; si después llega un mensaje con el mismo sessionId, sigue con la memoria en blanco.',
    bot: 'Lo mismo que en la lista, para un solo bot. {bot} puede ser el id, el nombre exacto o el nombre simplificado. Si no existe o es ambiguo: 404.',
    list: 'Las conversaciones de este bot, la más reciente primero, con un resumen (cantidad de mensajes, primero y último, datos precargados, classifications, environment y version). Los filtros van en la URL, son opcionales y se pueden combinar:',
    report: 'Cuántas conversaciones hubo con cada clasificación, en total y por día. Sirve para tableros o planillas. Los filtros son opcionales; sin ellos cuenta todas las conversaciones.',
    del: 'La elimina del todo, con su historial. No se puede deshacer.',
    messages: 'Lo nuevo de la conversación desde la entrada número after del historial (0 = todo). Sirve para recibir lo que escribe una persona desde la Bandeja cuando el bot pasó la charla (handoff): preguntá cada pocos segundos mandando como after el next de la respuesta anterior.',
    audio: 'Un mensaje de voz: Parla lo pasa a texto en esta computadora (sin servicios de afuera), lo atiende como un message y, con speak, te devuelve la respuesta también en audio. Trae lo mismo que message más heard y audio.',
  };

  const q = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";
  function curl(r) {
    let s = 'curl' + (r.method === 'GET' ? '' : ' -X ' + r.method) + ' ' + q(BASE() + r.path);
    if (window.authEnabled) s += " \\\n  -H 'Authorization: Bearer TU_CLAVE'";   // con usuarios creados la API pide clave
    if (r.body) {
      const json = JSON.stringify(r.body);
      s += " \\\n  -H 'Content-Type: application/json' \\\n  -d " + q(json.length > 70 ? JSON.stringify(r.body, null, 2) : json);
    }
    return s;
  }

  async function copy(textOf, btn, pre) {
    try { await navigator.clipboard.writeText(textOf()); btn.textContent = 'Copiado'; }
    catch { getSelection().selectAllChildren(pre); btn.textContent = 'Seleccionado: ⌘C / Ctrl+C'; }
    setTimeout(() => { btn.textContent = 'Copiar'; }, 1600);
  }
  function codeBox(textOf, light) {
    const pre = h('pre', {}, textOf());
    const btn = h('button', { class: 'ad-copy', type: 'button', onclick: () => copy(textOf, btn, pre) }, 'Copiar');
    const box = h('div', { class: 'ad-code' + (light ? ' light' : '') }, pre, btn);
    box.refresh = () => { pre.textContent = textOf(); };
    return box;
  }
  const inline = (t) => h('code', { class: 'ad-inline' }, t);

  function fields(rows) {
    return h('div', { class: 'ad-scroll' }, h('table', { class: 'ad-table' },
      h('tr', {}, h('th', {}, 'Campo'), h('th', {}, '¿Obligatorio?'), h('th', {}, 'Qué es')),
      rows.map(([f, req, d]) => h('tr', {}, h('td', {}, inline(f)), h('td', {}, req), h('td', {}, d)))));
  }

  function fieldsOut(rows, head = 'Respuesta') {
    return h('div', { class: 'ad-scroll' }, h('table', { class: 'ad-table' },
      h('tr', {}, h('th', {}, head), h('th', {}, 'Qué es')),
      rows.map(([f, d]) => h('tr', {}, h('td', {}, inline(f)), h('td', {}, d)))));
  }

  function resultBox(key) {
    const r = results[key];
    if (!r) return null;
    if (r.loading) return h('p', { class: 'help' }, 'Mandando…');
    return h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
      h('span', { class: 'ad-status ' + (r.status >= 200 && r.status < 300 ? 'ok' : 'bad') }, r.status ? 'Respuesta ' + r.status : 'No se pudo conectar'),
      h('div', { class: 'ad-code light' }, h('pre', { class: 'ad-res' }, r.body)));
  }

  async function run(key, slot) {
    const r = EX[key]();
    results[key] = { loading: true };
    slot.replaceChildren(resultBox(key));
    try {
      const res = await fetch(BASE() + r.path, { method: r.method, headers: r.body ? { 'Content-Type': 'application/json' } : undefined,
        body: r.body ? JSON.stringify(r.body) : undefined });
      const raw = await res.text();
      let body = raw;
      try { body = JSON.stringify(JSON.parse(raw), null, 2); } catch {}
      results[key] = { status: res.status, body };
    } catch (e) {
      results[key] = { status: 0, body: String(e.message || e) };
    }
    slot.replaceChildren(resultBox(key));
  }

  const refreshers = [];
  function endpoint(key, { step, title, purpose, rows, extra, after, noTry }) {
    const r = EX[key]();
    const code = codeBox(() => curl(EX[key]()));
    refreshers.push(code.refresh);
    const slot = h('div', { style: 'min-width:0' }, resultBox(key));
    const pathText = () => r.method + ' ' + EX[key]().path.replace(ref(), '{bot}').replace(encodeURIComponent(sid), '{sessionId}');
    return h('section', { class: 'panel ad-panel' },
      step && h('span', { class: 'ad-step' }, step),
      h('h2', {}, title),
      h('div', { class: 'ad-ep' }, h('span', { class: 'ad-m ' + r.method }, r.method), h('code', {}, pathText().slice(r.method.length + 1))),
      h('p', { class: 'help' }, purpose),
      extra,
      rows && fields(rows),
      code,
      !noTry && h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', onclick: () => run(key, slot) }, icon('spark'), 'Probar'),
        h('span', { class: 'help', style: 'font-size:13px' }, 'Manda el pedido de verdad a este servidor.')),
      slot,
      after);
  }

  function responseRef() {
    const rows = [
      ['bot', '{id, name} del bot que contestó.'],
      ['sessionId', 'La conversación. Usalo en los mensajes siguientes.'],
      ['channel', 'El canal que mandaste al empezar (por defecto "api").'],
      ['started / updated', 'Cuándo empezó y cuándo fue el último movimiento (hora local, AAAA-MM-DDThh:mm:ss).'],
      ['ended', 'true si la conversación se terminó con un evento end.'],
      ['slots', 'Todo lo que el bot tiene anotado: nombre del dato → valor (null si todavía no lo sabe).'],
      ['waiting_for', 'El dato que el bot acaba de preguntar y espera en el próximo mensaje, o null.'],
      ['flow', 'El flujo en el que está la conversación, o null.'],
      ['classifications', 'Los nombres de las clasificaciones que ya tiene la conversación, en el orden en que se marcaron (cada una una sola vez). [] si ninguna.'],
      ['environment', 'El entorno en el que empezó la conversación: "production", "staging" o "draft".'],
      ['version', 'El número de versión publicada con la que contesta esta conversación (queda fija desde que empezó). null = el borrador.'],
      ['messages', 'Lista de textos que el bot responde, en orden. Puede venir vacía. Mandalos tal cual al usuario.'],
      ['buttons', 'Botones de respuesta rápida del último mensaje: [{label, value}]. [] si no hay. Mostrá label; si la persona toca uno, mandá su value (o label) como el próximo message.'],
      ['handoff', 'true si la charla la atiende una persona (desde la Bandeja): el bot no contesta, messages viene vacía y lo que escribe la persona llega por …/messages.'],
      ['language', 'El idioma de la conversación ("es", "pt"…). Sale de data.idioma en start o del primer mensaje.'],
      ['via', 'Quién resolvió el turno: null (los flujos), "knowledge" (la base de conocimiento) o "ia" (la IA local).'],
      ['sources', 'Si contestó la base de conocimiento: [{title, doc, score}] de los documentos que usó. [] si no.'],
      ['next', 'Cuántas entradas tiene el historial: usalo como after en …/messages para recibir solo lo nuevo.'],
      ['understood', 'Qué entendió del mensaje: {intent, confidence (0 a 1), entities: [{entity, value}], answer_to (el dato que respondió, si era una respuesta)}. null en start.'],
      ['ignored_data', 'Solo en start: las claves de data que no son datos del agente y no se guardaron.'],
      ['trace', 'Solo en start: los pasos que siguió el bot, para depurar. No dependas de su formato.'],
    ];
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, 'Qué trae la respuesta de start y message'),
      fieldsOut(rows, 'Campo'),
      h('p', { class: 'help' }, 'Errores: siempre JSON con ', inline('{"error": "…"}'), ' y un mensaje en español. ',
        inline('400'), ' pedido mal armado (falta text, sessionId inválido, type o environment desconocido, staging sin ninguna versión), ',
        inline('401'), ' falta la clave (con usuarios creados), ', inline('403'), ' la clave no tiene permiso o el pedido viene de un sitio no autorizado, ',
        inline('404'), ' no existe el bot o la conversación, ', inline('405'), ' método no permitido en esa dirección.'));
  }

  // ---------- Exportar a Postman / Bruno / Insomnia / Hoppscotch y OpenAPI ----------
  const monthParams = () => { const d = new Date(); return { from: day(new Date(d.getFullYear(), d.getMonth(), 1)), to: day(d) }; };
  const SESSION_FILTERS = [
    ['channel', 'api', 'Solo las de ese canal, por ejemplo api o whatsapp.'],
    ['classification', () => firstClass() || '__none__', 'Solo las marcadas con esa clasificación (nombre exacto). __none__ trae las que no tienen ninguna.'],
    ['from', () => monthParams().from, 'Solo las que empezaron desde esa fecha, inclusive (AAAA-MM-DD).'],
    ['to', () => monthParams().to, 'Solo las que empezaron hasta esa fecha, inclusive (AAAA-MM-DD).'],
  ];
  const val = (v) => typeof v === 'function' ? v() : v;

  function postmanCollection() {
    const req = (name, method, path, description, { body, query } = {}) => {
      const qs = (query || []).filter((p) => !p.disabled).map((p) => p.key + '=' + p.value).join('&');
      return { name, request: {
        method, description,
        header: body ? [{ key: 'Content-Type', value: 'application/json' }] : [],
        ...(body && { body: { mode: 'raw', raw: JSON.stringify(body, null, 2), options: { raw: { language: 'json' } } } }),
        url: { raw: '{{baseUrl}}/' + path.join('/') + (qs ? '?' + qs : ''), host: ['{{baseUrl}}'], path, ...(query && { query }) },
      } };
    };
    const bot = ['bots', '{{bot}}'];
    const events = [...bot, 'events'];
    const session = [...bot, 'sessions', '{{sessionId}}'];
    const { from, to } = monthParams();
    return {
      info: { name: 'Parla · ' + agent.name, schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json',
        description: 'API de Parla para el agente «' + agent.name + '». JSON por HTTP. Sin usuarios creados no pide clave; con usuarios, poné tu clave en la variable apiKey (Authorization: Bearer). Solo responde en la computadora donde corre Parla (127.0.0.1).' },
      auth: { type: 'bearer', bearer: [{ key: 'token', value: '{{apiKey}}', type: 'string' }] },
      variable: [
        { key: 'apiKey', value: '' },
        { key: 'baseUrl', value: BASE() },
        { key: 'bot', value: botSlug() || agent.id },
        { key: 'sessionId', value: sid },
      ],
      item: [
        { name: 'Bots', item: [
          req('Ver qué bots hay', 'GET', ['bots'], PURPOSE.bots),
          req('Ver un bot', 'GET', bot, PURPOSE.bot),
        ] },
        { name: 'Conversación', item: [
          req('Empezar la conversación', 'POST', events, PURPOSE.start, { body: { type: 'start', sessionId: '{{sessionId}}', channel: 'api', data: sampleData() } }),
          req('Mandar un mensaje', 'POST', events, PURPOSE.message, { body: { type: 'message', sessionId: '{{sessionId}}', text: text() } }),
          req('Leer la conversación', 'GET', session, PURPOSE.read),
          req('Terminar la conversación', 'POST', events, PURPOSE.end, { body: { type: 'end', sessionId: '{{sessionId}}' } }),
          req('Recibir mensajes nuevos', 'GET', [...session, 'messages'], PURPOSE.messages,
            { query: [{ key: 'after', value: '0', description: 'Desde qué entrada del historial (el next de la respuesta anterior).' }] }),
          req('Mandar un mensaje de voz', 'POST', [...bot, 'audio'], PURPOSE.audio,
            { body: { sessionId: '{{sessionId}}', audio: '<la grabación en base64>', mime: 'audio/webm', speak: true } }),
        ] },
        { name: 'Conversaciones', item: [
          req('Listar conversaciones', 'GET', [...bot, 'sessions'], PURPOSE.list,
            { query: SESSION_FILTERS.map(([key, v, description]) => ({ key, value: val(v), description, disabled: true })) }),
          req('Ver una conversación', 'GET', session, PURPOSE.read),
          req('Borrar una conversación', 'DELETE', session, PURPOSE.del),
        ] },
        { name: 'Reportes', item: [
          req('Reporte de clasificaciones', 'GET', [...bot, 'report'], PURPOSE.report, { query: [
            { key: 'from', value: from, description: 'Desde esa fecha, inclusive (AAAA-MM-DD).' },
            { key: 'to', value: to, description: 'Hasta esa fecha, inclusive (AAAA-MM-DD).' },
            { key: 'channel', value: 'api', description: 'Solo las de ese canal.', disabled: true },
          ] }),
        ] },
      ],
    };
  }

  function openApi() {
    const ref = (n) => ({ $ref: '#/components/schemas/' + n });
    const str = (description, extra) => ({ type: 'string', ...(description && { description }), ...extra });
    const nstr = (description) => str(description, { nullable: true });
    const obj = (properties, required, extra) => ({ type: 'object', properties, ...(required && { required }), ...extra });
    const json = (schema, examples) => ({ content: { 'application/json': { schema, ...(examples && { examples }) } } });
    const ok = (description, schema, examples) => ({ description, ...json(schema, examples) });
    const err = (description) => ({ description, ...json(ref('Error')) });
    const param = (name, where, description, example, extra) => ({ name, in: where, required: where === 'path', description, schema: { type: 'string', ...extra }, example });
    const P = {
      bot: param('bot', 'path', 'El id del bot, su nombre exacto o su nombre simplificado (slug).', botSlug() || agent.id),
      sessionId: param('sessionId', 'path', 'La conversación.', sid, { pattern: SID_RE.source }),
    };
    const op = (summary, tag, description, responses, extra) => ({ summary, tags: [tag], description, responses, ...extra });
    const bot404 = { 404: err('No hay un bot con ese nombre o id (o el nombre es ambiguo).') };
    const session = obj({
      bot: obj({ id: str(), name: str() }),
      sessionId: str(), channel: str(), started: str('AAAA-MM-DDThh:mm:ss, hora local.'), updated: str(), ended: { type: 'boolean' },
      slots: { type: 'object', additionalProperties: {}, description: 'Nombre del dato → valor (null si todavía no se sabe).' },
      waiting_for: nstr('El dato que el bot espera en el próximo mensaje.'),
      flow: nstr('El flujo en el que está la conversación.'),
      classifications: { type: 'array', items: str() },
      environment: str('', { enum: ['production', 'staging', 'draft'] }),
      version: { type: 'integer', nullable: true, description: 'Versión publicada con la que contesta. null = el borrador.' },
      language: nstr('El idioma de la conversación ("es", "pt"…).'),
      next: { type: 'integer', description: 'Cantidad de entradas del historial: el after para …/messages.' },
    });
    const button = obj({ label: str('Lo que se muestra.'), value: str('Lo que se manda como message si lo tocan.') }, ['label', 'value']);
    const slots = Object.fromEntries(agent.slots.map((s) => [s.name, null]));
    const startData = sampleData();
    return {
      openapi: '3.0.3',
      info: { title: 'Parla · ' + agent.name, version: '1', description: 'API pública de Parla. JSON por HTTP. Sin usuarios creados no pide clave; con usuarios, Authorization: Bearer <clave> (Usuarios → Claves de API). Con el widget web prendido, events, audio y los messages del widget quedan abiertos y aceptan CORS de sus orígenes. Solo responde en 127.0.0.1: para exponerla poné adelante un proxy con HTTPS.' },
      servers: [{ url: BASE() }],
      security: [{}, { bearerAuth: [] }],
      tags: [{ name: 'Bots' }, { name: 'Conversación' }, { name: 'Conversaciones' }, { name: 'Reportes' }],
      paths: {
        '/bots': { get: op('Ver qué bots hay', 'Bots', PURPOSE.bots, { 200: ok('Los bots.', obj({ bots: { type: 'array', items: ref('Bot') } }, ['bots'])) }) },
        '/bots/{bot}': { parameters: [P.bot], get: op('Ver un bot', 'Bots', PURPOSE.bot, { 200: ok('El bot.', ref('Bot')), ...bot404 }) },
        '/bots/{bot}/events': { parameters: [P.bot], post: op('Mandar un evento: start (u online), message o end', 'Conversación',
          [PURPOSE.start, PURPOSE.message, PURPOSE.end].join('\n\n'), {
            200: ok('start y message devuelven la conversación con lo que contestó el bot; end devuelve {sessionId, ended}.',
              { oneOf: [ref('EventResponse'), ref('EndResponse')] }, {
                start: { value: { bot: { id: agent.id, name: agent.name }, sessionId: sid, channel: 'api', started: '2026-01-01T10:00:00', updated: '2026-01-01T10:00:00',
                  ended: false, slots: { ...slots, ...Object.fromEntries(Object.entries(startData).filter(([k]) => k in slots)) }, waiting_for: null, flow: null,
                  classifications: [], environment: 'production', version: null, messages: [], understood: null, ignored_data: [], trace: [] } },
                end: { value: { sessionId: sid, ended: true } },
              }),
            400: err('Pedido mal armado: falta text, sessionId inválido, type o environment desconocido, staging sin versión, data no es un objeto.'),
            401: err('Falta la clave (Parla tiene usuarios y el widget de este bot está apagado).'),
            404: err('No existe el bot, o (en end) la conversación.'),
          }, { requestBody: { required: true, ...json(ref('EventRequest'), {
            start: { summary: 'Empezar con datos precargados', value: { type: 'start', sessionId: sid, channel: 'api', data: startData } },
            message: { summary: 'Mandar lo que escribió la persona', value: { type: 'message', sessionId: sid, text: text() } },
            end: { summary: 'Terminar la conversación', value: { type: 'end', sessionId: sid } },
          }) } }) },
        '/bots/{bot}/audio': { parameters: [P.bot], post: op('Mandar un mensaje de voz', 'Conversación', PURPOSE.audio, {
          200: ok('Lo mismo que message, más heard y (con speak) audio.', ref('AudioResponse')),
          400: err('Falta audio, no es base64, no hay modelo de voz o no se entendió nada.'), 401: err('Falta la clave.'), 404: err('No existe el bot.'),
        }, { requestBody: { required: true, ...json(ref('AudioRequest')) } }) },
        '/bots/{bot}/sessions/{sessionId}/messages': { parameters: [P.bot, P.sessionId], get: op('Recibir mensajes nuevos', 'Conversación', PURPOSE.messages, {
          200: ok('Lo nuevo del historial.', ref('Messages')), 400: err('after no es un número.'), 404: err('No existe el bot o la conversación.'),
        }, { parameters: [param('after', 'query', 'Desde qué entrada del historial (0 = todo): el next de la respuesta anterior.', '0', { pattern: '^\\d+$' })] }) },
        '/bots/{bot}/sessions': { parameters: [P.bot], get: op('Listar conversaciones', 'Conversaciones', PURPOSE.list, {
          200: ok('Las conversaciones, la más reciente primero.', obj({ sessions: { type: 'array', items: ref('SessionSummary') } }, ['sessions'])), ...bot404,
        }, { parameters: SESSION_FILTERS.map(([key, v, description]) => param(key, 'query', description, val(v), key === 'from' || key === 'to' ? { format: 'date' } : {})) }) },
        '/bots/{bot}/sessions/{sessionId}': { parameters: [P.bot, P.sessionId],
          get: op('Leer la conversación', 'Conversaciones', PURPOSE.read, { 200: ok('La conversación con su historial.', ref('SessionDetail')), 404: err('No existe el bot o la conversación.') }),
          delete: op('Borrar una conversación', 'Conversaciones', PURPOSE.del, {
            200: ok('Borrada.', obj({ sessionId: str(), deleted: { type: 'boolean', enum: [true] } }, ['sessionId', 'deleted'])), 404: err('No existe el bot o la conversación.') }) },
        '/bots/{bot}/report': { parameters: [P.bot], get: op('Reporte de clasificaciones', 'Reportes', PURPOSE.report, { 200: ok('El reporte.', ref('Report')), ...bot404 }, {
          parameters: [param('from', 'query', 'Desde esa fecha, inclusive (AAAA-MM-DD).', monthParams().from, { format: 'date' }),
            param('to', 'query', 'Hasta esa fecha, inclusive (AAAA-MM-DD).', monthParams().to, { format: 'date' }), param('channel', 'query', 'Solo las de ese canal.', 'api')] }) },
      },
      components: { securitySchemes: { bearerAuth: { type: 'http', scheme: 'bearer', description: 'Solo si Parla tiene usuarios: una clave de Usuarios → Claves de API.' } }, schemas: {
        Error: obj({ error: str('Qué pasó, en español.') }, ['error']),
        Bot: obj({ id: str(), name: str(), slug: str('Nombre simplificado para la URL.'), online: { type: 'boolean' },
          trained_at: nstr('Cuándo se entrenó el borrador por última vez.'), intents: { type: 'array', items: str() },
          environments: obj({ production: { type: 'integer', nullable: true }, staging: { type: 'integer', nullable: true } }, null,
            { description: 'Qué versión tiene cada entorno. null = ninguna (production contesta con el borrador; staging da 400).' }) },
          null, { example: { id: agent.id, name: agent.name, slug: botSlug(), online: true, trained_at: null, intents: agent.intents.map((i) => i.name),
            environments: { production: agent.environments?.production ?? null, staging: agent.environments?.staging ?? null } } }),
        EventRequest: obj({
          type: str('start (u online) para empezar, message para un mensaje (se puede omitir si mandás text), end para terminar.', { enum: ['start', 'online', 'message', 'end'] }),
          sessionId: str('La conversación. Si no lo mandás en start o message, se crea uno. Obligatorio en end.', { pattern: SID_RE.source }),
          text: str('Solo en message: lo que escribió la persona (hasta 4000 caracteres).'),
          data: { type: 'object', additionalProperties: {}, description: 'Solo en start: datos que ya conocés. Se guardan las claves que se llaman igual que un dato del agente' +
            (agent.slots.length ? ' (' + agent.slots.map((s) => s.name).join(', ') + ')' : '') + '; las demás vuelven en ignored_data.' },
          channel: str('De dónde viene: whatsapp, web, ivr… Por defecto api.'),
          environment: str('Qué versión contesta. Solo cuenta al empezar la conversación.', { enum: ['production', 'staging', 'draft'], default: 'production' }),
        }),
        Understood: obj({ intent: nstr(), confidence: { type: 'number', minimum: 0, maximum: 1 },
          entities: { type: 'array', items: obj({ entity: str(), value: {} }) }, answer_to: nstr('El dato que respondió, si era una respuesta.') }),
        Session: session,
        EventResponse: { allOf: [ref('Session'), obj({
          messages: { type: 'array', items: str(), description: 'Lo que responde el bot, en orden. Puede venir vacía.' },
          understood: { allOf: [ref('Understood')], nullable: true, description: 'null en start.' },
          ignored_data: { type: 'array', items: str(), description: 'Solo en start: claves de data que no se guardaron.' },
          trace: { type: 'array', items: str(), description: 'Solo en start: pasos que siguió el bot, para depurar. No dependas de su formato.' },
          buttons: { type: 'array', items: button, description: 'Botones del último mensaje. [] si no hay.' },
          handoff: { type: 'boolean', description: 'true si la charla la atiende una persona: el bot no contesta.' },
          via: nstr('null (flujos), "knowledge" (base de conocimiento) o "ia" (IA local).'),
          sources: { type: 'array', items: obj({ title: str(), doc: str(), score: { type: 'number' } }), description: 'Documentos de la base de conocimiento que usó.' },
        }, ['messages', 'understood'])] },
        AudioRequest: obj({ audio: str('La grabación en base64 (o data:audio/...;base64,...).'), sessionId: str('', { pattern: SID_RE.source }),
          mime: str('audio/webm, audio/ogg, audio/wav…', { default: 'audio/webm' }), speak: { type: 'boolean', default: false, description: 'Devolver la respuesta también en audio.' },
          channel: str(), environment: str('', { enum: ['production', 'staging', 'draft'] }) }, ['audio']),
        AudioResponse: { allOf: [ref('EventResponse'), obj({ heard: str('Lo que entendió del audio.'), audio: str('Solo con speak: la respuesta en WAV, base64.') }, ['heard'])] },
        Messages: obj({ sessionId: str(), messages: { type: 'array', items: ref('HistoryEntry') }, next: { type: 'integer' },
          handoff: { type: 'boolean' }, ended: { type: 'boolean' } }, ['sessionId', 'messages', 'next']),
        EndResponse: obj({ sessionId: str(), ended: { type: 'boolean', enum: [true] } }, ['sessionId', 'ended']),
        HistoryEntry: obj({ from: str('"human" = una persona desde la Bandeja.', { enum: ['event', 'user', 'bot', 'human'] }), text: str(), at: str(),
          by: str('Solo human: quién escribió.'), buttons: { type: 'array', items: button, description: 'Solo bot: los botones de ese mensaje.' },
          fallback: { type: 'boolean', description: 'Solo user: el bot no lo entendió.' }, via: nstr('Solo user: quién resolvió ese turno.'),
          intent: nstr('Solo user.'), confidence: { type: 'number', description: 'Solo user.' },
          entities: { type: 'array', items: obj({ entity: str(), value: {} }), description: 'Solo user.' }, answer_to: nstr('Solo user.'),
          data: { type: 'object', additionalProperties: {}, description: 'Solo en el event de inicio: los datos precargados que se guardaron.' },
          classification: str('Solo en el event que marcó una clasificación.') }, ['from', 'text', 'at']),
        SessionDetail: { allOf: [ref('Session'), obj({ history: { type: 'array', items: ref('HistoryEntry') },
          handoff: obj({ active: { type: 'boolean' }, since: str(), reason: nstr(), by: nstr() }, null, { nullable: true, description: 'Si alguna vez pasó a una persona: desde cuándo, por qué y quién.' }) }, ['history'])] },
        SessionSummary: obj({ sessionId: str(), channel: str(), started: str(), updated: str(), ended: { type: 'boolean' },
          messages: { type: 'integer', description: 'Cantidad de entradas del historial.' }, last_message: nstr(), first_message: nstr(),
          data: { type: 'object', additionalProperties: {}, nullable: true, description: 'Datos precargados al empezar.' },
          classifications: { type: 'array', items: str() }, environment: str(), version: { type: 'integer', nullable: true } }),
        Report: obj({ bot: obj({ id: str(), name: str() }), from: nstr(), to: nstr(), channel: nstr(), sessions: { type: 'integer' }, unclassified: { type: 'integer' },
          classifications: { type: 'array', items: obj({ name: str(), count: { type: 'integer' }, configured: { type: 'boolean' } }) },
          by_day: { type: 'array', items: obj({ date: str('', { format: 'date' }), sessions: { type: 'integer' }, unclassified: { type: 'integer' },
            counts: { type: 'object', additionalProperties: { type: 'integer' } } }) } }),
      } },
    };
  }

  function download(name, data) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const a = h('a', { href: url, download: name });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
  const fileBase = () => 'parla-' + (botSlug() || agent.id);
  window.apiDocsExport = { postmanCollection, openApi };   // para probar desde la consola o node

  function exportSection() {
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, 'Llevar a tu herramienta de pruebas'),
      h('p', { class: 'help' }, 'Bajá la API de «', agent.name, '» lista para Postman, Bruno, Insomnia, Hoppscotch o cualquier herramienta que lea OpenAPI. Usa el sessionId y los datos de esta página.'),
      h('div', { class: 'row', style: 'flex-wrap:wrap' },
        h('button', { class: 'btn small', type: 'button', style: 'white-space:normal', onclick: () => download(fileBase() + '.postman_collection.json', postmanCollection()) }, 'Exportar para Postman / Bruno / Insomnia'),
        h('button', { class: 'btn small quiet', type: 'button', onclick: () => download(fileBase() + '.openapi.json', openApi()) }, 'Exportar OpenAPI')),
      h('p', { class: 'help', style: 'font-size:13px' }, 'Para importarla: en Postman, Import → elegí el archivo; en Bruno, Import Collection → Postman Collection u OpenAPI; en Insomnia y Hoppscotch, Import → el archivo.'));
  }

  function accessSection() {
    const w = agent.widget || {};
    const origins = (w.origins || []).filter(Boolean);
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, 'Claves y chat web'),
      h('p', { class: 'help' }, 'Mientras no haya usuarios creados, la API no pide clave. ', h('strong', {}, 'Con usuarios'), ', cada pedido tiene que traer ',
        inline('Authorization: Bearer <clave>'), '. La clave se crea en Usuarios → tu usuario → «Claves de API» y tiene los permisos de ese usuario: ',
        inline('owner'), ' y ', inline('editor'), ' todo; ', inline('analyst'), ' solo leer (GET); ', inline('agent'), ' solo conversaciones y Bandeja. Sin clave: 401.',
        window.authEnabled ? ' Este Parla tiene usuarios: los ejemplos ya traen el encabezado, cambiá TU_CLAVE por la tuya.' : ''),
      h('p', { class: 'help' }, 'Excepción: si el bot tiene el ', h('strong', {}, 'widget web'), ' prendido, ', inline('POST …/events'), ' y ', inline('POST …/audio'),
        ' quedan abiertos (es el chat público de tu web), y ', inline('GET …/sessions/{sessionId}/messages'), ' también, solo para conversaciones del widget (canal "web").'),
      h('p', { class: 'help' }, 'Un navegador solo puede llamar a la API desde otra web (CORS) en ', inline('…/events'), ', ', inline('…/audio'), ' y ', inline('…/messages'),
        ', y solo si el widget está prendido y ese sitio está en sus orígenes. Cualquier otro pedido que venga de otra web se rechaza con 403. ',
        'Desde un servidor (WhatsApp, IVR, CRM) no hay CORS: usá la clave. ',
        w.enabled ? ['El widget de «', agent.name, '» está prendido para: ', origins.length ? origins.map((o, i) => [i ? ', ' : '', inline(o)]) : 'ningún sitio todavía', '.']
          : ['El widget de «', agent.name, '» está apagado (se prende en «Widget web»).']));
  }

  function versionsSection() {
    const env = agent.environments || {};
    const where = (n) => n == null ? 'ninguna' : 'v' + n;
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, 'Versiones y paso a producción'),
      h('p', { class: 'help' }, 'Lo que editás en Parla es el ', h('strong', {}, 'borrador'), '. Al publicar, el borrador se congela como una versión numerada (v1, v2…) que ya no cambia. ',
        'Hay dos entornos: ', h('strong', {}, 'Producción'), ', la que usan tus integraciones, y ', h('strong', {}, 'Pruebas'), ' (', inline('staging'), '), para que el cliente la pruebe antes. ',
        'Cada entorno apunta a una versión y eso se maneja en la sección «Versiones».'),
      h('p', { class: 'help' }, 'Las integraciones normalmente no mandan ', inline('environment'), ' (o mandan ', inline('"production"'), '). Para que el cliente pruebe antes de salir, usá ', inline('"staging"'),
        ' desde un número o chat de pruebas. ', inline('"draft"'), ' sirve para ver cambios sin publicar.'),
      h('p', { class: 'help' }, 'Cada conversación queda ', h('strong', {}, 'atada a la versión con la que empezó'), ': si publicás o cambiás la versión de Producción, las conversaciones en curso siguen igual y las nuevas usan la nueva. ',
        'Si una versión nueva anda mal, volvé a poner la anterior en Producción (rollback) desde «Versiones»: las conversaciones nuevas vuelven a la anterior al instante. ',
        'Las respuestas traen ', inline('environment'), ' y ', inline('version'), ' para que sepas con cuál contestó.'),
      h('p', { class: 'help' }, 'Ahora «', agent.name, '» tiene en Producción: ', h('strong', {}, env.production == null ? 'ninguna (contesta el borrador)' : where(env.production)),
        ' · en Pruebas: ', h('strong', {}, env.staging == null ? 'ninguna (staging da 400)' : where(env.staging)), '.'));
  }

  window.apiDocsView = () => {
    refreshers.length = 0;
    const sf = startFlow();
    const data = sampleData();
    const slotNames = agent.slots.map((s) => s.name);

    const sidErr = h('span', { class: 'ad-err' });
    const sidInput = h('input', { value: sid, 'aria-label': 'sessionId de los ejemplos', spellcheck: 'false', autocomplete: 'off',
      oninput: (e) => {
        const v = e.target.value.trim();
        const ok = SID_RE.test(v);
        e.target.setAttribute('aria-invalid', ok ? 'false' : 'true');
        sidErr.textContent = ok ? '' : 'De 1 a 100 letras sin tildes, números o . @ + - _ (sin espacios, sin empezar con punto).';
        if (ok) { sid = v; refreshers.forEach((f) => f()); }
      } });

    const msgInput = h('input', { value: text(), 'aria-label': 'Texto del mensaje', style: 'width:100%',
      oninput: (e) => { msgText = e.target.value; refreshers.forEach((f) => f()); } });

    return h('div', { class: 'page' },
      h('h1', {}, 'API'),
      h('p', { class: 'help' }, 'Con la API, otro programa puede charlar con este agente igual que en la prueba: WhatsApp, un chat en tu web, un conmutador telefónico (IVR) o un CRM. ',
        'Le mandás lo que escribió la persona y te devuelve lo que contesta el bot, más los datos que fue anotando. Todo es JSON por HTTP, sin claves.'),
      h('p', { class: 'help' }, 'Con las clasificaciones (el paso «Clasificar la conversación» de un flujo) cada conversación queda marcada con lo que pasó, y con eso armás reportes: por ejemplo, un bot de turnos médicos que marca «Turno agendado» o «Cancelación» y te dice cuántos hubo por día.'),

      h('section', { class: 'panel ad-panel' },
        h('h2', {}, 'Dirección'),
        h('p', { class: 'help' }, 'Todas las direcciones empiezan con:'),
        codeBox(() => BASE(), true),
        h('p', { class: 'help' }, 'Este agente, «', agent.name, '», se puede nombrar en la URL por su nombre simplificado ', inline(botSlug() || '—'),
          ', por su id ', inline(agent.id), ' o por su nombre exacto. Si hay dos agentes con el mismo nombre, usá el id.'),
        codeBox(() => BASE() + '/bots/' + ref(), true),
        h('div', { class: 'notice warn' }, h('span', {},
          h('strong', {}, 'Solo funciona en esta computadora. '),
          'Parla escucha únicamente en 127.0.0.1, así que otros equipos o internet no lo ven. La API no pide clave: si querés que WhatsApp u otro servicio de afuera llegue, ',
          'poné adelante un proxy (por ejemplo nginx o Caddy) que pida autenticación y use HTTPS. Nunca la expongas tal cual.')),
        h('div', { class: 'notice' }, h('span', {},
          'La API contesta con la ', h('strong', {}, 'versión publicada en Producción'), ' (mirá «Versiones y paso a producción» más abajo). Mientras no publiques ninguna, contesta con el borrador tal como está ahora. ',
          'Las conversaciones se guardan en disco y siguen ahí aunque reinicies Parla.'))),

      exportSection(),

      accessSection(),

      versionsSection(),

      h('section', { class: 'panel ad-panel ad-sid' },
        h('h2', {}, 'Tu sessionId'),
        h('p', { class: 'help' }, 'Cada conversación tiene un sessionId que elegís vos. Lo ideal es usar el id de quien escribe, por ejemplo ', inline('wa-5491122334455'),
          ' para WhatsApp o el número de llamada en un IVR. Todos los ejemplos de abajo usan este:'),
        sidInput, sidErr),

      h('h2', { style: 'font:700 22px var(--display);margin-top:8px' }, 'Una conversación de ejemplo'),
      h('p', { class: 'help' }, 'Apretá «Probar» en orden y vas a tener una conversación de verdad con «', agent.name, '». Después la podés ver en Conversaciones.'),

      endpoint('bots', { step: 'Paso 1', title: 'Ver qué bots hay', purpose: PURPOSE.bots }),

      endpoint('start', {
        step: 'Paso 2', title: 'Empezar la conversación con datos precargados',
        purpose: PURPOSE.start,
        rows: [
          ['type', 'Sí', '"start" (o "online").'],
          ['sessionId', 'No', 'Si no lo mandás, se crea uno y viene en la respuesta.'],
          ['data', 'No', slotNames.length ? ['Datos que ya conocés. Cada clave que se llama igual que un dato del agente se guarda ahí: ', slotNames.map((n, i) => [i ? ', ' : '', inline(n)]), '. Las demás vuelven en ignored_data.']
            : 'Datos que ya conocés. Se guardan solo las claves que se llaman igual que un dato del agente (este todavía no tiene datos); las demás vuelven en ignored_data.'],
          ['channel', 'No', 'De dónde viene: "whatsapp", "web", "ivr"… Sirve para filtrar después. Por defecto "api".'],
          ['environment', 'No', ['Qué versión del bot contesta: ', inline('"production"'), ' (por defecto, la que ven tus usuarios), ', inline('"staging"'), ' (Pruebas, para que el cliente la pruebe antes de pasarla a producción) o ', inline('"draft"'), ' (el borrador, con los cambios sin publicar). Solo cuenta al empezar la conversación: después sigue en la misma.']],
        ],
        extra: h('div', { class: 'notice' }, h('span', {}, sf
          ? ['Este agente tiene el flujo «', sf.name, '» que corre apenas empieza la conversación, así que la respuesta ya puede traer mensajes en messages (por ejemplo, saludar por el nombre que vino en data).']
          : ['Este agente no tiene un flujo de inicio, así que start solo guarda los datos y messages vuelve vacía. Si querés que salude o busque algo apenas empieza (por ejemplo, un IVR que pasa el DNI y el bot consulta el nombre), ',
            'creá un flujo en Flujos y en «Lo dispara» elegí «Al empezar la conversación».'])),
      }),

      endpoint('message', {
        step: 'Paso 3', title: 'Mandar lo que escribió la persona',
        purpose: PURPOSE.message,
        rows: [
          ['text', 'Sí', 'Lo que escribió o dijo la persona (hasta 4000 caracteres).'],
          ['sessionId', 'No', 'La conversación. Si no lo mandás, se crea una nueva y viene en la respuesta. Si la conversación estaba terminada, sigue con la memoria en blanco.'],
          ['type', 'No', '"message". Se puede omitir si mandás text.'],
          ['environment', 'No', ['Qué versión del bot contesta: ', inline('"production"'), ' (por defecto, la que ven tus usuarios), ', inline('"staging"'), ' (Pruebas, para que el cliente la pruebe antes de pasarla a producción) o ', inline('"draft"'), ' (el borrador, con los cambios sin publicar). Solo cuenta al empezar la conversación: después sigue en la misma.']],
        ],
        extra: h('label', { class: 'f' }, 'Texto del mensaje (cambialo y volvé a probar para seguir la charla)', msgInput),
      }),

      endpoint('read', {
        step: 'Paso 4', title: 'Leer la conversación',
        purpose: PURPOSE.read,
      }),

      endpoint('end', {
        step: 'Paso 5', title: 'Terminar la conversación',
        purpose: PURPOSE.end,
        rows: [['type', 'Sí', '"end".'], ['sessionId', 'Sí', 'La conversación a terminar.']],
      }),

      h('h2', { style: 'font:700 22px var(--display);margin-top:8px' }, 'Otras direcciones'),

      endpoint('bot', { title: 'Ver un bot', purpose: PURPOSE.bot,
        after: fieldsOut([
          ['id / name / slug', 'El id, el nombre y el nombre simplificado para la URL.'],
          ['trained_at', 'Cuándo se entrenó el borrador por última vez.'],
          ['intents', 'Los nombres de las intenciones del borrador.'],
          ['environments', ['Qué versión tiene cada entorno: ', inline('{"production": 3, "staging": 4}'), '. null = ninguna (production contesta con el borrador; staging da 400).']],
        ]) }),
      endpoint('list', { title: 'Listar conversaciones',
        purpose: PURPOSE.list,
        rows: [
          ['channel', 'No', 'Solo las de ese canal, por ejemplo api o whatsapp.'],
          ['classification', 'No', ['Solo las marcadas con esa clasificación (el nombre exacto, codificado para URL). ', inline('__none__'), ' trae las que no tienen ninguna.']],
          ['from / to', 'No', 'Solo las que empezaron entre esas fechas, inclusive (AAAA-MM-DD).'],
        ],
        after: h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
          h('p', { class: 'help' }, firstClass() ? ['Por ejemplo, las de este mes clasificadas como «', firstClass(), '»:']
            : ['Por ejemplo, las de este mes con una clasificación (este agente todavía no tiene clasificaciones: cambiá «Turno agendado» por el nombre de la que crees):']),
          codeBox(() => curl({ method: 'GET', path: '/bots/' + ref() + '/sessions?classification=' + encodeURIComponent(firstClass() || 'Turno agendado') + '&' + monthRange() }))) }),
      endpoint('report', { title: 'Reporte de clasificaciones',
        purpose: PURPOSE.report,
        rows: [
          ['from / to', 'No', 'Solo las conversaciones que empezaron entre esas fechas, inclusive (AAAA-MM-DD). El ejemplo usa este mes.'],
          ['channel', 'No', 'Solo las de ese canal.'],
        ],
        after: fieldsOut([
          ['sessions', 'Cuántas conversaciones entraron en el reporte.'],
          ['unclassified', 'Cuántas no tienen ninguna clasificación.'],
          ['classifications', 'Una por clasificación: {name, count, configured}. count cuenta conversaciones (una conversación con dos clasificaciones suma en las dos). configured es false si el nombre se usó en conversaciones viejas pero ya no existe en el agente.'],
          ['by_day', 'Una por día con conversaciones, de la más vieja a la más nueva: {date, sessions, unclassified, counts: {nombre: cantidad}}. Solo trae en counts las clasificaciones que tuvieron alguna ese día.'],
          ['bot / from / to / channel', 'El bot y los filtros que se aplicaron (null si no mandaste).'],
        ]) }),
      endpoint('del', { title: 'Borrar una conversación', purpose: PURPOSE.del }),
      endpoint('messages', { title: 'Recibir mensajes nuevos (persona de la Bandeja)', purpose: PURPOSE.messages,
        rows: [['after', 'No', 'Desde qué entrada del historial (0 = todo). Mandá el next de la respuesta anterior.']],
        after: fieldsOut([
          ['messages', ['Las entradas nuevas del historial: {from, text, at, …}. from es "user", "bot", "event" o ', inline('"human"'), ' (una persona de la Bandeja; trae by con su nombre). Las del bot pueden traer buttons.']],
          ['next', 'El after para el próximo pedido.'],
          ['handoff', 'true mientras la charla la atiende una persona.'],
          ['ended', 'true si la conversación se terminó.'],
        ]) }),
      endpoint('audio', { title: 'Mandar un mensaje de voz', purpose: PURPOSE.audio, noTry: true,
        rows: [
          ['audio', 'Sí', ['La grabación en base64 (también acepta ', inline('data:audio/webm;base64,…'), '). Hasta 25 MB.']],
          ['sessionId', 'No', 'La conversación (como en message).'],
          ['mime', 'No', 'El formato: audio/webm (por defecto), audio/ogg, audio/wav, audio/mpeg…'],
          ['speak', 'No', 'true para que la respuesta venga también en audio.'],
          ['channel / environment', 'No', 'Igual que en message.'],
        ],
        after: fieldsOut([
          ['heard', 'Lo que entendió del audio (el texto que atendió como message).'],
          ['audio', 'Solo con speak: la respuesta hablada, WAV en base64. Para reproducirla: new Audio("data:audio/wav;base64," + audio).'],
          ['…', 'Todo lo demás, igual que la respuesta de message. 400 si no hay modelo de voz o no se entendió nada.'],
        ]) }),

      responseRef());
  };
})();
