"""Fechas y horas en lenguaje natural en español rioplatense, por reglas (sin modelo).

extract("el jueves que viene a la tarde") -> [{"start", "end", "value": "2026-11-26T16:00", "text"}]
"""
import datetime as dt
import re
import unicodedata

WEEKDAYS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
          "noviembre", "diciembre"]
NUMBERS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
           "ocho": 8, "nueve": 9, "diez": 10, "quince": 15}
PARTS = {"manana": 9, "tarde": 16, "noche": 20}   # «a la tarde» sin hora: una hora razonable de esa franja
NUM = r"(\d{1,3}|" + "|".join(NUMBERS) + ")"
B = r"(?<!\w)"   # borde de palabra que no se confunde con letras acentuadas (ya sin acento)

DATE = [
    ("rel", re.compile(B + r"pasado\s+manana\b")),
    ("rel", re.compile(B + r"(hoy|(?<!la )(?<!por )manana)\b")),
    ("in", re.compile(B + r"(?:dentro\s+de|en)\s+" + NUM + r"\s+(dias?|semanas?)\b")),
    ("week", re.compile(B + r"(?:la\s+)?(?:semana\s+que\s+viene|proxima\s+semana|semana\s+proxima)\b")),
    ("wday", re.compile(B + r"(?:el\s+)?(?:proximo\s+)?(" + "|".join(WEEKDAYS) + r")(?:\s+que\s+viene|\s+proximo)?\b")),
    ("dmy", re.compile(B + r"(?:el\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")),
    ("dm", re.compile(B + r"(?:el\s+)?(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")(?:\s+(?:de\s+)?(\d{4}))?\b")),
]
TIME = [
    ("hm", re.compile(B + r"(?:a\s+las?\s+)?(\d{1,2})(?::|\.)(\d{2})(?:\s*(?:hs|h)\b)?(?:\s+de\s+la\s+(manana|tarde|noche))?")),
    ("h", re.compile(B + r"a\s+las?\s+(\d{1,2})(\s+y\s+media|\s+y\s+cuarto)?(?:\s*(?:hs|h)\b)?(?:\s+de\s+la\s+(manana|tarde|noche))?")),
    ("h", re.compile(B + r"(\d{1,2})(\s+y\s+media|\s+y\s+cuarto)?\s*(?:hs)\b()")),
    ("noon", re.compile(B + r"al\s+mediodia\b")),
    ("part", re.compile(B + r"(?:a|de|por|en)\s+la\s+(manana|tarde|noche)\b")),
]


def _plain(text):
    """minúsculas y sin acentos, con el mismo largo para que las posiciones sirvan sobre el texto original"""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in text.lower())


def _num(word):
    return int(word) if word.isdigit() else NUMBERS[word]


def _date(kind, m, today):
    if kind == "rel":
        return today + dt.timedelta(days={"hoy": 0, "manana": 1}.get(m.group(0).strip(), 2))
    if kind == "in":
        n = _num(m.group(1))
        return today + dt.timedelta(days=n * (7 if m.group(2).startswith("semana") else 1))
    if kind == "week":
        return today + dt.timedelta(days=7 - today.weekday())          # el lunes que viene
    if kind == "wday":
        ahead = (WEEKDAYS.index(m.group(1)) - today.weekday()) % 7
        return today + dt.timedelta(days=ahead or 7)                     # «el jueves» un jueves = el de la otra semana
    if kind == "dmy":
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        day, month, year = int(m.group(1)), MONTHS.index(m.group(2)) + 1, m.group(3)
    year = int(year) + (2000 if year and len(year) == 2 else 0) if year else today.year
    try:
        value = dt.date(year, month, day)
    except ValueError:
        return None
    if not m.group(3) and value < today:                               # «15/3» en noviembre: el que viene
        value = value.replace(year=year + 1)
    return value


def _time(kind, m):
    if kind == "noon":
        return 12, 0
    if kind == "part":
        return PARTS[m.group(1)], 0
    hour = int(m.group(1))
    minute = int(m.group(2)) if kind == "hm" else {"media": 30, "cuarto": 15}.get((m.group(2) or "-").split()[-1], 0)
    part = m.group(3)
    if part in ("tarde", "noche") and hour < 12:
        hour += 12
    elif not part and kind == "h" and 1 <= hour <= 7:                  # «a las 5» para un turno = 17 hs
        hour += 12
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _scan(rules, plain, parse):
    found = []
    for kind, rx in rules:
        for m in rx.finditer(plain):
            value = parse(kind, m)
            if value is not None and not any(f[0] < m.end() and m.start() < f[1] for f in found):
                found.append((m.start(), m.end(), value))
    return found


def extract(text, today=None):
    """[{"start", "end", "value": "YYYY-MM-DD" o "YYYY-MM-DDTHH:MM", "text"}] en orden de aparición.
    Una fecha y una hora pegadas («el jueves a las 5», «a las 5 el jueves») salen juntas."""
    text = str(text or "")
    today = today or dt.date.today()
    plain = _plain(text)
    dates = _scan(DATE, plain, lambda k, m: _date(k, m, today))
    times = [t for t in _scan(TIME, plain, _time) if not any(d[0] < t[1] and t[0] < d[1] for d in dates)]
    out, used = [], set()
    for d in dates:
        pair = next((t for t in times if id(t) not in used and (
            re.fullmatch(r"[\s,]*", plain[d[1]:t[0]]) if t[0] >= d[1] else re.fullmatch(r"[\s,]*", plain[t[1]:d[0]]))), None)
        if pair:
            used.add(id(pair))
            start, end = min(d[0], pair[0]), max(d[1], pair[1])
            value = "%sT%02d:%02d" % (d[2].isoformat(), *pair[2])
        else:
            start, end, value = d[0], d[1], d[2].isoformat()
        out.append({"start": start, "end": end, "value": value, "text": text[start:end]})
    for t in times:
        if id(t) not in used:
            out.append({"start": t[0], "end": t[1], "value": "%sT%02d:%02d" % (today.isoformat(), *t[2]), "text": text[t[0]:t[1]]})
    return sorted(out, key=lambda f: f["start"])
