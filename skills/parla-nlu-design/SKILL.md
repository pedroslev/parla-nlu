---
name: parla-nlu-design
description: How to design intents, training phrases, entities and slots that Parla's NLU (embeddinggemma nearest-neighbour intent matching plus regex, lists and a CRF for entities) understands reliably. Use it when writing or reviewing intents and example phrases for a Parla agent, choosing an entity kind (list, examples, date, number, email, phone, dni, custom regex), marking [value](entity) in phrases, tuning threshold or knowledge_threshold, reading the training self-check or confusion matrix, or fixing a Parla bot that picks the wrong intent, falls back too often or doesn't capture a value.
---

# NLU design for Parla

## How Parla understands a message (what your design feeds)

- **Intent** = nearest neighbour. Every example phrase (lowercased, marks removed) becomes a vector with
  `google/embeddinggemma-300m`; the message is compared with all of them and each intent scores the cosine
  similarity of its **closest** phrase. The top intent wins if its score ≥ `threshold` (default 0.75).
  There is no heavy training: adding a phrase is enough (create/update retrain in a second).
- **Entities**, in priority order: `regex` (presets or custom) → `values` + `synonyms` (whole-word match,
  canonical value stored) → `date` rules (Rioplatense natural language: «mañana a las 10», «el jueves que viene»,
  «15/12» → `YYYY-MM-DD[THH:MM]`) → a CRF that learns entities with no regex, values or date from the context of
  marked phrases. Certain matches beat CRF guesses. Marked values (`[muzza](gusto)`) also become known forms.
- **Slots** fill from their entity in any turn, except while a question is pending: then only the asked slot is
  filled (so a number in an address doesn't land in `cantidad`).

## Numbers measured with the real model

Measured on a 4-intent dental bot (see `parla-build-bot/examples/dental-clinic.json`):

| Message vs training | Typical score |
|---|---|
| The exact training phrase (any case or punctuation) | 1.00 |
| Close paraphrase («che, me podés agendar para la semana que viene?») | 0.75–0.97 |
| Same meaning in another language (pt / en) | 0.79–0.82 |
| A *different* intent of the same domain («quiero un turno» vs «Cancelar turno») | 0.70–0.80 |
| Names, phone numbers, «jajaja» against any intent | 0.50–0.68 |
| Off-topic («¿cuál es la capital de Francia?») | 0.40–0.45 |

Consequences:

- Sibling intents sit only 0.1–0.2 apart. Phrases must carry the **distinguishing words** (the verb *and* the
  object: «cancelar **el turno**», not «cancelar»).
- 0.75 is a good default. Lowering it (the repo examples use 0.55) catches more paraphrases but lets intents
  swallow FAQ questions that should reach the knowledge base, and makes `clarify` fire less precisely. Change it
  only after self-check is clean and test conversations show real paraphrases scoring just below.
- `clarify` asks «¿Quisiste decir A o B?» when the top two user intents are **both** ≥ threshold and less than
  `system.clarify.margin` (0.04) apart. Overlapping intents show up as clarify questions — fix the phrases.

Full threshold table (system intents, interruptions, answers by meaning, AI rescue): [reference.md](reference.md).

## Checklist for intents

1. One intent = one user goal that triggers one flow. FAQs (hours, address, prices) are **knowledge**, not intents.
2. **6–12 phrases per intent**, similar counts across intents (validate warns under 3). Mix:
   short forms («turno», «un turno»), full requests, questions, indirect requests («quería ver si…»), typos the
   audience really makes, with and without data.
3. Write the way the audience writes. For Argentina/Uruguay: voseo («quiero», «pasame», «sacame», «¿tenés?»),
   «che», «dale». For other Spanish-speaking audiences use their forms; Parla's own default texts and date rules
   are Rioplatense.
4. Mark entities in some phrases: `"turno para [ortodoncia](tratamiento)"`, different values in different
   positions, and keep phrases without marks too. Data changes the vector: «¿salió la orden OR-77777?» scored
   0.71 until a phrase with a marked code in that shape was added (then 0.82). If users type codes, numbers or
   dates inside the request, have phrases that do too.
5. Don't duplicate system behaviours: cancel («cancelar», «olvidalo», «no quiero seguir»), repeat («¿cómo?»,
   «repetí»), talk to a human («quiero hablar con una persona», «pasame con alguien») already exist and compete
   in the ranking. Measured: «quiero cancelar» → system cancel 0.886 vs «Cancelar turno» 0.864. Give your
   domain intent the object («cancelar el turno» → 0.988). Add domain wording to the system examples instead
   (`"system": {"handoff": {"examples": ["pasame con recepción", …]}}`).
6. After `create_agent`/`update_agent`, read `trained.log.self_check`: fix every mistake (rewrite the phrase, move
   it, or add a contrasting phrase to the right intent) and re-run until 0 mistakes or only defensible ones.
7. Test with **paraphrases**, not training phrases (they always score 1.0). A paraphrase at 0.75–0.80 is a sign
   to add phrases like it.
8. Multilingual bots: `languages: ["es", "pt"]` and 1–2 phrases per extra language in each intent.

## Choosing the entity kind

| The data is… | Kind | Notes |
|---|---|---|
| a closed set of options (treatment, branch, flavour, yes/no) | `list` + `synonyms` (+ `phrasings`) | Stores the canonical value. Synonyms are exact words/phrases; `phrasings` are whole answers understood **by meaning** («la quiero desde mi casa» → `virtual`). |
| a date or time | `date` | No regex, no marks needed. Stores `2026-12-15` or `2026-12-15T10:00`. The rules are **Spanish only** («mañana», «el lunes», «15 de diciembre», «15/12 a las 10»; not «amanhã» or «tomorrow»; a bare «el 15» isn't a date). Numeric forms work in any language (`15/12`, `15/12 10:30`; «às 10» / «at 10» lose the time): in pt/en questions ask for «dd/mm hh:mm». |
| a number, email, phone, Argentine DNI | `number` / `email` / `phone` / `dni` | Omit `regex`: the preset is filled in. A different regex triggers a warning → use `custom`. |
| another fixed format (order code, CUIT, plate) | `custom` + `regex` | Python `re`, case-insensitive. With a group `(...)` group 1 is stored. |
| a name or free text in context | `examples` | Learned by the CRF from marks; needs ≥ 3 marked phrases in different contexts. Stores what the person wrote. |
| free text with no structure (reason, comment) | slot with `entity: ""` | The whole answer is stored. With AI on, `fill: "ai"` + `description` extracts it. |

Rules the validator enforces: `examples` has no regex/values; `list` needs values and no regex; `custom` needs a
regex; every `[x](ent)` mark must name an existing entity.

Validation behaviour that follows from the kind (it decides whether the bot re-asks):

- Slot with a regex/list/date entity: an answer without a value → «No reconocí ese dato, probemos de nuevo.» and
  the question again. Good for formats.
- Slot with an `examples` entity or no entity: any answer is accepted. Good for names, bad for formats.
- Two different values of the same entity in one answer («sí… no puedo») → neither is taken, it asks again.

## Anti-patterns

- 20 phrases for one intent and 4 for another (nearest neighbour favours the dense one).
- Near-identical phrases across intents («quiero un turno» / «quiero turno nuevo» in two intents).
- An intent per FAQ, or an intent for «gracias»/«ok» that interrupts questions (make that flow
  `"interrupts": false`, see `parla-flow-design`).
- `kind: "examples"` for something with a format (phones, dates, ids): no re-ask, garbage in the slot.
- Synonyms that are full sentences — put those in `phrasings`.
- Regex presets copied by hand with a typo (`validate_agent` warns when it differs from the preset).
- Fixing misclassification by lowering `threshold` to 0.5.

## Worked example

A list entity with synonyms and phrasings, a preset, a custom code, a learned name and a free-text slot:

```json parla-agent
{
  "name": "Turnos Kinesiología",
  "intents": [
    {"name": "Pedir turno", "examples": [
      "quiero un turno", "necesito sacar turno para [kinesio](servicio)", "turno de [masajes](servicio) por favor",
      "¿tenés lugar para [rehabilitación](servicio) esta semana?", "me llamo [Laura](nombre) y quiero un turno",
      "soy [Martín Pérez](nombre), quería pedir hora", "sacame un turno", "un turno"]},
    {"name": "Consultar orden", "examples": [
      "¿en qué quedó mi orden [OR-48213](orden)?", "quiero saber el estado de la orden", "estado de mi orden médica",
      "la orden [OR-10293](orden) ya está autorizada?", "consultar una orden", "me autorizaron la orden?",
      "¿ya salió la autorización?", "quiero saber si salió mi orden", "¿salió la orden [OR-20001](orden)?"]}],
  "entities": [
    {"name": "servicio", "kind": "list", "values": ["kinesiología", "masajes", "rehabilitación"],
     "synonyms": {"kinesiología": ["kinesio", "kine"], "masajes": ["masaje", "descontracturante"],
                  "rehabilitación": ["rehabilitacion", "rehab"]},
     "phrasings": {"rehabilitación": ["me operé la rodilla", "vengo de una lesión"],
                   "masajes": ["tengo la espalda contracturada"]}},
    {"name": "orden", "kind": "custom", "regex": "\\b(OR-\\d{5})\\b"},
    {"name": "email", "kind": "email"},
    {"name": "nombre", "kind": "examples", "examples": ["mi nombre es [Ana](nombre)", "habla [Jorge Díaz](nombre)"]}],
  "slots": [
    {"name": "servicio", "entity": "servicio"}, {"name": "orden", "entity": "orden"},
    {"name": "email", "entity": "email"}, {"name": "nombre", "entity": "nombre"}, {"name": "comentario", "entity": ""}],
  "flows": [
    {"name": "Turno", "trigger": "Pedir turno", "steps": [
      {"type": "ask", "slot": "servicio", "text": "¿Qué necesitás? Kinesiología, masajes o rehabilitación."},
      {"type": "ask", "slot": "nombre", "text": "¿A nombre de quién?"},
      {"type": "ask", "slot": "email", "text": "¿A qué email te mando la confirmación?"},
      {"type": "ask", "slot": "comentario", "text": "¿Algo que tengamos que saber antes de la sesión?"},
      {"type": "message", "text": "Listo {{ nombre }}, te escribimos a {{ email }} para confirmar {{ servicio }}."},
      {"type": "set", "slot": "servicio", "mode": "clear"}, {"type": "set", "slot": "comentario", "mode": "clear"}]},
    {"name": "Orden", "trigger": "Consultar orden", "steps": [
      {"type": "ask", "slot": "orden", "text": "¿Cuál es el número de orden? Es algo como OR-12345."},
      {"type": "message", "text": "La orden {{ orden }} está en revisión."},
      {"type": "set", "slot": "orden", "mode": "clear"}]}]
}
```

«me operé la rodilla» as an answer to the `servicio` question contains no value or synonym; with `phrasings` it is
understood by meaning (`via: "significado"`) when it scores ≥ 0.60 and beats the other options by 0.04.
