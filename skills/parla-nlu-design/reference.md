# Parla NLU: thresholds and rules (from the code)

Source: `parla/server.py` (`classify`, `read_answer`, `extract`, `handle`), `parla/brain.py`, `parla/knowledge.py`.

## Intent classification

| What | Value | Where it matters |
|---|---|---|
| Model | `google/embeddinggemma-300m` (fastembed, CPU), prefix `task: sentence similarity \| query: ` | Multilingual; ~10 ms per message. |
| Score | cosine of the message vs the **closest** phrase of each intent; text lowercased, marks removed | Case and `!!` don't matter («TURNO» = «turno»). |
| `threshold` | default 0.75 (UI range 0.2–0.9) | Below it: no intent → knowledge base → AI fallback → `fallback`. |
| `clarify.margin` | 0.04 | Both top-2 user intents ≥ threshold and ≤ margin apart → «¿Quisiste decir A o B?» with buttons. System intents are excluded. |
| Intent with no flow | understood but answers the `fallback` | validate warns. |

## While a question (`ask`) is pending

| What | Value |
|---|---|
| `strict` threshold for interruptions and `interrupts: "always"` | `max(threshold, 0.75)` |
| System intents (cancel, repeat, handoff) outside a question | `max(threshold, 0.65)` |
| System intents while a question with an entity (or `fill: "ai"`) is pending | `max(threshold, 0.75)` |
| System intents while a **free-text** question (no entity) is pending | 0.92 |
| System intents also never fire when | a button was pressed, or the message already carries the asked entity |

Order of evaluation for an answer: system intents → `interrupts: "always"` flows → side question (looks like a
question and the knowledge base answers) → correction of an earlier slot → the answer itself (`also` entities,
meaning, AI, re-ask) → interruption by another clear intent (then `resume` back to the question).

## Answers by meaning (`phrasings`, no generative AI)

Only for `list` entities that have `phrasings`. Compares the answer with values + synonyms + phrasings, with the
example phrases of intents that could interrupt, and with small talk («gracias», «un momento»).

| Rule | Value |
|---|---|
| Minimum similarity | 0.60 |
| Lead over the runner-up | 0.04 |
| Lead an *action* (other intent) needs over the best option | 0.10 |

When it decides, the turn has `via: "significado"`.

## AI (only if `ai.enabled`)

| Feature | Rule |
|---|---|
| `rescue_intents` | Candidates = up to 5 intents with score ≥ `max(0.25, threshold − 0.3)`; asked twice in reverse order, must agree; chosen intent gets confidence = threshold. |
| `fill: "ai"` slots | Value must appear literally in the message (normalised values like «dos» → «2» are rejected); dates go through the date rules first. |
| understanding an answer | Asked twice when it would interrupt or confirm a «sí»; must agree. |

## Entities

| Kind | Recognised by | Stored value |
|---|---|---|
| `list` | `values` and `synonyms` (whole word/phrase, case-insensitive, longest first) | canonical value |
| `number` | `\b\d+(?:[.,]\d+)?\b` | the text («2,5») |
| `email` | `[\w.+-]+@[\w-]+\.[\w.-]+` | the text |
| `phone` | `\+?\d[\d\s().-]{6,}\d` | the text («11 5555 1234») |
| `dni` | `\b\d{1,2}\.?\d{3}\.?\d{3}\b` | the text |
| `date` | Rioplatense date/time rules | `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM` |
| `custom` | your regex (Python, case-insensitive) | group 1 if there is a group, else the match |
| `examples` | CRF (python-crfsuite) trained on marked phrases; marked phrases weigh ×3 | the text as written |

- A value contained in a longer match of the same entity is dropped («2» inside «2,5»).
- The CRF trains only if some entity with no regex, values or date is marked; `trained.log.crf.reason` says why
  not. Training warns when a learned entity is marked fewer than 3 times.
- Slot values are **text** (`"2"`, `"si"`); `true`/`false`/numbers from http or functions keep their JSON type.

## Knowledge base search

| What | Value |
|---|---|
| Chunk size | target ~500 characters, max 700, overlap 120; «P: … R: …» pairs stay together |
| `knowledge_threshold` | default 0.75 |
| Reply without AI | the best chunk, up to 600 characters, without the question line |
| Measured (dental FAQ) | near-literal question 0.84–0.90; short paraphrase 0.65–0.76; off-topic ~0.44 |
| Measured effect of listing variant questions on the «P:» line | 0.69 → 0.76 and 0.73 → 0.89 |

The knowledge base is searched only when no intent reaches the threshold (and, during a question, when the
message looks like a question: a «?» or a question word at the start). Search is not lowercased: «¿atienden con
osde?» scored 0.68 and «atienden con osde?» 0.72 — try the real wording with `search_knowledge`.

## Language

`languages[0]` is the default. The conversation language comes from start data (`idioma`, `language`, `lang`) or
is guessed from frequent words of the first message (es/pt/en), defaulting to the first language on a tie.
Embeddings are multilingual, so a few phrases per extra language are enough for intents.

## Unrecognised phrases loop

`list_unrecognized` groups real fallbacks by meaning with a `suggested_intent`. Teach the good ones with
`teach_phrases` + `train_agent`; answer FAQs with `add_knowledge`; phrases you don't want to see again go in the
agent's `ignored_phrases` list (only hides them from «Para enseñar» / `list_unrecognized`).
