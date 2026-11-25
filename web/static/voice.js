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
  const mimeType = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find(t => MediaRecorder.isTypeSupported(t));

  async function transcribe(blob, opts) {   // -> texto (puede ser ''); tira Error con un mensaje para mostrar
    const id = window.agent && agent.id;
    const res = await fetch('/api/agents/' + encodeURIComponent(id) + '/voice/transcribe', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({audio: await toB64(blob), mime: blob.type, language: lang(opts)}),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && window.showLogin) window.showLogin();
    if (!res.ok || data.error) throw new Error(data.error || 'No pude transcribir el audio.');
    return (data.text || '').trim();
  }

  function browserSay(text, language) {     // voz del navegador: si el servidor no tiene piper
    const synth = window.speechSynthesis;
    if (!synth) return Promise.reject(new Error('La voz no está disponible.'));
    const u = new SpeechSynthesisUtterance(text);
    u.lang = language === 'es' ? 'es-AR' : language;
    u.voice = synth.getVoices().find(v => v.lang.replace('_', '-').startsWith(language)) || null;
    synth.cancel();
    return new Promise(done => { u.onend = u.onerror = done; synth.speak(u); });
  }

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
        const type = mimeType();
        rec = new MediaRecorder(s, type ? {mimeType: type} : undefined);
        const chunks = [];
        rec.ondataavailable = e => e.data && e.data.size && chunks.push(e.data);
        rec.onstop = async () => {
          stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(chunks, {type: rec.mimeType || type || 'audio/webm'});
          if (!blob.size) { state('idle'); return; }
          state('thinking');
          try {
            const text = await transcribe(blob, opts);
            state('idle');
            if (text) onText(text);
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

    hush() {                                  // corta lo que esté sonando
      ++turn;
      if (player) { player.pause(); player = null; }
      if (window.speechSynthesis) speechSynthesis.cancel();
    },

    // Lee en voz alta con piper (en el servidor); si no está, con la voz del navegador. Resuelve cuando termina de sonar.
    async speak(text, language) {
      this.hush();
      const mine = turn;
      if (!(text || '').trim()) return;
      let res;
      try {
        res = await fetch('/api/voice/speak', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({text, language: language || lang()}),
        });
      } catch (e) { res = null; }
      if (mine !== turn) return; // llegó otro speak() (o hush) mientras bajaba este
      if (!res || !res.ok) return browserSay(text, (language || lang()).split('-')[0]);
      const blob = await res.blob();
      if (mine !== turn) return;
      const a = player = new Audio(URL.createObjectURL(blob));
      await new Promise((done, fail) => {
        a.onended = a.onpause = done;
        a.onerror = () => fail(new Error('No pude reproducir el audio.'));
        a.play().catch(fail);
      }).finally(() => { URL.revokeObjectURL(a.src); if (player === a) player = null; });
    },

    // Llamada: deja el micrófono abierto. call.listen() graba hasta que la persona deja de hablar y devuelve el texto
    // (null si no habló en 15 s o se colgó). call.close() cuelga.
    async openCall() {
      if (!this.available()) throw new Error('Este navegador no permite grabar audio.');
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}}); }
      catch (e) {
        throw new Error(e && e.name === 'NotAllowedError'
          ? 'No tengo permiso para usar el micrófono. Habilitalo en el candado de la barra de direcciones.'
          : 'No encontré un micrófono disponible.');
      }
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const meter = ctx.createAnalyser();
      meter.fftSize = 1024;
      ctx.createMediaStreamSource(stream).connect(meter);
      const buf = new Float32Array(meter.fftSize);
      let closed = false, floor = 0.005;
      const level = () => { meter.getFloatTimeDomainData(buf); let sum = 0; for (const x of buf) sum += x * x; return Math.sqrt(sum / buf.length); };
      return {
        close() { closed = true; stream.getTracks().forEach(t => t.stop()); ctx.close().catch(() => {}); },
        listen(opts = {}) {
          if (closed) return Promise.resolve(null);
          ctx.resume().catch(() => {});
          // ponytail: VAD por energía con piso de ruido adaptativo; con mucho ruido de fondo corta mal -> usar un VAD de verdad (silero) si hace falta
          return new Promise((done, fail) => {
            const type = mimeType(), chunks = [];
            const rec = new MediaRecorder(stream, type ? {mimeType: type} : undefined);
            rec.ondataavailable = e => e.data && e.data.size && chunks.push(e.data);
            let spoke = 0, quiet = 0, waited = 0, finish = null;
            rec.onstop = async () => {
              if (closed || finish !== 'heard') return done(null);
              try {
                opts.onState && opts.onState('thinking');
                done(await transcribe(new Blob(chunks, {type: rec.mimeType || type || 'audio/webm'}), opts));
              } catch (e) { fail(e); }
            };
            const end = why => { finish = why; clearInterval(tick); if (rec.state !== 'inactive') rec.stop(); };
            const tick = setInterval(() => {
              if (closed) return end('closed');
              const rms = level(), loud = rms > Math.max(0.012, floor * 3);
              if (!loud) floor = floor * 0.95 + rms * 0.05;
              waited += 50;
              if (loud) { spoke += 50; quiet = 0; } else if (spoke >= 200) quiet += 50; else spoke = 0;
              if (spoke >= 200 && quiet >= (opts.silenceMs || 900)) end('heard');      // habló y se calló ~1 s
              else if (spoke < 200 && waited >= 15000) end('nothing');             // no habló: reintenta el que llama
              else if (waited >= 55000) end('heard');                              // el servidor acepta hasta 60 s
            }, 50);
            rec.start();
          });
        },
      };
    },
  };
})();
