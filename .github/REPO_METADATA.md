# Repository metadata (for the maintainer)

Proposed GitHub "About" settings. Not user documentation.

## Description (≤ 350 characters)

> Open-source, self-hosted conversational AI platform: build chatbots and voice bots with a no-code flow editor,
> embeddings + CRF NLU, optional local LLM (Ollama) and on-premise voice. Runs on a CPU, no cloud. Spanish-first.
> A free alternative to Rasa Pro, Dialogflow CX and Cognigy. Apache-2.0, no open core.

(307 characters.)

Website: leave empty until there is a docs site, or point to `https://github.com/pedroslev/parla-nlu/tree/main/docs`.

## Topics (20)

```
chatbot conversational-ai chatbot-builder nlu nlp self-hosted local-first
rasa-alternative dialogflow-alternative voice-bot voicebot llm ollama
local-llm speech-to-text text-to-speech mcp no-code spanish python
```

GitHub allows at most 20 topics, lowercase, with hyphens.

## Apply with the GitHub CLI

```sh
gh repo edit pedroslev/parla-nlu \
  --description "Open-source, self-hosted conversational AI platform: build chatbots and voice bots with a no-code flow editor, embeddings + CRF NLU, optional local LLM (Ollama) and on-premise voice. Runs on a CPU, no cloud. Spanish-first. A free alternative to Rasa Pro, Dialogflow CX and Cognigy. Apache-2.0, no open core." \
  --add-topic chatbot,conversational-ai,chatbot-builder,nlu,nlp,self-hosted,local-first \
  --add-topic rasa-alternative,dialogflow-alternative,voice-bot,voicebot,llm,ollama \
  --add-topic local-llm,speech-to-text,text-to-speech,mcp,no-code,spanish,python
```

Also worth enabling in **Settings**: private vulnerability reporting (Security → Advisories, needed by
SECURITY.md), Discussions (questions and ideas), and GitHub Packages visibility "public" for the ghcr.io image
after the first push.

## Social preview

Upload a 1280×640 image in **Settings → General → Social preview**. Suggested text on it:

> **Parla**
> Open-source conversational AI you can self-host.
> No-code flows · Local LLM · On-premise voice · Runs on a CPU
> Apache-2.0 · No open core

A good background is a screenshot of the flow editor (`docs/img/flujos.png`) dimmed behind the text.
