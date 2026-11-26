// Canales: WhatsApp, Telegram y Teléfono (agent.channels, ver parla/channels.py y parla/phone.py). Las claves van a la bóveda (secrets.js: scForm),
// nunca al JSON del agente. El estado (último mensaje, último error) vive en memoria del servidor.
document.head.append(h('style', {}, `
  .ch-ok, .ch-miss { font-size: 13px; font-weight: 600; white-space: nowrap; }
  .ch-ok { color: var(--ok); } .ch-miss { color: var(--warn); }
  .ch-url { display: flex; gap: 8px; align-items: center; } .ch-url .wg-snippet { flex: 1; min-width: 0; }
  .ch-events { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 14px; } .ch-events label { display: inline-flex; gap: 6px; align-items: center; }
  .ch-scroll { overflow-x: auto; } .ch-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .ch-table th { text-align: left; color: var(--muted); font-weight: 600; padding: 4px 6px; border-bottom: 1px solid var(--line); }
  .ch-table td { padding: 4px 6px; border-bottom: 1px solid var(--line); vertical-align: top; overflow-wrap: anywhere; }
`));

const CH_HELP = {
  WHATSAPP_TOKEN: t('Token de acceso permanente (usuario del sistema en Meta Business).'),
  WHATSAPP_APP_SECRET: t('Clave secreta de la app de Meta (Configuración de la app → Básica).'),
  WHATSAPP_VERIFY_TOKEN: t('Inventá una palabra larga y pegala también en Meta como «Token de verificación».'),
  TELEGRAM_TOKEN: t('El token que te da BotFather (123456:ABC…).'),
  TELEGRAM_WEBHOOK_SECRET: t('Se crea solo al tocar «Conectar webhook».'),
  TWILIO_AUTH_TOKEN: t('El Auth Token de la cuenta de Twilio (Console → Account Info). Con él se verifica la firma de cada llamada.'),
  JAMBONZ_WEBHOOK_SECRET: t('El «webhook secret» de tu cuenta de jambonz (Account). Se verifica la firma Jambonz-Signature.'),
  JAMBONZ_BASIC_USER: t('Opcional: usuario de HTTP basic que pusiste en la aplicación de jambonz.'),
  JAMBONZ_BASIC_PASSWORD: t('Opcional: la contraseña de HTTP basic de la aplicación de jambonz.'),
  TWILIO_ACCOUNT_SID: t('El Account SID de Twilio (Console → Account Info). Hace falta para que Parla llame (campañas y recordatorios).'),
  JAMBONZ_API_KEY: t('Una API key de jambonz (Account → API keys). Hace falta para que Parla llame (campañas y recordatorios).'),
  JAMBONZ_ACCOUNT_SID: t('El Account SID de tu cuenta de jambonz. Hace falta para que Parla llame (campañas y recordatorios).'),
};
const CH_PHONE = { twilio: ['TWILIO_AUTH_TOKEN', 'TWILIO_ACCOUNT_SID'], jambonz: ['JAMBONZ_WEBHOOK_SECRET', 'JAMBONZ_BASIC_USER', 'JAMBONZ_BASIC_PASSWORD', 'JAMBONZ_API_KEY', 'JAMBONZ_ACCOUNT_SID'] };
let chInfo = null, chFor = null, chError = '', chNote = '', chEditing = null, chBusy = false, chLog = null;

async function chLoad() {
  try { chInfo = await api('GET', '/' + agent.id + '/channels'); chError = ''; }
  catch (e) { chError = e.message; }
  try { chLog = (await api('GET', '/' + agent.id + '/webhooks/deliveries?limit=20')).deliveries; } catch { chLog = null; }
  if (section === 'channels') render();
}

// Derivación (parla/handoff.py): a quién pasa la charla, webhooks firmados y el contexto de la transferencia telefónica
const CH_EVENTS = {
  'handoff.requested': t('Pasó a una persona'), 'handoff.released': t('Volvió al bot'), 'conversation.started': t('Empezó una conversación'),
  'conversation.ended': t('Terminó una conversación'), 'message.user': t('Cada mensaje del cliente'), 'message.bot': t('Cada respuesta del bot'),
  'csat.received': t('Respuesta de la encuesta'), 'campaign.finished': t('Terminó una campaña'),
};
const CH_HEADERS = { session: t('Id de la conversación'), intent: t('Intención'), language: t('Idioma'), summary: t('Resumen'), context_url: t('Dirección del contexto (lookup)') };
const CH_STATUS = { queued: t('En cola'), sending: t('Enviando'), delivered: t('Entregado'), dead: t('Falló (sin más reintentos)') };

async function chWebhook(what, arg) {
  chBusy = true; chNote = ''; chError = ''; render();
  try {
    if (what === 'test') {
      await saveNow();                    // que el servidor ya tenga el webhook
      const d = await api('POST', '/' + agent.id + '/webhooks/test', { url: arg });
      chNote = d.status === 'delivered' ? t('Evento de prueba entregado (HTTP {code}).', { code: d.code }) : t('El evento de prueba no llegó: {error}.', { error: d.error || d.code });
    } else {
      await api('POST', '/' + agent.id + '/webhooks/deliveries/' + arg + '/retry');
      chNote = t('Vuelve a la cola: sale en unos segundos.');
    }
  } catch (e) { chError = e.message; }
  chBusy = false; chLoad();
}

function chHandoff() {
  const ho = (agent.handoff ||= {}), ph = (ho.phone ||= {}), hooks = (agent.webhooks ||= []);
  const upd = () => { touch(); render(); };
  const box = (list, value, label) => h('label', {}, h('input', { type: 'checkbox', checked: list.includes(value),
    onchange: (e) => { const i = list.indexOf(value); if (e.target.checked && i < 0) list.push(value); if (!e.target.checked && i >= 0) list.splice(i, 1); touch(); } }), label);
  const mode = ho.mode || 'inbox';
  return h('div', { class: 'panel' },
    h('h2', {}, t('Derivación')),
    h('p', { class: 'help' }, t('Qué pasa cuando el bot pasa la charla a una persona. Con un contact center propio (Genesys, Twilio Flex, Five9, Zendesk, Salesforce…), Parla le avisa por webhook y el contact center contesta por la API. Guía en docs/contact-centers_es.md.')),
    lab(t('Quién atiende'), chSelect(ho, 'mode', [['inbox', t('Bandeja de Parla')], ['external', t('Contact center externo')], ['both', t('Ambos')]])),
    mode === 'inbox' ? null : [
      lab(t('Si nadie la acepta en (minutos, 0 = esperar siempre)'), h('input', { type: 'number', min: 0, value: ho.timeout_minutes ?? 0, style: 'max-width:120px',
        oninput: (e) => { ho.timeout_minutes = Number(e.target.value) || 0; touch(); } })),
      lab(t('Al vencer'), chSelect(ho, 'on_timeout', [['bot', t('Vuelve al bot')], ['close', t('Se cierra la conversación')]])),
      lab(t('Cola o destino (se manda en el webhook)'), h('input', { ...bind(ho, 'target'), placeholder: 'ventas', spellcheck: 'false' }))],
    lab(t('Mensajes que van en el contexto'), h('input', { type: 'number', min: 0, max: 50, value: ho.last_messages ?? 10, style: 'max-width:120px',
      oninput: (e) => { ho.last_messages = Number(e.target.value); touch(); } })),
    h('div', { class: 'panel phrases' }, h('strong', {}, t('Webhooks')),
      h('p', { class: 'help', style: 'font-size:14px' }, t('Parla manda cada evento firmado (encabezado Parla-Signature) con la clave que elijas; si falla, reintenta durante unas 24 horas.')),
      hooks.map((w, i) => h('div', { class: 'stack', style: 'gap:6px;padding:8px 0;border-bottom:1px solid var(--line)' },
        h('div', { class: 'row' }, h('input', { ...bind(w, 'url'), placeholder: 'https://cc.midominio.com/parla', 'aria-label': t('Dirección del webhook'), spellcheck: 'false', class: 'grow' }),
          iconBtn('x', t('Quitar webhook'), () => { hooks.splice(i, 1); upd(); })),
        h('div', { class: 'ch-events' }, Object.entries(CH_EVENTS).map(([k, label]) => box((w.events ||= []), k, label))),
        h('div', { class: 'row' }, h('input', { ...bind(w, 'secret_name'), placeholder: 'CC_WEBHOOK_SECRET', 'aria-label': t('Clave para firmar'), spellcheck: 'false', class: 'grow' }),
          h('button', { class: 'link', type: 'button', onclick: () => { section = 'secrets'; render(); } }, t('Ir a Claves')),
          canEdit() ? h('button', { class: 'btn quiet small', type: 'button', disabled: chBusy || !/^https?:\/\//.test(w.url || ''), onclick: () => chWebhook('test', w.url) }, t('Enviar evento de prueba')) : null))),
      canEdit() ? h('div', {}, h('button', { class: 'link', type: 'button', onclick: () => { hooks.push({ url: '', events: ['handoff.requested', 'handoff.released'], secret_name: '' }); upd(); } }, t('Agregar webhook'))) : null),
    hooks.length ? h('div', { class: 'panel phrases' }, h('strong', {}, t('Últimas entregas')),
      !chLog?.length ? h('p', { class: 'help', style: 'font-size:14px' }, t('Todavía no salió ningún evento.')) : h('div', { class: 'ch-scroll' }, h('table', { class: 'ch-table' },
        h('thead', {}, h('tr', {}, [t('Cuándo'), t('Evento'), t('Estado'), t('Respuesta'), ''].map((x) => h('th', {}, x)))),
        h('tbody', {}, chLog.map((d) => h('tr', {}, h('td', {}, d.updated), h('td', {}, h('code', {}, d.event), d.sessionId ? h('small', { style: 'display:block' }, d.sessionId) : null),
          h('td', {}, CH_STATUS[d.status] || d.status, d.attempts > 1 ? h('small', { style: 'display:block' }, t('{n} intentos', { n: d.attempts })) : null),
          h('td', {}, d.code ? 'HTTP ' + d.code : '', d.error ? h('small', { class: 'wg-error', style: 'display:block' }, d.error) : null),
          h('td', {}, canEdit() && (d.status === 'dead' || d.status === 'queued') ? h('button', { class: 'btn quiet small', type: 'button', disabled: chBusy, onclick: () => chWebhook('retry', d.id) }, t('Reintentar')) : null))))))) : null,
    h('div', { class: 'panel phrases' }, h('strong', {}, t('Contexto en la transferencia telefónica')),
      h('p', { class: 'help', style: 'font-size:14px' }, t('Al transferir una llamada a una dirección SIP, Parla agrega estos encabezados X-Parla-* (recortados a lo que entra en SIP). A un número común no se le pueden agregar.')),
      h('div', { class: 'ch-events' }, Object.entries(CH_HEADERS).map(([k, label]) => box((ph.headers ||= []), k, label)),
        h('label', {}, h('input', { type: 'checkbox', checked: !!ph.uui, onchange: (e) => { ph.uui = e.target.checked; touch(); } }), t('User-to-User (UUI)'))),
      lab(t('Slots que viajan como encabezado'), h('input', { value: (ph.slots || []).join(', '), placeholder: t('dni, producto'), spellcheck: 'false',
        onchange: (e) => { ph.slots = e.target.value.split(',').map((v) => v.trim()).filter(Boolean); touch(); } })),
      lab(t('Twilio Flex: Workflow SID de TaskRouter (opcional)'), h('input', { ...bind(ph, 'twilio_workflow_sid'), placeholder: 'WW…', spellcheck: 'false' })),
      h('p', { class: 'help', style: 'font-size:14px' }, t('Con un Workflow SID, la llamada entra a Flex con <Enqueue> y el contexto va en los atributos de la tarea, en vez de transferirse.'))));
}
const chAll = () => (agent.channels = agent.channels || {});
const chConf = (c) => (chAll()[c] = chAll()[c] || { enabled: false });
const chBase = () => (chAll().public_url || chInfo?.env_public_url || '').trim().replace(/\/+$/, '');
const chHook = (c) => chBase() + '/api/v1/bots/' + agent.id + '/' + c;

function chUrl(url) {
  const pre = h('pre', { class: 'wg-snippet' }, url);
  return h('div', { class: 'ch-url' }, pre,
    h('button', { class: 'btn small', type: 'button', onclick: (e) => wgCopy(url, e.currentTarget) }, h('span', {}, t('Copiar'))));
}

function chSecrets(c, only) {
  const have = chInfo?.[c]?.secrets || {};
  return h('div', { class: 'panel phrases' }, h('strong', {}, t('Claves')),
    Object.keys(have).filter((n) => !only || only.includes(n)).map((n) => chEditing === n ? scForm(n, () => { chEditing = null; chLoad(); }) : h('div', { class: 'phrase-row' },
      h('span', { class: 'phrase' }, h('code', {}, n), h('small', { class: 'help', style: 'display:block' }, CH_HELP[n])),
      h('span', { class: have[n] ? 'ch-ok' : 'ch-miss' }, have[n] ? t('Cargada') : t('Falta')),
      n === 'TELEGRAM_WEBHOOK_SECRET' ? null
        : h('button', { class: 'btn quiet small', type: 'button', onclick: () => { chEditing = n; render(); } }, have[n] ? t('Cambiar') : t('Cargar')))));
}

function chStatus(c) {
  const s = chInfo?.[c]?.status || {};
  return h('dl', { class: 'kv' },
    h('dt', {}, t('Último mensaje recibido')), h('dd', {}, s.last_in || t('ninguno desde que arrancó Parla')),
    h('dt', {}, t('Última respuesta enviada')), h('dd', {}, s.last_out || t('ninguna desde que arrancó Parla')),
    s.error ? [h('dt', {}, t('Último error')), h('dd', { class: 'wg-error' }, s.error + ' · ' + s.error_at)] : null);
}

function chCheck(c, text, sub) {
  const conf = chConf(c);
  return h('label', { class: 'wg-check' },
    h('input', { type: 'checkbox', class: 'switch', role: 'switch', checked: !!conf.enabled, onchange: (e) => { conf.enabled = e.target.checked; touch(); render(); } }),
    h('span', {}, text, h('small', {}, sub)));
}

async function chTelegram(connect) {
  chBusy = true; chNote = ''; render();
  try {
    await saveNow();                      // que el servidor ya tenga la dirección pública
    await api('POST', '/' + agent.id + '/channels/telegram', { connect });
    chNote = connect ? t('Listo: Telegram ya le manda los mensajes a Parla. Probá escribirle a tu bot.') : t('Desconectado: Telegram dejó de mandar mensajes.');
  } catch (e) { chError = e.message; }
  chBusy = false; chLoad();
}

function chSelect(conf, key, options) {
  return h('select', { onchange: (e) => { conf[key] = e.target.value; touch(); render(); } },
    options.map(([value, label]) => h('option', { value, selected: (conf[key] || options[0][0]) === value }, label)));
}

function chTemplates(wa) {             // catálogo de plantillas aprobadas en Meta: [{name, language, params: [slots en orden para {{1}}, {{2}}…]}]
  const list = (wa.templates ||= []);
  const upd = () => { touch(); render(); };
  return h('div', { class: 'panel phrases' }, h('strong', {}, t('Plantillas aprobadas')),
    h('p', { class: 'help', style: 'font-size:14px' }, t('Para escribirle primero a alguien (campañas y recordatorios después de 24 horas), WhatsApp exige una plantilla aprobada en Meta. Cargá acá su nombre exacto, el idioma y qué slot va en cada {{1}}, {{2}}…')),
    list.map((x, i) => h('div', { class: 'row', style: 'padding:6px 0' },
      h('input', { ...bind(x, 'name'), placeholder: 'recordatorio_turno', 'aria-label': t('Nombre de la plantilla'), spellcheck: 'false', class: 'grow' }),
      h('input', { ...bind(x, 'language'), placeholder: 'es_AR', 'aria-label': t('Idioma de la plantilla'), spellcheck: 'false', style: 'width:90px' }),
      h('input', { value: (x.params || []).join(', '), placeholder: t('nombre, fecha, hora'), 'aria-label': t('Slots para {{1}}, {{2}}… separados por coma'), title: t('Slots para {{1}}, {{2}}… separados por coma'),
        spellcheck: 'false', class: 'grow', onchange: (e) => { x.params = e.target.value.split(',').map((v) => v.trim()).filter(Boolean); touch(); } }),
      iconBtn('x', t('Quitar plantilla'), () => { list.splice(i, 1); upd(); }))),
    h('div', {}, h('button', { class: 'link', type: 'button', onclick: () => { list.push({ name: '', language: 'es', params: [] }); upd(); } }, t('Agregar plantilla'))));
}

function chPhone(base) {
  const ph = chConf('phone'), provider = ph.provider || 'twilio';
  const hook = base + '/api/v1/bots/' + agent.id + '/phone/' + provider;
  return h('div', { class: 'panel' },
    h('h2', {}, t('Teléfono')),
    chCheck('phone', t('Atender llamadas'), ph.enabled ? t('Prendido: Parla atiende las llamadas firmadas por tu proveedor.') : t('Apagado: el webhook responde 403.')),
    lab(t('Proveedor'), chSelect(ph, 'provider', [['twilio', 'Twilio'], ['jambonz', t('jambonz (código abierto, propio)')]])),
    lab(t('Idioma de la llamada'), h('input', { ...bind(ph, 'language'), placeholder: 'es-AR' })),
    lab(t('Número desde el que se llama'), h('input', { ...bind(ph, 'from'), placeholder: '+5491112345678', inputmode: 'tel' })),
    provider === 'jambonz' ? [lab(t('Dirección de la API de jambonz'), h('input', { ...bind(ph, 'api_url'), placeholder: 'https://api.jambonz.cloud', spellcheck: 'false' })),
      lab(t('Application SID'), h('input', { ...bind(ph, 'application_sid'), spellcheck: 'false' }))] : null,
    h('p', { class: 'help', style: 'font-size:14px' }, t('El número, la dirección y las claves de abajo hacen falta solo para que Parla llame (campañas y recordatorios). Para atender no.')),
    lab(t('Voz'), chSelect(ph, 'tts', [['provider', t('La del proveedor')], ['parla', t('La de Parla (piper, en este servidor)')]])),
    ph.tts === 'parla' ? null : lab(t('Nombre de la voz del proveedor (opcional)'), h('input', { ...bind(ph, 'voice'), placeholder: provider === 'twilio' ? 'Polly.Mia-Neural' : 'es-US-Neural2-A' })),
    lab(t('Transferir a una persona'), h('input', { ...bind(ph, 'handoff_to'), placeholder: '+5491112345678 · sip:mesa@pbx.midominio.com' })),
    lab(t('Tecla para terminar un número'), h('input', { ...bind(ph, 'finish_on_key'), placeholder: '#', maxlength: 1, style: 'max-width:80px' })),
    h('p', { class: 'help' }, provider === 'twilio'
      ? t('En Twilio, Phone Numbers → tu número → Voice: en «A call comes in» pegá esta URL (Webhook, HTTP POST) y en «Call status changes» la segunda.')
      : t('En jambonz, Applications → tu aplicación: pegá la primera URL en «Calling webhook» y la segunda en «Call status webhook», las dos con POST.')),
    chUrl(hook), chUrl(hook + '/status'),
    h('p', { class: 'help' }, provider === 'twilio'
      ? t('Con Twilio, la voz de quien llama la transcribe Twilio (sale de tu servidor). Con jambonz elegís el reconocedor, incluso uno propio.')
      : t('Con jambonz, el reconocedor y la voz se eligen en la aplicación de jambonz.')),
    chSecrets('phone', CH_PHONE[provider]), chStatus('phone'));
}

window.channelsView = () => {
  if (chFor !== agent.id) { chFor = agent.id; chInfo = null; chEditing = null; chError = chNote = ''; chLoad(); }
  const wa = chConf('whatsapp'), tg = chConf('telegram'), base = chBase();
  return h('div', { class: 'page' },
    h('div', { class: 'page-head' }, h('h1', {}, t('Canales'))),
    h('p', { class: 'help' }, t('Conectá este bot a WhatsApp, Telegram y llamadas telefónicas: contesta lo publicado en Producción, con sus botones y archivos, y lo que respondés desde la Bandeja también llega por ahí. Guía paso a paso en docs/channels_es.md.')),
    chError ? h('p', { class: 'notice warn', role: 'alert' }, chError) : null,
    chNote ? h('p', { class: 'notice', role: 'status' }, chNote) : null,
    h('div', { class: 'panel' },
      h('h2', {}, t('Dirección pública de Parla')),
      h('p', { class: 'help' }, t('Meta y Telegram tienen que poder llegar a Parla por internet con HTTPS (un servidor, un proxy o un túnel). Escribí la dirección sin nada al final.')),
      lab(t('Dirección pública'), h('input', { ...bind(chAll(), 'public_url'), onchange: () => render(), placeholder: chInfo?.env_public_url || 'https://bots.midominio.com' })),
      chInfo?.env_public_url && !chAll().public_url ? h('p', { class: 'help' }, t('Usando PARLA_PUBLIC_URL del servidor.')) : null,
      base && !/^https:\/\//.test(base) ? h('p', { class: 'wg-error' }, t('Tiene que empezar con https://')) : null),
    h('div', { class: 'panel' },
      h('h2', {}, 'WhatsApp'),
      chCheck('whatsapp', t('Atender por WhatsApp'), wa.enabled ? t('Prendido: Parla acepta los mensajes firmados por tu app de Meta.') : t('Apagado: el webhook responde 403.')),
      lab(t('Identificador del número (Phone number ID)'), h('input', { ...bind(wa, 'phone_number_id'), inputmode: 'numeric', placeholder: '123456789012345' })),
      h('p', { class: 'help' }, t('En Meta, WhatsApp → Configuración → Webhook: pegá esta URL de devolución de llamada y tu token de verificación, y suscribite a «messages».')),
      chUrl(chHook('whatsapp')),
      chTemplates(wa), chSecrets('whatsapp'), chStatus('whatsapp')),
    h('div', { class: 'panel' },
      h('h2', {}, 'Telegram'),
      chCheck('telegram', t('Atender por Telegram'), tg.enabled ? t('Prendido: Parla acepta los mensajes que traen el secreto del webhook.') : t('Apagado: el webhook responde 403.')),
      chSecrets('telegram'),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', type: 'button', disabled: chBusy || !tg.enabled || !/^https:\/\//.test(base), onclick: () => chTelegram(true) }, t('Conectar webhook')),
        h('button', { class: 'btn quiet small', type: 'button', disabled: chBusy, onclick: () => chTelegram(false) }, t('Desconectar'))),
      h('p', { class: 'help' }, t('Conectar le dice a Telegram que mande los mensajes a '), h('code', {}, chHook('telegram')), t('.')),
      chStatus('telegram')),
    chPhone(base), chHandoff());
};
