"""Mensajes del servidor para la interfaz, en el idioma de quien la usa (encabezado Accept-Language).

La clave es el texto en español tal como lo arma el código, con %s / %d donde va un dato: así un mensaje ya
formateado ("no existe la función «cobrar»") se reconoce y se traduce ("there's no function «cobrar»"), y los datos
de adentro también se traducen si son otro mensaje conocido. Solo se traducen los campos error / warnings / problems
de las respuestas JSON (server.py, reply); los logs y lo que el bot le dice a la gente quedan como están.
Sumar un idioma: otro diccionario como EN en DICTS. Ver CONTRIBUTING.md.
"""
import re

EN = {
}
DICTS = {"en": EN}
FIELDS = ("error", "warnings", "problems")


def _compile(key):
    return re.compile(re.escape(key).replace("%s", "(.+?)").replace("%d", r"(-?\d+)"), re.S)


_PATTERNS = {lang: [(_compile(k), v) for k, v in sorted(d.items(), key=lambda kv: -len(kv[0])) if "%" in k] for lang, d in DICTS.items()}


def lang_of(header):
    """'en-US,en;q=0.9' -> 'en'. Sin encabezado o en español -> 'es' (las APIs siguen contestando como siempre)."""
    first = (header or "").split(",")[0].strip().lower()[:2]
    return first if first in DICTS else "es" if first in ("", "es") else "en"


def tr(msg, lang):
    """Traduce un mensaje (ya formateado) del español a lang. Si no se conoce, sale igual."""
    d = DICTS.get(lang)
    if not d or not isinstance(msg, str):
        return msg
    if msg in d:
        return d[msg]
    for pattern, english in _PATTERNS[lang]:
        m = pattern.fullmatch(msg)
        if m:
            return english.replace("%d", "%s") % tuple(tr(g, lang) for g in m.groups())
    return msg


def translate(data, lang):
    """Traduce los campos de mensajes de una respuesta (dicts y listas anidadas), sin tocar el resto."""
    if lang not in DICTS:
        return data
    if isinstance(data, list):
        return [translate(x, lang) for x in data]
    if not isinstance(data, dict):
        return data
    out = {}
    for k, v in data.items():
        if k in FIELDS and isinstance(v, str):
            out[k] = tr(v, lang)
        elif k in FIELDS and isinstance(v, list):
            out[k] = [tr(x, lang) if isinstance(x, str) else translate(x, lang) for x in v]
        else:
            out[k] = translate(v, lang)
    return out


if __name__ == "__main__":
    EN.update({"no existe": "not found", "no existe la función «%s»": "there's no function «%s»", "falló: %s": "failed: %s"})
    _PATTERNS["en"] = [(_compile(k), v) for k, v in EN.items() if "%" in k]
    assert tr("no existe", "en") == "not found" and tr("no existe", "es") == "no existe"
    assert tr("no existe la función «cobrar»", "en") == "there's no function «cobrar»"
    assert tr("falló: no existe", "en") == "failed: not found"
    assert translate({"error": "no existe", "x": {"warnings": ["no existe", "otro"]}, "text": "no existe"}, "en") == \
        {"error": "not found", "x": {"warnings": ["not found", "otro"]}, "text": "no existe"}
    assert lang_of("en-US,en;q=0.9") == "en" and lang_of(None) == "es" and lang_of("es-AR") == "es" and lang_of("fr") == "en"
    print("ok")
