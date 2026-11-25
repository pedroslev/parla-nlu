"""Pruebas de knowledge.py: `.venv/bin/python tests/test_knowledge.py` imprime "ok"."""
import base64
import time

import support
support.temp_data()
from parla import knowledge, server as app  # noqa: E402

assert knowledge.encode is app._encode

FAQ = """# Horarios
P: ¿Qué días abren?
R: Abrimos de lunes a viernes de 9 a 18 y los sábados de 9 a 13. Los domingos está cerrado.

P: ¿Dónde queda el local?

R: Estamos en Av. Corrientes 1234, CABA, a dos cuadras del subte B.

# Pagos
Pregunta: ¿Qué medios de pago aceptan?
Respuesta: Efectivo, tarjeta de débito, crédito en 3 cuotas sin interés y Mercado Pago.

¿Hacen envíos?
Sí, enviamos a todo el país por correo; tarda entre 3 y 5 días hábiles.
"""

# ---- fragmentos: cada pregunta con su respuesta, y el título de sección adelante
parts = [t for t, _ in knowledge.chunks(FAQ)]
assert len(parts) == 4, parts
assert parts[0].startswith("Horarios\nP: ¿Qué días abren?") and "domingos" in parts[0], parts[0]
assert "Corrientes" in parts[1] and "¿Dónde queda" in parts[1], parts[1]   # P y R separados por línea en blanco
assert parts[2].startswith("Pagos\n") and "Mercado Pago" in parts[2]
assert "todo el país" in parts[3] and parts[3].startswith("Pagos\n¿Hacen envíos?")
long = " ".join("Si el producto llegó fallado o no te gustó, podés devolverlo dentro de los %d días; te reintegramos el dinero o lo cambiamos por otro." % d for d in range(10, 40))
pieces = knowledge.chunks(long)
assert len(pieces) > 2 and all(len(t) <= 700 for t, _ in pieces), [len(t) for t, _ in pieces]

# ---- búsqueda: pregunta reformulada → el fragmento correcto
agent = {"knowledge": [{"id": "k1", "title": "Preguntas frecuentes", "source": "texto", "text": FAQ},
                       {"id": "k2", "title": "Devoluciones", "source": "texto", "text": long}]}
assert knowledge.search({"knowledge": []}, "hola") == [] and knowledge.search({}, "hola") == []
cases = {"¿abren el domingo?": "domingos", "cuál es la dirección": "Corrientes", "¿puedo pagar con tarjeta?": "Mercado Pago",
         "¿mandan pedidos a otras provincias?": "todo el país", "quiero devolver un producto": "devolverlo"}
for q, word in cases.items():
    hits = knowledge.search(agent, q, 3)
    assert word in hits[0]["text"], (q, hits)
    assert hits == sorted(hits, key=lambda x: -x["score"]) and 0 < hits[0]["score"] <= 1.0001
    assert set(hits[0]) == {"text", "title", "doc", "score"}
assert knowledge.search(agent, "¿abren el domingo?", 3)[0]["doc"] == "k1"
big = {"knowledge": [{"id": "b%d" % i, "title": "t", "text": "Párrafo número %d sobre el producto %d." % (i, i)} for i in range(2000)]}
knowledge.search(big, "producto")                       # calienta el caché de vectores
t = time.time(); knowledge.search(big, "producto 17"); assert time.time() - t < 0.5, time.time() - t

# ---- html: texto legible, sin script/style/nav, títulos como secciones
html = """<html><head><title>Mi Tienda</title><style>.x{color:red}</style><script>alert(1)</script></head>
<body><nav><a href="/">Inicio</a> <a href="/c">Contacto</a></nav><h1>Envíos</h1><p>Enviamos a <b>todo</b> el país.</p>
<ul><li>Correo</li><li>Moto</li></ul></body></html>"""
out = knowledge.extract("html", html)
assert out["title"] == "Mi Tienda", out
assert "alert" not in out["text"] and "color" not in out["text"] and "Inicio" not in out["text"], out["text"]
assert "# Envíos" in out["text"] and "Enviamos a todo el país." in out["text"] and "- Correo" in out["text"], out["text"]
assert knowledge.extract("text", "  Hola\n\n\n\nchau ")["text"] == "Hola\n\nchau"


# ---- pdf: uno chiquito escrito a mano
def tiny_pdf(text):
    stream = b"BT /F1 12 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % x for x in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


out = knowledge.extract("pdf", base64.b64encode(tiny_pdf("Horario de atencion: 9 a 18")).decode())
assert "Horario de atencion" in out["text"], out
out = knowledge.extract("pdf", "data:application/pdf;base64," + base64.b64encode(tiny_pdf("hola pdf")).decode())
assert "hola pdf" in out["text"]


def fails(kind, payload, word):
    try:
        knowledge.extract(kind, payload)
    except ValueError as error:
        assert word in str(error), error
    else:
        raise AssertionError("tenía que fallar: %s %r" % (kind, payload))


fails("pdf", base64.b64encode(b"no soy un pdf").decode(), "PDF")
fails("text", "   ", "texto")
fails("otro", "x", "no sé leer")
# ---- url: solo http/https
for bad in ["file:///etc/passwd", "ftp://x.com/a", "javascript:alert(1)", "www.sin-esquema.com", ""]:
    fails("url", bad, "http")
print("ok")
