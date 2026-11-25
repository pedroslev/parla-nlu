#!/usr/bin/env python3
"""Servidor MCP de Parla (las configs de Claude Code, Codex, Claude Desktop y Cursor apuntan a este archivo).
Ver docs/mcp.md.   .venv/bin/python mcp_server.py [--http --port 8001]"""
from parla.mcp_server import main

if __name__ == "__main__":
    main()
