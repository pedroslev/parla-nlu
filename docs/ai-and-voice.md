# Local AI and voice

**English** · [Español](ai-and-voice_es.md)

All of this is optional and, by default, all of it runs on your computer. Without AI, Parla works the same: the NLU
(embeddings + CRF + rules) doesn't need a language model. If you want, the AI features can also use any
[OpenAI-compatible endpoint](#openai-compatible-endpoints) (vLLM, llama.cpp, LM Studio, OpenAI, Azure OpenAI, …).

## The embedding model (always)

It isn't optional and it isn't "generative AI": it's what the NLU uses to compare phrases.

- Model: `google/embeddinggemma-300m` with [fastembed](https://github.com/qdrant/fastembed) (ONNX, CPU), with the
  prefix `task: sentence similarity | query: `. It was chosen by measuring with an appointments bot: it got more
  answers right than `paraphrase-multilingual-MiniLM` and `mpnet`, with no errors, in about 10 ms per message.
- It's used by intents, [understanding answers by meaning](#understanding-answers-by-meaning), the knowledge base
  and «Para enseñar» (To teach). It's loaded only once.
- It's downloaded the first time it's used (~1.2 GB) to `data/models/embeddings` inside the repo, even if you change
  `PARLA_DATA`. For a different folder: `PARLA_EMBED_CACHE=/ruta`.

## Installing Ollama

1. Download it from [ollama.com](https://ollama.com) and install it (or on Linux `curl -fsSL https://ollama.com/install.sh | sh`).
2. Pull the default model:
   ```sh
   ollama pull qwen2.5:0.5b
   ```
   (`scripts/setup.sh --ollama` does it for you.) You can also download it from the **IA** (AI) section with
   «Descargar» (Download).
3. In the agent, **Inteligencia → IA** (Intelligence → AI): turn it on and test the connection.

Parla talks to Ollama at `http://127.0.0.1:11434`. Ollama is the default and nothing leaves your machine. To use
another server, see [OpenAI-compatible endpoints](#openai-compatible-endpoints).

## Suggested models

| Model | Approx. size | Note |
|---|---|---|
| `qwen2.5:0.5b` (default) | 400 MB | The lightest. Fast on any computer. |
| `qwen3:0.6b` | 520 MB | Very light, a bit smarter. |
| `gemma3:1b` | 820 MB | Light, good Spanish. |
| `qwen2.5:1.5b` | 990 MB | More accurate; needs a bit more memory. |
| `llama3.2:1b` | 1.3 GB | Good at following instructions. |

With Ollama the model stays loaded for 30 minutes between messages (`keep_alive`) and a 4096-token context is
used: the first reply takes longer, the rest don't.

## Configuration (`agent.ai`)

The defaults:

```json
{"enabled": false, "provider": "ollama", "url": "http://127.0.0.1:11434", "model": "qwen2.5:0.5b",
 "temperature": 0.2, "rescue_intents": true, "use_knowledge": true, "generative_fallback": true, "persona": ""}
```

`persona` is how the bot talks («Hablás de vos, sos amable y breve.»); it's added to the requests that write text.

## OpenAI-compatible endpoints

With `"provider": "openai"` (in the UI: **Programa → Compatible con OpenAI**) every AI feature calls
`POST {url}/chat/completions` (`model`, `messages`, `temperature`, `max_tokens`, `stream: false`). That covers vLLM,
llama.cpp server, LM Studio, LocalAI, OpenAI, Azure OpenAI, Groq, OpenRouter and anything else that speaks that API.

| Field | What it is |
|---|---|
| `url` | Base URL, usually ending in `/v1` (`http://localhost:8000/v1`). A URL with no path (`http://127.0.0.1:1234`) gets `/v1` added. |
| `model` | The model id the server expects. In the UI it's free text, with suggestions from `GET {url}/models` when the server lists them. |
| `api_key_secret` | The **name** of a key in the agent's **Claves** (Keys) vault, for example `OPENAI_KEY`. The key itself is never stored in the agent JSON. The «API key» field in the AI screen saves it to the vault for you (as `AI_API_KEY` unless you already picked a name). |
| `azure` | `true` for Azure OpenAI: the key goes in the `api-key` header instead of `Authorization: Bearer`, and `?api-version=` is added (`api_version`, default `2024-10-21`). Turned on automatically for `*.openai.azure.com` URLs. |

Examples (`agent.ai`; leave `api_key_secret` out when the server has no key):

```jsonc
// vLLM (vllm serve Qwen/Qwen2.5-1.5B-Instruct)
{"enabled": true, "provider": "openai", "url": "http://localhost:8000/v1", "model": "Qwen/Qwen2.5-1.5B-Instruct"}
// llama.cpp server (llama-server -m model.gguf --port 8080)
{"enabled": true, "provider": "openai", "url": "http://localhost:8080/v1", "model": "local"}
// LM Studio (local server tab)
{"enabled": true, "provider": "openai", "url": "http://127.0.0.1:1234/v1", "model": "qwen2.5-1.5b-instruct"}
// OpenAI
{"enabled": true, "provider": "openai", "url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_secret": "OPENAI_KEY"}
// Azure OpenAI: the URL includes your deployment; "model" is ignored by Azure
{"enabled": true, "provider": "openai", "url": "https://my-resource.openai.azure.com/openai/deployments/my-gpt4o-mini",
 "model": "gpt-4o-mini", "api_key_secret": "AZURE_OPENAI_KEY", "azure": true}
// OpenRouter
{"enabled": true, "provider": "openai", "url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.1-8b-instruct", "api_key_secret": "OPENROUTER_KEY"}
// Groq
{"enabled": true, "provider": "openai", "url": "https://api.groq.com/openai/v1", "model": "llama-3.1-8b-instant", "api_key_secret": "GROQ_KEY"}
```

How it behaves:

- **Structured answers:** where Ollama gets a JSON schema (`format`), the OpenAI path sends
  `response_format: {"type": "json_object"}` plus the schema in a system message. If the server rejects
  `response_format` with a 400, Parla retries without it (JSON asked for in the prompt only, and pulled out of
  a ```` ```json ```` block if needed) and remembers that for that URL until the server restarts.
- **Status:** «Volver a mirar» calls `GET {url}/models`. Servers that don't implement it (404) show as
  "connected, try it": use **Probar conexión** (Test connection), which sends one message and shows the reply and
  the latency.
- **Errors** are shown in Spanish: 401/403 (bad or missing key, without echoing the provider's message, which often
  repeats part of the key), 404 (wrong URL or model), 429 (rate limit or no credit), 5xx and timeouts. The key is
  masked (`••••`) in every error. When the provider fails, the bot carries on as if the AI were off.
- **Downloading models** («Descargar») is Ollama-only; on other servers you load the model there.
- **Embeddings stay local** (fastembed): intents, meaning matching and the knowledge base search never call the
  provider.

**Privacy:** with a hosted provider (OpenAI, Azure, Groq, OpenRouter, …) the text of the conversations, the recent
turns, your persona and the knowledge base snippets used for an answer are sent to that provider and handled
under its terms. The AI screen warns when the URL isn't on this machine or your private network. If that's not
acceptable, use Ollama or a server you run yourself (vLLM, llama.cpp, LM Studio).

## What each feature does and its guards

The general rule: **the AI proposes and the engine decides**. If the AI is off, doesn't respond or returns
something odd, the bot carries on with its usual behavior (no AI failure ends the conversation). Model responses
are requested as JSON with a schema whenever possible.

### Rescuing intents (`rescue_intents`)

When confidence doesn't reach the threshold, or two intents are tied, the AI picks among the 5 closest (or
"none").

- It can only pick a letter from the list (JSON output with `enum`).
- Distant candidates are discarded (similarity below `max(0.25, threshold − 0.3)`).
- It's asked twice with the order reversed, because small models tend to pick the first one: it only counts if
  both answers match. The chosen intent gets its confidence raised to the threshold.

### Filling slots (`fill: "ai"`)

For a slot with `"fill": "ai"` and a `description` («el nombre y apellido»), the AI reads the value from the
message.

- Dates: if the entity is `date` or the name or description mentions a date, day, time or appointment, they're
  resolved first with `dates.py` (rules, no model).
- The value has to be written in the message: each word is looked up in the text. If the AI normalizes it («dos» →
  «2»), it's discarded.
- A second question ("is this a value of type …? yes/no") confirms it.

### Understanding answers by meaning

It doesn't use generative AI: it compares with the embedding model. Only for list entities that have `phrasings`
(the ways of saying each option). See [concepts.md](concepts.md#understanding-an-answer-by-meaning). It decides
only when it's clear:

| Threshold | Value |
|---|---|
| Minimum similarity | 0.60 |
| Lead over the second option | 0.04 |
| Lead "another action" needs over the best answer | 0.10 |

If it decides, the turn has `via: "significado"` and the trace says which phrase it matched.

### Understanding the turn with AI

When the bot is waiting for an option (list, format or date), the answer doesn't contain it and the previous steps
weren't enough, the AI reads the turn along with the recent conversation and picks what the person did: answered
with an option, asked something, asked for something else (an intent with a flow) or nothing (said hello, said
thanks). If it picked "another action" or "yes", it's asked again with the list reversed and only counts if it
matches: a bad reading could confirm an appointment.

### Questions in the middle of a question

If the answer looks like a question («¿qué es presencial?», «cuánto sale»), the knowledge base is searched first
(this works without AI). With AI, if the knowledge base has nothing, the model decides whether it's a question or an
answer with question marks («¿y el jueves hay algo?»); if it's a question, the bot says it can't answer that here
(it never makes things up) and asks again.

### Knowledge base (`use_knowledge`)

You load documents in **Inteligencia → Conocimiento** (Intelligence → Knowledge): text, HTML, a PDF or a URL (a
page of up to 3 MB). Parla splits them into chunks of about 500 characters ("P: / R:" FAQs stay together) and
searches them with the same embedding model as the NLU.

- It **also works without AI**: if a chunk reaches `knowledge_threshold` (0.75 by default), it replies with that
  chunk (up to 600 characters, without repeating the question).
- **With AI**: it writes a one- or two-sentence answer using only the 2 best chunks. The answer is discarded (and
  the chunk is shown as-is) if it has numbers that aren't in the text, a negation the text doesn't have, too many
  new words, more than 400 characters or leftovers from the prompt.
- The response has `via: "knowledge"` and `sources` with title and score.

### Generative re-prompt (`generative_fallback`)

If it didn't understand and there's nothing in the knowledge base, the AI writes a short, friendly follow-up
question.

- It has to be a question and can't contain numbers, `$`, `@` or links (that would be made-up data); otherwise a
  fixed phrase is used. It's trimmed to two sentences.
- The «Puedo ayudarte con: …» (I can help you with: …) list is built by the engine from the names of the first 8
  intents, not by the model.
- If the model isn't available, the usual `fallback` is used.

### `agent` step

An AI island inside a flow (see [concepts.md](concepts.md#agent-let-the-ai-converse)). The model returns JSON:
either it calls a function, or it replies.

- It can only call the functions listed in the step; a made-up name is rejected.
- Up to 4 function calls per turn; if it repeats the same call, it's reminded of the result and forced to answer.
  It remembers the latest results across turns.
- It only saves the slots listed in the step.
- It ends when it meets the `goal` or reaches `max_turns` (8 by default).
- With `knowledge: true` it receives, as "trusted information", the chunks scoring at least 80% of
  `knowledge_threshold`.

## Reference latencies

Measured on an M4 Mac with `qwen2.5:0.5b`, with the model already loaded. They can vary a lot on another machine.

| What | Time |
|---|---|
| Rescuing an intent | ~0.5 s |
| Filling a slot | ~0.4 s |
| Knowledge base answer | 0.2–0.3 s |
| One turn of the `agent` step | 1.6–2.2 s |
| Transcribing audio (Whisper `base`, warm) | ~0.4 s |
| Reading aloud (piper) | ~0.4 s |

## Voice

Install the extras:

```sh
scripts/setup.sh --voice
# or: .venv/bin/pip install -r requirements-voice.txt
```

You need `ffmpeg` on the system for audio formats PyAV can't open (Parla looks for it in `/opt/homebrew/bin`,
`/usr/local/bin` and `/usr/bin`, or on the `PATH`).

- **Transcription**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `base` model, CPU, int8, with a
  silence filter (VAD). `PARLA_WHISPER=tiny` if the machine is slow. The bot's words (entity values and synonyms,
  up to 600 characters) are passed as `hotwords`, so it writes «muzzarella» and not «multareza». Segments the
  model itself flags as "not speech" or as abnormal repetition are discarded (Whisper makes things up with nearly
  silent audio). Audio from 0.3 to 60 seconds.
- **Speech**: [piper](https://github.com/rhasspy/piper). Voices: `es_AR-daniela-high` (with `es_MX-claude-high` and
  `es_ES-davefx-medium` as fallbacks), `pt_BR-faber-medium`, `en_US-lessac-medium`. Any other language uses the
  Spanish voice.
- **Pre-generated phrases**: once some voice has been downloaded, every time an agent is saved Parla generates in
  the background the audio for the fixed phrases (messages, questions, handoffs to a person, the `fallback` and «No
  reconocí ese dato»), in the default language and sentence by sentence. Phrases with `{{ }}` are generated on the
  fly and aren't saved. The cache lives in `<PARLA_DATA>/models/tts-cache/` and isn't cleared automatically.
- The first time, the models (~150 MB) are downloaded to `<PARLA_DATA>/models/`.
- Only one audio is processed at a time (enough for a local server).

Where it's used:

- **Test chat**: when you click **Probar** (Test) you choose **Chat** or **Llamada (voz)** (Call (voice)). The
  chat has a microphone for dictation and a button to read replies aloud.
- **Llamada (voz)**: the whole conversation by voice, like a phone call. The browser listens with its own voice
  detector (it cuts off after ~0.5 s of silence; if you don't speak for 15 s, it keeps waiting without sending
  anything), the server transcribes, the bot replies and the reply is read sentence by sentence while the next one
  is requested. The bot's voice goes through a local WebRTC connection so the browser's echo canceller subtracts it
  from the microphone: that way you can interrupt the bot by talking. If that doesn't connect, the bot plays
  directly and doesn't hear you while it's speaking. It shows subtitles and can be muted. If the server doesn't
  have piper, it uses the browser's voice. With `localStorage['parla.voice.debug'] = '1'` the console shows levels
  and timings for each turn.
- **Widget** with `data-voice="true"`: a microphone button that records, sends to
  `POST /api/v1/bots/{bot}/audio` with `speak: true` and plays the reply.
- **API**: `POST /api/v1/bots/{bot}/audio` (see [api.md](api.md#post-apiv1botsbotaudio)).
