# Getting started: your first bot

**English** · [Español](getting-started_es.md)

We're going to build a pizzeria bot that takes orders: it understands «quiero una pizza de muzza» ("I want a
mozzarella pizza"), asks for whatever is missing and confirms. It takes about 15 minutes. (If you want to see a
finished one, import `examples/pizzeria.json` with **Import agent**.)

The bot's phrases below are in Spanish, since Parla bots are aimed at Spanish-speaking users.

## 0. Install and open

```sh
scripts/setup.sh     # or: make setup
make run             # or: .venv/bin/python app.py
```

Open `http://127.0.0.1:8000`. The first time it trains, Parla downloads the embedding model (~1.2 GB, only once).
Python 3.11 or newer is required. If you prefer a container, see [deployment.md](deployment.md).

In **Your agents**, create a new agent and give it a name, for example «Pizzería».

## 1. Intents: what it has to understand

In **Build → Intents**, create two:

- `Saludar` (greet): «hola», «buenas», «buen día», «qué tal».
- `Pedir pizza` (order pizza): «quiero una pizza», «me mandás una de muzza», «quiero pedir», «dos de fugazza»,
  «quiero hacer un pedido».

5 to 10 different phrases per intent already work well. Vary the words, not just the ending.

## 2. Entities: what data to pull out of the message

In **Entities**, create:

- `gusto` (flavor), of type **From a list of options**, with values `muzzarella`,
  `fugazza`, `napolitana`. In synonyms, set «muzza» to mean `muzzarella`.
- `cantidad` (quantity), of type **A number**.

Now mark the data inside the phrases. In the `Pedir pizza` intent, select «muzza» in «me mandás una de muzza» and
choose `gusto`. Internally it looks like this:

```
me mandás una de [muzza](gusto)
[dos](cantidad) de [fugazza](gusto)
```

Marking matters most for entities of type **From the examples I mark in the
phrases**, for example a name: there Parla learns from context and recognizes new values. With 3 or more
marked examples in different phrases it recognizes them better.

## 3. Slots: what to remember

In **Slots**, create `gusto` (connected to the `gusto` entity) and `cantidad` (connected to `cantidad`). A slot is
the conversation's memory: when the person says a flavor, it is stored in the `gusto` slot.

## 4. Flows: what to do

In **Flows**, create:

**Saludo** (Greeting; triggered by `Saludar`):
1. Send a message: «¡Hola! ¿Qué pizza querés?» ("Hi! Which pizza do you want?")

**Pedido** (Order; triggered by `Pedir pizza`):
1. Ask a question → slot `gusto`: «¿De qué gusto?» ("Which flavor?") (add buttons Muzzarella, Fugazza,
   Napolitana).
2. Ask a question → slot `cantidad`: «¿Cuántas?» ("How many?")
3. Send a message: «Listo: {{ cantidad }} de {{ gusto }}. ¡Ya sale!» ("Done: {{ cantidad }} {{ gusto }}. Coming
   right up!")
4. Set a value → `gusto`, clear mode; the same with `cantidad` (for the next order).

A question skips itself if the slot already has a value: if the person said «dos de fugazza» ("two fugazza"), the
bot goes straight to the confirmation.

## 5. Train

At the top right, click **Train**. It takes seconds. The training log shows:

- how many phrases were turned into vectors,
- whether the entity model needed training,
- the **self-evaluation**: for each phrase, "if I didn't know it, which intent would I send it to?", with accuracy
  percentage and confusion matrix,
- tips ("“Saludar” has 2 phrases: add at least 3 more so it's recognized reliably.").

## 6. Test

Click **Try it** to open the test chat and choose **Chat** (or **Call (voice)**, if you
installed voice, see [ai-and-voice.md](ai-and-voice.md#voice)). Type «hola», then «quiero dos de muzza». For each
message you can see which intent it understood, with what confidence, which entities it found and the flow trace.
With **Start with data** you start the conversation with preloaded slots, as an IVR would.

Also try: «cancelar» (cancel) in the middle of the order, «¿cómo?» ("what?", repeats the last message) or «mejor
de fugazza» ("make it fugazza") while it's asking for the quantity (corrects the value).

## 7. Publish

What you edit is the **draft**. Click **Publish**: a numbered version (v1) is frozen with its own
trained model. You can first put it in **Staging**, test it by choosing that environment in the chat and
then move it to **Production**. In **Versions** you see what changes between the
published version and the draft, and to roll back you point production to the previous version.

As long as production has no version, the API answers with the draft.

## 8. Connect it

- **Web widget**: in **Publish → Web widget**, turn it on, add your site's address and
  copy the `<script>`.
- **API**: the reference is in **Publish → API**; see also [api.md](api.md).

```sh
curl -s http://127.0.0.1:8000/api/v1/bots/pizzeria/events \
  -H 'Content-Type: application/json' \
  -d '{"type": "message", "sessionId": "prueba-1", "text": "quiero dos de muzza"}'
```

## Next steps

- [Concepts](concepts.md): all the step types and the system flows.
- [Local AI](ai-and-voice.md): make the bot understand more with a small model.
- [Security](security.md): create a user before sharing Parla with anyone.
