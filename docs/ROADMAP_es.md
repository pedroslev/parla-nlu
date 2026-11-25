# Hoja de ruta

[English](ROADMAP.md) · **Español**

Hacia dónde va Parla, agrupado por cercanía. Es un plan, no un compromiso de fechas: las prioridades se mueven con lo
que necesitan quienes lo usan. Todo lo que figura acá va a llegar al proyecto open source bajo Apache-2.0; no hay
una edición paga que se guarde funciones.

¿Querés ayudar o necesitás algo antes? Abrí un issue o comentá en uno existente; ver
[CONTRIBUTING_es.md](../CONTRIBUTING_es.md). Para ver cómo se compara Parla hoy con otras plataformas, ver
[comparison_es.md](comparison_es.md).

## Ahora (en curso)

- **Importador de proyectos Rasa**: traer intenciones, entidades, ejemplos y respuestas de un proyecto Rasa
  (`domain.yml`, `nlu.yml`) a un agente de Parla.
- **Canal de WhatsApp** (WhatsApp Business Cloud API).
- **Canal de Telegram**.

## Después

- **Telefonía**: llamadas SIP / telefónicas con Jambonz y Twilio, con entrada DTMF, sobre la voz local que ya existe.
- **Persistencia en base de datos**: SQLite y Postgres como alternativa a los archivos JSON, con políticas de
  **retención de sesiones** y un **registro de auditoría** de quién cambió qué.
- **Suites de pruebas de conversación en CI**: escribir conversaciones esperadas y correrlas en cada cambio (línea
  de comandos y GitHub Actions).
- **Enmascarado de datos personales (PII)**: tapar emails, teléfonos, documentos y tarjetas en las conversaciones
  guardadas y en los registros.
- **Inicio de sesión único con OIDC** (Keycloak, Entra ID, Google, Okta y otros).
- **Endpoints de modelos compatibles con OpenAI**: apuntar las funciones de IA a cualquier API compatible con
  OpenAI, local o en la nube, no solo a servidores locales.
- **Interfaz en inglés** (internacionalización de la interfaz).

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
