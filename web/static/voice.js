// Voz para el chat de prueba: grabar -> transcribir en el servidor (local) y leer respuestas en voz alta. Sin UI propia.
(() => {
  let player = null, turn = 0; // audio sonando ahora (se corta al pedir otro); turn descarta pedidos viejos

  const toB64 = blob => new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = fail;
    r.readAsDataURL(blob);
  });

  const lang = opts => (opts && opts.language) || (window.agent && agent.languages && agent.languages[0]) || 'es';

  window.parlaVoice = {
    available() {
      return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    },

    // record(onText, {onState, onError, language, maxMs}) -> stop(). onState: 'listening'|'thinking'|'idle'|'error'
    record(onText, opts = {}) {
      const state = (s, msg) => { try { opts.onState && opts.onState(s, msg); } catch (e) { /* UI ajena */ } };
      const fail = msg => { state('error', msg); opts.onError && opts.onError(msg); };
      let rec = null, stream = null, cancelled = false, timer = null;
      const stop = () => { cancelled = !rec; clearTimeout(timer); if (rec && rec.state !== 'inactive') rec.stop(); };
      if (!this.available()) { fail('Este navegador no permite grabar audio.'); return () => {}; }
      navigator.mediaDevices.getUserMedia({audio: true}).then(s => {
        stream = s;
        if (cancelled) { s.getTracks().forEach(t => t.stop()); state('idle'); return; }
        const type = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find(t => MediaRecorder.isTypeSupported(t));
        rec = new MediaRecorder(s, type ? {mimeType: type} : undefined);
        const chunks = [];
        rec.ondataavailable = e => e.data && e.data.size && chunks.push(e.data);
        rec.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(chunks, {type: rec.mimeType || type || 'audio/webm'});
          if (!blob.size) { state('idle'); return; }
          state('thinking');
          try {
            const id = window.agent && agent.id;
            const res = await fetch('/api/agents/' + encodeURIComponent(id) + '/voice/transcribe', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({audio: await toB64(blob), mime: blob.type, language: lang(opts)}),
            });
            const data = await res.json().catch(() => ({}));
            if (res.status === 401 && window.showLogin) window.showLogin();
            if (!res.ok || data.error) throw new Error(data.error || 'No pude transcribir el audio.');
            state('idle');
            if ((data.text || '').trim()) onText(data.text.trim(), data);
            else fail('No escuché nada. Probá de nuevo, más cerca del micrófono.');
          } catch (e) { fail(e.message || 'No pude transcribir el audio.'); }
        };
        rec.start();
        state('listening');
        timer = setTimeout(stop, opts.maxMs || 55000); // el servidor acepta hasta 60 s
      }).catch(e => {
        fail(e && e.name === 'NotAllowedError'
          ? 'No tengo permiso para usar el micrófono. Habilitalo en el candado de la barra de direcciones.'
          : 'No encontré un micrófono disponible.');
      });
      return stop;
    },

    async speak(text, language) {
      if (player) { player.pause(); URL.revokeObjectURL(player.src); player = null; }
      const mine = ++turn;
      if (!(text || '').trim()) return;
      const res = await fetch('/api/voice/speak', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, language: language || lang()}),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || 'La voz no está disponible.');
      const blob = await res.blob();
      if (mine !== turn) return; // llegó otro speak() mientras bajaba este
      const a = player = new Audio(URL.createObjectURL(blob));
      a.onended = () => { URL.revokeObjectURL(a.src); if (player === a) player = null; };
      await a.play();
    },
  };
})();
