#!/usr/bin/env bash
# Installs Parla: creates .venv with Python >= 3.11 and the dependencies. See --help.
set -euo pipefail

usage() {
  cat <<'TXT'
Usage: scripts/setup.sh [--voice] [--ollama] [--lang en|es|pt] [--help]

  --voice    also install voice (faster-whisper + piper-tts; needs ffmpeg)
  --ollama   download the local AI model qwen2.5:0.5b (if Ollama is installed)
  --lang xx  default interface language: en, es or pt (asked if omitted and interactive; saved as PARLA_LANG in .env)
  --help     show this help

PYTHON variable: the interpreter to use (default: the first of python3.13, python3.12, python3.11, python3).
TXT
}

VOICE=0; OLLAMA=0; UILANG=""
while [ $# -gt 0 ]; do
  arg="$1"; shift
  case "$arg" in
    --voice) VOICE=1 ;;
    --ollama) OLLAMA=1 ;;
    --lang) UILANG="${1:-}"; shift || true ;;
    --lang=*) UILANG="${arg#--lang=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

case "$UILANG" in ""|en|es|pt) ;; *) echo "--lang must be en, es or pt" >&2; exit 2 ;; esac

cd "$(dirname "$0")/.."

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi
if [ -z "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
  echo "Parla needs Python 3.11 or newer (found: ${PY:-none}). Install it or pass PYTHON=/path/to/python3.11" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv with $("$PY" --version)…"
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip
echo "Installing dependencies…"
.venv/bin/pip install -q -r requirements.txt

if [ "$VOICE" = 1 ]; then
  echo "Installing voice…"
  .venv/bin/pip install -q -r requirements-voice.txt
  command -v ffmpeg >/dev/null 2>&1 || echo "Warning: ffmpeg is missing (brew install ffmpeg / apt install ffmpeg); it's needed to read audio from the browser."
fi

if [ "$OLLAMA" = 1 ]; then
  if command -v ollama >/dev/null 2>&1; then
    ollama pull qwen2.5:0.5b
  else
    echo "Warning: Ollama is not installed (https://ollama.com); local AI stays off."
  fi
fi

# Default interface language (each user can still change it in the UI)
if [ -z "$UILANG" ]; then
  guess="$(printf '%s' "${LC_ALL:-${LANG:-en}}" | cut -c1-2)"
  case "$guess" in es|pt) ;; *) guess=en ;; esac
  UILANG="$guess"
  if [ -t 0 ]; then
    read -r -p "Interface language / Idioma / Idioma da interface [en/es/pt] ($guess): " answer || true
    case "${answer:-$guess}" in en|es|pt) UILANG="${answer:-$guess}" ;; *) echo "Unknown language, using $guess." ;; esac
  fi
fi
[ -f .env ] || cp .env.example .env
if grep -Eq '^#? *PARLA_LANG=' .env; then
  sed -i.bak "s/^#\{0,1\} *PARLA_LANG=.*/PARLA_LANG=$UILANG/" .env && rm -f .env.bak
else
  printf '\n# Default interface language: en, es or pt\nPARLA_LANG=%s\n' "$UILANG" >> .env
fi
echo "Interface language: $UILANG (PARLA_LANG in .env)"

cat <<'TXT'

Done. Next steps:
  make run                           # opens http://127.0.0.1:8000 (loads .env)
  .venv/bin/python app.py            # same, without .env: export PARLA_LANG yourself
  .venv/bin/python tests/run_all.py  # runs the tests
  .venv/bin/python mcp_server.py     # MCP server (Claude Code, Codex, Cursor…)
TXT
