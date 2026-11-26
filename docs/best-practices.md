# Bot-building best practices

**English** · [Español](best-practices_es.md)

A short guide for people building Parla bots by hand or reviewing what an AI built. Each section links to the
[skill](skills.md) with the details, numbers and examples. A complete bot that follows all of it:
[`skills/parla-build-bot/examples/dental-clinic.json`](../skills/parla-build-bot/examples/dental-clinic.json).

## Work in small, tested steps

- Start with a greeting, one intent, one flow and its tests. Validate, create, try it, then add the next piece.
- Every change is a draft; real users only see what you deploy to production. Publish to staging first.
- Every bug you fix becomes a conversation test.

Details: [`parla-build-bot`](../skills/parla-build-bot/SKILL.md).

## Intents and phrases

- One intent per user goal; 6–12 varied phrases each, similar counts across intents, in the way your users write
  (voseo for Argentina: «quiero», «pasame», «¿tenés?»).
- Sibling intents score only 0.1–0.2 apart with the embedding model: phrases need the distinguishing words
  («cancelar **el turno**», not «cancelar», which goes to the system's cancel).
- Read the training self-check after every change and fix the phrases it lists.
- Test with paraphrases, never only with the training phrases (those always score 1.0).
- Keep `threshold` at 0.75 unless tests show real paraphrases just below it. FAQs don't go in intents.
- Don't create intents for cancel, repeat or «talk to a person»: the system flows do it; add your wording to their
  examples.

Details: [`parla-nlu-design`](../skills/parla-nlu-design/SKILL.md).

## Entities and slots

| Data | Entity |
|---|---|
| closed options | `list` with `synonyms` (and `phrasings` for answers understood by meaning) |
| date and time | `date` (Spanish natural language; numeric `dd/mm hh:mm` in any language) |
| number, email, phone, DNI | the preset |
| other formats | `custom` regex |
| names | `examples`, marked in 3+ phrases |
| free text | slot without entity |

Entities with a format or list make the bot re-ask when the answer doesn't fit. Clear slots that must be asked
again at the end of the flow: a question whose slot is filled is skipped.

## Flows and wording

- One goal per flow; shared pieces as subflows with `call`.
- A greeting with 2–4 buttons whose value is a phrase that triggers the intent (WhatsApp doesn't run the greeting:
  intents must work without it).
- One short question per message, saying the expected format. Confirm before costly actions, reading the data
  back. Branch on every API result and function `ok`.
- Small-talk flows `"interrupts": false`, emergencies `"interrupts": "always"` with a handoff.
- Buttons: 2–6, labels ≤ 20 characters (WhatsApp shows 3 as buttons, up to 10 as a list).
- Voice: short sentences, no emojis or links, options spelled out, dates formatted for people.
- `classify` where the goal is met, `handoff` with a reason where the bot can't solve it.

Details: [`parla-flow-design`](../skills/parla-flow-design/SKILL.md).

## Integrations and safety

- Credentials only as `{{ secret.NAME }}` in `http` steps or `secret.NAME` function inputs, loaded by a person in
  «Claves». Never in messages, never in the JSON, never pasted into an AI chat.
- `http`: 10 s timeout; status 0 = no connection; 4xx/5xx don't stop the flow, so always check the status. URL
  values are encoded, the JSON body isn't: interpolate only validated slots.
- Functions: for real logic, tested with `test_function` (happy path and an edge case), with `ok`/`error` saved
  and handled. They are not a sandbox; off with `PARLA_FUNCTIONS=0`.
- Knowledge base: «P: … R: …» pairs, one question per pair with several phrasings on the «P:» line; check scores
  with `search_knowledge`.
- AI is optional. With a hosted provider, conversation text leaves the machine.
- `pii_redaction` and `retention_days` for personal data.

Details: [`parla-integrations`](../skills/parla-integrations/SKILL.md).

## Tests, releases and improvement

- Cover, per flow: happy path, everything in the first message, an invalid answer, a «no», a failing integration,
  an interruption, a FAQ, off-topic.
- `says` with a distinctive part of the message or a regex; no dates or AI text.
- Publishing to production runs the tests and stops on failures. Rollback = deploy the previous version.
- With real traffic: `list_unrecognized` → teach phrases or add knowledge; `get_analytics` for drop-off, fallbacks
  and CSAT.

Details: [`parla-testing-and-release`](../skills/parla-testing-and-release/SKILL.md). Coming from Rasa:
[`parla-migrate-from-rasa`](../skills/parla-migrate-from-rasa/SKILL.md).
