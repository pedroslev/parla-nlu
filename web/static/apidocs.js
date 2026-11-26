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
    const initial = agent.slots.filter((s) => s.start).map((s) => s.name);
    if (initial.length) return Object.fromEntries(initial.map((n) => [n, SAMPLE[n] ?? 'ejemplo']));
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
    audio: () => ({ method: 'POST', path: '/bots/' + ref() + '/audio', body: { sessionId: sid, audio: t('<la grabación en base64>'), mime: 'audio/webm', speak: true } }),
    outbound: () => ({ method: 'POST', path: '/bots/' + ref() + '/outbound', body: { channel: 'whatsapp', to: '+5491122334455',
      template: { name: (agent.channels?.whatsapp?.templates || [])[0]?.name || 'recordatorio_turno' }, flow: agent.flows[0]?.name || null, data: sampleData() } }),
    handoff: () => ({ method: 'POST', path: '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) + '/handoff', body: { action: 'accept', agent_name: 'Marta' } }),
    reply: () => ({ method: 'POST', path: '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) + '/messages', body: { text: t('Hola, soy Marta. ¿En qué te ayudo?'), from_name: 'Marta' } }),
    lookup: () => ({ method: 'GET', path: '/bots/' + ref() + '/lookup?phone=5491122334455' }),
    status: () => ({ method: 'GET', path: '/bots/' + ref() + '/outbound/42' }),
    statuses: () => ({ method: 'GET', path: '/bots/' + ref() + '/outbound?status=failed&' + monthRange().replace('to=', 'to_date=') }),
    costs: () => ({ method: 'GET', path: '/bots/' + ref() + '/costs?' + monthRange() + '&group=day' }),
  };

  // Qué hace cada dirección: lo usan la página y los archivos exportados.
  const PURPOSE = {
    bots: t('Lista todos los agentes de este Parla con su id, su nombre para la URL, cuándo se entrenaron, sus intenciones y qué versión tiene cada entorno (environments).'),
    start: t('Abre (o reinicia) la conversación. Si ya existía, arranca con la memoria en blanco pero conserva lo charlado en el historial. "online" funciona igual que "start".'),
    message: t('Un mensaje del usuario. Te devuelve las respuestas del bot en messages y qué entendió en understood. Repetilo por cada mensaje.'),
    read: t('La conversación completa: datos anotados, en qué flujo está, sus clasificaciones y el historial (from: "event", "user" o "bot"; los mensajes del usuario traen lo que se entendió; cada clasificación aparece como un event con classification).'),
    end: t('Cierra la conversación y borra lo que el bot tenía en memoria. Queda en el historial; si después llega un mensaje con el mismo sessionId, sigue con la memoria en blanco.'),
    bot: t('Lo mismo que en la lista, para un solo bot. {bot} puede ser el id, el nombre exacto o el nombre simplificado. Si no existe o es ambiguo: 404.'),
    list: t('Las conversaciones de este bot, la más reciente primero, con un resumen (cantidad de mensajes, primero y último, datos precargados, classifications, environment y version). Los filtros van en la URL, son opcionales y se pueden combinar:'),
    report: t('Cuántas conversaciones hubo con cada clasificación, en total y por día. Sirve para tableros o planillas. Los filtros son opcionales; sin ellos cuenta todas las conversaciones.'),
    del: t('La elimina del todo, con su historial. No se puede deshacer.'),
    messages: t('Lo nuevo de la conversación desde la entrada número after del historial (0 = todo). Sirve para recibir lo que escribe una persona desde la Bandeja cuando el bot pasó la charla (handoff): preguntá cada pocos segundos mandando como after el next de la respuesta anterior.'),
    outbound: t('El bot escribe primero: un mensaje de WhatsApp (con plantilla aprobada), Telegram o una llamada a una sola persona. Para muchas, armá una campaña en «Campañas». No se manda a quien se dio de baja.'),
    handoff: t('Para un contact center fuera de Parla: tomar la conversación derivada (accept), devolverla al bot (release, con data y flow opcionales) o cerrarla (close, con resolution). Devuelve la conversación sin history.'),
    reply: t('Lo que escribe la persona del contact center: Parla lo entrega por el canal de la charla (widget, WhatsApp, Telegram). 409 en llamadas, conversaciones terminadas o WhatsApp fuera de las 24 h.'),
    lookup: t('La conversación abierta más reciente de ese cliente (primero las derivadas), por phone, chat o sid. El mismo cuerpo que el webhook. 404 si no hay.'),
    status: t('El estado de un envío con el id que devolvió POST …/outbound: sent, delivered, read, replied o failed (con error), y sus fechas. Analista o más, o una clave «integration».'),
    statuses: t('Los envíos del bot, el más nuevo primero (API, campañas y recordatorios). Filtros opcionales: to, status, from y to_date (AAAA-MM-DD), kind, channel y limit (hasta 500).'),
    costs: t('Lo que costó cada conversación: el uso medido (tokens, minutos, caracteres, mensajes) por la tabla de precios de esta instalación. Estimado con los precios actuales; la factura del proveedor es la fuente de verdad. Analista o más.'),
    audio: t('Un mensaje de voz: Parla lo pasa a texto en esta computadora (sin servicios de afuera), lo atiende como un message y, con speak, te devuelve la respuesta también en audio. Trae lo mismo que message más heard y audio.'),
  };

  const q = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";
  function curl(r) {
    let s = 'curl' + (r.method === 'GET' ? '' : ' -X ' + r.method) + ' ' + q(BASE() + r.path);
    if (window.authEnabled) s += " \\\n  -H 'Authorization: Bearer " + t('TU_CLAVE') + "'";   // con usuarios creados la API pide clave
    if (r.body) {
      const json = JSON.stringify(r.body);
      s += " \\\n  -H 'Content-Type: application/json' \\\n  -d " + q(json.length > 70 ? JSON.stringify(r.body, null, 2) : json);
    }
    return s;
  }

  async function copy(textOf, btn, pre) {
    try { await navigator.clipboard.writeText(textOf()); btn.textContent = t('Copiado'); }
    catch { getSelection().selectAllChildren(pre); btn.textContent = t('Seleccionado: ⌘C / Ctrl+C'); }
    setTimeout(() => { btn.textContent = t('Copiar'); }, 1600);
  }
  function codeBox(textOf, light) {
    const pre = h('pre', {}, textOf());
    const btn = h('button', { class: 'ad-copy', type: 'button', onclick: () => copy(textOf, btn, pre) }, t('Copiar'));
    const box = h('div', { class: 'ad-code' + (light ? ' light' : '') }, pre, btn);
    box.refresh = () => { pre.textContent = textOf(); };
    return box;
  }
  const inline = (txt) => h('code', { class: 'ad-inline' }, txt);
  const prose = (d) => typeof d === 'string' ? d.split(/\bnull\b/).flatMap((x, i) => i ? [inline('null'), x] : [x]) : d;   // «null» del JSON va como código

  function fields(rows) {
    return h('div', { class: 'ad-scroll' }, h('table', { class: 'ad-table' },
      h('tr', {}, h('th', {}, t('Campo')), h('th', {}, t('¿Obligatorio?')), h('th', {}, t('Qué es'))),
      rows.map(([f, req, d]) => h('tr', {}, h('td', {}, inline(f)), h('td', {}, req), h('td', {}, prose(d))))));
  }

  function fieldsOut(rows, head = t('Respuesta')) {
    return h('div', { class: 'ad-scroll' }, h('table', { class: 'ad-table' },
      h('tr', {}, h('th', {}, head), h('th', {}, t('Qué es'))),
      rows.map(([f, d]) => h('tr', {}, h('td', {}, inline(f)), h('td', {}, prose(d))))));
  }

  function resultBox(key) {
    const r = results[key];
    if (!r) return null;
    if (r.loading) return h('p', { class: 'help' }, t('Mandando…'));
    return h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
      h('span', { class: 'ad-status ' + (r.status >= 200 && r.status < 300 ? 'ok' : 'bad') }, r.status ? t('Respuesta {status}', { status: r.status }) : t('No se pudo conectar')),
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
        h('button', { class: 'btn small', type: 'button', onclick: () => run(key, slot) }, icon('spark'), t('Probar')),
        h('span', { class: 'help', style: 'font-size:13px' }, t('Manda el pedido de verdad a este servidor.'))),
      slot,
      after);
  }

  function responseRef() {
    const rows = [
      ['bot', t('{id, name} del bot que contestó.')],
      ['sessionId', t('La conversación. Usalo en los mensajes siguientes.')],
      ['channel', t('El canal que mandaste al empezar (por defecto "api").')],
      ['started / updated', t('Cuándo empezó y cuándo fue el último movimiento (hora local, AAAA-MM-DDThh:mm:ss).')],
      ['ended', t('true si la conversación se terminó con un evento end.')],
      ['slots', t('Todo lo que el bot tiene anotado: nombre del dato → valor (null si todavía no lo sabe).')],
      ['waiting_for', t('El dato que el bot acaba de preguntar y espera en el próximo mensaje, o null.')],
      ['flow', t('El flujo en el que está la conversación, o null.')],
      ['classifications', t('Los nombres de las clasificaciones que ya tiene la conversación, en el orden en que se marcaron (cada una una sola vez). [] si ninguna.')],
      ['environment', t('El entorno en el que empezó la conversación: "production", "staging" o "draft".')],
      ['version', t('El número de versión publicada con la que contesta esta conversación (queda fija desde que empezó). null = el borrador.')],
      ['messages', t('Lista de textos que el bot responde, en orden. Puede venir vacía. Mandalos tal cual al usuario.')],
      ['buttons', t('Botones de respuesta rápida del último mensaje: [{label, value}]. [] si no hay. Mostrá label; si la persona toca uno, mandá su value (o label) como el próximo message.')],
      ['handoff', t('true si la charla la atiende una persona (desde la Bandeja): el bot no contesta, messages viene vacía y lo que escribe la persona llega por …/messages.')],
      ['language', t('El idioma de la conversación ("es", "pt"…). Sale de data.idioma en start o del primer mensaje.')],
      ['via', t('Quién resolvió el turno: null (los flujos), "knowledge" (la base de conocimiento) o "ia" (la IA local).')],
      ['sources', t('Si contestó la base de conocimiento: [{title, doc, score}] de los documentos que usó. [] si no.')],
      ['next', t('Cuántas entradas tiene el historial: usalo como after en …/messages para recibir solo lo nuevo.')],
      ['understood', t('Qué entendió del mensaje: {intent, confidence (0 a 1), entities: [{entity, value}], answer_to (el dato que respondió, si era una respuesta)}. null en start.')],
      ['ignored_data', t('Solo en start: las claves de data que no son datos del agente y no se guardaron.')],
      ['trace', t('Solo en start: los pasos que siguió el bot, para depurar. No dependas de su formato.')],
    ];
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Qué trae la respuesta de start y message')),
      fieldsOut(rows, t('Campo')),
      h('p', { class: 'help' }, t('Errores: siempre JSON con '), inline('{"error": "…"}'), t(' y un mensaje en español. '),
        inline('400'), t(' pedido mal armado (falta text, sessionId inválido, type o environment desconocido, staging sin ninguna versión), '),
        inline('401'), t(' falta la clave (con usuarios creados), '), inline('403'), t(' la clave no tiene permiso o el pedido viene de un sitio no autorizado, '),
        inline('404'), t(' no existe el bot o la conversación, '), inline('405'), t(' método no permitido en esa dirección.')));
  }

  // ---------- Exportar a Postman / Bruno / Insomnia / Hoppscotch y OpenAPI ----------
  const monthParams = () => { const d = new Date(); return { from: day(new Date(d.getFullYear(), d.getMonth(), 1)), to: day(d) }; };
  const SESSION_FILTERS = [
    ['channel', 'api', t('Solo las de ese canal, por ejemplo api o whatsapp.')],
    ['classification', () => firstClass() || '__none__', t('Solo las marcadas con esa clasificación (nombre exacto). __none__ trae las que no tienen ninguna.')],
    ['from', () => monthParams().from, t('Solo las que empezaron desde esa fecha, inclusive (AAAA-MM-DD).')],
    ['to', () => monthParams().to, t('Solo las que empezaron hasta esa fecha, inclusive (AAAA-MM-DD).')],
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
        description: t('API de Parla para el agente «{name}». JSON por HTTP. Sin usuarios creados no pide clave; con usuarios, poné tu clave en la variable apiKey (Authorization: Bearer). Solo responde en la computadora donde corre Parla (127.0.0.1).', { name: agent.name }) },
      auth: { type: 'bearer', bearer: [{ key: 'token', value: '{{apiKey}}', type: 'string' }] },
      variable: [
        { key: 'apiKey', value: '' },
        { key: 'baseUrl', value: BASE() },
        { key: 'bot', value: botSlug() || agent.id },
        { key: 'sessionId', value: sid },
      ],
      item: [
        { name: 'Bots', item: [
          req(t('Ver qué bots hay'), 'GET', ['bots'], PURPOSE.bots),
          req(t('Ver un bot'), 'GET', bot, PURPOSE.bot),
        ] },
        { name: t('Conversación'), item: [
          req(t('Empezar la conversación'), 'POST', events, PURPOSE.start, { body: { type: 'start', sessionId: '{{sessionId}}', channel: 'api', data: sampleData() } }),
          req(t('Mandar un mensaje'), 'POST', events, PURPOSE.message, { body: { type: 'message', sessionId: '{{sessionId}}', text: text() } }),
          req(t('Leer la conversación'), 'GET', session, PURPOSE.read),
          req(t('Terminar la conversación'), 'POST', events, PURPOSE.end, { body: { type: 'end', sessionId: '{{sessionId}}' } }),
          req(t('Recibir mensajes nuevos'), 'GET', [...session, 'messages'], PURPOSE.messages,
            { query: [{ key: 'after', value: '0', description: t('Desde qué entrada del historial (el next de la respuesta anterior).') }] }),
          req(t('Mandar un mensaje de voz'), 'POST', [...bot, 'audio'], PURPOSE.audio,
            { body: { sessionId: '{{sessionId}}', audio: t('<la grabación en base64>'), mime: 'audio/webm', speak: true } }),
        ] },
        { name: t('Conversaciones'), item: [
          req(t('Listar conversaciones'), 'GET', [...bot, 'sessions'], PURPOSE.list,
            { query: SESSION_FILTERS.map(([key, v, description]) => ({ key, value: val(v), description, disabled: true })) }),
          req(t('Ver una conversación'), 'GET', session, PURPOSE.read),
          req(t('Borrar una conversación'), 'DELETE', session, PURPOSE.del),
        ] },
        { name: t('Reportes'), item: [
          req(t('Reporte de clasificaciones'), 'GET', [...bot, 'report'], PURPOSE.report, { query: [
            { key: 'from', value: from, description: t('Desde esa fecha, inclusive (AAAA-MM-DD).') },
            { key: 'to', value: to, description: t('Hasta esa fecha, inclusive (AAAA-MM-DD).') },
            { key: 'channel', value: 'api', description: t('Solo las de ese canal.'), disabled: true },
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
      bot: param('bot', 'path', t('El id del bot, su nombre exacto o su nombre simplificado (slug).'), botSlug() || agent.id),
      sessionId: param('sessionId', 'path', t('La conversación.'), sid, { pattern: SID_RE.source }),
    };
    const op = (summary, tag, description, responses, extra) => ({ summary, tags: [tag], description, responses, ...extra });
    const bot404 = { 404: err(t('No hay un bot con ese nombre o id (o el nombre es ambiguo).')) };
    const session = obj({
      bot: obj({ id: str(), name: str() }),
      sessionId: str(), channel: str(), started: str(t('AAAA-MM-DDThh:mm:ss, hora local.')), updated: str(), ended: { type: 'boolean' },
      slots: { type: 'object', additionalProperties: {}, description: t('Nombre del dato → valor (null si todavía no se sabe).') },
      waiting_for: nstr(t('El dato que el bot espera en el próximo mensaje.')),
      flow: nstr(t('El flujo en el que está la conversación.')),
      classifications: { type: 'array', items: str() },
      environment: str('', { enum: ['production', 'staging', 'draft'] }),
      version: { type: 'integer', nullable: true, description: t('Versión publicada con la que contesta. null = el borrador.') },
      language: nstr(t('El idioma de la conversación ("es", "pt"…).')),
      next: { type: 'integer', description: t('Cantidad de entradas del historial: el after para …/messages.') },
    });
    const button = obj({ label: str(t('Lo que se muestra.')), value: str(t('Lo que se manda como message si lo tocan.')) }, ['label', 'value']);
    const slots = Object.fromEntries(agent.slots.map((s) => [s.name, null]));
    const startData = sampleData();
    return {
      openapi: '3.0.3',
      info: { title: 'Parla · ' + agent.name, version: '1', description: t('API pública de Parla. JSON por HTTP. Sin usuarios creados no pide clave; con usuarios, Authorization: Bearer <clave> (Usuarios → Claves de API). Con el widget web prendido, events, audio y los messages del widget quedan abiertos y aceptan CORS de sus orígenes. Solo responde en 127.0.0.1: para exponerla poné adelante un proxy con HTTPS.') },
      servers: [{ url: BASE() }],
      security: [{}, { bearerAuth: [] }],
      tags: [{ name: 'Bots' }, { name: t('Conversación') }, { name: t('Conversaciones') }, { name: t('Reportes') }],
      paths: {
        '/bots': { get: op(t('Ver qué bots hay'), 'Bots', PURPOSE.bots, { 200: ok(t('Los bots.'), obj({ bots: { type: 'array', items: ref('Bot') } }, ['bots'])) }) },
        '/bots/{bot}': { parameters: [P.bot], get: op(t('Ver un bot'), 'Bots', PURPOSE.bot, { 200: ok(t('El bot.'), ref('Bot')), ...bot404 }) },
        '/bots/{bot}/events': { parameters: [P.bot], post: op(t('Mandar un evento: start (u online), message o end'), t('Conversación'),
          [PURPOSE.start, PURPOSE.message, PURPOSE.end].join('\n\n'), {
            200: ok(t('start y message devuelven la conversación con lo que contestó el bot; end devuelve {sessionId, ended}.'),
              { oneOf: [ref('EventResponse'), ref('EndResponse')] }, {
                start: { value: { bot: { id: agent.id, name: agent.name }, sessionId: sid, channel: 'api', started: '2026-01-01T10:00:00', updated: '2026-01-01T10:00:00',
                  ended: false, slots: { ...slots, ...Object.fromEntries(Object.entries(startData).filter(([k]) => k in slots)) }, waiting_for: null, flow: null,
                  classifications: [], environment: 'production', version: null, messages: [], understood: null, ignored_data: [], trace: [] } },
                end: { value: { sessionId: sid, ended: true } },
              }),
            400: err(t('Pedido mal armado: falta text, sessionId inválido, type o environment desconocido, staging sin versión, data no es un objeto.')),
            401: err(t('Falta la clave (Parla tiene usuarios y el widget de este bot está apagado).')),
            404: err(t('No existe el bot, o (en end) la conversación.')),
          }, { requestBody: { required: true, ...json(ref('EventRequest'), {
            start: { summary: t('Empezar con datos precargados'), value: { type: 'start', sessionId: sid, channel: 'api', data: startData } },
            message: { summary: t('Mandar lo que escribió la persona'), value: { type: 'message', sessionId: sid, text: text() } },
            end: { summary: t('Terminar la conversación'), value: { type: 'end', sessionId: sid } },
          }) } }) },
        '/bots/{bot}/audio': { parameters: [P.bot], post: op(t('Mandar un mensaje de voz'), t('Conversación'), PURPOSE.audio, {
          200: ok(t('Lo mismo que message, más heard y (con speak) audio.'), ref('AudioResponse')),
          400: err(t('Falta audio, no es base64, no hay modelo de voz o no se entendió nada.')), 401: err(t('Falta la clave.')), 404: err(t('No existe el bot.')),
        }, { requestBody: { required: true, ...json(ref('AudioRequest')) } }) },
        '/bots/{bot}/sessions/{sessionId}/messages': { parameters: [P.bot, P.sessionId], get: op(t('Recibir mensajes nuevos'), t('Conversación'), PURPOSE.messages, {
          200: ok(t('Lo nuevo del historial.'), ref('Messages')), 400: err(t('after no es un número.')), 404: err(t('No existe el bot o la conversación.')),
        }, { parameters: [param('after', 'query', t('Desde qué entrada del historial (0 = todo): el next de la respuesta anterior.'), '0', { pattern: '^\\d+$' })] }),
          post: op(t('Contact center: escribirle al cliente'), t('Conversación'), PURPOSE.reply, {
            200: ok(t('La conversación, con delivered.'), ref('Session')), 409: err(t('Llamada, conversación terminada o WhatsApp fuera de las 24 h.')), 502: err(t('El proveedor lo rechazó.')),
          }, { requestBody: { required: true, ...json(obj({ text: str(), from_name: str() }, ['text'])) } }) },
        '/bots/{bot}/sessions': { parameters: [P.bot], get: op(t('Listar conversaciones'), t('Conversaciones'), PURPOSE.list, {
          200: ok(t('Las conversaciones, la más reciente primero.'), obj({ sessions: { type: 'array', items: ref('SessionSummary') } }, ['sessions'])), ...bot404,
        }, { parameters: SESSION_FILTERS.map(([key, v, description]) => param(key, 'query', description, val(v), key === 'from' || key === 'to' ? { format: 'date' } : {})) }) },
        '/bots/{bot}/sessions/{sessionId}': { parameters: [P.bot, P.sessionId],
          get: op(t('Leer la conversación'), t('Conversaciones'), PURPOSE.read, { 200: ok(t('La conversación con su historial.'), ref('SessionDetail')), 404: err(t('No existe el bot o la conversación.')) }),
          delete: op(t('Borrar una conversación'), t('Conversaciones'), PURPOSE.del, {
            200: ok(t('Borrada.'), obj({ sessionId: str(), deleted: { type: 'boolean', enum: [true] } }, ['sessionId', 'deleted'])), 404: err(t('No existe el bot o la conversación.')) }) },
        '/bots/{bot}/sessions/{sessionId}/handoff': { parameters: [P.bot, P.sessionId], post: op(t('Contact center: tomar, devolver o cerrar'), t('Conversación'), PURPOSE.handoff, {
          200: ok(t('La conversación, sin history.'), ref('Session')), 400: err(t('action o flow desconocido.')), 404: err(t('No existe el bot o la conversación.')), 409: err(t('La conversación ya terminó.')),
        }, { requestBody: { required: true, ...json(obj({ action: str('', { enum: ['accept', 'release', 'close'] }), agent_name: str(), data: { type: 'object', additionalProperties: {} },
          flow: str(), resolution: str() }, ['action'])) } }),
          },
        '/bots/{bot}/lookup': { parameters: [P.bot], get: op(t('Contact center: buscar la conversación de un cliente'), t('Conversación'), PURPOSE.lookup, {
          200: ok(t('La conversación, como en el webhook.'), { type: 'object' }), 404: err(t('No hay una conversación abierta con esa persona.')),
        }, { parameters: [param('phone', 'query', t('El teléfono, con código de país.'), '5491122334455'), param('chat', 'query', t('El chat id de Telegram.'), ''), param('sid', 'query', 'sessionId', '')] }) },
        '/bots/{bot}/costs': { parameters: [P.bot], get: op(t('Costos'), t('Reportes'), PURPOSE.costs, { 200: ok(t('Los costos.'), { type: 'object' }), ...bot404 }, {
          parameters: [param('from', 'query', t('Desde esa fecha, inclusive (AAAA-MM-DD).'), monthParams().from, { format: 'date' }),
            param('to', 'query', t('Hasta esa fecha, inclusive (AAAA-MM-DD).'), monthParams().to, { format: 'date' }),
            param('group', 'query', t('Además, groups agrupado por day, channel o provider.'), 'day'), param('campaign', 'query', t('Solo las conversaciones de esa campaña.'), '')] }) },
        '/bots/{bot}/report': { parameters: [P.bot], get: op(t('Reporte de clasificaciones'), t('Reportes'), PURPOSE.report, { 200: ok(t('El reporte.'), ref('Report')), ...bot404 }, {
          parameters: [param('from', 'query', t('Desde esa fecha, inclusive (AAAA-MM-DD).'), monthParams().from, { format: 'date' }),
            param('to', 'query', t('Hasta esa fecha, inclusive (AAAA-MM-DD).'), monthParams().to, { format: 'date' }), param('channel', 'query', t('Solo las de ese canal.'), 'api')] }) },
      },
      components: { securitySchemes: { bearerAuth: { type: 'http', scheme: 'bearer', description: t('Solo si Parla tiene usuarios: una clave de Usuarios → Claves de API.') } }, schemas: {
        Error: obj({ error: str(t('Qué pasó, en español.')) }, ['error']),
        Bot: obj({ id: str(), name: str(), slug: str(t('Nombre simplificado para la URL.')), online: { type: 'boolean' },
          trained_at: nstr(t('Cuándo se entrenó el borrador por última vez.')), intents: { type: 'array', items: str() },
          environments: obj({ production: { type: 'integer', nullable: true }, staging: { type: 'integer', nullable: true } }, null,
            { description: t('Qué versión tiene cada entorno. null = ninguna (production contesta con el borrador; staging da 400).') }) },
          null, { example: { id: agent.id, name: agent.name, slug: botSlug(), online: true, trained_at: null, intents: agent.intents.map((i) => i.name),
            environments: { production: agent.environments?.production ?? null, staging: agent.environments?.staging ?? null } } }),
        EventRequest: obj({
          type: str(t('start (u online) para empezar, message para un mensaje (se puede omitir si mandás text), end para terminar.'), { enum: ['start', 'online', 'message', 'end'] }),
          sessionId: str(t('La conversación. Si no lo mandás en start o message, se crea uno. Obligatorio en end.'), { pattern: SID_RE.source }),
          text: str(t('Solo en message: lo que escribió la persona (hasta 4000 caracteres).')),
          data: { type: 'object', additionalProperties: {}, description: agent.slots.length
            ? t('Solo en start: datos que ya conocés. Se guardan las claves que se llaman igual que un dato del agente ({slots}); las demás vuelven en ignored_data.', { slots: agent.slots.map((s) => s.name).join(', ') })
            : t('Solo en start: datos que ya conocés. Se guardan las claves que se llaman igual que un dato del agente; las demás vuelven en ignored_data.') },
          channel: str(t('De dónde viene: whatsapp, web, ivr… Por defecto api.')),
          environment: str(t('Qué versión contesta. Solo cuenta al empezar la conversación.'), { enum: ['production', 'staging', 'draft'], default: 'production' }),
        }),
        Understood: obj({ intent: nstr(), confidence: { type: 'number', minimum: 0, maximum: 1 },
          entities: { type: 'array', items: obj({ entity: str(), value: {} }) }, answer_to: nstr(t('El dato que respondió, si era una respuesta.')) }),
        Session: session,
        EventResponse: { allOf: [ref('Session'), obj({
          messages: { type: 'array', items: str(), description: t('Lo que responde el bot, en orden. Puede venir vacía.') },
          understood: { allOf: [ref('Understood')], nullable: true, description: t('null en start.') },
          ignored_data: { type: 'array', items: str(), description: t('Solo en start: claves de data que no se guardaron.') },
          trace: { type: 'array', items: str(), description: t('Solo en start: pasos que siguió el bot, para depurar. No dependas de su formato.') },
          buttons: { type: 'array', items: button, description: t('Botones del último mensaje. [] si no hay.') },
          handoff: { type: 'boolean', description: t('true si la charla la atiende una persona: el bot no contesta.') },
          via: nstr(t('null (flujos), "knowledge" (base de conocimiento) o "ia" (IA local).')),
          sources: { type: 'array', items: obj({ title: str(), doc: str(), score: { type: 'number' } }), description: t('Documentos de la base de conocimiento que usó.') },
        }, ['messages', 'understood'])] },
        AudioRequest: obj({ audio: str(t('La grabación en base64 (o data:audio/...;base64,...).')), sessionId: str('', { pattern: SID_RE.source }),
          mime: str('audio/webm, audio/ogg, audio/wav…', { default: 'audio/webm' }), speak: { type: 'boolean', default: false, description: t('Devolver la respuesta también en audio.') },
          channel: str(), environment: str('', { enum: ['production', 'staging', 'draft'] }) }, ['audio']),
        AudioResponse: { allOf: [ref('EventResponse'), obj({ heard: str(t('Lo que entendió del audio.')), audio: str(t('Solo con speak: la respuesta en WAV, base64.')) }, ['heard'])] },
        Messages: obj({ sessionId: str(), messages: { type: 'array', items: ref('HistoryEntry') }, next: { type: 'integer' },
          handoff: { type: 'boolean' }, ended: { type: 'boolean' } }, ['sessionId', 'messages', 'next']),
        EndResponse: obj({ sessionId: str(), ended: { type: 'boolean', enum: [true] } }, ['sessionId', 'ended']),
        HistoryEntry: obj({ from: str(t('"human" = una persona desde la Bandeja.'), { enum: ['event', 'user', 'bot', 'human'] }), text: str(), at: str(),
          by: str(t('Solo human: quién escribió.')), buttons: { type: 'array', items: button, description: t('Solo bot: los botones de ese mensaje.') },
          fallback: { type: 'boolean', description: t('Solo user: el bot no lo entendió.') }, via: nstr(t('Solo user: quién resolvió ese turno.')),
          intent: nstr(t('Solo user.')), confidence: { type: 'number', description: t('Solo user.') },
          entities: { type: 'array', items: obj({ entity: str(), value: {} }), description: t('Solo user.') }, answer_to: nstr(t('Solo user.')),
          data: { type: 'object', additionalProperties: {}, description: t('Solo en el event de inicio: los datos precargados que se guardaron.') },
          classification: str(t('Solo en el event que marcó una clasificación.')) }, ['from', 'text', 'at']),
        SessionDetail: { allOf: [ref('Session'), obj({ history: { type: 'array', items: ref('HistoryEntry') },
          handoff: obj({ active: { type: 'boolean' }, since: str(), reason: nstr(), by: nstr() }, null, { nullable: true, description: t('Si alguna vez pasó a una persona: desde cuándo, por qué y quién.') }) }, ['history'])] },
        SessionSummary: obj({ sessionId: str(), channel: str(), started: str(), updated: str(), ended: { type: 'boolean' },
          messages: { type: 'integer', description: t('Cantidad de entradas del historial.') }, last_message: nstr(), first_message: nstr(),
          data: { type: 'object', additionalProperties: {}, nullable: true, description: t('Datos precargados al empezar.') },
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

  function exportSection() {
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Llevar a tu herramienta de pruebas')),
      h('p', { class: 'help' }, t('Bajá la API de «{name}» lista para Postman, Bruno, Insomnia, Hoppscotch o cualquier herramienta que lea OpenAPI. Usa el sessionId y los datos de esta página.', { name: agent.name })),
      h('div', { class: 'row', style: 'flex-wrap:wrap' },
        h('button', { class: 'btn small', type: 'button', style: 'white-space:normal', onclick: () => download(fileBase() + '.postman_collection.json', postmanCollection()) }, t('Exportar para Postman / Bruno / Insomnia')),
        h('button', { class: 'btn small quiet', type: 'button', onclick: () => download(fileBase() + '.openapi.json', openApi()) }, t('Exportar OpenAPI'))),
      h('p', { class: 'help', style: 'font-size:13px' }, t('Para importarla: en Postman, Import → elegí el archivo; en Bruno, Import Collection → Postman Collection u OpenAPI; en Insomnia y Hoppscotch, Import → el archivo.')));
  }

  function accessSection() {
    const w = agent.widget || {};
    const origins = (w.origins || []).filter(Boolean);
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Claves y chat web')),
      h('p', { class: 'help' }, t('Mientras no haya usuarios creados, la API no pide clave. '), h('strong', {}, t('Con usuarios')), t(', cada pedido tiene que traer '),
        inline('Authorization: Bearer <clave>'), t('. La clave se crea en Usuarios → tu usuario → «Claves de API» y tiene los permisos de ese usuario: '),
        inline('owner'), t(' y '), inline('editor'), t(' todo; '), inline('analyst'), t(' solo leer (GET); '), inline('agent'), t(' solo conversaciones y Bandeja. Sin clave: 401.'),
        window.authEnabled ? t(' Este Parla tiene usuarios: los ejemplos ya traen el encabezado, cambiá {key} por la tuya.', { key: t('TU_CLAVE') }) : ''),
      h('p', { class: 'help' }, t('Excepción: si el bot tiene el '), h('strong', {}, t('widget web')), t(' prendido, '), inline('POST …/events'), t(' y '), inline('POST …/audio'),
        t(' quedan abiertos (es el chat público de tu web), y '), inline('GET …/sessions/{sessionId}/messages'), t(' también, solo para conversaciones del widget (canal "web").')),
      h('p', { class: 'help' }, t('Un navegador solo puede llamar a la API desde otra web (CORS) en '), inline('…/events'), ', ', inline('…/audio'), t(' y '), inline('…/messages'),
        t(', y solo si el widget está prendido y ese sitio está en sus orígenes. Cualquier otro pedido que venga de otra web se rechaza con 403. '),
        t('Desde un servidor (WhatsApp, IVR, CRM) no hay CORS: usá la clave. '),
        w.enabled ? [t('El widget de «{name}» está prendido para: ', { name: agent.name }), origins.length ? origins.map((o, i) => [i ? ', ' : '', inline(o)]) : t('ningún sitio todavía'), '.']
          : t('El widget de «{name}» está apagado (se prende en «Widget web»).', { name: agent.name })));
  }

  function versionsSection() {
    const env = agent.environments || {};
    const where = (n) => n == null ? t('ninguna') : 'v' + n;
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Versiones y paso a producción')),
      h('p', { class: 'help' }, t('Lo que editás en Parla es el '), h('strong', {}, t('borrador')), t('. Al publicar, el borrador se congela como una versión numerada (v1, v2…) que ya no cambia. '),
        t('Hay dos entornos: '), h('strong', {}, t('Producción')), t(', la que usan tus integraciones, y '), h('strong', {}, t('Pruebas')), ' (', inline('staging'), t('), para que el cliente la pruebe antes. '),
        t('Cada entorno apunta a una versión y eso se maneja en la sección «Versiones».')),
      h('p', { class: 'help' }, t('Las integraciones normalmente no mandan '), inline('environment'), t(' (o mandan '), inline('"production"'), t('). Para que el cliente pruebe antes de salir, usá '), inline('"staging"'),
        t(' desde un número o chat de pruebas. '), inline('"draft"'), t(' sirve para ver cambios sin publicar.')),
      h('p', { class: 'help' }, t('Cada conversación queda '), h('strong', {}, t('atada a la versión con la que empezó')), t(': si publicás o cambiás la versión de Producción, las conversaciones en curso siguen igual y las nuevas usan la nueva. '),
        t('Si una versión nueva anda mal, volvé a poner la anterior en Producción (rollback) desde «Versiones»: las conversaciones nuevas vuelven a la anterior al instante. '),
        t('Las respuestas traen '), inline('environment'), t(' y '), inline('version'), t(' para que sepas con cuál contestó.')),
      h('p', { class: 'help' }, t('Ahora «{name}» tiene en Producción: ', { name: agent.name }), h('strong', {}, env.production == null ? t('ninguna (contesta el borrador)') : where(env.production)),
        t(' · en Pruebas: '), h('strong', {}, env.staging == null ? t('ninguna (staging da 400)') : where(env.staging)), '.'));
  }

  function pushSection() {
    const ws = 'ws://' + location.host + '/api/v1/bots/' + ref() + '/ws';
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Recibir en vivo: WebSocket y SSE')),
      h('p', { class: 'help' }, t('El mismo puerto y la misma autenticación que las rutas de arriba. Preguntar cada pocos segundos sigue andando.')),
      h('div', { class: 'ad-ep' }, h('span', { class: 'ad-m GET' }, 'GET'), h('code', {}, '/bots/{bot}/ws')),
      h('p', { class: 'help' }, t('WebSocket: mandás los mismos cuerpos que POST …/events, con un id opcional que vuelve en reply. Llegan delta (la IA mientras escribe), reply y messages (lo que escribe una persona de la Bandeja). follow escucha sin mandar.')),
      codeBox(() => ws + '\n→ {"id": 1, "type": "message", "sessionId": "' + sid + '", "text": "' + text() + '"}\n← {"type": "delta", "stream": 7, "text": "…"}\n← {"type": "reply", "id": 1, "status": 200, "body": {…}}\n→ {"type": "follow", "sessionId": "' + sid + '", "after": 12}'),
      h('div', { class: 'ad-ep' }, h('span', { class: 'ad-m GET' }, 'GET'), h('code', {}, '/bots/{bot}/sessions/{sessionId}/stream?after=N')),
      h('p', { class: 'help' }, t('SSE (text/event-stream): eventos messages (el mismo cuerpo que GET …/messages), delta y replace (el texto final si cambió lo que se mandó en vivo). Para la Bandeja y las campañas: /api/agents/{id}/inbox/stream y /api/agents/{id}/campaigns/stream.')),
      codeBox(() => 'curl -N ' + q(BASE() + '/bots/' + ref() + '/sessions/' + encodeURIComponent(sid) + '/stream?after=0')));
  }

  function voiceSection() {
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Voz en tiempo real: WebSocket')),
      h('p', { class: 'help' }, t('Misma autenticación y reglas de Origin que /ws (el widget público incluido). Los mensajes binarios son audio PCM16 little-endian mono a 16 kHz, de ida y de vuelta (20 a 100 ms por mensaje); los de texto son JSON. La conversación tiene que existir: empezala con POST …/events.')),
      h('div', { class: 'ad-ep' }, h('span', { class: 'ad-m GET' }, 'GET'), h('code', {}, '/bots/{bot}/voice/ws')),
      codeBox(() => '← {"type": "ready", "rate": 16000}\n→ {"type": "start", "sessionId": "' + sid + '", "language": "es", "channel": "web", "replay": true}\n→ <PCM16>   ← <PCM16>\n← {"type": "partial", "text": "quiero una"}\n← {"type": "transcript", "text": "quiero una muzza"}\n← {"type": "speaking", "latency_ms": 412}\n← {"type": "reply", "status": 200, "body": {…}}\n← {"type": "clear"}\n→ {"type": "stop"}'),
      h('p', { class: 'help' }, t('partial solo con Deepgram. transcript cierra el turno de la persona y corre como un message. clear: la persona interrumpió, cortá lo que suena y lo que está en cola.')),
      h('p', { class: 'help' }, t('Teléfono: '), inline('/bots/{bot}/phone/twilio/stream'), t(' (Twilio Media Streams, μ-law 8 kHz) y '), inline('/bots/{bot}/phone/jambonz/stream?t=…'),
        t(' (jambonz listen, L16 8 kHz) usan el protocolo de cada proveedor; Parla los arma solo con el modo «stream» de Canales → Teléfono.')));
  }

  function webhookSection() {
    return h('section', { class: 'panel ad-panel' },
      h('h2', {}, t('Webhooks que manda Parla')),
      h('p', { class: 'help' }, t('Se configuran en Canales → Derivación. Cada evento es un POST con el contexto de la conversación (el mismo cuerpo que lookup, más id y type), firmado. Si falla, se reintenta con espera creciente durante ~24 h; el que recibe deduplica por id.')),
      fieldsOut([
        ['handoff.requested', t('La charla pasó a una persona. Trae handoff.summary: el resumen de la IA si llega a tiempo, si no el fijo.')],
        ['handoff.released', t('Volvió al bot.')], ['conversation.started / conversation.ended', t('Empezó o terminó una conversación.')],
        ['message.user / message.bot', t('Cada mensaje de la persona y del bot.')], ['csat.received', t('Una respuesta de la encuesta de satisfacción.')],
        ['campaign.finished', t('Terminó una campaña.')],
      ], t('Evento')),
      h('p', { class: 'help' }, t('Firma: el encabezado Parla-Signature trae t (segundos) y v1 = HMAC-SHA256 con tu clave de «t.cuerpo». Compará con compare_digest y rechazá un t de hace más de 5 minutos.')),
      codeBox(() => 'Parla-Signature: t=1767225600,v1=5f2b…\n\nexpected = hmac_sha256(secret, t + "." + raw_body)\nok = compare_digest(expected, v1) and abs(now - t) < 300'));
  }

  window.apiDocsView = () => {
    refreshers.length = 0;
    const sf = startFlow();
    const data = sampleData();
    const slotNames = agent.slots.map((s) => s.name);

    const sidErr = h('span', { class: 'ad-err' });
    const sidInput = h('input', { value: sid, 'aria-label': t('sessionId de los ejemplos'), spellcheck: 'false', autocomplete: 'off',
      oninput: (e) => {
        const v = e.target.value.trim();
        const ok = SID_RE.test(v);
        e.target.setAttribute('aria-invalid', ok ? 'false' : 'true');
        sidErr.textContent = ok ? '' : t('De 1 a 100 letras sin tildes, números o . @ + - _ (sin espacios, sin empezar con punto).');
        if (ok) { sid = v; refreshers.forEach((f) => f()); }
      } });

    const msgInput = h('input', { value: text(), 'aria-label': t('Texto del mensaje'), style: 'width:100%',
      oninput: (e) => { msgText = e.target.value; refreshers.forEach((f) => f()); } });

    return h('div', { class: 'page' },
      h('h1', {}, 'API'),
      h('p', { class: 'help' }, t('Con la API, otro programa puede charlar con este agente igual que en la prueba: WhatsApp, un chat en tu web, un conmutador telefónico (IVR) o un CRM. '),
        t('Le mandás lo que escribió la persona y te devuelve lo que contesta el bot, más los datos que fue anotando. Todo es JSON por HTTP, sin claves.')),
      h('p', { class: 'help' }, t('Con las clasificaciones (el paso «Clasificar la conversación» de un flujo) cada conversación queda marcada con lo que pasó, y con eso armás reportes: por ejemplo, un bot de turnos médicos que marca «Turno agendado» o «Cancelación» y te dice cuántos hubo por día.')),

      h('section', { class: 'panel ad-panel' },
        h('h2', {}, t('Dirección')),
        h('p', { class: 'help' }, t('Todas las direcciones empiezan con:')),
        codeBox(() => BASE(), true),
        h('p', { class: 'help' }, t('Este agente, «{name}», se puede nombrar en la URL por su nombre simplificado ', { name: agent.name }), inline(botSlug() || '—'),
          t(', por su id '), inline(agent.id), t(' o por su nombre exacto. Si hay dos agentes con el mismo nombre, usá el id.')),
        codeBox(() => BASE() + '/bots/' + ref(), true),
        h('div', { class: 'notice warn' }, h('span', {},
          h('strong', {}, t('Solo funciona en esta computadora. ')),
          t('Parla escucha únicamente en 127.0.0.1, así que otros equipos o internet no lo ven. La API no pide clave: si querés que WhatsApp u otro servicio de afuera llegue, '),
          t('poné adelante un proxy (por ejemplo nginx o Caddy) que pida autenticación y use HTTPS. Nunca la expongas tal cual.'))),
        h('div', { class: 'notice' }, h('span', {},
          t('La API contesta con la '), h('strong', {}, t('versión publicada en Producción')), t(' (mirá «Versiones y paso a producción» más abajo). Mientras no publiques ninguna, contesta con el borrador tal como está ahora. '),
          t('Las conversaciones se guardan en disco y siguen ahí aunque reinicies Parla.')))),

      exportSection(),

      accessSection(),

      versionsSection(),

      h('section', { class: 'panel ad-panel ad-sid' },
        h('h2', {}, t('Tu sessionId')),
        h('p', { class: 'help' }, t('Cada conversación tiene un sessionId que elegís vos. Lo ideal es usar el id de quien escribe, por ejemplo '), inline('wa-5491122334455'),
          t(' para WhatsApp o el número de llamada en un IVR. Todos los ejemplos de abajo usan este:')),
        sidInput, sidErr),

      h('h2', { style: 'font:700 22px var(--display);margin-top:8px' }, t('Una conversación de ejemplo')),
      h('p', { class: 'help' }, t('Apretá «Probar» en orden y vas a tener una conversación de verdad con «{name}». Después la podés ver en Conversaciones.', { name: agent.name })),

      endpoint('bots', { step: t('Paso 1'), title: t('Ver qué bots hay'), purpose: PURPOSE.bots }),

      endpoint('start', {
        step: t('Paso 2'), title: t('Empezar la conversación con datos precargados'),
        purpose: PURPOSE.start,
        rows: [
          ['type', t('Sí'), t('"start" (o "online").')],
          ['sessionId', t('No'), t('Si no lo mandás, se crea uno y viene en la respuesta.')],
          ['data', t('No'), slotNames.length ? [t('Datos que ya conocés. Cada clave que se llama igual que un dato del agente se guarda ahí: '), slotNames.map((n, i) => [i ? ', ' : '', inline(n)]), t('. Las demás vuelven en ignored_data.')]
            : t('Datos que ya conocés. Se guardan solo las claves que se llaman igual que un dato del agente (este todavía no tiene datos); las demás vuelven en ignored_data.')],
          ['channel', t('No'), t('De dónde viene: "whatsapp", "web", "ivr"… Sirve para filtrar después. Por defecto "api".')],
          ['environment', t('No'), [t('Qué versión del bot contesta: '), inline('"production"'), t(' (por defecto, la que ven tus usuarios), '), inline('"staging"'), t(' (Pruebas, para que el cliente la pruebe antes de pasarla a producción) o '), inline('"draft"'), t(' (el borrador, con los cambios sin publicar). Solo cuenta al empezar la conversación: después sigue en la misma.')]],
        ],
        extra: h('div', { class: 'notice' }, h('span', {}, sf
          ? t('Este agente tiene el flujo «{flow}» que corre apenas empieza la conversación, así que la respuesta ya puede traer mensajes en messages (por ejemplo, saludar por el nombre que vino en data).', { flow: sf.name })
          : [t('Este agente no tiene un flujo de inicio, así que start solo guarda los datos y messages vuelve vacía. Si querés que salude o busque algo apenas empieza (por ejemplo, un IVR que pasa el DNI y el bot consulta el nombre), '),
            t('creá un flujo en Flujos y en «Lo dispara» elegí «Al empezar la conversación».')])),
      }),

      endpoint('message', {
        step: t('Paso 3'), title: t('Mandar lo que escribió la persona'),
        purpose: PURPOSE.message,
        rows: [
          ['text', t('Sí'), t('Lo que escribió o dijo la persona (hasta 4000 caracteres).')],
          ['sessionId', t('No'), t('La conversación. Si no lo mandás, se crea una nueva y viene en la respuesta. Si la conversación estaba terminada, sigue con la memoria en blanco.')],
          ['type', t('No'), t('"message". Se puede omitir si mandás text.')],
          ['media', t('No'), [t('Lo que mandó la persona por WhatsApp o Telegram (lo arma Parla): '), inline('{type, url, mime, name, size, caption, transcript, description, lat, lng}'),
            t('. En los pasos: '), inline('{{ media.url }}'), ', ', inline('{{ media.type }}'), t('… url solo puede ser un /files/ de este bot.')]],
          ['environment', t('No'), [t('Qué versión del bot contesta: '), inline('"production"'), t(' (por defecto, la que ven tus usuarios), '), inline('"staging"'), t(' (Pruebas, para que el cliente la pruebe antes de pasarla a producción) o '), inline('"draft"'), t(' (el borrador, con los cambios sin publicar). Solo cuenta al empezar la conversación: después sigue en la misma.')]],
        ],
        extra: h('label', { class: 'f' }, t('Texto del mensaje (cambialo y volvé a probar para seguir la charla)'), msgInput),
      }),

      endpoint('read', {
        step: t('Paso 4'), title: t('Leer la conversación'),
        purpose: PURPOSE.read,
      }),

      endpoint('end', {
        step: t('Paso 5'), title: t('Terminar la conversación'),
        purpose: PURPOSE.end,
        rows: [['type', t('Sí'), t('"end".')], ['sessionId', t('Sí'), t('La conversación a terminar.')]],
      }),

      h('h2', { style: 'font:700 22px var(--display);margin-top:8px' }, t('Otras direcciones')),

      endpoint('bot', { title: t('Ver un bot'), purpose: PURPOSE.bot,
        after: fieldsOut([
          ['id / name / slug', t('El id, el nombre y el nombre simplificado para la URL.')],
          ['trained_at', t('Cuándo se entrenó el borrador por última vez.')],
          ['intents', t('Los nombres de las intenciones del borrador.')],
          ['environments', [t('Qué versión tiene cada entorno: '), inline('{"production": 3, "staging": 4}'),
            ...prose(t('. null = ninguna (production contesta con el borrador; staging da 400).'))]],
        ]) }),
      endpoint('list', { title: t('Listar conversaciones'),
        purpose: PURPOSE.list,
        rows: [
          ['channel', t('No'), t('Solo las de ese canal, por ejemplo api o whatsapp.')],
          ['classification', t('No'), [t('Solo las marcadas con esa clasificación (el nombre exacto, codificado para URL). '), inline('__none__'), t(' trae las que no tienen ninguna.')]],
          ['from / to', t('No'), t('Solo las que empezaron entre esas fechas, inclusive (AAAA-MM-DD).')],
        ],
        after: h('div', { style: 'display:flex;flex-direction:column;gap:6px;min-width:0' },
          h('p', { class: 'help' }, firstClass() ? t('Por ejemplo, las de este mes clasificadas como «{name}»:', { name: firstClass() })
            : [t('Por ejemplo, las de este mes con una clasificación (este agente todavía no tiene clasificaciones: cambiá «Turno agendado» por el nombre de la que crees):')]),
          codeBox(() => curl({ method: 'GET', path: '/bots/' + ref() + '/sessions?classification=' + encodeURIComponent(firstClass() || t('Turno agendado')) + '&' + monthRange() }))) }),
      endpoint('report', { title: t('Reporte de clasificaciones'),
        purpose: PURPOSE.report,
        rows: [
          ['from / to', t('No'), t('Solo las conversaciones que empezaron entre esas fechas, inclusive (AAAA-MM-DD). El ejemplo usa este mes.')],
          ['channel', t('No'), t('Solo las de ese canal.')],
        ],
        after: fieldsOut([
          ['sessions', t('Cuántas conversaciones entraron en el reporte.')],
          ['unclassified', t('Cuántas no tienen ninguna clasificación.')],
          ['classifications', t('Una por clasificación: {name, count, configured}. count cuenta conversaciones (una conversación con dos clasificaciones suma en las dos). configured es false si el nombre se usó en conversaciones viejas pero ya no existe en el agente.')],
          ['by_day', t('Una por día con conversaciones, de la más vieja a la más nueva: {date, sessions, unclassified, counts: {nombre: cantidad}}. Solo trae en counts las clasificaciones que tuvieron alguna ese día.')],
          ['bot / from / to / channel', t('El bot y los filtros que se aplicaron (null si no mandaste).')],
        ]) }),
      endpoint('del', { title: t('Borrar una conversación'), purpose: PURPOSE.del }),
      endpoint('messages', { title: t('Recibir mensajes nuevos (persona de la Bandeja)'), purpose: PURPOSE.messages,
        rows: [['after', t('No'), t('Desde qué entrada del historial (0 = todo). Mandá el next de la respuesta anterior.')]],
        after: fieldsOut([
          ['messages', [t('Las entradas nuevas del historial: {from, text, at, …}. from es "user", "bot", "event" o '), inline('"human"'), t(' (una persona de la Bandeja; trae by con su nombre). Las del bot pueden traer buttons.')]],
          ['next', t('El after para el próximo pedido.')],
          ['handoff', t('true mientras la charla la atiende una persona.')],
          ['ended', t('true si la conversación se terminó.')],
        ]) }),
      endpoint('outbound', { title: t('Escribirle primero a alguien'), purpose: PURPOSE.outbound, noTry: true,
        rows: [
          ['channel', t('No'), t('"whatsapp" (por defecto), "telegram" o "phone".')],
          ['to', t('Sí'), t('El número con código de país (+5491122334455) o el chat id de Telegram.')],
          ['template', t('En WhatsApp'), t('La plantilla aprobada: su nombre o {name, language, params}. Se completa con el catálogo de Canales.')],
          ['flow', t('No'), t('El flujo que corre: enseguida en Telegram y en llamadas, cuando la persona responde en WhatsApp.')],
          ['data', t('No'), t('Datos que se guardan en slots y completan la plantilla.')],
        ] }),
      endpoint('status', { title: t('Estado de un envío'), purpose: PURPOSE.status, noTry: true,
        after: fieldsOut([
          ['id / kind / channel / to', t('El envío: api, campaign o remind, por qué canal y a quién.')],
          ['status / error', t('queued, sending, sent, delivered, read, replied, failed, opted_out o canceled; error dice por qué falló.')],
          ['created / sent_at / updated', t('Cuándo se pidió, cuándo salió y el último cambio de estado.')],
          ['sessionId / message_id / campaign', t('La conversación, el id del canal (wamid) y la campaña, si es de una.')],
        ]) }),
      endpoint('statuses', { title: t('Listar envíos'), purpose: PURPOSE.statuses, noTry: true }),
      endpoint('costs', { title: t('Costos'), purpose: PURPOSE.costs,
        rows: [
          ['from / to', t('No'), t('Solo el uso de esos días, inclusive (AAAA-MM-DD).')],
          ['group', t('No'), t('day, channel o provider: además viene groups agrupado así.')],
          ['channel / campaign', t('No'), t('Solo ese canal, o las conversaciones de esa campaña.')],
        ],
        after: fieldsOut([
          ['total / currency', t('El total estimado y la moneda de la tabla de precios.')],
          ['by_day / by_channel / by_kind / by_provider', t('El costo por día, canal, tipo (IA, voz, teléfono, mensajería) y proveedor con modelo y cantidad.')],
          ['conversations', t('{count, avg, median, p95} por conversación.')],
          ['resolved', t('{count, cost_per}: el total dividido por las conversaciones que no pasaron a una persona.')],
          ['top / missing_prices', t('Las conversaciones más caras y lo que no tiene precio todavía.')],
        ]) }),
      h('h2', { style: 'font:700 22px var(--display);margin-top:8px' }, t('Contact center')),
      endpoint('handoff', { title: t('Tomar, devolver o cerrar una conversación derivada'), purpose: PURPOSE.handoff, noTry: true,
        rows: [
          ['action', t('Sí'), t('"accept", "release" o "close".')],
          ['agent_name', t('No'), t('En accept: quién la atiende.')],
          ['data / flow', t('No'), t('En release: datos que se guardan y el flujo que sigue.')],
          ['resolution', t('No'), t('En close: cómo terminó.')],
        ] }),
      endpoint('reply', { title: t('Escribirle al cliente desde el contact center'), purpose: PURPOSE.reply, noTry: true,
        rows: [['text', t('Sí'), t('El mensaje.')], ['from_name', t('No'), t('El nombre de quien escribe.')],
          ['template', t('No'), t('WhatsApp fuera de las 24 h: {name, language?, params?} de una plantilla del catálogo. params son los valores de {{1}}, {{2}}…; si no vienen, salen de los slots. Sin plantilla: 409 con code "template_required" y la lista en templates.')]] }),
      endpoint('lookup', { title: t('Buscar la conversación de un cliente'), purpose: PURPOSE.lookup, noTry: true,
        rows: [['phone / chat / sid', t('Uno'), t('El teléfono (con código de país), el chat de Telegram o el sessionId.')]] }),
      h('p', { class: 'help' }, t('Estas rutas aceptan una clave de dueño o editor, o una clave con scope «integration» (sirve solo para esto).')),
      webhookSection(),
      pushSection(),
      voiceSection(),
      endpoint('audio', { title: t('Mandar un mensaje de voz'), purpose: PURPOSE.audio, noTry: true,
        rows: [
          ['audio', t('Sí'), [t('La grabación en base64 (también acepta '), inline('data:audio/webm;base64,…'), t('). Hasta 25 MB.')]],
          ['sessionId', t('No'), t('La conversación (como en message).')],
          ['mime', t('No'), t('El formato: audio/webm (por defecto), audio/ogg, audio/wav, audio/mpeg…')],
          ['speak', t('No'), t('true para que la respuesta venga también en audio.')],
          ['channel / environment', t('No'), t('Igual que en message.')],
        ],
        after: fieldsOut([
          ['heard', t('Lo que entendió del audio (el texto que atendió como message).')],
          ['audio', t('Solo con speak: la respuesta hablada, WAV en base64. Para reproducirla: new Audio("data:audio/wav;base64," + audio).')],
          ['…', t('Todo lo demás, igual que la respuesta de message. 400 si no hay modelo de voz o no se entendió nada.')],
        ]) }),

      responseRef());
  };
})();
