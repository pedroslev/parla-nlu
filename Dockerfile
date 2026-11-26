# Parla in a container. See docs/deployment.md.
#   docker build -t parla .
#   docker build -t parla:voice --build-arg INSTALL_VOICE=1 .                 # + ffmpeg, faster-whisper, piper
#   docker build -t parla:byok --build-arg INSTALL_PROVIDERS=1 .               # + anthropic SDK (Claude)
#   docker build -t parla:baked --build-arg BAKE_EMBED_DIR=/opt/embeddings .  # embedding model (~1.2 GB) baked in
FROM python:3.12-slim

ARG INSTALL_VOICE=0
ARG INSTALL_PROVIDERS=0
# psycopg (Postgres backend, PARLA_DATABASE_URL): ~10 MB, in the default image so the published one runs with
# several replicas without a rebuild. INSTALL_POSTGRES=0 to leave it out.
ARG INSTALL_POSTGRES=1
# Empty: the embedding model is downloaded to the data volume the first time you train.
ARG BAKE_EMBED_DIR=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PARLA_HOST=0.0.0.0 \
    PARLA_DATA=/data \
    PARLA_EMBED_CACHE=${BAKE_EMBED_DIR:-/data/models/embeddings} \
    HF_HOME=/data/models/hf \
    PARLA_FUNCTIONS=0

WORKDIR /app

COPY requirements.txt requirements-voice.txt requirements-providers.txt requirements-postgres.txt ./
RUN if [ "$INSTALL_VOICE" = 1 ]; then \
        apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/* && \
        pip install -r requirements-voice.txt; \
    else \
        pip install -r requirements.txt; \
    fi && \
    if [ "$INSTALL_PROVIDERS" = 1 ]; then pip install -r requirements-providers.txt; fi && \
    if [ "$INSTALL_POSTGRES" = 1 ]; then pip install -r requirements-postgres.txt; fi

# Before copying the code, so 1.2 GB isn't downloaded again on every change. The name must match MODEL
# in parla/server.py.
RUN if [ -n "$BAKE_EMBED_DIR" ]; then \
        HF_HOME=/tmp/hf python -c "from fastembed import TextEmbedding; TextEmbedding('google/embeddinggemma-300m', cache_dir='$BAKE_EMBED_DIR')" && \
        rm -rf /tmp/hf; \
    fi

RUN useradd --uid 10001 --create-home --home-dir /home/parla parla && mkdir /data && chown parla:parla /data
COPY --chown=root:root app.py mcp_server.py ./
COPY --chown=root:root parla ./parla
COPY --chown=root:root web ./web

USER 10001
VOLUME /data
EXPOSE 8000
# The container port must be the same one you open in the browser (see "Origin" in docs/deployment.md).
CMD ["python", "app.py", "8000"]
