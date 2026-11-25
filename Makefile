PY ?= .venv/bin/python
PORT ?= 8000

.PHONY: setup setup-voice run test mcp clean-pyc docker-build docker-run

setup:          ## create .venv and install the core
	scripts/setup.sh

setup-voice:    ## core + voice (faster-whisper, piper-tts)
	scripts/setup.sh --voice

run:            ## open Parla at http://127.0.0.1:$(PORT)
	$(PY) app.py $(PORT)

test:           ## all tests (voice/AI are skipped if models or Ollama are missing)
	$(PY) tests/run_all.py

mcp:            ## MCP server over HTTP on :8001/mcp (for stdio: $(PY) mcp_server.py)
	$(PY) mcp_server.py --http --port 8001

docker-build:   ## parla:local image (VOICE=1 adds voice)
	docker build -t parla:local --build-arg INSTALL_VOICE=$(or $(VOICE),0) .

docker-run:     ## run the image at http://127.0.0.1:8000 with the parla-data volume
	docker run --rm -it --read-only --tmpfs /tmp -p 127.0.0.1:8000:8000 -v parla-data:/data parla:local

clean-pyc:
	find . -name __pycache__ -type d -not -path './.venv/*' -prune -exec rm -rf {} +
	find . -name '*.pyc' -not -path './.venv/*' -delete
