// Idioma de la interfaz. t('Texto en español', { n: 3 }) devuelve el texto en el idioma elegido; la clave es el español,
// así el código se sigue leyendo igual. Las {llaves} se reemplazan por vars. Una clave sin traducción sale en español
// (con localStorage['parla-i18n-debug'] = '1' la consola avisa una vez por clave). Se carga antes que todo lo demás.
// Sumar un idioma: un diccionario más (como EN) en DICTS y su nombre en LANGS. Ver CONTRIBUTING.md.
(() => {
  const LANGS = { es: 'Español', en: 'English' };
  // EN-BEGIN (JSON: una entrada por línea, comillas dobles; tests/test_i18n.py lo lee)
  const EN = {
  };
  // EN-END
  const DICTS = { en: EN };
  const KEY = 'parla-lang';
  const get = (k) => { try { return localStorage.getItem(k); } catch { return null; } };
  const nav = (navigator.language || '').toLowerCase();
  const lang = LANGS[get(KEY)] ? get(KEY) : Object.keys(LANGS).find((l) => nav.startsWith(l)) || 'en';
  const dict = DICTS[lang] || {};
  const debug = !!get('parla-i18n-debug'), warned = new Set();
  const fill = (s, vars) => vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m)) : s;

  window.t = (text, vars) => {
    const out = lang === 'es' ? text : dict[text];
    if (out == null && debug && !warned.has(text)) { warned.add(text); console.warn('[i18n] falta traducir (' + lang + '):', text); }
    return fill(out ?? text, vars);
  };
  t.lang = lang;
  t.locale = { es: 'es-AR', en: 'en-US' }[lang] || lang;          // para toLocaleString y compañía
  t.plural = (n, one, many, vars) => t(n === 1 ? one : many, { n, ...vars });   // t.plural(3, '{n} flujo', '{n} flujos')
  document.documentElement.lang = lang;

  // el servidor contesta los errores en el idioma de la interfaz (parla/i18n.py)
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (url, opts = {}) => {
    if (typeof url === 'string' && url.startsWith('/')) {
      const headers = new Headers(opts.headers);
      if (!headers.has('Accept-Language')) headers.set('Accept-Language', lang);
      opts = { ...opts, headers };
    }
    return nativeFetch(url, opts);
  };

  // selector ES | EN (menú «⋯» y pantalla de entrada); cambiar recarga la página
  window.langSwitcher = () => {
    const box = document.createElement('div');
    box.className = 'th-switch lang-switch'; box.setAttribute('role', 'group'); box.setAttribute('aria-label', t('Idioma'));
    for (const [id, name] of Object.entries(LANGS)) {
      const b = document.createElement('button');
      b.type = 'button'; b.textContent = id.toUpperCase(); b.title = name; b.lang = id; b.setAttribute('aria-label', name);
      b.setAttribute('aria-pressed', String(id === lang));
      b.onclick = () => { if (id === lang) return; try { localStorage.setItem(KEY, id); } catch {} location.reload(); };
      box.append(b);
    }
    return box;
  };
})();
