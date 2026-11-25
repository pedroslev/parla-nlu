# IA local y voz

[English](ai-and-voice.md) · **Español**

Todo es opcional y, por defecto, todo corre en tu compu. Sin IA, Parla funciona igual: el NLU (embeddings + CRF +
reglas) no necesita un modelo de lenguaje. Si querés, las funciones de IA también pueden usar cualquier
[endpoint compatible con OpenAI](#endpoints-compatibles-con-openai) (vLLM, llama.cpp, LM Studio, OpenAI, Azure OpenAI, …).

## El modelo de vectores (siempre)

No es opcional ni es «IA generativa»: es lo que usa el NLU para comparar frases.

- Modelo: `google/embeddinggemma-300m` con [fastembed](https://github.com/qdrant/fastembed) (ONNX, CPU), con el
  prefijo `task: sentence similarity | query: `. Se eligió midiendo con un bot de citas: acertó más respuestas que
  `paraphrase-multilingual-MiniLM` y `mpnet`, sin errores, en unos 10 ms por mensaje.
- Lo usan las intenciones, [entender respuestas por significado](#entender-respuestas-por-significado), la base de
  conocimiento y «Para enseñar». Se carga una sola vez.
- Se baja la primera vez que se usa (~1,2 GB) a `data/models/embeddings` dentro del repo, aunque cambies
  `PARLA_DATA`. Para otra carpeta: `PARLA_EMBED_CACHE=/ruta`.

## Instalar Ollama

1. Bajalo de [ollama.com](https://ollama.com) e instalalo (o en Linux `curl -fsSL https://ollama.com/install.sh | sh`).
2. Bajá el modelo por defecto:
   ```sh
   ollama pull qwen2.5:0.5b
   ```
   (`scripts/setup.sh --ollama` lo hace por vos.) También se puede bajar desde la sección **IA** con «Descargar».
3. En el agente, **Inteligencia → IA**: prendela y probá la conexión.

Parla habla con Ollama en `http://127.0.0.1:11434`. Ollama es lo que viene por defecto y nada sale de tu máquina.
Para usar otro servidor, mirá [Endpoints compatibles con OpenAI](#endpoints-compatibles-con-openai).

## Modelos sugeridos

| Modelo | Tamaño aprox. | Nota |
|---|---|---|
| `qwen2.5:0.5b` (por defecto) | 400 MB | El más liviano. Rápido en cualquier compu. |
| `qwen3:0.6b` | 520 MB | Muy liviano, un poco más listo. |
| `gemma3:1b` | 820 MB | Liviano, buen español. |
| `qwen2.5:1.5b` | 990 MB | Más preciso; necesita algo más de memoria. |
| `llama3.2:1b` | 1,3 GB | Buen seguidor de instrucciones. |

Con Ollama el modelo queda cargado 30 minutos entre mensajes (`keep_alive`) y se usa un contexto de 4096 tokens: la
primera respuesta tarda más, las demás no.

## Configuración (`agent.ai`)

Los valores por defecto:

```json
{"enabled": false, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
 "temperature": 0.2, "rescue_intents": true, "use_knowledge": true, "generative_fallback": true, "persona": ""}
```

`persona` es cómo habla el bot («Hablás de vos, sos amable y breve.»); se suma a los pedidos que redactan texto.

## Endpoints compatibles con OpenAI

Con `"provider": "openai"` (en la interfaz: **Programa → Compatible con OpenAI**) cada función de IA llama a
`POST {url}/chat/completions` (`model`, `messages`, `temperature`, `max_tokens`, `stream: false`). Sirve para vLLM,
llama.cpp server, LM Studio, LocalAI, OpenAI, Azure OpenAI, Groq, OpenRouter y cualquier otro que hable esa API.

| Campo | Qué es |
|---|---|
| `url` | La dirección base, casi siempre terminada en `/v1` (`http://localhost:8000/v1`). Si no tiene ruta (`http://127.0.0.1:1234`), se le agrega `/v1`. |
| `model` | El id del modelo que espera el servidor. En la interfaz es texto libre, con sugerencias de `GET {url}/models` cuando el servidor las da. |
| `api_key_secret` | El **nombre** de una clave de la sección **Claves** del agente, por ejemplo `OPENAI_KEY`. La key nunca se guarda en el JSON del agente. El campo «API key» de la pantalla IA la guarda en Claves por vos (como `AI_API_KEY` si no elegiste otro nombre). |
| `azure` | `true` para Azure OpenAI: la key va en el encabezado `api-key` en vez de `Authorization: Bearer` y se agrega `?api-version=` (`api_version`, por defecto `2024-10-21`). Se prende solo con direcciones `*.openai.azure.com`. |

Ejemplos (`agent.ai`; sin `api_key_secret` si el servidor no pide key):

```jsonc
// vLLM (vllm serve Qwen/Qwen2.5-1.5B-Instruct)
{"enabled": true, "provider": "openai", "url": "http://localhost:8000/v1", "model": "Qwen/Qwen2.5-1.5B-Instruct"}
// llama.cpp server (llama-server -m modelo.gguf --port 8080)
{"enabled": true, "provider": "openai", "url": "http://localhost:8080/v1", "model": "local"}
// LM Studio (pestaña del servidor local)
{"enabled": true, "provider": "openai", "url": "http://127.0.0.1:1234/v1", "model": "qwen2.5-1.5b-instruct"}
// OpenAI
{"enabled": true, "provider": "openai", "url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_secret": "OPENAI_KEY"}
// Azure OpenAI: la URL incluye tu deployment; Azure ignora "model"
{"enabled": true, "provider": "openai", "url": "https://mi-recurso.openai.azure.com/openai/deployments/mi-gpt4o-mini",
 "model": "gpt-4o-mini", "api_key_secret": "AZURE_OPENAI_KEY", "azure": true}
// OpenRouter
{"enabled": true, "provider": "openai", "url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.1-8b-instruct", "api_key_secret": "OPENROUTER_KEY"}
// Groq
{"enabled": true, "provider": "openai", "url": "https://api.groq.com/openai/v1", "model": "llama-3.1-8b-instant", "api_key_secret": "GROQ_KEY"}
```

Cómo se comporta:

- **Respuestas estructuradas:** donde a Ollama se le pasa un JSON schema (`format`), por acá se manda
  `response_format: {"type": "json_object"}` más el esquema en un mensaje de sistema. Si el servidor rechaza
  `response_format` con un 400, Parla reintenta sin él (el JSON se pide solo en el prompt y se saca de un bloque
  ```` ```json ```` si hace falta) y lo recuerda para esa URL hasta que se reinicia el servidor.
- **Estado:** «Volver a mirar» llama a `GET {url}/models`. Los servidores que no lo tienen (404) quedan como
  «conectado, probalo»: usá **Probar conexión**, que manda un mensaje y muestra la respuesta y cuánto tardó.
- **Errores** en castellano: 401/403 (key mala o faltante, sin repetir el mensaje del proveedor, que suele incluir
  parte de la key), 404 (dirección o modelo equivocados), 429 (límite de pedidos o sin crédito), 5xx y timeouts.
  La key se tapa (`••••`) en todos los errores. Si el proveedor falla, el bot sigue como si la IA estuviera apagada.
- **Descargar modelos** («Descargar») es solo para Ollama; en los otros servidores el modelo se carga ahí.
- **Los embeddings siguen siendo locales** (fastembed): las intenciones, el significado y la búsqueda en la base de
  conocimiento nunca llaman al proveedor.

**Privacidad:** con un proveedor en la nube (OpenAI, Azure, Groq, OpenRouter, …) el texto de las conversaciones,
los turnos recientes, la persona y los fragmentos de la base de conocimiento que se usan para responder se mandan
a ese proveedor y quedan sujetos a sus condiciones. La pantalla IA avisa cuando la dirección no es de esta compu ni
de tu red privada. Si eso no sirve, usá Ollama o un servidor propio (vLLM, llama.cpp, LM Studio).

## Qué hace cada función y sus guardas

La regla general: **la IA propone y el motor decide**. Si la IA está apagada, no responde o devuelve algo raro,
el bot sigue con el comportamiento de siempre (ninguna falla de la IA corta la conversación). Las respuestas del
modelo se piden en JSON con un esquema siempre que se puede.

### Rescatar intenciones (`rescue_intents`)

Cuando la confianza no llega al umbral, o dos intenciones están empatadas, la IA elige entre las 5 más parecidas
(o «ninguna»).

- Solo puede elegir una letra de la lista (salida JSON con `enum`).
- Se descartan candidatas lejanas (similitud menor a `max(0.25, umbral − 0.3)`).
- Se pregunta dos veces con el orden invertido, porque los modelos chicos tienden a elegir la primera: solo vale
  si las dos respuestas coinciden. La intención elegida queda con la confianza llevada al umbral.

### Completar slots (`fill: "ai"`)

Para un slot con `"fill": "ai"` y una `description` («el nombre y apellido»), la IA lee el valor del mensaje.

- Fechas: si la entidad es `date` o el nombre o la descripción hablan de fecha, día, hora o turno, se resuelven
  primero con `dates.py` (reglas, sin modelo).
- El valor tiene que estar escrito en el mensaje: cada palabra se busca en el texto. Si la IA normaliza («dos» →
  «2»), se descarta.
- Una segunda pregunta («¿esto es un dato del tipo …? sí/no») confirma.

### Entender respuestas por significado

No usa la IA generativa: compara con el modelo de vectores. Solo para entidades de lista que tienen `phrasings`
(las formas de decir cada opción). Ver [concepts.md](concepts_es.md#entender-una-respuesta-por-significado). Decide
solo si está claro:

| Umbral | Valor |
|---|---|
| Similitud mínima | 0.60 |
| Ventaja sobre la segunda opción | 0.04 |
| Ventaja que necesita «otra acción» sobre la mejor respuesta | 0.10 |

Si decide, el turno trae `via: "significado"` y la traza dice a qué frase se pareció.

### Entender el turno con IA

Cuando el bot espera una opción (lista, formato o fecha), la respuesta no la trae y lo anterior no alcanzó, la IA
lee el turno con la charla reciente y elige qué hizo la persona: contestó una opción, preguntó algo, pidió otra cosa
(una intención con flujo) o nada (saludó, agradeció). Si eligió «otra acción» o «sí», se pregunta de nuevo con la
lista al revés y solo vale si coincide: una mala lectura podría confirmar una cita.

### Preguntas en medio de una pregunta

Si la respuesta parece una pregunta («¿qué es presencial?», «cuánto sale»), primero se busca en la base de
conocimiento (esto funciona sin IA). Con IA, si la base no tiene nada, el modelo decide si es una pregunta o una
respuesta con signos de pregunta («¿y el jueves hay algo?»); si es una pregunta, el bot dice que no puede responder
eso por acá (nunca inventa) y vuelve a preguntar.

### Base de conocimiento (`use_knowledge`)

Cargás documentos en **Inteligencia → Conocimiento**: texto, HTML, un PDF o una URL (una página de hasta 3 MB). Parla los parte
en fragmentos de unos 500 caracteres (las preguntas frecuentes «P: / R:» quedan juntas) y los busca con el mismo
modelo de vectores del NLU.

- **Sin IA** también funciona: si un fragmento llega a `knowledge_threshold` (0.75 por defecto), responde con ese
  fragmento (hasta 600 caracteres, sin repetir la pregunta).
- **Con IA**: arma una respuesta de una o dos oraciones usando solo los 2 mejores fragmentos. Se descarta (y se
  muestra el fragmento tal cual) si tiene números que no están en el texto, una negación que el texto no tiene,
  demasiadas palabras nuevas, más de 400 caracteres o restos del prompt.
- La respuesta trae `via: "knowledge"` y `sources` con título y puntaje.

### Repregunta generativa (`generative_fallback`)

Si no entendió y no hay nada en el conocimiento, la IA escribe una repregunta corta y amable.

- Tiene que ser una pregunta y no puede tener números, `$`, `@` ni links (sería un dato inventado); si no, se usa
  una frase fija. Se recorta a dos oraciones.
- La lista de «Puedo ayudarte con: …» la arma el motor con los nombres de las primeras 8 intenciones, no el modelo.
- Si el modelo no está disponible, se usa el `fallback` de siempre.

### Paso `agent`

Una isla de IA dentro de un flujo (ver [concepts.md](concepts_es.md#agent-dejar-que-la-ia-converse)). El modelo
devuelve JSON: o llama a una función, o responde.

- Solo puede llamar a las funciones listadas en el paso; un nombre inventado se rechaza.
- Hasta 4 llamadas a funciones por turno; si repite la misma llamada se le recuerda el resultado y se lo obliga a
  contestar. Recuerda los últimos resultados entre turnos.
- Solo guarda los slots listados en el paso.
- Termina al cumplir `goal` o al llegar a `max_turns` (8 por defecto).
- Con `knowledge: true` recibe como «información confiable» los fragmentos con puntaje de al menos el 80 % de
  `knowledge_threshold`.

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

Hace falta `ffmpeg` en el sistema para los formatos de audio que PyAV no abre (Parla lo busca en
`/opt/homebrew/bin`, `/usr/local/bin` y `/usr/bin`, o en el `PATH`).

- **Transcripción**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) modelo `base`, CPU, int8, con
  filtro de silencio (VAD). `PARLA_WHISPER=tiny` si la máquina es lenta. Las palabras del bot (valores y sinónimos
  de entidades, hasta 600 caracteres) se pasan como `hotwords`, para que escriba «muzzarella» y no «multareza». Se
  descartan los pedazos que el propio modelo marca como «no es voz» o como repetición anormal (Whisper inventa con
  audio casi mudo). Audios de 0,3 a 60 segundos.
- **Voz**: [piper](https://github.com/rhasspy/piper). Voces: `es_AR-daniela-high` (con `es_MX-claude-high` y
  `es_ES-davefx-medium` de respaldo), `pt_BR-faber-medium`, `en_US-lessac-medium`. Otro idioma usa la voz en español.
- **Frases pregeneradas**: con alguna voz ya bajada, cada vez que se guarda un agente Parla genera en segundo plano el
  audio de las frases fijas (mensajes, preguntas, pases a persona, el `fallback` y el «No reconocí ese dato»), en el
  idioma por defecto y oración por oración. Las frases con `{{ }}` se generan en el momento y no se guardan. La caché
  vive en `<PARLA_DATA>/models/tts-cache/` y no se borra sola.
- La primera vez se bajan los modelos (~150 MB) a `<PARLA_DATA>/models/`.
- Un solo audio se procesa a la vez (alcanza para un servidor local).

Dónde se usa:

- **Chat de prueba**: al tocar **Probar** elegís **Chat** o **Llamada (voz)**. En el chat hay micrófono para
  dictar y un botón para leer las respuestas en voz alta.
- **Llamada (voz)**: la conversación entera por voz, como por teléfono. El navegador escucha con un detector de voz
  propio (corta al quedar ~0,5 s en silencio; si no hablás en 15 s, sigue esperando sin mandar nada), el servidor
  transcribe, el bot contesta y la respuesta se lee oración por oración mientras se pide la siguiente. La voz del bot
  pasa por una conexión WebRTC local para que el cancelador de eco del navegador la reste del micrófono: así podés
  interrumpir al bot hablando. Si eso no conecta, el bot suena directo y no te escucha mientras habla. Muestra
  subtítulos y se puede silenciar. Si el servidor no tiene piper, usa la voz del navegador. Con
  `localStorage['parla.voice.debug'] = '1'` la consola muestra niveles y tiempos de cada turno.
- **Widget** con `data-voice="true"`: un botón de micrófono que graba, manda a
  `POST /api/v1/bots/{bot}/audio` con `speak: true` y reproduce la respuesta.
- **API**: `POST /api/v1/bots/{bot}/audio` (ver [api.md](api_es.md#post-apiv1botsbotaudio)).
