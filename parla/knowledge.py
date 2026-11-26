"""Base de conocimiento del agente: documentos en agent["knowledge"] = [{"id","title","source","url","text"}].

extract() convierte texto/HTML/URL/PDF en texto legible; search() lo parte en fragmentos y busca por similitud
con el mismo modelo de vectores que el NLU (server.py apunta `encode` a su _encode). Sin LLM: eso lo hace brain.fallback.
"""
import base64
import binascii
import io
import re
import urllib.error
import urllib.request
from functools import lru_cache
from html.parser import HTMLParser

import numpy as np

from . import telemetry

encode = None   # server.py lo apunta a su _encode (mismo modelo de vectores, cargado una sola vez)

MAX_BYTES = 3 * 1024 * 1024
TARGET, MAX_CHUNK, OVERLAP = 500, 700, 120
_vectors = {}   # texto -> vector. ponytail: nunca se vacía; purgar si se borran miles de documentos


# ---------- extraer texto ----------
class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "noscript", "svg", "template", "iframe"}
    BLOCK = {"p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol", "dl", "dt", "dd",
             "blockquote", "pre", "header", "footer", "aside", "form", "hr", "figure", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self.in_title = True
        elif re.fullmatch(r"h[1-6]", tag):
            self.out.append("\n\n# ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self.in_title = False
        elif re.fullmatch(r"h[1-6]", tag) or tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip:
            self.out.append(data)


def _tidy(text):
    lines = [re.sub(r"[ \t ]+", " ", l).strip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [l for l in lines if l not in ("#", "-")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _html(raw):
    p = _Text()
    p.feed(raw)
    p.close()
    return {"title": _tidy(p.title)[:120], "text": _tidy("".join(p.out))}


def _b64(payload):
    data = str(payload or "")
    if data.startswith("data:"):
        data = data.split(",", 1)[-1]
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError):
        raise ValueError("el archivo llegó dañado; probá subirlo de nuevo")


def _pdf(raw):
    if not raw.lstrip()[:5].startswith(b"%PDF"):
        raise ValueError("el archivo no parece un PDF")
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        title = str((reader.metadata or {}).get("/Title") or "")
    except Exception as error:
        raise ValueError("no pude leer el PDF (%s)" % error) from error
    text = _tidy(text)
    if not text:
        raise ValueError("el PDF no tiene texto para leer (¿es una imagen escaneada?)")
    return {"title": title.strip()[:120], "text": text}


def _url(url):
    url = str(url or "").strip()
    if not re.match(r"https?://", url, re.I):
        raise ValueError("la dirección tiene que empezar con http:// o https://")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Parla)", "Accept": "text/html,text/plain,application/pdf,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(MAX_BYTES + 1)
            ctype = r.headers.get("Content-Type", "").lower()
            charset = r.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as error:
        raise ValueError("la página respondió con error %s" % error.code) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ValueError("no pude abrir la página (%s)" % getattr(error, "reason", error)) from error
    if len(raw) > MAX_BYTES:
        raise ValueError("la página es demasiado grande (más de 3 MB)")
    if "pdf" in ctype or raw[:5] == b"%PDF-":
        out = _pdf(raw)
    else:
        body = raw.decode(charset, errors="replace")
        out = _html(body) if "html" in ctype or re.search(r"<(html|body|p|div)\b", body[:5000], re.I) else {"title": "", "text": _tidy(body)}
    if not out["text"]:
        raise ValueError("la página no tiene texto para leer (puede que necesite JavaScript)")
    out["title"] = out["title"] or re.sub(r"^https?://(www\.)?", "", url).split("/")[0]
    return out


def extract(kind, payload):
    """kind: "text" | "url" | "pdf" (payload base64) | "html". Devuelve {"title", "text"}; lanza ValueError."""
    if kind == "url":
        return _url(payload)
    if kind == "pdf":
        return _pdf(_b64(payload))
    if kind == "html":
        out = _html(str(payload or ""))
    elif kind == "text":
        out = {"title": "", "text": _tidy(str(payload or ""))}
    else:
        raise ValueError("no sé leer «%s»: usá texto, html, url o pdf" % kind)
    if not out["text"]:
        raise ValueError("no hay texto para guardar")
    out["title"] = out["title"] or out["text"].split("\n", 1)[0].lstrip("# ")[:80]
    return out


# ---------- fragmentos ----------
QUESTION = re.compile(r"^(p|pregunta|q|question)\s*[:.)-]\s*", re.I)
HEADING = re.compile(r"^#{1,6}\s+(.+)$")


def _units(text):
    """[(título de sección, texto, pregunta|None)]: párrafos, o pares pregunta/respuesta que no se separan."""
    units, heading, cur, question = [], "", [], None

    def flush():
        nonlocal cur, question
        if cur:
            units.append((heading, "\n".join(cur), question))
        cur, question = [], None

    for line in text.split("\n"):
        line = line.strip()
        m = HEADING.match(line)
        if m:
            flush()
            heading = m.group(1).strip()
        elif not line:
            if not (question and len(cur) == 1):      # «P:» y su «R:» separados por una línea en blanco siguen juntos
                flush()
        elif QUESTION.match(line) or (line.endswith("?") and len(line) < 200 and (not cur or (question and len(cur) > 1))):
            flush()
            cur, question = [line], QUESTION.sub("", line)
        else:
            cur.append(line)
    flush()
    return units


def _split(body):
    """Un párrafo largo en pedazos de ~TARGET letras por oraciones, repitiendo un poco del final del anterior."""
    sentences = re.split(r"(?<=[.!?;:])\s+", body)
    pieces, cur = [], ""
    for s in sentences:
        while len(s) > MAX_CHUNK:                        # una «oración» sin puntos: se corta por palabras
            cut = s.rfind(" ", 0, TARGET)
            cut = cut if cut > 0 else TARGET
            head, s = s[:cut], s[cut:].strip()
            if cur:
                pieces.append(cur)
            pieces.append(head)
            cur = ""
        if cur and len(cur) + len(s) + 1 > TARGET:
            pieces.append(cur)
            tail = cur[-OVERLAP:]
            cur = tail[tail.find(" ") + 1:] + " " + s if " " in tail else s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        pieces.append(cur)
    return pieces


@lru_cache(maxsize=512)
def chunks(text):
    """Tupla de (texto del fragmento, pregunta|None). Las preguntas frecuentes van una por fragmento."""
    out, buf, buf_head = [], "", None

    def emit(head, body, question=None):
        out.append(((head + "\n" + body) if head else body, question))

    for head, body, question in _units(text or ""):
        if question or len(body) > MAX_CHUNK or head != buf_head or len(buf) + len(body) + 2 > TARGET:
            if buf:
                emit(buf_head, buf)
            buf, buf_head = "", head
        if question:
            emit(head, body, question)
        elif len(body) > MAX_CHUNK:
            for piece in _split(body):
                emit(head, piece)
        else:
            buf = (buf + "\n\n" + body).strip()
    if buf:
        emit(buf_head, buf)
    return tuple(out)


# ---------- búsqueda ----------
def _vecs(texts):
    missing = list({t for t in texts if t not in _vectors})
    if missing:
        _vectors.update(zip(missing, encode(missing)))
    return np.stack([_vectors[t] for t in texts])


def search(agent, query, k=3):
    """[{"text", "title", "doc", "score"}] de mayor a menor. score = similitud coseno (0..1 aprox.)."""
    with telemetry.span("knowledge.search", metric="parla_knowledge_search_duration_seconds",
                        **{"parla.knowledge.docs": len((agent or {}).get("knowledge") or [])}) as sp:
        hits = _search(agent, query, k)
        sp.set(**{"parla.knowledge.hits": len(hits), "parla.knowledge.top_score": hits[0]["score"] if hits else None})
        return hits


def _search(agent, query, k):
    query = (query or "").strip()
    rows = []   # (texto, título, id del doc, clave a comparar)
    for doc in (agent or {}).get("knowledge") or []:
        title, did = doc.get("title") or "", doc.get("id") or ""
        for text, question in chunks(doc.get("text") or ""):
            rows.append((text, title, did, (title + "\n" + text).lower()))   # el título del documento da contexto
            if question:                                  # la pregunta sola también cuenta: «¿abren los domingos?» ≈ «P: ¿Qué días abren?»
                rows.append((text, title, did, question.lower()))
    if not rows or not query or encode is None:
        return []
    sims = _vecs([r[3] for r in rows]) @ encode([query.lower()])[0]   # la consulta no se cachea: crecería sin fin
    best = {}
    for (text, title, doc, _), score in zip(rows, sims.tolist()):
        if score > best.get((doc, text), (None, -2))[1]:
            best[(doc, text)] = ({"text": text, "title": title, "doc": doc}, score)
    ranked = sorted(best.values(), key=lambda x: -x[1])[:max(1, int(k))]
    return [{**hit, "score": round(score, 4)} for hit, score in ranked]
