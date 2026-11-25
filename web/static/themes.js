// Temas: Claro (el de siempre), Oscuro y Colorido. Cargar en <head>, después del <style> principal,
// para que el tema se aplique antes de pintar. window.themeSwitcher() devuelve el selector.
(() => {
  const KEY = 'parla-theme';
  const THEMES = [['light', 'Claro', 'M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z|M12 2v2|M12 20v2|M4.9 4.9l1.4 1.4|M17.7 17.7l1.4 1.4|M2 12h2|M20 12h2|M4.9 19.1l1.4-1.4|M17.7 6.3l1.4-1.4'],
    ['dark', 'Oscuro', 'M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z'],
    ['color', 'Colorido', 'M12 21a9 9 0 1 1 9-9c0 2.5-2 3-3.5 3H16a2 2 0 0 0-1.4 3.4A1.5 1.5 0 0 1 13.5 21z|M7.5 11h.01|M10.5 7h.01|M15.5 8h.01']];
  const css = `
  :root { color-scheme: light; }
  dialog { background: var(--surface); }
  /* Selector de tema: control segmentado. Especificidad de id para que "#nav button" (padding, flex, radio) no se cuele. */
  .th-switch, #nav .th-switch { display: inline-flex; align-items: center; gap: 2px; padding: 3px; border: 1px solid var(--line); border-radius: 999px; background: var(--surface); flex: none; }
  .th-switch button, #nav .th-switch button {
    display: grid; place-items: center; width: 30px; height: 30px; padding: 0; margin: 0; gap: 0; flex: none;
    border-radius: 999px; color: var(--muted); background: none; font-weight: inherit;
    transition: background-color .15s ease-out, color .15s ease-out, box-shadow .15s ease-out;
  }
  .th-switch button:hover, #nav .th-switch button:hover { color: var(--ink); background: var(--soft); }
  .th-switch button[aria-pressed="true"], #nav .th-switch button[aria-pressed="true"] { background: var(--brand-soft); color: var(--brand); box-shadow: 0 1px 2px rgba(0, 0, 0, .08); }
  .th-switch button:focus-visible, #nav .th-switch button:focus-visible { outline: 2px solid var(--brand); outline-offset: -2px; }
  .th-switch .ic { width: 16px; height: 16px; display: block; }
  .lang-switch button { font-size: 12px; font-weight: 700; letter-spacing: .02em; }
  #nav .nav-theme { display: flex; justify-content: center; padding: 12px 0 0; }
  @media (max-width: 1080px) {   /* barra angosta de 64px: segmentos apilados */
    #nav .th-switch { flex-direction: column; }
  }
  @media (max-width: 760px) {    /* barra horizontal: el selector va al final, separado con una línea vertical */
    #nav .nav-theme { margin: 0 0 0 auto; padding: 0 0 0 10px; border-top: 0; border-left: 1px solid var(--line); align-items: center; }
    #nav .th-switch { flex-direction: row; }
  }

  /* ---------- Inicio: entrada en una sola secuencia y tarjetas con más vida ---------- */
  @keyframes home-fade { from { opacity: 0; } }
  @keyframes home-rise { from { opacity: 0; transform: translateY(8px); } }
  .home > *, .home .agents > * { animation: home-fade .25s ease-out backwards; }
  .home > :nth-child(2) { animation-delay: 40ms; }
  .home > :nth-child(n+3) { animation-delay: 80ms; }
  .home .agents > * { animation-name: home-rise; animation-duration: .3s; animation-delay: 120ms; }
  .home .agents > :nth-child(2) { animation-delay: 160ms; }
  .home .agents > :nth-child(3) { animation-delay: 200ms; }
  .home .agents > :nth-child(4) { animation-delay: 240ms; }
  .home .agents > :nth-child(5) { animation-delay: 280ms; }
  .home .agents > :nth-child(n+6) { animation-delay: 320ms; }
  .home .brand .logo::after { content: ""; display: inline-block; width: 6px; height: 6px; margin-left: 3px; border-radius: 50%; background: currentColor; animation: home-fade .3s ease-out 250ms backwards; }

  .home .agent { position: relative; transition: transform .2s ease-out, box-shadow .2s ease-out, border-color .2s ease-out, background-color .2s ease-out, color .2s ease-out; }
  .home .agent:not(.new)::after {
    content: ""; position: absolute; top: 20px; right: 18px; width: 18px; height: 18px; background: var(--brand); opacity: 0; transform: translateX(-4px);
    -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12h14M13 6l6 6-6 6'/%3E%3C/svg%3E") center / contain no-repeat;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M5 12h14M13 6l6 6-6 6'/%3E%3C/svg%3E") center / contain no-repeat;
    transition: opacity .2s ease-out, transform .2s ease-out;
  }
  .home .agent:not(.new) strong { padding-right: 24px; }
  .home .agent:hover, .home .agent:focus-visible {
    border-color: color-mix(in srgb, var(--brand) 55%, var(--line));
    box-shadow: 0 10px 24px -14px color-mix(in srgb, var(--brand) 60%, transparent), 0 2px 6px -2px rgba(0, 0, 0, .08);
    transform: translateY(-2px);
  }
  .home .agent:hover::after, .home .agent:focus-visible::after { opacity: 1; transform: none; }
  .home .agent:active { transform: translateY(0) scale(.985); box-shadow: none; transition-duration: .08s; }
  .home .agent.new:hover, .home .agent.new:focus-visible { background: var(--brand-soft); border-color: var(--brand); border-style: dashed; }
  .home .agent.new .ic { transition: transform .25s ease-out; }
  .home .agent.new:hover .ic, .home .agent.new:focus-visible .ic { transform: rotate(90deg) scale(1.1); }

  .home .home-head .btn.quiet { transition: transform .15s ease-out, border-color .15s ease-out, color .15s ease-out, background-color .15s ease-out; }
  .home .home-head .btn.quiet:hover { border-color: color-mix(in srgb, var(--brand) 55%, var(--line)); color: var(--brand); transform: translateY(-1px); }
  .home .home-head .btn.quiet:active { transform: scale(.97); transition-duration: .08s; }

  @media (prefers-reduced-motion: reduce) {   /* sin movimiento: solo aparece por opacidad */
    .home .agents > * { animation-name: home-fade; }
    .home .agent, .home .agent:hover, .home .agent:focus-visible, .home .agent:active, .home .home-head .btn.quiet:hover, .home .home-head .btn.quiet:active,
    .home .agent::after, .home .agent.new .ic { transform: none !important; }
  }
  @media (prefers-reduced-motion: no-preference) {
    :root.th-anim, :root.th-anim * { transition: background-color .2s, border-color .2s, color .2s !important; }
  }

  /* ---------- Oscuro ---------- */
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg: #0F1420; --surface: #171D2B; --ink: #E6EAF2; --muted: #9AA5BC; --line: #2C3549; --soft: #1F2636;
    --brand: #8E9BFF; --brand-soft: #252E57; --user: #232C52; --warn: #FF9A73; --warn-soft: #3A2119; --ok: #5CCB93;
  }
  :root[data-theme="dark"] .btn:not(.quiet):not(.danger), :root[data-theme="dark"] .msg.user { color: #0F1420; }
  :root[data-theme="dark"] input::placeholder, :root[data-theme="dark"] textarea::placeholder { color: #7C879E; }
  :root[data-theme="dark"] .badge.http, :root[data-theme="dark"] .ad-m.POST { background: #12362D; color: #6FD8B4; }
  :root[data-theme="dark"] .badge.if { background: #2C2150; color: #C3A8FF; }
  :root[data-theme="dark"] .badge.set { background: #3A2D0E; color: #F0C766; }
  :root[data-theme="dark"] .badge.classify { background: #3D1A2C; color: #FF9CC8; }
  :root[data-theme="dark"] .leaf.saved { background: #12362D; border-color: #2E7A62; }
  :root[data-theme="dark"] .answer { border-color: #5A66A8; }
  :root[data-theme="dark"] .tl-score.meh strong { color: #E0B050; }
  :root[data-theme="dark"] .ad-code:not(.light) { background: #0A0E17; border: 1px solid var(--line); }
  :root[data-theme="dark"] .pop { box-shadow: 0 12px 32px rgba(0, 0, 0, .5); }
  :root[data-theme="dark"] dialog { box-shadow: 0 24px 64px rgba(0, 0, 0, .6); border: 1px solid var(--line); }
  :root[data-theme="dark"] dialog::backdrop { background: rgba(4, 6, 12, .65); }
  /* las marcas de entidades traen colores pastel inline (texto oscuro sobre pastel, se lee bien); se bajan un poco para que no encandilen */
  :root[data-theme="dark"] mark, :root[data-theme="dark"] .dot, :root[data-theme="dark"] .tag[style], :root[data-theme="dark"] .sv-tag[style],
  :root[data-theme="dark"] .words button[aria-pressed="true"], :root[data-theme="dark"] .rp-track span { filter: brightness(.86) saturate(.9); }

  /* ---------- Colorido: barra y navegación índigo, contenido calmo sobre lavanda ---------- */
  :root[data-theme="color"] {
    --bg: #F1EFFB; --surface: #FFFFFF; --ink: #1E1B3A; --muted: #57537A; --line: #DCD8EE; --soft: #F6F4FD;
    --brand: #5B3FD9; --brand-soft: #E9E4FF; --user: #E1E6FF; --warn: #A8401A; --warn-soft: #FDEDE4; --ok: #1F7A4D;
  }
  :root[data-theme="color"] input::placeholder, :root[data-theme="color"] textarea::placeholder { color: #8A86A8; }
  :root[data-theme="color"] .answer { border-color: #A99BEA; }
  :root[data-theme="color"] .pop { box-shadow: 0 12px 32px rgba(42, 30, 107, .18); }
  :root[data-theme="color"] dialog { box-shadow: 0 24px 64px rgba(42, 30, 107, .3); }
  :root[data-theme="color"] dialog::backdrop { background: rgba(30, 22, 80, .45); }
  :root[data-theme="color"] .top, :root[data-theme="color"] #nav {
    --surface: #2A1E6B; --ink: #F4F2FF; --muted: #C3BDEB; --line: #4A3F95; --soft: #43378A;
    --brand: #C9BFFF; --brand-soft: #43378A; --ok: #7FE0AE; --warn: #FFB494;
    background: var(--surface); color: var(--ink); border-color: #1E155A;
  }
  :root[data-theme="color"] .top .btn:not(.quiet):not(.danger) { color: #1E1B3A; }
  /* inicio en colorido: toda la pantalla es el cielo de Parla (en claro es una tarjeta sobre lavanda gris) */
  :root[data-theme="color"] .home { background: radial-gradient(70% 60% at 0% 0%, #6A4CF5 0%, transparent 60%), radial-gradient(60% 60% at 100% 100%, #1FB8C9 0%, transparent 55%),
    radial-gradient(45% 45% at 85% 5%, #FF7AB8 0%, transparent 50%), #2A36B8; background-attachment: fixed; }
  :root[data-theme="color"] .home-hero { background: none; box-shadow: none; }
  :root[data-theme="color"] .home-hero::after { display: none; }
  :root[data-theme="color"] .home::before { content: ""; position: fixed; inset: 0; pointer-events: none; opacity: .4;
    background-image: radial-gradient(rgba(255,255,255,.18) 1px, transparent 1.4px); background-size: 22px 22px; }
  :root[data-theme="color"] .home-body { position: relative; }
  :root[data-theme="color"] .home-body h2 { color: #fff; }
  :root[data-theme="color"] .home-body h2 .count { background: rgba(255,255,255,.2); color: #fff; }
  :root[data-theme="color"] .home .agent.new { background: rgba(255,255,255,.12); color: #fff; border-color: rgba(255,255,255,.45); backdrop-filter: blur(6px); }
  :root[data-theme="color"] .home .agent.new:hover { background: rgba(255,255,255,.2); border-color: #fff; }
  :root[data-theme="color"] .home .agent { box-shadow: 0 18px 40px -22px rgba(10, 12, 60, .7); }
  :root[data-theme="color"] .lg-side { background: #F1EFFB; }
  :root[data-theme="color"] .top input::placeholder { color: #A9A2D9; }

  /* ---------- Foco de luz que sigue al mouse: inicio (pantalla, cabecera, tarjetas) y entrada ---------- */
  .home > * { position: relative; z-index: 1; }
  .home::after { content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;   /* la mesa de taller: puntos que se iluminan bajo el foco */
    background: radial-gradient(color-mix(in srgb, #6A4CF5 70%, transparent) 1.3px, transparent 1.7px) 0 0 / 22px 22px;
    -webkit-mask: radial-gradient(260px circle at var(--mx, -999px) var(--my, -999px), #000, transparent 75%);
    mask: radial-gradient(260px circle at var(--mx, -999px) var(--my, -999px), #000, transparent 75%); }
  :root:not([data-theme="color"]) .home::before { content: ""; position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background: radial-gradient(color-mix(in srgb, var(--muted) 30%, transparent) 1px, transparent 1.4px) 0 0 / 22px 22px,
                radial-gradient(520px circle at var(--mx, -999px) var(--my, -999px), color-mix(in srgb, #6A4CF5 12%, transparent), transparent 65%); }
  :root[data-theme="color"] .home::before { background: radial-gradient(rgba(255,255,255,.18) 1px, transparent 1.4px) 0 0 / 22px 22px,
                radial-gradient(560px circle at var(--mx, -999px) var(--my, -999px), rgba(255,255,255,.2), transparent 65%); z-index: 0; opacity: 1; }
  :root[data-theme="color"] .home::after { background-image: radial-gradient(rgba(255,255,255,.85) 1.3px, transparent 1.7px); }
  .home-hero::before, .lg-stage::before { content: ""; position: absolute; inset: 0; z-index: 0; pointer-events: none; opacity: 0; transition: opacity .35s;
    background: radial-gradient(420px circle at var(--mx, 50%) var(--my, 50%), rgba(255,255,255,.32), transparent 60%); }
  .home-hero:hover::before, .lg-stage:hover::before { opacity: 1; }
  .home .agent::before { content: ""; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; opacity: 0; transition: opacity .25s;
    background: radial-gradient(240px circle at var(--mx, 50%) var(--my, 50%), color-mix(in srgb, var(--hue, var(--brand)) 20%, transparent), transparent 65%); }
  .home .agent > * { position: relative; }
  .home .agent { overflow: hidden; isolation: isolate; }            /* el brillo no se sale del borde redondeado */
  :root[data-theme="color"] .home-hero::before { display: none; }  /* en colorido la cabecera es transparente: alcanza el foco de la pantalla */
  :root[data-theme="color"] .home-hero { overflow: visible; }
  .home .agent:hover::before { opacity: 1; }
  .home .agent:not(.new):hover { border-color: color-mix(in srgb, var(--hue, var(--brand)) 60%, var(--line)); }
  .lg-side { background: radial-gradient(520px circle at var(--mx, -999px) var(--my, -999px), color-mix(in srgb, #6A4CF5 10%, transparent), transparent 65%), var(--bg); }
  :root[data-theme="color"] .lg-side { background: radial-gradient(520px circle at var(--mx, -999px) var(--my, -999px), color-mix(in srgb, #6A4CF5 14%, transparent), transparent 65%), #F1EFFB; }
  /* ---------- Menú lateral: mismo cielo, puntos de taller y foco que el resto ---------- */
  #nav { position: relative; isolation: isolate;
    background: radial-gradient(color-mix(in srgb, var(--muted) 22%, transparent) 1px, transparent 1.4px) 0 0 / 18px 18px,
                linear-gradient(180deg, color-mix(in srgb, #6A4CF5 8%, var(--surface)), color-mix(in srgb, #1FB8C9 7%, var(--surface)) 70%, color-mix(in srgb, #FF7AB8 6%, var(--surface))); }
  #nav button { transition: background-color .15s, color .15s, transform .15s; }
  #nav button:hover { transform: translateX(2px); }
  :root[data-theme="dark"] #nav { background: radial-gradient(rgba(255,255,255,.07) 1px, transparent 1.4px) 0 0 / 18px 18px,
                linear-gradient(180deg, #1B1745, #121A30 65%, #0F1F2C); }
  :root[data-theme="color"] #nav { --muted: #DAD5FF; --ink: #fff; --brand: #fff; --brand-soft: rgba(255,255,255,.18); border-color: rgba(255,255,255,.12);
    background: radial-gradient(rgba(255,255,255,.16) 1px, transparent 1.4px) 0 0 / 18px 18px,
                radial-gradient(140% 45% at 0% 0%, #6A4CF5 0%, transparent 65%), radial-gradient(140% 40% at 100% 100%, #1FB8C9 0%, transparent 60%),
                radial-gradient(100% 30% at 100% 40%, rgba(255,122,184,.55) 0%, transparent 60%), #2A36B8; }
  :root[data-theme="color"] #nav button:hover { background: rgba(255,255,255,.12); color: #fff; }
  :root[data-theme="color"] #nav button[aria-current="page"] { background: rgba(255,255,255,.2); color: #fff; box-shadow: inset 0 0 0 1px rgba(255,255,255,.25); }
  /* barra de arriba: la misma tela que el menú lateral, así se leen como una sola pieza */
  .top { background: radial-gradient(color-mix(in srgb, var(--muted) 22%, transparent) 1px, transparent 1.4px) 0 0 / 18px 18px,
                linear-gradient(90deg, color-mix(in srgb, #6A4CF5 8%, var(--surface)), color-mix(in srgb, #1FB8C9 6%, var(--surface)) 60%, color-mix(in srgb, #FF7AB8 6%, var(--surface))); }
  :root[data-theme="dark"] .top { background: radial-gradient(rgba(255,255,255,.07) 1px, transparent 1.4px) 0 0 / 18px 18px,
                linear-gradient(90deg, #1B1745, #121A30 60%, #1A1530); }
  :root[data-theme="color"] .top { border-color: rgba(255,255,255,.12);
    background: radial-gradient(rgba(255,255,255,.16) 1px, transparent 1.4px) 0 0 / 18px 18px,
                radial-gradient(60% 160% at 0% 0%, #6A4CF5 0%, transparent 70%), radial-gradient(40% 180% at 100% 0%, rgba(255,122,184,.55) 0%, transparent 70%),
                radial-gradient(40% 160% at 70% 100%, rgba(31,184,201,.45) 0%, transparent 70%), #2A36B8; }
  /* ---------- Marco del editor: barra + menú son UNA pieza (un solo fondo, sin línea entre ellos) y el contenido es un panel encastrado ---------- */
  html:root .work > .top, html:root .work > #nav { background: transparent; border-color: transparent; }
  .work { background: radial-gradient(color-mix(in srgb, var(--muted) 22%, transparent) 1px, transparent 1.4px) 0 0 / 18px 18px,
    radial-gradient(60% 90% at 0% 0%, color-mix(in srgb, #6A4CF5 10%, transparent), transparent 70%),
    radial-gradient(50% 70% at 0% 100%, color-mix(in srgb, #1FB8C9 9%, transparent), transparent 70%),
    radial-gradient(40% 30% at 100% 0%, color-mix(in srgb, #FF7AB8 8%, transparent), transparent 70%), var(--surface); }
  :root[data-theme="dark"] .work { background: radial-gradient(rgba(255,255,255,.07) 1px, transparent 1.4px) 0 0 / 18px 18px,
    radial-gradient(60% 90% at 0% 0%, #1F1A52, transparent 70%), radial-gradient(50% 70% at 0% 100%, #0F2733, transparent 70%), #121A2C; }
  :root[data-theme="color"] .work { background: radial-gradient(rgba(255,255,255,.16) 1px, transparent 1.4px) 0 0 / 18px 18px,
    radial-gradient(60% 90% at 0% 0%, #6A4CF5, transparent 70%), radial-gradient(50% 70% at 0% 100%, #1FB8C9, transparent 70%),
    radial-gradient(40% 40% at 100% 0%, rgba(255,122,184,.6), transparent 70%), #2A36B8; }
  .work > #center { background: var(--bg); border-top-left-radius: 18px; box-shadow: inset 1px 1px 0 color-mix(in srgb, var(--line) 80%, transparent); }
  :root[data-theme="color"] .work > #center { box-shadow: none; }
  .work > #chat { border-top-left-radius: 0; }
  @media (max-width: 760px) { .work > #center { border-radius: 0; box-shadow: none; } }
  @media (hover: none) { .home::after, .home-hero::before, .lg-stage::before, .home .agent::before { display: none; } }
  `;
  document.head.append(Object.assign(document.createElement('style'), { textContent: css }));

  // un solo listener: pasa la posición del mouse (relativa a cada elemento) a --mx/--my, una vez por cuadro
  const SPOT = '.home, .home-hero, .home .agent, .lg-stage, .lg-side';
  let spotFrame = 0;
  document.addEventListener('pointermove', (e) => {
    if (e.pointerType !== 'mouse' || spotFrame) return;
    spotFrame = requestAnimationFrame(() => {
      spotFrame = 0;
      document.querySelectorAll(SPOT).forEach((el) => {
        const r = el.getBoundingClientRect();
        el.style.setProperty('--mx', (e.clientX - r.left) + 'px');
        el.style.setProperty('--my', (e.clientY - r.top) + 'px');
      });
    });
  }, { passive: true });

  const root = document.documentElement;
  const saved = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const os = matchMedia('(prefers-color-scheme: dark)');
  const valid = (t) => THEMES.some(([id]) => id === t);
  const sync = () => document.querySelectorAll('.th-switch button[data-theme]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.theme === root.dataset.theme));
  const apply = (t) => { root.dataset.theme = t; sync(); };
  apply(valid(saved()) ? saved() : os.matches ? 'dark' : 'light');
  os.addEventListener('change', (e) => { if (!valid(saved())) apply(e.matches ? 'dark' : 'light'); });   // sin elección guardada, sigue al sistema

  let anim;
  function choose(t) {
    try { localStorage.setItem(KEY, t); } catch {}
    root.classList.add('th-anim'); clearTimeout(anim); anim = setTimeout(() => root.classList.remove('th-anim'), 300);
    apply(t);
  }
  const svg = (paths) => {
    const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true');
    s.innerHTML = paths.split('|').map((d) => '<path d="' + d + '"/>').join('');
    return s;
  };
  window.themeSwitcher = () => {
    const box = document.createElement('div');
    box.className = 'th-switch'; box.setAttribute('role', 'group'); box.setAttribute('aria-label', 'Tema');
    for (const [id, label, paths] of THEMES) {
      const b = document.createElement('button');
      b.type = 'button'; b.dataset.theme = id; b.title = 'Tema ' + label.toLowerCase(); b.setAttribute('aria-label', label);
      b.setAttribute('aria-pressed', id === root.dataset.theme);
      b.onclick = () => choose(id);
      b.append(svg(paths));
      box.append(b);
    }
    return box;
  };
})();
