# IA local y voz

Todo es opcional y todo corre en tu compu. Sin IA, Parla funciona igual: el NLU (embeddings + CRF + reglas) no
necesita un modelo de lenguaje.

## Instalar Ollama

1. Bajalo de [ollama.com](https://ollama.com) e instalalo (o en Linux `curl -fsSL https://ollama.com/install.sh | sh`).
2. Bajá el modelo por defecto:
   ```sh
   ollama pull qwen2.5:0.5b
   ```
   (`scripts/setup.sh` ofrece hacerlo por vos.) También se puede bajar desde la sección **IA** con «Descargar».
3. En el agente, **Inteligencia → IA**: prendela y probá la conexión.

Parla habla con Ollama en `http://127.0.0.1:11434`. También acepta un servidor local compatible con OpenAI (LM
Studio, llama.cpp server): `provider: "openai"` y su URL. No usa servicios en la nube.

## Modelos sugeridos

| Modelo | Tamaño aprox. | Nota |
|---|---|---|
| `qwen2.5:0.5b` (por defecto) | 400 MB | El más liviano. Rápido en cualquier compu. |
| `qwen3:0.6b` | 520 MB | Muy liviano, un poco más listo. |
| `gemma3:1b` | 820 MB | Liviano, buen español. |
| `qwen2.5:1.5b` | 990 MB | Más preciso; necesita algo más de memoria. |
| `llama3.2:1b` | 1,3 GB | Buen seguidor de instrucciones. |

El modelo queda cargado 30 minutos entre mensajes: la primera respuesta tarda más, las demás no.

## Configuración (`agent.ai`)

```json
{"enabled": true, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
 "temperature": 0.2, "rescue_intents": true, "use_knowledge": true, "generative_fallback": true,
 "persona": "Hablás de vos, sos amable y breve."}
```

## Qué hace cada función y sus guardas

La regla general: **la IA propone y el motor decide**. Si la IA está apagada, no responde o devuelve algo raro,
el bot sigue con el comportamiento de siempre (ninguna falla de la IA corta la conversación).

### Rescatar intenciones (`rescue_intents`)

Cuando la confianza no llega al umbral, o dos intenciones están empatadas, la IA elige entre las 5 más parecidas
(o «ninguna»).

- Solo puede elegir un nombre de la lista (salida JSON con `enum`).
- Se descartan candidatas lejanas (similitud menor a `max(0.25, umbral − 0.3)`).
- Se pregunta dos veces con el orden invertido, porque los modelos chicos tienden a elegir la primera: solo vale
  si las dos respuestas coinciden.

### Completar slots (`fill: "ai"`)

Para un slot con `"fill": "ai"` y una `description` («el nombre y apellido»), la IA lee el valor del mensaje.

- El valor tiene que estar escrito en el mensaje: cada palabra se busca en el texto. Si la IA normaliza («dos» →
  «2»), se descarta.
- Una segunda pregunta («¿esto es un dato del tipo …? sí/no») confirma.
- Fechas: se resuelven con `dates.py` (reglas, sin modelo) antes de llamar a la IA.

### Base de conocimiento (`use_knowledge`)

Cargás documentos en **Inteligencia → Conocimiento**: texto, HTML, una URL o un PDF. Parla los parte en
fragmentos (las preguntas frecuentes «P: / R:» quedan juntas) y los busca con el mismo modelo de vectores del NLU.

- **Sin IA** también funciona: si un fragmento supera `knowledge_threshold` (0.55), responde con ese fragmento.
- **Con IA**: arma una respuesta corta usando solo los 2 mejores fragmentos. Se descarta (y se muestra el
  fragmento tal cual) si tiene números que no están en el texto, una negación que el texto no tiene, demasiadas
  palabras nuevas, más de 400 caracteres o restos del prompt.
- La respuesta trae `via: "knowledge"` y `sources` con título y puntaje.

### Repregunta generativa (`generative_fallback`)

Si no entendió y no hay nada en el conocimiento, la IA escribe una repregunta corta y amable.

- Tiene que ser una pregunta y no puede tener números, `$`, `@` ni links (sería un dato inventado); si no, se usa
  una frase fija.
- La lista de «Puedo ayudarte con: …» la arma el motor con los nombres de las intenciones, no el modelo.

### Paso `agent`

Una isla de IA dentro de un flujo (ver [concepts.md](concepts.md#agent-dejar-que-la-ia-converse)). El modelo
devuelve JSON: o llama a una función, o responde.

- Solo puede llamar a las funciones listadas en el paso; un nombre inventado se rechaza.
- Hasta 4 llamadas a funciones por turno; si repite la misma llamada se le recuerda el resultado y se lo obliga a
  contestar.
- Solo guarda los slots listados en el paso.
- Termina al cumplir `goal` o al llegar a `max_turns` (8 por defecto).
- Con `knowledge: true` recibe los fragmentos relevantes como «información confiable».

## Latencias de referencia

Medidas en una Mac con M4 y `qwen2.5:0.5b`, con el modelo ya cargado. En otra máquina pueden variar mucho.

| Qué | Tiempo |
|---|---|
| Rescatar intención | ~0,5 s |
| Completar un slot | ~0,4 s |
| Respuesta de la base de conocimiento | 0,2–0,3 s |
| Un turno del paso `agent` | 1,6–2,2 s |
| Transcribir audio (Whisper `base`, en caliente) | ~0,4 s |
| Leer en voz alta (piper) | ~0,4 s |

## Voz

Instalá los extras:

```sh
scripts/setup.sh --voice
# o: .venv/bin/pip install -r requirements-voice.txt
```

Hace falta `ffmpeg` en el sistema para algunos formatos de audio del navegador (Parla lo busca en
`/opt/homebrew/bin`, `/usr/local/bin` y `/usr/bin`, o en el `PATH`).

- **Transcripción**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) modelo `base`, CPU, int8.
  `PARLA_WHISPER=tiny` si la máquina es lenta. Las palabras del bot (valores y sinónimos de entidades) se pasan
  como pista, para que escriba «muzzarella» y no «multareza». Audios de hasta 60 segundos.
- **Voz**: [piper](https://github.com/rhasspy/piper). Voces: `es_AR-daniela-high` (con `es_MX-claude-high` y
  `es_ES-davefx-medium` de respaldo), `pt_BR-faber-medium`, `en_US-lessac-medium`.
- La primera vez se bajan los modelos (~150 MB) a la carpeta de modelos de Parla.
- Un solo audio se procesa a la vez (alcanza para un servidor local).

Dónde se usa: el micrófono del chat de prueba, el widget con `data-voice="true"` y el endpoint
`POST /api/v1/bots/{bot}/audio` (ver [api.md](api.md#audio-post-botsbotaudio)).
