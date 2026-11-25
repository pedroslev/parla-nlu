"""Parla: armá bots que entienden. Paquete del servidor, el motor y sus módulos."""
import os

__version__ = "0.9.0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # la carpeta del repo
DATA = os.path.abspath(os.environ.get("PARLA_DATA") or os.path.join(ROOT, "data"))   # agentes, usuarios y modelos
