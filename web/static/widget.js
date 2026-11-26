// Parla · widget web. Se pega en cualquier sitio:
// <script src="http://HOST/static/widget.js" data-bot="id-o-slug" data-title="Hablá con nosotros" data-color="#2f6bff"
//         data-greeting="¡Hola!" data-position="right" data-voice="false" data-lang="es" async></script>
// data-lang es el idioma principal del bot (no el del navegador de quien visita): elige los textos del chat. Sin él, español.
// Sin dependencias. Todo vive en un Shadow DOM: ni el sitio pisa el estilo del chat ni el chat el del sitio.
// Solo habla con el servidor de Parla de donde se cargó este archivo.
(() => {
  const me = document.currentScript || [...document.querySelectorAll('script[src*="widget.js"][data-bot]')].pop();
  const d = me?.dataset || {};
  if (!d.bot) return console.warn('Parla: falta data-bot en el <script> del widget');
  // textos propios del widget (no carga i18n.js). Un idioma por línea, mismas claves en todos (tests/test_i18n.py lo revisa)
  const TEXTS = {
    es: { title: 'Hablá con nosotros', placeholder: 'Escribí un mensaje…', input: 'Tu mensaje', send: 'Enviar', speak: 'Hablar', stopRec: 'Dejar de grabar', restart: 'Nueva conversación', close: 'Cerrar', closeChat: 'Cerrar chat', openChat: 'Abrir chat · {title}', closeChatTitle: 'Cerrar chat · {title}', log: 'Mensajes', chips: 'Respuestas sugeridas', open: 'Abrir', human: 'Te atiende una persona', person: 'Persona', origin: 'Este sitio no está autorizado para usar este chat. Si sos el dueño, agregá {origin} en Parla, sección «Widget web».', offline: 'No me pude conectar. Probá de nuevo en un rato.', missing: 'Este chat no está disponible en este momento.', failed: 'Algo salió mal ({error})', noMic: 'No tengo permiso para usar el micrófono.', noVoice: 'La voz no está disponible ahora. Escribime, por favor.' },
    en: { title: 'Chat with us', placeholder: 'Type a message…', input: 'Your message', send: 'Send', speak: 'Speak', stopRec: 'Stop recording', restart: 'New conversation', close: 'Close', closeChat: 'Close chat', openChat: 'Open chat · {title}', closeChatTitle: 'Close chat · {title}', log: 'Messages', chips: 'Suggested replies', open: 'Open', human: 'A person is helping you', person: 'Agent', origin: 'This site is not allowed to use this chat. If you are the owner, add {origin} in Parla, in the “Web widget” section.', offline: 'Could not connect. Please try again in a moment.', missing: 'This chat is not available right now.', failed: 'Something went wrong ({error})', noMic: 'I do not have permission to use the microphone.', noVoice: 'Voice is not available right now. Please type instead.' },
    pt: { title: 'Fale com a gente', placeholder: 'Digite uma mensagem…', input: 'Sua mensagem', send: 'Enviar', speak: 'Falar', stopRec: 'Parar de gravar', restart: 'Nova conversa', close: 'Fechar', closeChat: 'Fechar chat', openChat: 'Abrir chat · {title}', closeChatTitle: 'Fechar chat · {title}', log: 'Mensagens', chips: 'Respostas sugeridas', open: 'Abrir', human: 'Uma pessoa está te atendendo', person: 'Atendente', origin: 'Este site não tem permissão para usar este chat. Se você é o dono, adicione {origin} no Parla, na seção “Widget web”.', offline: 'Não consegui me conectar. Tente de novo daqui a pouco.', missing: 'Este chat não está disponível no momento.', failed: 'Algo deu errado ({error})', noMic: 'Não tenho permissão para usar o microfone.', noVoice: 'A voz não está disponível agora. Escreva, por favor.' },
  };
  const lang = (d.lang || 'es').slice(0, 2).toLowerCase(), L = TEXTS[lang] || TEXTS.es;
  const fill = (s, vars) => s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  const bot = d.bot, base = new URL(me.src, location.href).origin, api = base + '/api/v1/bots/' + encodeURIComponent(bot);
  const title = d.title || L.title, color = /^#[0-9a-f]{6}$/i.test(d.color || '') ? d.color : '#2f6bff';
  const left = d.position === 'left', channel = d.channel || 'web';
  const canVoice = d.voice === 'true' && !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  const key = 'parla.widget.' + bot;
  const remember = (v) => { try { localStorage.setItem(key, v); } catch {} };
  const newSid = () => 'web-' + (crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2)).replace(/-/g, '');
  let sid = (() => { try { return localStorage.getItem(key); } catch { return null; } })() || newSid();
  remember(sid);

  const lum = (hex) => [1, 3, 5].map((i) => { const c = parseInt(hex.slice(i, i + 2), 16) / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; })
    .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
  const ink = (1.05 / (lum(color) + 0.05)) >= 4.5 ? '#fff' : '#111827';

  // si ya había un widget de este bot (p. ej. la vista previa se recarga), se va
  document.querySelectorAll('[data-parla-widget="' + CSS.escape(bot) + '"]').forEach((el) => el.parlaDestroy?.());
  const host = document.createElement('div');
  host.setAttribute('data-parla-widget', bot);
  host.lang = TEXTS[lang] ? lang : 'es';
  const root = host.attachShadow({ mode: 'open' });
  const h = (tag, props, ...kids) => { const el = document.createElement(tag); for (const [k, v] of Object.entries(props || {})) if (v != null && v !== false) k.startsWith('on') ? (el[k] = v) : el.setAttribute(k, v === true ? '' : v); el.append(...kids.filter((k) => k != null)); return el; };
  const svg = (paths) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); s.innerHTML = paths.map((p) => '<path d="' + p + '"/>').join(''); return s; };
  const I = { chat: ['M4 5h16v11H9l-5 4z'], x: ['M6 6l12 12', 'M18 6L6 18'], redo: ['M20 12a8 8 0 1 1-2.3-5.6', 'M20 4v4h-4'], send: ['M4 12l16-8-6 16-2-7z'],
    mic: ['M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z', 'M5 11a7 7 0 0 0 14 0', 'M12 18v3'], stop: ['M7 7h10v10H7z'],
    clip: ['M20 11.5l-8.4 8.4a5 5 0 0 1-7.1-7.1l8.4-8.4a3.3 3.3 0 0 1 4.7 4.7l-8.4 8.4a1.7 1.7 0 0 1-2.4-2.4l7.7-7.7'] };

  root.append(h('style', {}, `
    :host { all: initial; --c: ${color}; --ci: ${ink}; --bg: #fff; --ink: #172033; --muted: #5d6880; --line: #d5dbe6; --soft: #f1f3f7;
      font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink); }
    @media (prefers-color-scheme: dark) { :host { --bg: #161b26; --ink: #e8ecf4; --muted: #9aa4b8; --line: #2c3446; --soft: #212838; } }
    * { box-sizing: border-box; }
    button, input { font: inherit; color: inherit; }
    button { cursor: pointer; border: 0; background: none; padding: 0; }
    button:disabled { opacity: .4; cursor: default; }
    :focus-visible { outline: 2px solid var(--c); outline-offset: 2px; }
    svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.9; stroke-linecap: round; stroke-linejoin: round; }
    .launch { position: fixed; bottom: 20px; ${left ? 'left' : 'right'}: 20px; z-index: 2147483000; width: 58px; height: 58px; border-radius: 50%;
      background: var(--c); color: var(--ci); display: grid; place-items: center; box-shadow: 0 6px 20px rgba(0,0,0,.25); transition: transform .15s; }
    .launch:hover { transform: scale(1.06); }
    .launch svg { width: 26px; height: 26px; }
    .panel { position: fixed; bottom: 92px; ${left ? 'left' : 'right'}: 20px; z-index: 2147483001; width: 370px; height: min(600px, calc(100vh - 120px));
      background: var(--bg); border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 16px 48px rgba(0,0,0,.25);
      display: flex; flex-direction: column; overflow: hidden; animation: up .18s ease-out; }
    .panel[hidden] { display: none; }
    @keyframes up { from { opacity: 0; transform: translateY(12px); } }
    header { background: var(--c); color: var(--ci); padding: 12px 10px 12px 16px; display: flex; align-items: center; gap: 4px; }
    header div { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    header strong { font-size: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    header small { font-size: 12px; opacity: .9; }
    header small:empty { display: none; }
    .ib { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: inherit; }
    .ib:hover { background: rgba(127,127,127,.2); }
    .log { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 8px; overscroll-behavior: contain; }
    .m { max-width: 85%; padding: 8px 12px; border-radius: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
    .m.bot { align-self: flex-start; background: var(--soft); border-bottom-left-radius: 4px; }
    .m.user { align-self: flex-end; background: var(--c); color: var(--ci); border-bottom-right-radius: 4px; }
    .m.err { align-self: stretch; max-width: none; background: none; border: 1px dashed var(--line); color: var(--muted); font-size: 14px; text-align: center; }
    .m .who { display: block; font-size: 11px; font-weight: 600; color: var(--muted); }
    .m .file { display: flex; align-items: center; gap: 8px; margin-top: 6px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 10px;
      background: var(--bg); color: var(--ink); text-decoration: none; white-space: normal; }
    .m .file:hover { border-color: var(--c); } .m .file svg { flex: none; } .m .file small { display: block; color: var(--muted); font-size: 12px; }
    .m img.att { display: block; max-width: 100%; max-height: 220px; border-radius: 10px; margin-top: 6px; }
    .typing { align-self: flex-start; background: var(--soft); border-radius: 14px; padding: 12px 14px; display: flex; gap: 4px; }
    .typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: b 1s infinite; }
    .typing i:nth-child(2) { animation-delay: .15s; } .typing i:nth-child(3) { animation-delay: .3s; }
    @keyframes b { 0%, 60%, 100% { opacity: .3; } 30% { opacity: 1; } }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 14px 10px; }
    .chips:empty { display: none; }
    .chips button { border: 1px solid var(--c); color: var(--ink); border-radius: 999px; padding: 6px 12px; font-size: 14px; background: var(--bg); }
    .chips button:hover { background: var(--soft); }
    form { display: flex; gap: 6px; padding: 10px; border-top: 1px solid var(--line); align-items: center; }
    form input { flex: 1; min-width: 0; border: 1px solid var(--line); border-radius: 999px; padding: 9px 14px; background: var(--bg); }
    form .ib { color: var(--c); }
    .ib[aria-pressed="true"] { background: var(--c); color: var(--ci); }
    @media (max-width: 480px) { .panel { inset: 0; width: auto; height: auto; border-radius: 0; border: 0; } }
    @media (prefers-reduced-motion: reduce) { *, .panel { animation: none !important; transition: none !important; } }
  `));

  const status = h('small', { 'aria-live': 'polite' });
  const log = h('div', { class: 'log', role: 'log', 'aria-live': 'polite', 'aria-label': L.log });
  const chips = h('div', { class: 'chips', role: 'group', 'aria-label': L.chips });
  const input = h('input', { type: 'text', placeholder: L.placeholder, 'aria-label': L.input, autocomplete: 'off', maxlength: '4000' });
  const sendBtn = h('button', { type: 'submit', class: 'ib', 'aria-label': L.send, title: L.send }, svg(I.send));
  const mic = canVoice ? h('button', { type: 'button', class: 'ib', 'aria-label': L.speak, title: L.speak, 'aria-pressed': 'false', onclick: () => toggleMic() }, svg(I.mic)) : null;
  const form = h('form', { onsubmit: (e) => { e.preventDefault(); const t = input.value.trim(); if (t) { input.value = ''; send(t); } } }, input, mic, sendBtn);
  const panel = h('section', { class: 'panel', id: 'parla-panel', role: 'dialog', 'aria-label': title, hidden: true },
    h('header', {}, h('div', {}, h('strong', {}, title), status),
      h('button', { type: 'button', class: 'ib', 'aria-label': L.restart, title: L.restart, onclick: () => restart() }, svg(I.redo)),
      h('button', { type: 'button', class: 'ib', 'aria-label': L.closeChat, title: L.close, onclick: () => toggle(false) }, svg(I.x))),
    log, chips, form);
  const launch = h('button', { type: 'button', class: 'launch', 'aria-label': fill(L.openChat, { title }), 'aria-expanded': 'false', 'aria-controls': 'parla-panel', onclick: () => toggle() }, svg(I.chat));
  root.append(launch, panel);
  (document.body || document.documentElement).append(host);

  // ---------- pantalla ----------
  const scroll = () => { log.scrollTop = log.scrollHeight; };
  function attach(f) {                      // un archivo del paso «Enviar un archivo»: imagen a la vista, el resto como tarjeta
    if (!/^\/files\//.test(f.url || '')) return null;
    const url = base + f.url, size = f.size < 1048576 ? Math.max(1, Math.round(f.size / 1024)) + ' KB' : (f.size / 1048576).toFixed(1) + ' MB';
    return /^image\//.test(f.mime || '') ? h('a', { href: url, target: '_blank', rel: 'noopener' }, h('img', { class: 'att', src: url, alt: f.name }))
      : h('a', { class: 'file', href: url, target: '_blank', rel: 'noopener' }, svg(I.clip), h('span', {}, String(f.name), h('small', {}, size + ' · ' + L.open)));
  }
  function add(kind, text, who, file) {
    log.append(h('div', { class: 'm ' + kind }, who ? h('span', { class: 'who' }, who) : null, file && text === file.name ? null : String(text), file ? attach(file) : null));
    scroll();
  }
  function showButtons(list) {
    chips.replaceChildren(...(list || []).map((b) => h('button', { type: 'button', onclick: () => send(b.value ?? b.label, b.label) }, b.label)));
  }
  let typing = null, busy = 0;
  function setBusy(on) {
    busy += on ? 1 : -1;
    if (busy > 0 && !typing) { typing = h('div', { class: 'typing', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')); log.append(typing); scroll(); }
    if (busy <= 0 && typing) { typing.remove(); typing = null; }
  }
  function toggle(open = panel.hidden) {
    panel.hidden = !open;
    launch.setAttribute('aria-expanded', String(open));
    launch.setAttribute('aria-label', fill(open ? L.closeChatTitle : L.openChat, { title }));
    if (open) { input.focus(); if (!ready) ready = boot(); } else launch.focus();
  }
  panel.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); return toggle(false); }
    if (e.key !== 'Tab') return;             // foco «atrapado» liviano: Tab no se escapa del panel abierto
    const f = [...panel.querySelectorAll('button:not(:disabled), input')].filter((el) => el.offsetParent !== null);
    const at = root.activeElement;
    if (e.shiftKey && at === f[0]) { e.preventDefault(); f.at(-1).focus(); } else if (!e.shiftKey && at === f.at(-1)) { e.preventDefault(); f[0].focus(); }
  });

  // ---------- servidor ----------
  // WebSocket al mismo servidor: los turnos, lo que escribe la persona de la bandeja y la respuesta de la IA mientras
  // se escribe llegan por una sola conexión. Si no conecta (proxy viejo, red), todo sigue como antes: fetch + polling.
  let ws = null, wsOk = null, wsSeq = 0, live = null, humanOn = false;
  const pending = new Map();
  function socket() {
    if (wsOk === false || !('WebSocket' in window)) return Promise.resolve(null);
    if (ws?.readyState === 1) return Promise.resolve(ws);
    return new Promise((res) => {
      const s = new WebSocket(api.replace(/^http/, 'ws') + '/ws');
      let opened = false;
      s.onopen = () => { opened = true; ws = s; wsOk = true; res(s); };
      s.onclose = () => {
        if (!opened && wsOk === null) wsOk = false;          // nunca conectó: polling para siempre
        ws = null; res(null);
        pending.forEach((p) => p.reject(Object.assign(new Error('offline'), { status: 0 }))); pending.clear();
        if (humanOn && !poller) poller = setInterval(poll, 3000);
      };
      s.onmessage = (e) => { try { onSocket(JSON.parse(e.data)); } catch {} };
    });
  }
  function onSocket(m) {
    if (m.type === 'reply') {
      const p = pending.get(m.id); pending.delete(m.id);
      if (p) m.status === 200 ? p.resolve(m.body) : p.reject(Object.assign(new Error(m.body?.error || String(m.status)), { status: m.status }));
    } else if (m.type === 'delta') {                         // la IA escribiendo: una burbuja que crece
      if (live?.stream !== m.stream) { live?.el.remove(); live = { stream: m.stream, el: h('div', { class: 'm bot' }) }; log.append(live.el); }
      live.el.textContent += m.text; scroll();
    } else if (m.type === 'replace' && live?.stream === m.stream) {   // un guardrail cambió el texto final
      if (m.text) live.el.textContent = m.text; else { live.el.remove(); live = null; }
    } else if (m.type === 'messages') {                      // la persona de la bandeja (o el bot cuando la devuelven)
      (m.messages || []).filter((x) => x.from === 'human' || x.from === 'bot').forEach((x) => add('bot', x.text, x.from === 'human' ? (x.by || L.person) : null, x.file));
      if (m.messages?.at(-1)?.buttons) showButtons(m.messages.at(-1).buttons);
      if (Number.isInteger(m.next)) after = m.next;
      if (m.handoff === false) handoff(false);
    }
  }
  async function call(method, path, body) {
    const s = method === 'POST' && path === '/events' ? await socket() : null;
    if (s) return new Promise((resolve, reject) => { const id = ++wsSeq; pending.set(id, { resolve, reject }); s.send(JSON.stringify({ ...body, id })); });
    let r;
    try {
      r = await fetch(api + path, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined });
    } catch {
      // un sitio no autorizado ve un error de red (el servidor no le da permiso CORS): si Parla responde igual, es eso
      const up = await fetch(me.src, { mode: 'no-cors', cache: 'no-store' }).then(() => true, () => false);
      throw Object.assign(new Error(up ? 'origin' : 'offline'), { status: up ? 403 : 0 });
    }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data.error || String(r.status)), { status: r.status });
    return data;
  }
  function oops(e) {
    add('err', e.status === 403 ? fill(L.origin, { origin: location.origin })
      : e.status === 0 ? L.offline
      : e.status === 404 ? L.missing
      : fill(L.failed, { error: e.message }));
  }
  let after = null, poller = null, ready = null;
  function turn(res) {
    live?.el.remove(); live = null;
    (res.messages || []).forEach((m, i) => add('bot', typeof m === 'string' ? m : m.text, null, res.replies?.[i]?.file));
    showButtons(res.buttons);
    if (res.audio) try { new Audio('data:audio/wav;base64,' + res.audio).play().catch(() => {}); } catch {}
    if (Number.isInteger(res.next)) after = res.next;
    handoff(!!res.handoff);
  }
  function handoff(on) {
    status.textContent = on ? L.human : '';
    humanOn = on;
    if (on && ws?.readyState === 1) return;                 // por el WebSocket llega solo, sin preguntar cada 3 s
    if (on && !poller) { poller = setInterval(poll, 3000); if (after == null) poll(true); }
    if (!on && poller) { clearInterval(poller); poller = null; }
  }
  // Lo que escribe la persona que atiende (o el bot cuando lo devuelven). Sin «next» del servidor, la primera
  // vuelta solo marca desde dónde mirar. ponytail: un mensaje humano que llegue en esos primeros 3 s puede perderse
  async function poll(baseline) {
    try {
      const r = await call('GET', '/sessions/' + encodeURIComponent(sid) + '/messages?after=' + (after ?? 0));
      const list = r.messages || [];
      if (!baseline) list.filter((m) => m.from === 'human' || m.from === 'bot').forEach((m) => add('bot', m.text, m.from === 'human' ? (m.by || L.person) : null, m.file));
      if (!baseline && list.at(-1)?.buttons) showButtons(list.at(-1).buttons);
      after = Number.isInteger(r.next) ? r.next : (after ?? 0) + list.length;
      if (r.handoff === false) handoff(false);
    } catch (e) {                            // sin la ruta (o sin permiso) no hay respuestas en vivo: se deja de preguntar
      if ([403, 404, 405].includes(e.status)) { clearInterval(poller); poller = null; }
    }
  }
  async function boot() {                     // primera apertura: retomar la charla guardada o empezar una
    if (d.greeting) add('bot', d.greeting);
    try {
      const r = await call('GET', '/sessions/' + encodeURIComponent(sid) + '/messages?after=0');
      const list = (r.messages || []).filter((m) => ['user', 'bot', 'human'].includes(m.from));
      if (list.length && !r.ended) {
        list.forEach((m) => add(m.from === 'user' ? 'user' : 'bot', m.text, m.from === 'human' ? (m.by || L.person) : null, m.file));
        showButtons(list.at(-1).buttons);
        after = Number.isInteger(r.next) ? r.next : (r.messages || []).length;
        if (r.handoff) (await socket())?.send(JSON.stringify({ type: 'follow', sessionId: sid, after }));
        return handoff(!!r.handoff);
      }
    } catch {}
    return start();
  }
  async function start() {
    setBusy(true);
    try { turn(await call('POST', '/events', { type: 'start', sessionId: sid, channel })); } catch (e) { oops(e); ready = null; }
    finally { setBusy(false); }
  }
  async function send(text, label) {
    await ready;
    add('user', label || text); showButtons([]); setBusy(true);
    try { turn(await call('POST', '/events', { type: 'message', sessionId: sid, channel, text })); } catch (e) { oops(e); }
    finally { setBusy(false); input.focus(); }
  }
  async function restart() {
    const old = sid;
    sid = newSid(); remember(sid); after = null; handoff(false);
    call('POST', '/events', { type: 'end', sessionId: old }).catch(() => {});
    log.replaceChildren(); showButtons([]);
    if (d.greeting) add('bot', d.greeting);
    ready = start(); input.focus();
  }

  // ---------- voz (opcional) ----------
  let rec = null;
  async function toggleMic() {
    if (rec) return rec.stop();
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { return add('err', L.noMic); }
    const chunks = [];
    rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const mime = rec.mimeType || 'audio/webm';
      rec = null; clearTimeout(limit);
      mic.setAttribute('aria-pressed', 'false'); mic.setAttribute('aria-label', L.speak); mic.replaceChildren(svg(I.mic));
      const blob = new Blob(chunks, { type: mime });
      if (!blob.size) return;
      const audio = await new Promise((ok) => { const fr = new FileReader(); fr.onload = () => ok(String(fr.result).split(',')[1]); fr.readAsDataURL(blob); });
      await ready; setBusy(true);
      try {
        const res = await call('POST', '/audio', { sessionId: sid, audio, mime, speak: true });
        if (res.heard) add('user', res.heard);
        turn(res);
      } catch (e) { e.status === 404 || e.status === 405 ? add('err', L.noVoice) : oops(e); }
      finally { setBusy(false); }
    };
    rec.start();
    const limit = setTimeout(() => rec?.stop(), 60000);   // un minuto como mucho
    mic.setAttribute('aria-pressed', 'true'); mic.setAttribute('aria-label', L.stopRec); mic.replaceChildren(svg(I.stop));
  }

  host.parlaDestroy = () => { clearInterval(poller); rec?.stop(); host.remove(); };
})();
