// Canales: WhatsApp, Telegram y Teléfono (agent.channels, ver parla/channels.py y parla/phone.py). Las claves van a la bóveda (secrets.js: scForm),
// nunca al JSON del agente. El estado (último mensaje, último error) vive en memoria del servidor.
document.head.append(h('style', {}, `
  .ch-ok, .ch-miss { font-size: 13px; font-weight: 600; white-space: nowrap; }
  .ch-ok { color: var(--ok); } .ch-miss { color: var(--warn); }
  .ch-url { display: flex; gap: 8px; align-items: center; } .ch-url .wg-snippet { flex: 1; min-width: 0; }
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
let chInfo = null, chFor = null, chError = '', chNote = '', chEditing = null, chBusy = false;

async function chLoad() {
  try { chInfo = await api('GET', '/' + agent.id + '/channels'); chError = ''; }
  catch (e) { chError = e.message; }
  if (section === 'channels') render();
}
const chAll = () => (agent.channels = agent.channels || {});
const chConf = (c) => (chAll()[c] = chAll()[c] || { enabled: false });
const chBase = () => (chAll().public_url || chInfo?.env_public_url || '').trim().replace(/\/+$/, '');
const chHook = (c) => chBase() + '/api/v1/bots/' + agent.id + '/' + c;

function chUrl(url) {
  const pre = h('pre', { class: 'wg-snippet' }, url);
  return h('div', { class: 'ch-url' }, pre,
    h('button', { class: 'btn small', type: 'button', onclick: (e) => wgCopy(url, e.currentTarget) }, icon('check'), h('span', {}, t('Copiar'))));
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
    h('input', { type: 'checkbox', checked: !!conf.enabled, onchange: (e) => { conf.enabled = e.target.checked; touch(); render(); } }),
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
    chPhone(base));
};
