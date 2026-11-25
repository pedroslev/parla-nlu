#!/usr/bin/env bash
# Instala Parla: crea .venv con Python >= 3.11 y las dependencias. Ver --help.
set -euo pipefail

usage() {
  cat <<'TXT'
Uso: scripts/setup.sh [--voice] [--ollama] [--help]

  --voice    instala también la voz (faster-whisper + piper-tts; necesita ffmpeg)
  --ollama   baja el modelo de IA local qwen2.5:0.5b (si Ollama está instalado)
  --help     muestra esta ayuda

Variable PYTHON: el intérprete a usar (por defecto el primero de python3.13, python3.12, python3.11, python3).
TXT
}

VOICE=0; OLLAMA=0
for arg in "$@"; do
  case "$arg" in
    --voice) VOICE=1 ;;
    --ollama) OLLAMA=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Opción desconocida: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "Parla necesita Python 3.11 o más nuevo (encontrado: ${PY:-ninguno}). Instalalo o pasá PYTHON=/ruta/a/python3.11" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creando .venv con $("$PY" --version)…"
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
echo "Instalando dependencias…"
.venv/bin/pip install -q -r requirements.txt

if [ "$VOICE" = 1 ]; then
  echo "Instalando voz…"
  .venv/bin/pip install -q -r requirements-voice.txt
  command -v ffmpeg >/dev/null 2>&1 || echo "Aviso: falta ffmpeg (brew install ffmpeg / apt install ffmpeg) para leer el audio del navegador."
fi

if [ "$OLLAMA" = 1 ]; then
  if command -v ollama >/dev/null 2>&1; then
    ollama pull qwen2.5:0.5b
  else
    echo "Aviso: Ollama no está instalado (https://ollama.com); la IA local queda apagada."
  fi
fi

cat <<'TXT'

Listo. Próximos pasos:
  .venv/bin/python app.py            # abre http://127.0.0.1:8000
  .venv/bin/python tests/run_all.py  # corre las pruebas
  .venv/bin/python mcp_server.py     # servidor MCP (Claude Code, Codex, Cursor…)
TXT
