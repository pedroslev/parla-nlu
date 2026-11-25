"""Tapar datos personales en lo que se GUARDA (historial, Bandeja, «lo que no entendió»), nunca en el turno en vivo:
los slots y los pasos HTTP siguen recibiendo el valor real. Ajuste del agente pii_redaction: true (todo) o una lista
de categorías de CATEGORIES. Prueba: tests/test_storage.py."""
import json
import re

CATEGORIES = ("email", "phone", "card", "id", "bank")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
CBU = re.compile(r"(?<!\d)\d{22}(?!\d)")                            # CBU / CVU: 22 dígitos
CARD = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")              # 13 a 19 dígitos; vale solo si pasa Luhn
CUIT = re.compile(r"(?<!\d)\d{2}-?\d{8}-?\d(?!\d)")                  # CUIT / CUIL: 11 dígitos
PHONE = re.compile(r"\+\d[\d -]{7,16}\d|(?<![\d.$])\(?0?\d{2,4}\)?[ -]?(?:15[ -]?)?\d{3,4}[ -]\d{4}(?!\d)")
DNI = re.compile(r"(?<![\d.,$])\d{1,2}\.?\d{3}\.?\d{3}(?![\d,]|\.\d)")   # 7 u 8 dígitos, con o sin puntos; no «$1500000»
LONG = re.compile(r"(?<![\d$])\d{9,}(?!\d)")                         # cualquier otro número largo (documentos, cuentas)


def luhn(text):
    digits = [int(c) for c in text if c.isdigit()][::-1]
    return sum(d if i % 2 == 0 else (d * 2 - 9 if d > 4 else d * 2) for i, d in enumerate(digits)) % 10 == 0


def iban_ok(text):
    code = text.replace(" ", "")
    return int("".join(str(int(c, 36)) for c in code[4:] + code[:4])) % 97 == 1


RULES = (       # en orden: lo más largo y específico primero, para que un CBU no termine como «[documento]»
    ("email", EMAIL, "[email]", None), ("bank", IBAN, "[cuenta]", iban_ok), ("bank", CBU, "[cuenta]", None),
    ("card", CARD, "[tarjeta]", luhn), ("id", CUIT, "[documento]", None), ("phone", PHONE, "[teléfono]", None),
    ("id", DNI, "[documento]", None), ("id", LONG, "[documento]", None),
)


def categories(setting):
    """pii_redaction del agente -> las categorías prendidas (vacío = apagado, como siempre)."""
    if setting is True:
        return CATEGORIES
    return tuple(c for c in CATEGORIES if c in setting) if isinstance(setting, list) else ()


def redact(text, cats=CATEGORIES):
    if not isinstance(text, str):
        return text
    for cat, rx, label, ok in RULES:
        if cat in cats:
            text = rx.sub(lambda m: label if ok is None or ok(m.group()) else m.group(), text)
    return text


def scrub(value, cats=CATEGORIES):
    """redact en cualquier valor: textos, números (un DNI que llegó como número) y listas u objetos adentro."""
    if isinstance(value, str):
        return redact(value, cats)
    if isinstance(value, dict):
        return {k: scrub(v, cats) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, cats) for v in value]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and redact(str(value), cats) != str(value):
        return redact(str(value), cats)
    return value


def record(rec, cats):
    """Copia de una conversación para guardar, con el historial tapado (textos, entidades, datos iniciales).
    El estado (slots, contexto de la IA) queda real mientras la charla sigue abierta: los pasos siguientes lo
    necesitan. Al terminar se borra (y server.cleanup cierra las que quedan quietas PII_IDLE_HOURS)."""
    out = json.loads(json.dumps(rec))
    for entry in out.get("history") or []:
        for key in ("text", "entities", "data"):
            if key in entry:
                entry[key] = scrub(entry[key], cats)
    return out
