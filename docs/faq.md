# FAQ

**English** · [Español](faq_es.md)

**Do I need a GPU or internet?**
No. Everything runs on CPU. Internet is only needed to install and to download the models the first time (the
embedding model, ~1.2 GB; the Ollama model and the voice models, if you use them). After that, apart from the
`http` steps you build yourself, nothing leaves your machine.

**Do I need AI for the bot to work?**
No. Intents, entities, flows and the knowledge base (in extractive mode) work without a language model. AI adds:
rescuing uncertain messages, filling slots, written answers and the `agent` step.

**How many phrases per intent?**
Between 5 and 10 different ones already work well. Check the self-evaluation after training: if two intents get
confused, add phrases that tell them apart or merge them.

**I changed phrases and the chat doesn't notice.**
Click **Entrenar** (Train). The chat uses the latest trained model. While it trains, the bot keeps answering with
the previous one.

**I changed the bot and the API still answers the old way.**
The API talks to **Producción** (Production). Publish a version and put it in production. (If you never published
anything, the API uses the draft.) Conversations already in progress keep the version they started with.

**How do I roll back?**
In **Versiones** (Versions), point production to the previous version. To undo draft changes, use **Restaurar**
(Restore) on a version.

**Which languages does it work in?**
The embedding model is multilingual. The interface and dates are in Spanish; the bot's messages can be translated
to Portuguese and English, and Parla detects the language of the first message (or receives it in
`data.idioma`).

**How do I put it on my website?**
**Publicar → Widget web** (Publish → Web widget): turn it on, add your site's address and paste the `<script>`:
```html
<script src="http://127.0.0.1:8000/static/widget.js" data-bot="pizzeria" data-title="Hablá con nosotros"
        data-color="#2f6bff" data-greeting="¡Hola!" data-position="right" data-voice="false" async></script>
```
For outside users to see it, Parla has to be published behind a proxy (see [deployment.md](deployment.md)) and
the `src` has to point to that address.

**Can I talk to it by voice?**
Yes, with the voice extras installed: a microphone in the test chat and in the widget (`data-voice="true"`), and in
**Probar → Llamada (voz)** (Test → Call (voice)) a full voice conversation, like a phone call, that you can
interrupt by speaking. See [ai-and-voice.md](ai-and-voice.md#voice).

**Can the bot send a PDF or a photo?**
Yes, with the «Enviar un archivo» (Send a file) step (`file`): you upload the file from the step itself (up to
10 MB). The link is public to whoever receives it, so don't upload anything private. See
[concepts.md](concepts.md#file-send-a-file).

**Can it run on Docker or Kubernetes?**
Yes: there's a `Dockerfile`, `docker-compose.yml` and manifests in `deploy/`. See [deployment.md](deployment.md).

**Does it have WhatsApp, Telegram or phone?**
There are no built-in channels yet. The HTTP API can be used to connect it from your own bridge or IVR. WhatsApp and
telephony are on the roadmap.

**How do I hand a conversation off to a person?**
With a `handoff` step, or when the person asks for it («quiero hablar con alguien», "I want to talk to someone").
It shows up in the **Bandeja** (Inbox): there you take it over, reply and hand it back to the bot. The widget
receives those replies automatically.

**Where do I see what the bot didn't understand?**
In **Operar → Para enseñar** (Operate → To teach): grouped by similarity, with a suggested intent, so you can
teach it to an intent.

**I forgot the password of the only owner.**
With Parla stopped, move or delete `users.json` from the data folder: Parla becomes open again and you can create
the owner again (the other users and their API keys are lost).

**Are functions safe?**
They run isolated from the conversation (if they fail, the bot keeps going), but they are not a security sandbox.
Read [security.md](security.md#functions-not-a-sandbox).

**Can I use a model that isn't from Ollama?**
Yes, any local OpenAI-compatible server (LM Studio, llama.cpp server) with `provider: "openai"`.

**How do I change the theme?**
With the interface's selector: Claro (Light), Oscuro (Dark) or Colorido (Colorful). It's remembered in that
browser.

**What's the license?**
To be defined.
