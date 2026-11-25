# Política de seguridad

[English](SECURITY.md) · **Español**

## Versiones soportadas

Parla se publica desde `main`. Los arreglos de seguridad van al **último `main`** (y a la próxima versión
etiquetada que salga de ahí); las versiones y ramas anteriores no reciben backports. Actualizá a la última versión
antes de reportar.

| Versión | Soportada |
|---|---|
| último `main` / última versión | Sí |
| cualquier otra anterior | No |

## Reportar una vulnerabilidad

**No abras un issue, una discusión ni un pull request público por un problema de seguridad.**

Reportalo en privado con el reporte privado de vulnerabilidades de GitHub:
**<https://github.com/pedroslev/parla-nlu/security/advisories/new>** (o **Security → Report a vulnerability** en
la página del repositorio).

Si podés, incluí:

- La versión o el commit afectado, y cómo corría Parla (local, Docker, Kubernetes; detrás de un proxy o no).
- Los pasos para reproducirlo, una prueba de concepto y qué gana quien ataca.
- Si había usuarios creados (sin usuarios Parla está abierto a propósito, ver abajo).

Qué esperar: una confirmación de recepción en pocos días, un arreglo o plan de mitigación cuando el problema se
confirme, y crédito en el aviso y en [CHANGELOG.md](CHANGELOG.md) si lo querés. Danos un tiempo razonable para
publicar el arreglo antes de difundirlo.

## Alcance

Dentro del alcance: el código de este repositorio, incluidos el servidor HTTP y el motor (`parla/`), la
autenticación, los roles y las claves de API, la bóveda de secretos, la API pública y el widget web (`/api/v1`,
`web/static/widget.js`), el servidor MCP, «Conectar con IA», el `Dockerfile`, `docker-compose.yml` y los
manifiestos de `deploy/`.

Fuera del alcance, o funciona como está documentado en [docs/security_es.md](docs/security_es.md):

- Una instancia **sin usuarios creados**: hasta que existe el primer usuario, quien llegue al puerto es dueño.
- Lo que haga alguien que puede **editar un bot**: es de confianza (puede hacer que los pasos `http` llamen a
  cualquier URL y, como dueño y con las funciones prendidas, correr código). Las funciones no son un sandbox.
- Exponer la interfaz de administración a internet sin los pasos de
  [Antes de exponerlo a internet](docs/security_es.md#antes-de-exponerlo-a-internet).
- Vulnerabilidades de dependencias o modelos de terceros sin un impacto propio en Parla (reportalas en su
  proyecto; Dependabot sigue las actualizaciones acá).
- Denegación de servicio que necesite grandes volúmenes de tráfico, y hallazgos de escáneres automáticos sin un
  impacto demostrable.

El modelo de amenazas, qué protege Parla y qué todavía no, está en [docs/security_es.md](docs/security_es.md).
