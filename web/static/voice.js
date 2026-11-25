// Voz para el chat de prueba: grabar -> transcribir en el servidor (local) y leer respuestas en voz alta. Sin UI propia.
(() => {
  let player = null, turn = 0; // audio sonando ahora (se corta al pedir otro); turn descarta pedidos viejos

  const toB64 = blob => new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = fail;
    r.readAsDataURL(blob);
  });

  // «agent» es un let de index.html: comparte el ámbito global de los scripts pero NO está en window (window.agent es undefined)
  const current = () => (typeof agent !== 'undefined' && agent) || null;
  const lang = opts => (opts && opts.language) || (current() && current().languages && current().languages[0]) || 'es';
  const mimeType = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find(t => MediaRecorder.isTypeSupported(t));

  async function transcribe(blob, opts) {   // -> texto (puede ser ''); tira Error con un mensaje para mostrar
    const id = (opts && opts.agent) || (current() && current().id);
    if (!id) throw new Error('No hay un agente abierto para transcribir el audio.');
    const res = await fetch('/api/agents/' + encodeURIComponent(id) + '/voice/transcribe', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      // context: la última pregunta del bot; el servidor la usa para que Whisper escriba bien «Bogotá», «presencial»…
      body: JSON.stringify({audio: await toB64(blob), mime: blob.type, language: lang(opts), context: (opts && opts.context) || undefined}),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && window.showLogin) window.showLogin();
    if (!res.ok || data.error) throw new Error(data.error || 'No pude transcribir el audio.');
    return (data.text || '').trim();
  }

  // localStorage['parla.voice.debug'] = '1' -> la consola muestra niveles, umbrales y decisiones del VAD (para calibrar)
  const debug = () => { try { return localStorage.getItem('parla.voice.debug') === '1'; } catch (e) { return false; } };
  const log = (...a) => { if (debug()) console.log('[voz]', ...a); };

  const TAP = `class Tap extends AudioWorkletProcessor {
    constructor() { super(); this.b = new Float32Array(512); this.n = 0; }
    process(inputs) {
      const x = inputs[0] && inputs[0][0];
      if (x) for (let i = 0; i < x.length; i++) { this.b[this.n++] = x[i]; if (this.n === 512) { this.port.postMessage(this.b.slice(0)); this.n = 0; } }
      return true;
    }
  }
  registerProcessor('parla-tap', Tap);`;

  function wav(frames, rate) {               // cuadros Float32 -> WAV 16 kHz mono 16 bits (lo que Whisper usa)
    const n = frames.reduce((a, f) => a + f.length, 0), all = new Float32Array(n);
    let k = 0; for (const f of frames) { all.set(f, k); k += f.length; }
    const ratio = rate / 16000, len = Math.floor(n / ratio), out = new DataView(new ArrayBuffer(44 + len * 2));
    const str = (o, t) => { for (let i = 0; i < t.length; i++) out.setUint8(o + i, t.charCodeAt(i)); };
    str(0, 'RIFF'); out.setUint32(4, 36 + len * 2, true); str(8, 'WAVEfmt '); out.setUint32(16, 16, true); out.setUint16(20, 1, true);
    out.setUint16(22, 1, true); out.setUint32(24, 16000, true); out.setUint32(28, 32000, true); out.setUint16(32, 2, true);
    out.setUint16(34, 16, true); str(36, 'data'); out.setUint32(40, len * 2, true);
    for (let i = 0; i < len; i++) {
      const p = i * ratio, j = Math.floor(p), t = p - j, v = all[j] + ((all[j + 1] ?? all[j]) - all[j]) * t;
      out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true);
    }
    return new Blob([out], {type: 'audio/wav'});
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

  async function loopback(ctx) {             // pc1 manda la voz del bot, pc2 la recibe y la reproduce en un <audio>
    const dest = ctx.createMediaStreamDestination();
    const pc1 = new RTCPeerConnection(), pc2 = new RTCPeerConnection();
    const audio = new Audio();
    const close = () => {
      pc1.close(); pc2.close();
      dest.stream.getTracks().forEach(t => t.stop());
      audio.pause(); audio.srcObject = null;
    };
    try {
      pc1.onicecandidate = e => e.candidate && pc2.addIceCandidate(e.candidate).catch(() => {});
      pc2.onicecandidate = e => e.candidate && pc1.addIceCandidate(e.candidate).catch(() => {});
      const track = new Promise(ok => { pc2.ontrack = e => ok(e.streams[0] || new MediaStream([e.track])); });
      pc1.addTrack(dest.stream.getAudioTracks()[0], dest.stream);
      await pc1.setLocalDescription(await pc1.createOffer());
      await pc2.setRemoteDescription(pc1.localDescription);
      await pc2.setLocalDescription(await pc2.createAnswer());
      await pc1.setRemoteDescription(pc2.localDescription);
      const connected = new Promise((ok, no) => {
        const check = () => { const s = pc2.connectionState; if (s === 'connected') ok(); else if (s === 'failed' || s === 'closed') no(new Error('WebRTC: ' + s)); };
        pc2.onconnectionstatechange = check; check();
      });
      const timeout = new Promise((ok, no) => setTimeout(() => no(new Error('WebRTC no conectó en 4 s')), 4000));
      audio.srcObject = await Promise.race([track, timeout]);
      await Promise.race([connected, timeout]);
      await audio.play();
      return {dest, close};
    } catch (e) { close(); throw e; }
  }

  window.parlaVoice = {
    log,
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

    // Desbloquea el audio: llamarlo DENTRO del click que arranca la llamada (antes de cualquier await).
    unlock() {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      ctx.resume().catch(() => {});
      return ctx;
    },

    // Llamada por WebRTC, toda en el navegador. La voz del bot sale por una conexión WebRTC local (pc1 -> pc2) y suena
    // desde un <audio> con el stream remoto: así el cancelador de eco de Chrome la trata como «la otra punta» y la
    // resta del micrófono, y la persona puede interrumpir al bot hablando (barge-in). Si el loopback no conecta,
    // suena directo (aec: false) y mientras habla el bot no se escucha el micrófono.
    // call.say(texto) -> 'done' | 'cut'; call.listen() -> texto o null (no habló en 15 s / colgó); mute(bool); close().
    async openCall(opts = {}) {
      if (!this.available() || !window.AudioContext && !window.webkitAudioContext) throw new Error('Este navegador no permite llamadas de voz.');
      const ctx = opts.ctx || this.unlock();
      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}});
      } catch (e) {
        ctx.close().catch(() => {});
        throw new Error(e && e.name === 'NotAllowedError'
          ? 'No tengo permiso para usar el micrófono. Habilitalo en el candado de la barra de direcciones y volvé a llamar.'
          : 'No encontré un micrófono disponible.');
      }
      ctx.resume().catch(() => {});
      // El micrófono crudo (PCM) por un AudioWorklet: VAD por cuadro de ~10 ms, pre-roll exacto y WAV sin MediaRecorder.
      try {
        await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([TAP], {type: 'application/javascript'})));
      } catch (e) {
        stream.getTracks().forEach(t => t.stop()); ctx.close().catch(() => {});
        throw new Error('Este navegador no permite procesar el audio del micrófono (AudioWorklet).');
      }
      const tap = new AudioWorkletNode(ctx, 'parla-tap');
      const sink = ctx.createGain();
      sink.gain.value = 0;                     // el worklet tiene que estar conectado para que corra; no suena
      ctx.createMediaStreamSource(stream).connect(tap).connect(sink).connect(ctx.destination);
      let route = null;
      try { route = await loopback(ctx); } catch (e) { console.warn('[Parla] sin loopback WebRTC, la voz suena directo:', e); }
      const RATE = ctx.sampleRate, FR_MS = 512 / RATE * 1000;
      let closed = false, muted = false, speaking = null, floor = 0.003, listener = null, echoLevel = null, calibrated = false, first = [];   // echoLevel: lo que queda del bot en el mic
      const ring = [];                         // pre-roll: los últimos ~700 ms (ventana de arranque + ~450 ms antes)
      tap.port.onmessage = e => {
        const f = e.data;
        ring.push(f); if (ring.length * FR_MS > 700) ring.shift();
        if (!listener) return;
        let sum = 0; for (let i = 0; i < f.length; i++) sum += f[i] * f[i];
        listener(f, muted ? 0 : Math.sqrt(sum / f.length));
      };
      const agentId = opts.agent;
      const abort = new AbortController();     // al colgar se cancelan los pedidos de voz que estén en camino
      const sources = new Set();               // y se paran todos los audios del bot ya programados

      const call = {
        aec: !!route,
        mute(on) { muted = !!on; stream.getAudioTracks().forEach(t => { t.enabled = !muted; }); },
        stopSpeaking() { if (speaking) speaking.stop(); },
        close() {                              // después de esto no puede sonar nada de la llamada
          if (closed) return;
          closed = true;
          abort.abort();
          call.stopSpeaking();
          sources.forEach(src => { try { src.onended && src.onended(); src.stop(); src.disconnect(); } catch (e) { /* ya paró */ } });
          sources.clear();
          if (window.speechSynthesis) speechSynthesis.cancel();
          if (listener) listener(null, 0);
          tap.port.onmessage = null;
          try { tap.disconnect(); } catch (e) { /* ya desconectado */ }
          stream.getTracks().forEach(t => t.stop());
          if (route) route.close();
          ctx.close().catch(() => {});
        },

        // Lee la respuesta oración por oración: mientras suena una ya se pide la siguiente (un TTS lento igual arranca rápido).
        // El servidor tiene en caché cada oración partida con esta misma regex: no cambiarla sin cambiar parla/server.py.
        // onPlay() avisa cuando empieza a sonar de verdad. -> 'done' | 'cut' (la interrumpieron o colgaron)
        async say(text, language, onPlay) {
          const language2 = (language || lang(opts)).split('-')[0];
          const parts = String(text || '').split(/\n+|(?<=[.!?…])\s+/).map(t => t.trim()).filter(Boolean);
          let cut = false, started = false, src = null;
          // sentenceAt: el VAD mide el eco que queda (sobre todo en los primeros 300 ms de cada oración) y pide un margen claro encima
          const turn = {bargeable: !!route, sentenceAt: 0, stop() { cut = true; try { src && src.stop(); } catch (e) { /* ya paró */ } window.speechSynthesis && speechSynthesis.cancel(); }};
          const synth = t => closed ? Promise.reject(new Error('colgó')) : fetch('/api/voice/speak', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: t, language: language2}), signal: abort.signal})
            .then(async r => closed ? Promise.reject(new Error('colgó')) : r.ok ? ctx.decodeAudioData(await r.arrayBuffer()) : Promise.reject(new Error((await r.json().catch(() => ({}))).error || 'La voz del bot no está disponible.')));
          const play = audio => new Promise(done => {
            if (closed || cut) return done();
            src = ctx.createBufferSource();
            src.buffer = audio;
            src.connect(route ? route.dest : ctx.destination);
            const me = src;
            sources.add(me);
            src.onended = () => { me.onended = null; sources.delete(me); done(); };
            turn.sentenceAt = performance.now();
            src.start();
          });
          speaking = turn;                       // dura toda la respuesta (también entre oraciones): hablar encima la corta
          let next = parts.length ? synth(parts[0]).catch(e => e) : null;
          for (let i = 0; i < parts.length && !cut && !closed; i++) {
            const audio = await next;
            if (cut || closed) break;              // antes de pedir la siguiente: al colgar no sale ningún pedido nuevo
            next = i + 1 < parts.length ? synth(parts[i + 1]).catch(e => e) : null;
            if (!started) { started = true; onPlay && onPlay(); }
            if (audio instanceof Error) {          // sin TTS en el servidor: la voz del navegador (no pasa por WebRTC, no se interrumpe)
              if (!window.speechSynthesis) { speaking = null; throw audio; }
              turn.bargeable = false;
              await browserSay(parts[i], language2);
              turn.bargeable = !!route;
            } else await play(audio);
          }
          speaking = null;
          return cut || closed ? 'cut' : 'done';
        },

        // ponytail: VAD por energía con piso de ruido adaptativo (y piso de eco mientras habla el bot); con mucho ruido de
        // fondo corta mal -> un VAD entrenado (silero) en el mismo worklet si hace falta.
        // o: {language, context (la última pregunta del bot, para el ASR), onState, onBargeIn}
        listen(o = {}) {
          if (closed) return Promise.resolve(null);
          // MIN_BARGE es corto a propósito: mientras suena el bot el cancelador de eco de Chrome atenúa a la persona (doble
          // conversación) y de un «Bogotá» pasan ~110 ms; a cambio pide un pico claro (no lo dispara un ruidito, sí puede una tos fuerte)
          const MIN_SPEECH = 220, MIN_BARGE = 100, SILENCE = o.silenceMs || 520;
          return new Promise((done, fail) => {
            let spoke = 0, peak = 0, quiet = 0, idle = 0, utt = null, uttMs = 0, logAt = 0, endAt = 0;
            const dbg = debug();
            const finish = (v, err) => { listener = null; err ? fail(err) : done(v); };
            listener = (f, rms) => {
              if (!f) return finish(null);         // colgó
              const now = performance.now();
              let thr = Math.max(0.01, floor * 3), mode = '-';
              if (speaking && !speaking.bargeable) mode = 'eco';       // sin cancelación de eco lo que entra es el bot
              else if (speaking && speaking.sentenceAt) {
                // Los primeros 300 ms de cada oración recalibran el eco rápido; si la persona habla ahí cuenta igual contra el
                // eco ya medido (así no «envenena» la calibración). Solo la primera oración de la llamada no se puede cortar al toque.
                const calib = now - speaking.sentenceAt < 300;
                if (!calibrated && !calib && first.length) {   // la mediana: si justo habló la persona, no se la toma por eco
                  echoLevel = first.sort((a, b) => a - b)[first.length >> 1]; calibrated = true;
                }
                mode = !calibrated ? 'calibra' : calib ? 'bot+calibra' : 'bot';
                if (calibrated) thr = Math.max(thr, echoLevel * 3, echoLevel + 0.008);
              }
              const loud = mode !== 'eco' && mode !== 'calibra' && rms > thr;
              if (!loud && !speaking) floor = Math.min(0.05, floor * 0.97 + rms * 0.03);
              if (mode === 'calibra') first.push(rms);
              else if (!loud && mode !== '-' && mode !== 'eco') {
                const k = mode === 'bot' ? 0.03 : 0.2;
                echoLevel = echoLevel * (1 - k) + rms * k;
              }
              if (dbg && now - logAt > 200) { logAt = now; log('nivel', rms.toFixed(4), 'umbral', thr.toFixed(4), 'piso', floor.toFixed(4), 'modo', mode, 'voz', Math.round(spoke), utt ? 'grabando ' + Math.round(uttMs) : ''); }
              if (!utt) {
                spoke = loud ? spoke + FR_MS : Math.max(0, spoke - FR_MS / 3);   // aguanta las pausas entre sílabas; una tos no llega
                peak = spoke ? Math.max(peak, rms) : 0;
                if (speaking ? spoke >= MIN_BARGE && peak >= Math.max(0.04, thr * 4) : spoke >= MIN_SPEECH) {
                  utt = ring.slice(); uttMs = utt.length * FR_MS;              // arranca con el pre-roll: no se pierde la primera sílaba
                  if (speaking) { speaking.stop(); log('barge-in: corto al bot', rms.toFixed(4), '>', thr.toFixed(4)); o.onBargeIn && o.onBargeIn(); }
                  else log('empezó a hablar', rms.toFixed(4), '>', thr.toFixed(4));
                  o.onState && o.onState('listening');
                  return;
                }
                if (!speaking) idle += FR_MS;
                if (idle >= 15000) finish(null);
                return;
              }
              utt.push(f); uttMs += FR_MS;
              quiet = loud ? 0 : quiet + FR_MS;
              if (quiet >= SILENCE || uttMs >= 55000) {     // el servidor acepta hasta 60 s
                listener = null; endAt = now;
                log('fin de la frase:', Math.round(uttMs), 'ms de audio, silencio', Math.round(quiet), 'ms');
                o.onState && o.onState('thinking');
                transcribe(wav(utt, RATE), {agent: agentId, language: o.language, context: o.context})
                  .then(text => { log('transcripción en', Math.round(performance.now() - endAt), 'ms:', text); done(text); }, fail);
              }
            };
          });
        },
      };
      return call;
    },
  };
})();
