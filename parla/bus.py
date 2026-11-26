"""Bus de eventos en el proceso: publicar desde cualquier hilo, escuchar desde el loop de asyncio (aserver.py).

Temas: "session:<agente>:<sessionId>" (cada vez que se guarda la conversación, deltas y replace de la IA),
"inbox:<agente>" (cambió algo de una charla con persona) y "campaign:<agente>" (avance de campañas).
Un suscriptor lento no frena a nadie: si su cola se llena, se descarta y se le avisa con {"type": "overflow"}
(el cliente vuelve a pedir el estado completo). ponytail: un solo proceso; con PARLA_WORKERS haría falta un broker.
"""
import asyncio
import contextlib
import threading

QUEUE_MAX = 256
_subs = {}                  # tema -> {(loop, cola)}
_lock = threading.Lock()
STATS = {"published": 0, "dropped": 0}


def has(topic):
    return bool(_subs.get(topic))


def subscribers():
    with _lock:
        return sum(len(s) for s in _subs.values())


def _put(queue, event):
    if queue.qsize() >= QUEUE_MAX - 1:
        STATS["dropped"] += 1
        if queue.qsize() < QUEUE_MAX:
            queue.put_nowait({"type": "overflow"})
        return
    queue.put_nowait(event)


def publish(topic, event):
    """Sin suscriptores no cuesta nada. Seguro desde cualquier hilo."""
    subs = _subs.get(topic)
    if not subs:
        return
    with _lock:
        subs = list(subs)
    STATS["published"] += 1
    for loop, queue in subs:
        try:
            loop.call_soon_threadsafe(_put, queue, event)
        except RuntimeError:        # el loop ya cerró
            pass


@contextlib.contextmanager
def subscribe(*topics):
    """Una cola de asyncio que recibe los eventos de esos temas (usar desde el loop)."""
    entry = (asyncio.get_running_loop(), asyncio.Queue(QUEUE_MAX))
    with _lock:
        for topic in topics:
            _subs.setdefault(topic, set()).add(entry)
    try:
        yield entry[1]
    finally:
        with _lock:
            for topic in topics:
                _subs.get(topic, set()).discard(entry)
                if not _subs.get(topic):
                    _subs.pop(topic, None)
