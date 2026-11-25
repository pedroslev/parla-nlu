# Hoja de ruta

[English](ROADMAP.md) · **Español**

Hacia dónde va Parla, agrupado por cercanía. Es un plan, no un compromiso de fechas: las prioridades se mueven con lo
que necesitan quienes lo usan. Todo lo que figura acá va a llegar al proyecto open source bajo Apache-2.0; no hay
una edición paga que se guarde funciones.

¿Querés ayudar o necesitás algo antes? Abrí un issue o comentá en uno existente; ver
[CONTRIBUTING_es.md](../CONTRIBUTING_es.md). Para ver cómo se compara Parla hoy con otras plataformas, ver
[comparison_es.md](comparison_es.md).

## Recién salido

- **Canal de WhatsApp** (WhatsApp Business Cloud API) y **canal de Telegram**, con botones, archivos y respuestas
  desde la Bandeja. Ver [channels_es.md](channels_es.md).
- **Importador de proyectos Rasa**: los proyectos de Rasa 3.x, clásicos y CALM, pasan a agentes de Parla, con un
  aviso por todo lo que no se convierte. Ver [migrate-from-rasa_es.md](migrate-from-rasa_es.md).
- **Endpoints de modelos compatibles con OpenAI**: las funciones de IA pueden usar cualquier API compatible con
  OpenAI (vLLM, llama.cpp, LM Studio, OpenAI, Azure OpenAI, Groq, OpenRouter), con la key en Claves. Ollama sigue
  siendo lo que viene por defecto. Ver [ai-and-voice_es.md](ai-and-voice_es.md#endpoints-compatibles-con-openai).

## Ahora (en curso)

- **Persistencia en base de datos**: SQLite y Postgres como alternativa a los archivos JSON, con políticas de
  **retención de sesiones** y un **registro de auditoría** de quién cambió qué.
- **Suites de pruebas de conversación en CI**: escribir conversaciones esperadas y correrlas en cada cambio (línea
  de comandos y GitHub Actions).
- **Enmascarado de datos personales (PII)**: tapar emails, teléfonos, documentos y tarjetas en las conversaciones
  guardadas y en los registros.
- **Interfaz en inglés** (internacionalización de la interfaz).

## Después

- **Telefonía**: llamadas SIP / telefónicas con Jambonz y Twilio, con entrada DTMF, sobre la voz local que ya existe.
- **Inicio de sesión único con OIDC** (Keycloak, Entra ID, Google, Okta y otros).

## Más adelante

- **Escalado horizontal**: varias réplicas sobre almacenamiento compartido, con las sesiones fuera del proceso.
- **Herramientas en el paso de agente de IA**: que el paso `agent` llame herramientas externas como **cliente MCP**.
- **Observabilidad**: exportar trazas y métricas con OpenTelemetry.
- **Experimentos A/B** entre versiones de flujos o de bots.
- **Campañas salientes**: iniciar conversaciones de forma proactiva (recordatorios, avisos).

## Lo que ya está

Como referencia, lo que Parla hace hoy: constructor sin código, NLU con embeddings + CRF, flujos con muchos tipos de
paso, LLM local opcional, voz local, versiones con `staging`/`production`, usuarios y roles, bóveda de secretos,
bandeja, analíticas, API HTTP, widget web, servidor MCP, Docker y Kubernetes. Ver el
[README](../README_es.md#qué-trae).
