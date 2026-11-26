# A/B experiments

*[Leer en español](experiments_es.md)*

Compare published versions of a bot with real traffic before switching everyone over.

## How it works

- An experiment belongs to one environment (usually `production`) and has 2 to 4 **variants**: each is a published
  version with a weight (1 to 100). A is the control (usually the version in the environment now).
- Every **new** conversation in that environment gets a variant from `sha256(experiment id + ":" + sessionId)`
  modulo the total weight. Same session, same variant, on every replica, with no shared state. The conversation stays
  on that version until it ends (Parla's usual version binding); if the same `sessionId` starts again while the
  experiment runs, it gets the same variant.
- **Channels** (optional): only conversations from those channels (`whatsapp`, `web`, `api`, `phone`…) take part. The
  editor's test chat never does.
- **Goal** (optional): `flow` (the conversation went through that flow), `intent` (the person said it) or
  `classification` (the conversation got it).
- **Start / pause / stop.** Paused: new conversations go to the environment's version; the ones in progress keep their
  variant. Stop: choose a winner (it is deployed to the environment with the normal deploy, and logged) or stop
  without changing anything. Only one running experiment per environment; a started experiment can't be edited.
- In the UI: **Versions → A/B experiments**. Results also appear in **Reports** when you filter by an experiment
  (and variant); conversations show their variant.

## Metrics and statistics

Per variant, from the stored conversations and usage: conversations, **resolved** (no handoff), **handoff**,
**fallback** (conversations with at least one message not understood), **goal** rate, **CSAT** average and count,
messages per conversation, estimated **cost** per conversation ([costs.md](costs.md)) and average response time.

Each variant is compared with A:

- Rates: two-proportion **z-test** (pooled for the p-value; unpooled for the confidence interval of the difference).
- Averages (CSAT, cost, messages): **Welch's t-test** (unequal variances; p-value from the regularized incomplete beta
  function, no SciPy).
- With more than two variants, **Bonferroni**: α = 0.05 / (variants − 1); intervals are at 1 − α.
- A difference is marked significant only if p < α **and** both sides have the minimum sample: 100 conversations per
  variant (30 CSAT answers for CSAT). Below that the result says "not enough data" and the API returns `warnings`.
- Parla never declares a winner: `"summary": "sin diferencia significativa todavía"` until something is significant,
  and even then a person decides when stopping.

## Running a good test

1. **One change per experiment.** If B changes the greeting and the menu, you won't know which one helped.
2. **Pick the goal and the sample size before starting**, and run it at least a full week (weekday vs weekend
   traffic differs). As a rule of thumb, detecting a 5-point change on a 50 % rate needs ~1,500 conversations per
   variant; a 10-point change, ~400.
3. **Don't stop at the first significant p-value** ("peeking"): checking every day and stopping as soon as it turns
   green inflates false positives. Decide the duration up front.
4. **Run an A/A test once** (the same version twice): it should show no difference; if it does, something in the
   traffic split or the metric is off.
5. **Watch guardrails**, not only the goal: a variant that completes more flows but hands off more or costs more may
   not be better.
6. Keep 50/50 unless the new version is risky; a 90/10 split protects users but takes much longer to reach a result.

## Pitfalls

- Results only count conversations assigned while the experiment ran; editing weights would reshuffle new
  assignments, so a started experiment can't be changed: stop it and create another.
- CSAT is answered by few people and is biased toward the extremes; treat it as a guardrail.
- Cost is estimated with today's price table; usage that has no price counts as 0.
- Metrics are computed on the fly from the conversations (fine for tens of thousands; very large agents should use
  shorter experiments or the `from`/`to` report filters).
- Retention (`retention_days`) deletes old conversations, and with them their experiment data.

## API

See [api.md](api.md#ab-experiments). Prometheus: `parla_experiment_conversations_total{agent,experiment,variant}`
counts assignments while an experiment runs ([observability.md](observability.md)).
