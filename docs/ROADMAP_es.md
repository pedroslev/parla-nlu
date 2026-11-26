# Hoja de ruta

[English](ROADMAP.md) · **Español**

Hacia dónde va Parla, agrupado por cercanía. Es un plan, no un compromiso de fechas: las prioridades se mueven con lo
que necesitan quienes lo usan. Todo lo que figura acá va a llegar al proyecto open source bajo Apache-2.0; no hay
una edición paga que se guarde funciones.

¿Querés ayudar o necesitás algo antes? Abrí un issue o comentá en uno existente; ver
[CONTRIBUTING_es.md](../CONTRIBUTING_es.md). Para ver cómo se compara Parla hoy con otras plataformas, ver
[comparison_es.md](comparison_es.md).

## Recién salido

- **Experimentos A/B**: reparte las conversaciones nuevas de un entorno entre 2 y 4 versiones publicadas según su peso
  (determinístico por conversación, anda con varias réplicas), con resueltas, derivadas, no entendidas, objetivo, CSAT
  y costo por variante, pruebas z / t de Welch y una persona que elige al ganador ([experiments_es.md](experiments_es.md)).
- **Claves cifradas en disco**: AES-256-GCM con una clave derivada de `PARLA_SECRET_KEY`, migración de los archivos
  planos y `python -m parla.vault rotate` ([security_es.md](security_es.md#claves-cifradas-en-disco)).
- **Escalado horizontal y Postgres**: `PARLA_DATABASE_URL` lleva conversaciones, logins, auditoría, colas y contadores
  compartidos a Postgres; varias réplicas mantienen el orden de cada conversación (advisory locks), comparten los
  eventos en vivo (`LISTEN/NOTIFY`), reservan filas de las colas con `SKIP LOCKED` y eligen una líder para las
  tareas únicas. Helm `replicaCount > 1` con RollingUpdate, PDB y HPA, `python -m parla.migrate sqlite-to-postgres`
  ([deployment_es.md](deployment_es.md#postgres-y-alta-disponibilidad)).
- **Archivos entrantes**: las fotos, documentos y notas de voz de WhatsApp/Telegram se descargan y quedan con la
  conversación; las notas de voz se transcriben y se contestan; ubicaciones y contactos llegan como texto; descripción
  opcional de imágenes para la IA (`ai.vision`). Plantillas desde la Bandeja y la API del contact center después de
  24 horas, y API de estado de los envíos (`GET …/outbound[/{id}]`).

- **Costos por conversación**: tokens, minutos de audio, caracteres, minutos de teléfono y mensajes de
  WhatsApp/Telegram medidos por turno, con una tabla de precios que edita el dueño (valores de fábrica verificados,
  con fuente y fecha), en Reportes, el visor de conversaciones, las campañas, una API de costos, CSV y Prometheus. El
  resumen de la IA del handoff ya no demora el turno. Ver [costs_es.md](costs_es.md).

- **Contact centers externos**: modos de derivación (la Bandeja de Parla, un contact center externo o ambos),
  webhooks firmados con reintentos, una API para que el contact center acepte, responda, devuelva o cierre, búsqueda
  por teléfono o chat, y transferencias telefónicas con contexto en encabezados SIP o tareas de Twilio Flex. Recetas
  para Genesys Cloud, Twilio Flex, Five9, Zendesk y Salesforce. Ver [contact-centers_es.md](contact-centers_es.md).

- **Núcleo por eventos, WebSocket/SSE, streaming de la IA**: un servidor asyncio con keep-alive y una fila por
  conversación, embeddings en micro-lotes y un solo escritor de SQLite (~5-13x lo de antes, sin errores con 1.000
  charlas a la vez, 5.000 conexiones quietas); WebSocket y SSE para el widget, la Bandeja y Campañas; respuestas de
  la IA token a token con los guardrails aplicados al final.
- **Mensajes salientes y campañas**: el bot escribe primero con una API de salida, campañas desde un CSV
  (plantillas aprobadas de WhatsApp con la ventana de 24 horas resuelta sola, Telegram, llamadas salientes por
  Twilio o jambonz) con fecha de inicio, ritmo, horario de silencio, reintentos, estados de entrega y conversiones,
  recordatorios desde un flujo (paso `remind`) y bajas automáticas. Ver [outbound_es.md](outbound_es.md).
- **Observabilidad**: métricas de Prometheus en `/metrics` (pedidos, turnos, tasa de fallback, NLU, IA, voz, pasos
  HTTP, funciones, pases a una persona, CSAT, sesiones activas), trazas de OpenTelemetry por OTLP/HTTP con atributos
  GenAI y contexto de traza W3C, y logs de pedidos en JSON. Solo biblioteca estándar, apagado por defecto, sin el
  contenido de las conversaciones salvo que lo pidas. Ver [observability_es.md](observability_es.md).
- **Proveedores con tu propia key**: la IA puede usar OpenAI, Claude (Anthropic), Google Gemini o cualquier endpoint
  compatible con OpenAI, y la voz puede usar OpenAI, Deepgram, ElevenLabs o Google Cloud para transcribir y
  sintetizar (también para la voz de Parla en el teléfono). Las keys quedan en Claves; lo local sigue siendo lo que
  viene por defecto. Ver [ai-and-voice_es.md](ai-and-voice_es.md).
- **Herramientas en el paso de agente de IA**: el paso `agent` puede llamar funciones, APIs HTTP y herramientas
  habilitadas de servidores MCP (Parla como **cliente MCP**, Streamable HTTP), con un límite de llamadas por mensaje
  y un tiempo máximo. Ver [ai-and-voice_es.md](ai-and-voice_es.md#herramientas-en-el-paso-agente).
- **Inicio de sesión único con OIDC**: entrar con Keycloak, Entra ID, Google Workspace, Okta, Authentik o Auth0,
  con roles mapeados desde los grupos del proveedor y un modo opcional solo SSO. Ver [sso_es.md](sso_es.md).
- **Telefonía**: llamadas entrantes por Twilio Programmable Voice o jambonz (código abierto, se puede instalar en
  casa), con voz y teclado (DTMF), menús de teclas para los botones, interrupción (barge-in), transferencia a una
  persona y la voz de Parla (piper) como opción. Ver [channels_es.md](channels_es.md#llamadas-telefónicas-twilio-y-jambonz).
- **Voz en tiempo real**: audio por WebSocket para el teléfono (Twilio Media Streams, jambonz `listen`), la llamada del
  navegador y el widget: ASR en streaming (Deepgram live, o VAD + ASR por frase), TTS desde la primera oración,
  barge-in de verdad y métricas de latencia. Ver [ai-and-voice.md](ai-and-voice_es.md#voz-en-tiempo-real). Después:
  adaptadores de OpenAI Realtime / STT realtime de ElevenLabs, un VAD entrenado (silero), sockets de audio de una
  llamada que pasen de una réplica a otra.
- **Interfaz en inglés y portugués**: toda la interfaz, los mensajes del servidor y el widget web en español, inglés
  o portugués (pt-BR), a elección de cada usuario (al lado del selector de tema: inicio, menú ⋯ o pantalla de
  entrada), con un idioma por defecto de la instalación en `PARLA_LANG` (`scripts/setup.sh --lang en|es|pt`); los bots con inglés como idioma principal traen en
  inglés los textos de los flujos del sistema. Para sumar un idioma, ver
  [CONTRIBUTING_es.md](../CONTRIBUTING_es.md#traducciones).
- **Canal de WhatsApp** (WhatsApp Business Cloud API) y **canal de Telegram**, con botones, archivos y respuestas
  desde la Bandeja. Ver [channels_es.md](channels_es.md).
- **Importador de proyectos Rasa**: los proyectos de Rasa 3.x, clásicos y CALM, pasan a agentes de Parla, con un
  aviso por todo lo que no se convierte. Ver [migrate-from-rasa_es.md](migrate-from-rasa_es.md).
- **Endpoints de modelos compatibles con OpenAI**: las funciones de IA pueden usar cualquier API compatible con
  OpenAI (vLLM, llama.cpp, LM Studio, OpenAI, Azure OpenAI, Groq, OpenRouter), con la key en Claves. Ollama sigue
  siendo lo que viene por defecto. Ver [ai-and-voice_es.md](ai-and-voice_es.md#endpoints-compatibles-con-openai).
- **Suites de pruebas de conversación**: conversaciones esperadas guardadas en el bot, que se corren desde la
  interfaz, la API, el MCP y la línea de comandos (también en GitHub Actions), y antes de cada publicación a
  producción. Ver [testing-bots_es.md](testing-bots_es.md).
- **Conversaciones en SQLite** (`parla.db`), con migración automática desde los archivos JSON viejos, y **sesiones
  de login que sobreviven a un reinicio**. Ver [deployment_es.md](deployment_es.md#dónde-quedan-los-datos).
- **Retención de conversaciones** por agente y **registro de auditoría** de quién cambió qué. Ver
  [security_es.md](security_es.md#registro-de-auditoría).
- **Enmascarado de datos personales (PII)**: tapar emails, teléfonos, documentos, tarjetas y cuentas bancarias en
  las conversaciones guardadas. Ver [concepts_es.md](concepts_es.md#retención-y-datos-personales).

## Después

- **Canales validados con cuentas reales**: probar WhatsApp Cloud API, Telegram, Twilio y jambonz de punta a punta con
  cuentas reales (hoy se prueban contra imitaciones fieles) y corregir lo que aparezca.
- **Comunidad e integraciones**: más bots de ejemplo y conectores (CRM, mesas de ayuda), y documentación para
  contribuirlos.
- **Salientes, lo que sigue**: detección de contestadores en las llamadas y zona horaria por destinatario.

## Lo que ya está

Como referencia, lo que Parla hace hoy: constructor sin código, NLU con embeddings + CRF, flujos con muchos tipos de
paso, LLM opcional (local o con tu propia key), voz (local o con tu propia key), versiones con `staging`/`production`, usuarios y roles, inicio de sesión único con OIDC, bóveda de secretos,
bandeja, analíticas, API HTTP, widget web, servidor MCP, herramientas en el paso agente (cliente MCP), métricas de Prometheus y trazas de OpenTelemetry, mensajes salientes y campañas, Docker y Kubernetes. Ver el
[README](../README_es.md#qué-trae).
