// Versiones: publicar el borrador como una versión fija y ponerla en Pruebas o Producción (como los alias de Lex).
(() => {
  // como replaceChildren pero descarta null/false, igual que h(): si no, el DOM pinta la palabra «null»
  const fill = (el, ...kids) => el.replaceChildren(...kids.flat(Infinity).filter((k) => k != null && k !== false));
  document.head.append(h('style', {}, `
    .work { grid-template-rows: auto minmax(0, 1fr); }
    .top { flex-wrap: wrap; min-height: 56px; padding: 8px 16px; row-gap: 8px; }
    .rl-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; border: 1px solid var(--line); color: var(--muted); background: var(--surface); white-space: nowrap; }
    .rl-chip::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
    .rl-chip.live { color: var(--ok); }
    .rl-chip:hover { border-color: var(--brand); }
    .rl-dialog { width: min(540px, calc(100vw - 32px)); max-height: min(88vh, 900px); }
    .rl-dialog form { gap: 14px; }
    .rl-diff { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
    .rl-diff li { overflow-wrap: anywhere; }
    .rl-choice { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; cursor: pointer; }
    .rl-choice:has(input:checked) { border-color: var(--brand); background: var(--brand-soft); }
    .rl-choice input { margin-top: 4px; }
    .rl-choice small { display: block; color: var(--muted); font-size: 13px; }
    .rl-envs { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
    .rl-env { gap: 8px; }
    .rl-env .rl-kind { font-size: 13px; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: .04em; }
    .rl-env .rl-big { font: 700 30px/1.1 var(--display); }
    .rl-env .rl-big.none { font-size: 18px; color: var(--muted); }
    .rl-env p { font-size: 14px; color: var(--muted); }
    .rl-env .row { margin-top: auto; }
    .rl-env.prod { border-color: var(--ok); }
    .rl-list { display: flex; flex-direction: column; }
    .rl-ver { display: flex; flex-direction: column; gap: 6px; padding: 12px 0; border-bottom: 1px solid var(--line); }
    .rl-ver:last-child { border-bottom: 0; }
    .rl-ver .rl-num { font: 700 18px var(--display); }
    .rl-ver .rl-meta { color: var(--muted); font-size: 13px; }
    .rl-ver .rl-note { overflow-wrap: anywhere; }
    .rl-ver .rl-note.none { color: var(--muted); font-style: italic; }
    .rl-ver .rl-actions { gap: 4px 14px; font-size: 14px; }
    .rl-ver .rl-actions .link { font-size: 14px; }
    .rl-tag { background: var(--soft); color: var(--muted); }
    .rl-tag.production { background: var(--ok); color: var(--surface); }
    .rl-tag.staging { background: var(--brand-soft); color: var(--brand); }
    .rl-log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
    .rl-log span { color: var(--muted); }
    .rl-box { background: var(--soft); border-radius: 10px; padding: 10px 14px; }
  `));

  const ENV = { production: t('Producción'), staging: t('Pruebas') };
  const v = (n) => n == null ? t('nada') : 'v' + n;
  const when = (iso) => {
    const d = new Date(iso);
    return d.toLocaleDateString(t.locale, { day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }) + ' ' + iso.slice(11, 16);
  };
  const envs = () => agent.environments || {};
  const quote = (x) => t('«{name}»', { name: x });
  const names = (list) => list.slice(0, 4).map(quote).join(', ') + (list.length > 4 ? t(' y {n} más', { n: list.length - 4 }) : '');

  // ---------- el diff en palabras ----------
  const PARTS = [['intents', t('Intenciones'), 'a'], ['entities', t('Entidades'), 'a'], ['slots', t('Slots'), 'o'], ['flows', t('Flujos'), 'o'], ['classifications', t('Clasificaciones'), 'a'], ['tests', t('Tests'), 'o']];
  const SETTINGS = { name: t('el nombre'), threshold: t('qué tan seguro tiene que estar'), fallback: t('qué responde cuando no entiende') };
  function describe(d) {
    const lines = [];
    for (const [key, label, g] of PARTS) {
      const p = d[key];
      if (!p) continue;
      const bits = [];
      const added = (n) => g === 'a' ? t.plural(n, '{n} nueva', '{n} nuevas') : t.plural(n, '{n} nuevo', '{n} nuevos');
      const removed = (n) => g === 'a' ? t.plural(n, '{n} borrada', '{n} borradas') : t.plural(n, '{n} borrado', '{n} borrados');
      if (p.added.length) bits.push(added(p.added.length) + ' (' + names(p.added) + ')');
      if (p.removed.length) bits.push(removed(p.removed.length) + ' (' + names(p.removed) + ')');
      for (const c of p.changed) {
        const what = [];
        if (c.added_phrases?.length) what.push(t.plural(c.added_phrases.length, '{n} frase nueva', '{n} frases nuevas'));
        if (c.removed_phrases?.length) what.push(t.plural(c.removed_phrases.length, '{n} frase borrada', '{n} frases borradas'));
        if (c.trigger) what.push(t('cambió cuándo arranca'));
        if (c.steps && c.steps[0] !== c.steps[1]) what.push(t.plural(c.steps[1], 'pasó de {from} a {n} paso', 'pasó de {from} a {n} pasos', { from: c.steps[0] }));
        bits.push(t('«{name}» {what}', { name: c.name, what: what.length ? what.join(', ') : t('cambió') }));
      }
      if (bits.length) lines.push(h('li', {}, h('strong', {}, label + ': '), bits.join('; ')));
    }
    if (d.settings?.length) lines.push(h('li', {}, h('strong', {}, t('Ajustes') + ': '), t('cambió {what}', { what: d.settings.map((k) => SETTINGS[k] || k).join(', ') })));
    return h('ul', { class: 'rl-diff' }, lines);
  }
  const getDiff = (from, to) => api('GET', '/' + agent.id + '/diff?from=' + from + '&to=' + (to ?? 'draft'));

  // ---------- después de cambiar un entorno ----------
  function refresh() {
    window.renderLive();
    if (section === 'releases') render();
    if ($('#chat')) renderChat();     // el selector de entorno del chat de prueba
  }
  async function deployTo(environment, version) {
    const r = await api('POST', '/' + agent.id + '/deploy', { environment, version });
    (agent.environments ||= {})[environment] = r.version;
    refresh();
    return r;
  }
  const safely = (fn) => async () => { try { await fn(); } catch (e) { alert(t('No se pudo: {error}', { error: e.message })); } };

  // chip de la barra de arriba: qué está en vivo
  window.renderLive = () => {
    const el = $('#live');
    if (!el || !agent) return;
    const p = envs().production;
    el.className = 'rl-chip' + (p != null ? ' live' : '');
    el.textContent = p != null ? t('Producción: v{n}', { n: p }) : t('Sin publicar');
    el.title = p != null ? t('La API responde con la v{n}. Tocá para ver las versiones.', { n: p }) : t('Todavía no publicaste: la API responde con el borrador. Tocá para ver las versiones.');
  };
  window.openReleases = () => { section = 'releases'; render(); $('#center').scrollTop = 0; };

  // ---------- publicar ----------
  window.publishDialog = async () => {
    await saveNow();
    const body = h('div', { class: 'stack' }, h('p', { class: 'help' }, t('Mirando qué cambió…')));
    const d = h('dialog', { class: 'rl-dialog' }, h('form', { onsubmit: (e) => e.preventDefault() }, h('h2', {}, t('Publicar')), body));
    d.onclose = () => d.remove();
    document.body.append(d); d.showModal();
    let list, change, last;
    try {
      list = await api('GET', '/' + agent.id + '/versions');
      last = list.versions[0]?.version;
      const prod = list.environments.production;
      change = prod != null ? await getDiff('production') : last != null ? await getDiff(last) : null;
      if (prod != null && last != null && last !== prod) {               // por si el borrador ya es igual a la última versión (en Pruebas, por ejemplo)
        const sinceLast = await getDiff(last);
        if (!sinceLast.changes) change = sinceLast;
      }
    } catch (e) { fill(body, h('p', { class: 'notice warn' }, t('No se pudo revisar: {error}', { error: e.message })), h('div', {}, h('button', { class: 'btn quiet', onclick: () => d.close() }, t('Cerrar')))); return; }
    const prod = list.environments.production, next = (last || 0) + 1;
    const cancel = h('button', { class: 'btn quiet', type: 'button', onclick: () => d.close() }, t('Cancelar'));
    if (change && !change.changes) {
      fill(body,
        h('p', { class: 'notice' }, t('No hay nada nuevo para publicar: el borrador es igual a la v{n}. Hacé algún cambio primero.', { n: change.from })),
        change.from !== prod ? h('p', { class: 'help' }, t('Si querés que la v{n} responda en Producción, hacelo desde ', { n: change.from }), h('button', { class: 'link', type: 'button', onclick: () => { d.close(); window.openReleases(); } }, t('Versiones')), '.') : null,
        h('div', { class: 'row' }, h('button', { class: 'btn', disabled: true }, t('Publicar')), cancel));
      return;
    }
    const note = h('textarea', { rows: 2, placeholder: t('Por ejemplo: sumé la cancelación de turnos'), maxlength: 500, oninput: (e) => grow(e.target) });
    const radio = (value, title, sub, checked) => h('label', { class: 'rl-choice' }, h('input', { type: 'radio', name: 'rl-env', value, checked }), h('span', {}, title, h('small', {}, sub)));
    const go = h('button', { class: 'btn' }, t('Publicar v{n}', { n: next }));
    const problem = h('p', { class: 'notice warn', hidden: true, role: 'alert' });
    const anyway = h('button', { class: 'btn', type: 'button', hidden: true, style: 'background:var(--warn)' }, t('Publicar igual'));
    const failed = h('div', { class: 'stack', hidden: true });
    anyway.onclick = () => go.onclick(null, true);
    go.onclick = async (e, force) => {
      const environment = d.querySelector('input[name=rl-env]:checked').value;
      go.disabled = true; cancel.disabled = true; anyway.disabled = true; go.textContent = environment === 'production' && agent.tests?.length && !force ? t('Corriendo las pruebas…') : t('Publicando…');
      try {
        await saveNow();
        let r;
        try { r = await api('POST', '/' + agent.id + '/versions', { note: note.value.trim(), environment, force: !!force }); }
        catch (err) {
          if (err.status !== 409 || !err.data?.tests) throw err;
          // fallaron pruebas: no se publicó; se muestran y se puede publicar igual (force)
          fill(failed, h('p', { class: 'notice warn', role: 'alert' }, t('No se publicó: fallaron {failed} de {total} pruebas.', { failed: err.data.tests.failed, total: err.data.tests.total })),
            window.testFailures(err.data.tests), h('button', { class: 'link', type: 'button', onclick: () => { d.close(); section = 'tests'; render(); } }, t('Ver las pruebas')));
          failed.hidden = false; anyway.hidden = false; anyway.disabled = false; problem.hidden = true;
          go.disabled = false; cancel.disabled = false; go.textContent = t('Publicar v{n}', { n: next });
          return;
        }
        (agent.environments ||= {})[environment] = r.version;
        refresh();
        fill(body,
          h('p', { class: 'notice' }, environment === 'production'
            ? t('Publicaste la v{n} en Producción.', { n: r.version }) + ' ' + (prod != null ? t('Las conversaciones que ya estaban en curso terminan con la versión anterior.') : t('Desde ahora la API responde con esta versión, y lo que sigas editando no sale en vivo hasta que publiques de nuevo.'))
            : t('Publicaste la v{n} en Pruebas. Probala en el chat eligiendo «Pruebas», o por la API con environment: "staging". Cuando esté lista, pasala a Producción desde Versiones.', { n: r.version })),
          h('div', { class: 'row' }, h('button', { class: 'btn', onclick: () => d.close() }, t('Listo')), h('button', { class: 'btn quiet', onclick: () => { d.close(); window.openReleases(); } }, t('Ver versiones'))));
      } catch (e) {
        problem.hidden = false; problem.textContent = t('No se pudo publicar: {error}', { error: e.message });
        go.disabled = false; cancel.disabled = false; go.textContent = t('Publicar v{n}', { n: next });
      }
    };
    fill(body,
      h('p', { class: 'help' }, t('Se guarda una copia fija de cómo está el bot ahora, como la v{n}. Después podés seguir editando el borrador sin que cambie.', { n: next })),
      h('h3', { style: 'margin:0;font-size:15px' }, change ? (change.from === prod ? t('Qué cambia respecto de Producción (v{n})', { n: prod }) : t('Qué cambia respecto de la v{n}', { n: change.from })) : t('Es tu primera publicación')),
      change ? h('div', { class: 'rl-box' }, describe(change))
        : h('p', { class: 'help' }, t('Va todo lo que armaste: {intents}, {flows}.', { intents: t.plural(agent.intents.length, '{n} intención', '{n} intenciones'), flows: t.plural(agent.flows.length, '{n} flujo', '{n} flujos') })),
      untrained() ? h('p', { class: 'notice warn' }, t('Hay cambios en frases o entidades que todavía no probaste en el chat. La versión se entrena sola al publicar, pero conviene entrenar y probar antes.')) : null,
      lab(t('¿Qué cambiaste?'), note),
      h('div', { class: 'stack' },
        radio('staging', t('Probar primero en Pruebas'), t('Producción sigue igual. Probala vos o tu cliente y después la pasás.'), true),
        radio('production', t('Publicar directo en Producción'), prod != null ? t('Reemplaza a la v{n} para las conversaciones nuevas.', { n: prod }) : t('La API empieza a responder con esta versión.'), false)),
      agent.tests?.length ? h('p', { class: 'help', style: 'font-size:14px' }, t.plural(agent.tests.length, 'Al publicar en Producción primero corren las {n} prueba del bot.', 'Al publicar en Producción primero corren las {n} pruebas del bot.')) : null,
      problem, failed,
      h('div', { class: 'row' }, go, anyway, cancel));
    note.focus();
  };

  // ---------- página de versiones ----------
  function useAsDraft(n, after) {
    confirmBox(t('Usar la v{n} como borrador', { n }), t('Tu borrador pasa a ser una copia de la v{n}. Los cambios que no publicaste se pierden. Las versiones publicadas y los entornos no cambian.', { n }), t('Usar la v{n}', { n }),
      safely(async () => {
        clearTimeout(timer); dirty = false;      // que el guardado automático no pise lo restaurado
        agent = await api('POST', '/' + agent.id + '/versions/' + n + '/restore');
        agent.classifications ||= [];
        sel = { intents: 0, flows: 0 };
        after?.();
        render(); renderChat(); renderTrain(); window.renderLive();
        if (untrained()) trainNow();
      }));
  }

  function envCard(key, info, list, draft) {
    const n = info.environments[key];
    const ver = list.find((x) => x.version === n);
    const lastDeploy = info.deployments.find((x) => x.environment === key);
    const actions = [];
    if (key === 'staging' && n != null && n !== info.environments.production)
      actions.push(h('button', { class: 'btn small', onclick: () => confirmBox(t('Pasar la v{n} a Producción', { n }),
        t('Las conversaciones nuevas van a usar la v{n}.', { n }) + ' ' + (info.environments.production != null ? t('Las que ya están en curso terminan con la v{n}.', { n: info.environments.production }) : t('Hasta ahora la API respondía con el borrador.')) + ' ' + t('Si algo sale mal, podés volver atrás desde acá.'),
        t('Pasar a Producción'), safely(() => deployTo('production', n))) }, t('Pasar a Producción')));
    if (key === 'production' && lastDeploy?.previous != null && lastDeploy.previous !== n)
      actions.push(h('button', { class: 'btn quiet small', onclick: () => confirmBox(t('Volver a la v{n}', { n: lastDeploy.previous }),
        t('Producción vuelve a la v{prev}. Las conversaciones nuevas la usan desde ya; las que están en curso terminan con la v{n}. La v{n} queda guardada por si querés volver a ponerla.', { prev: lastDeploy.previous, n }),
        t('Volver a la v{n}', { n: lastDeploy.previous }), safely(() => deployTo('production', lastDeploy.previous))) }, t('Volver a la versión anterior (v{n})', { n: lastDeploy.previous })));
    return h('div', { class: 'panel rl-env' + (key === 'production' ? ' prod' : '') },
      h('span', { class: 'rl-kind' }, ENV[key]),
      n != null ? h('span', { class: 'rl-big' }, 'v' + n) : h('span', { class: 'rl-big none' }, key === 'production' ? t('Responde el borrador') : t('Vacío')),
      h('p', {}, n != null
        ? (ver?.note ? quote(ver.note) + ' · ' : '') + (lastDeploy ? t('desde el {date}', { date: when(lastDeploy.at) }) : '')
        : key === 'production' ? t('Todavía no publicaste: cada cambio que hacés sale en vivo al instante.') : t('Poné una versión acá para probarla antes de que la usen tus clientes.')),
      key === 'production' ? h('p', {}, t('Es la que usa la API.')) : h('p', {}, t('Por la API, con environment: "staging".')),
      actions.length ? h('div', { class: 'row' }, actions) : null);
  }

  function draftCard(draft, info) {
    const base = draft?.from;
    return h('div', { class: 'panel rl-env' },
      h('span', { class: 'rl-kind' }, t('Borrador')),
      h('span', { class: 'rl-big' + (draft?.changes ? '' : ' none') }, draft == null ? t('Sin publicar') : draft.changes ? t.plural(draft.changes, '{n} cambio', '{n} cambios') : t('Al día')),
      h('p', {}, draft == null ? t('Es lo que estás editando. Probalo en el chat con «Borrador».')
        : draft.changes ? t('Sin publicar, respecto de la v{n}. Lo probás en el chat con «Borrador».', { n: base }) : t('Es igual a la v{n}.', { n: base })),
      h('div', { class: 'row' },
        h('button', { class: 'btn small', onclick: () => window.publishDialog() }, t('Publicar')),
        draft?.changes ? h('button', { class: 'btn danger small', onclick: () => useAsDraft(base) }, t('Descartar cambios')) : null));
  }

  function versionRow(x, info, page) {
    const out = h('div', { hidden: true });
    const show = safely(async () => {
      if (!out.hidden) { out.hidden = true; return; }
      out.hidden = false;
      fill(out, h('p', { class: 'help' }, t('Mirando…')));
      if (x.version === 1) { fill(out, h('p', { class: 'help rl-box', style: 'font-size:14px' }, t('Es la primera versión: {intents}, {flows}.', { intents: t.plural(x.stats.intents, '{n} intención', '{n} intenciones'), flows: t.plural(x.stats.flows, '{n} flujo', '{n} flujos') }))); return; }
      const d = await getDiff(x.version - 1, x.version);
      fill(out, h('div', { class: 'rl-box' }, h('p', { style: 'font-size:13px;color:var(--muted);margin-bottom:6px' }, t('Respecto de la v{n}:', { n: x.version - 1 })),
        d.changes ? describe(d) : h('p', { class: 'help', style: 'font-size:14px' }, t('No cambió nada.'))));
    });
    const inProd = x.environments.includes('production'), inStaging = x.environments.includes('staging');
    return h('div', { class: 'rl-ver' },
      h('div', { class: 'row' }, h('span', { class: 'rl-num' }, 'v' + x.version),
        x.environments.map((e) => h('span', { class: 'tag rl-tag ' + e }, ENV[e])),
        h('span', { class: 'rl-meta grow' }, when(x.created) + ' · ' + t.plural(x.stats.intents ?? 0, '{n} intención', '{n} intenciones') + ' · ' + t.plural(x.stats.flows ?? 0, '{n} flujo', '{n} flujos') + ' · ' + t.plural(x.stats.phrases ?? 0, '{n} frase', '{n} frases'))),
      h('p', { class: 'rl-note' + (x.note ? '' : ' none') }, x.note || t('Sin nota')),
      h('div', { class: 'row rl-actions' },
        inStaging ? null : h('button', { class: 'link', onclick: safely(() => deployTo('staging', x.version)) }, t('Poner en Pruebas')),
        inProd ? null : h('button', { class: 'link', onclick: () => confirmBox(t('Poner la v{n} en Producción', { n: x.version }),
          info.environments.production != null
            ? t('Las conversaciones nuevas van a usar la v{n} en lugar de la v{prev}. Las que ya están en curso terminan con la que empezaron.', { n: x.version, prev: info.environments.production })
            : t('Las conversaciones nuevas van a usar la v{n}. Hasta ahora la API respondía con el borrador.', { n: x.version }),
          t('Poner en Producción'), safely(() => deployTo('production', x.version))) }, t('Poner en Producción')),
        h('button', { class: 'link', onclick: show }, t('Ver cambios')),
        h('button', { class: 'link', onclick: () => useAsDraft(x.version) }, t('Usar como borrador'))),
      out);
  }

  window.releasesView = () => {
    const page = h('div', { class: 'page' },
      h('div', { class: 'row' }, h('h1', { class: 'grow' }, t('Versiones')), h('button', { class: 'btn', onclick: () => window.publishDialog() }, t('Publicar'))),
      h('p', { class: 'help' }, t('Lo que editás es el '), h('strong', {}, t('borrador')), t(': podés cambiarlo y probarlo sin que lo vea nadie. Cuando está listo, lo publicás y queda guardado como una '),
        h('strong', {}, t('versión')), t(' con número (v1, v2…) que ya no cambia. Cada versión se pone en un '), h('strong', {}, t('entorno')), ': ',
        h('strong', {}, t('Producción')), t(' es la que usa la API, o sea tus clientes; '), h('strong', {}, t('Pruebas')), t(' sirve para revisarla antes. Las conversaciones que ya empezaron terminan con la versión con la que arrancaron.')),
      h('p', { class: 'help' }, t('Cargando…')));
    (async () => {
      await saveNow();
      const info = await api('GET', '/' + agent.id + '/versions');
      agent.environments = info.environments;
      window.renderLive();
      const base = info.environments.production ?? info.versions[0]?.version;
      const draft = base != null ? await getDiff(base) : null;
      page.lastChild.replaceWith(
        info.environments.production == null ? h('p', { class: 'notice warn' }, t('Todavía no publicaste: la API responde con el borrador, así que cada cambio que hacés sale en vivo. Publicá para que tus clientes usen una versión fija.')) : '',
        h('div', { class: 'rl-envs' }, draftCard(draft, info), envCard('staging', info, info.versions, draft), envCard('production', info, info.versions, draft)),
        window.experimentsPanel(info, () => { if (section === 'releases') render(); }),      // A/B (static/experiments.js)
        h('div', { class: 'panel' }, h('h2', {}, t('Historial de versiones')),
          info.versions.length ? h('div', { class: 'rl-list' }, info.versions.map((x) => versionRow(x, info, page)))
            : h('div', { class: 'empty' }, t('Todavía no hay versiones. Tocá «Publicar» para guardar la primera.'))),
        info.deployments.length ? h('div', { class: 'panel' }, h('h2', {}, t('Qué se puso dónde')),
          h('ul', { class: 'rl-log' }, info.deployments.map((x) => h('li', {},
            x.version == null ? t('Se vació {env}', { env: ENV[x.environment] }) : v(x.version) + ' → ' + ENV[x.environment],
            x.previous != null ? t(' (antes v{n})', { n: x.previous }) : x.environment === 'production' ? t(' (antes el borrador)') : t(' (antes vacío)'),
            h('span', {}, ' · ' + when(x.at)))))) : null);
    })().catch((e) => { page.lastChild.replaceWith(h('p', { class: 'notice warn' }, t('No se pudieron cargar las versiones: {error}', { error: e.message }))); });
    return page;
  };
})();
