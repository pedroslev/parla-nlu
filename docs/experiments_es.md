# Experimentos A/B

*[Read in English](experiments.md)*

Compará versiones publicadas de un bot con tráfico real antes de pasar a todos.

## Cómo funciona

- Un experimento es de un entorno (casi siempre `production`) y tiene de 2 a 4 **variantes**: cada una es una versión
  publicada con un peso (de 1 a 100). A es el control (normalmente la versión que está hoy en el entorno).
- Cada conversación **nueva** de ese entorno recibe una variante según `sha256(id del experimento + ":" + sessionId)`
  módulo el peso total. Misma conversación, misma variante, en cualquier réplica y sin estado compartido. La
  conversación sigue con esa versión hasta terminar (la atadura de versión de siempre); si el mismo `sessionId` vuelve
  a empezar mientras corre el experimento, le toca la misma variante.
- **Canales** (opcional): solo participan las conversaciones de esos canales (`whatsapp`, `web`, `api`, `phone`…). El
  chat de prueba del editor nunca.
- **Objetivo** (opcional): `flow` (la conversación pasó por ese flujo), `intent` (la persona la dijo) o
  `classification` (la conversación quedó así clasificada).
- **Empezar / pausar / terminar.** En pausa: las nuevas van a la versión del entorno; las que están en curso siguen con
  su variante. Terminar: elegís un ganador (se despliega en el entorno con el deploy normal, y queda registrado) o
  terminás sin cambiar nada. Un solo experimento corriendo por entorno; uno que ya empezó no se edita.
- En la interfaz: **Versiones → Experimentos A/B**. Los resultados también aparecen en **Reportes** al filtrar por un
  experimento (y variante); las conversaciones muestran su variante.

## Métricas y estadística

Por variante, con las conversaciones y el uso guardados: conversaciones, **resueltas** (sin pasar a una persona),
**derivadas**, **no entendidas** (conversaciones con al menos un mensaje que no entendió), tasa de **objetivo**,
**CSAT** promedio y cantidad, mensajes por conversación, **costo** estimado por conversación ([costs_es.md](costs_es.md))
y tiempo de respuesta promedio.

Cada variante se compara con A:

- Tasas: **prueba z de dos proporciones** (agrupada para el valor p; sin agrupar para el intervalo de la diferencia).
- Promedios (CSAT, costo, mensajes): **t de Welch** (varianzas distintas; valor p con la beta incompleta regularizada,
  sin SciPy).
- Con más de dos variantes, **Bonferroni**: α = 0,05 / (variantes − 1); los intervalos son al 1 − α.
- Una diferencia es significativa solo si p < α **y** los dos lados tienen la muestra mínima: 100 conversaciones por
  variante (30 respuestas para CSAT). Con menos dice «faltan datos» y la API devuelve `warnings`.
- Parla nunca declara un ganador: `"summary": "sin diferencia significativa todavía"` hasta que algo lo sea, y aun así
  decide una persona al terminarlo.

## Cómo hacer una buena prueba

1. **Un cambio por experimento.** Si B cambia el saludo y el menú, no vas a saber cuál ayudó.
2. **Elegí el objetivo y el tamaño de muestra antes de empezar**, y dejalo al menos una semana completa (el tráfico
   de semana y de fin de semana es distinto). Como referencia, detectar 5 puntos de cambio sobre una tasa del 50 %
   pide ~1.500 conversaciones por variante; 10 puntos, ~400.
3. **No cortes con el primer p significativo** («espiar»): mirar todos los días y parar apenas se pone verde infla los
   falsos positivos. Decidí la duración de antemano.
4. **Hacé una prueba A/A una vez** (la misma versión dos veces): no debería dar diferencia; si da, algo del reparto o de
   la métrica está mal.
5. **Mirá las métricas de resguardo**, no solo el objetivo: una variante que completa más flujos pero deriva más o
   cuesta más puede no ser mejor.
6. Dejá 50/50 salvo que la versión nueva sea riesgosa; un 90/10 cuida a la gente pero tarda mucho más en dar resultado.

## Trampas

- Solo cuentan las conversaciones asignadas mientras corrió el experimento; cambiar los pesos reordenaría las
  asignaciones nuevas, por eso un experimento que empezó no se cambia: terminalo y creá otro.
- El CSAT lo contesta poca gente y se va a los extremos; usalo como resguardo.
- El costo se estima con la tabla de precios de hoy; el uso sin precio cuenta 0.
- Las métricas se calculan al vuelo con las conversaciones (bien para decenas de miles; con agentes muy grandes,
  experimentos más cortos o los filtros `from`/`to` de los reportes).
- La retención (`retention_days`) borra las conversaciones viejas, y con ellas sus datos del experimento.

## API

Ver [api_es.md](api_es.md#experimentos-ab). Prometheus: `parla_experiment_conversations_total{agent,experiment,variant}`
cuenta las asignaciones mientras corre un experimento ([observability_es.md](observability_es.md)).
