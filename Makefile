PY ?= .venv/bin/python
PORT ?= 8000

.PHONY: setup setup-voice run test mcp clean-pyc

setup:          ## crea .venv e instala el núcleo
	scripts/setup.sh

setup-voice:    ## núcleo + voz (faster-whisper, piper-tts)
	scripts/setup.sh --voice

run:            ## abre Parla en http://127.0.0.1:$(PORT)
	$(PY) app.py $(PORT)

test:           ## todas las pruebas (voz/IA se saltean si faltan modelos u Ollama)
	$(PY) tests/run_all.py

mcp:            ## servidor MCP por HTTP en :8001/mcp (para stdio: $(PY) mcp_server.py)
	$(PY) mcp_server.py --http --port 8001

clean-pyc:
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
	find . -name '*.pyc' -not -path './.venv/*' -delete
