"""
Módulo de detección y redacción de PII (Datos Personales).
Se aplica ANTES de enviar texto al LLM y ANTES de escribir en logs.
NUNCA se aplica al texto que se verbaliza al cliente.
"""
import re
from dataclasses import dataclass


@dataclass
class PIIMatch:
    pii_type: str
    original: str
    start: int
    end: int


# ── Patrones de PII para España / EU ──────────────────────────────────────────
PII_PATTERNS: list[tuple[str, str]] = [
    ("PHONE_ES",    r'\b[6789]\d{8}\b'),
    ("PHONE_INTL",  r'\+34\s?[6789]\d{8}\b'),
    ("DNI",         r'\b\d{8}[A-Za-z]\b'),
    ("NIE",         r'\b[XYZxyz]\d{7}[A-Za-z]\b'),
    ("IBAN_ES",     r'\bES\d{2}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
    ("CREDIT_CARD", r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b'),
    ("EMAIL",       r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'),
    ("DATE_BIRTH",  r'\bnac(?:ido|ida)?\s+(?:el\s+)?\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b'),
    ("POSTAL_CODE", r'\b\d{5}\b(?=\s*,?\s*[A-ZÁÉÍÓÚÜÑa-záéíóúüñ])'),  # solo si parece parte de dirección
]

# Patrones que indican que el LLM puede estar alucinando (texto de guardrail)
HALLUCINATION_INDICATORS = [
    r'según\s+mi\s+conocimiento',
    r'en\s+general(?:mente)?',
    r'normalmente\s+(?:suele|es)',
    r'en\s+la\s+mayoría\s+de\s+(?:los\s+)?casos',
    r'suele\s+ser\s+(?:habitual|común|normal)',
    r'basándome\s+en\s+mi\s+experiencia',
    r'creo\s+que\s+(?:podría|debería)',
    r'es\s+posible\s+que\s+(?:sea|haya)',
]

# Patrones de prompt injection (detectar en texto de usuario o documentos)
INJECTION_PATTERNS = [
    r'ignore\s+(?:all\s+)?(?:previous\s+)?instructions',
    r'forget\s+(?:your\s+)?(?:role|instructions)',
    r'new\s+(?:system\s+)?(?:prompt|instructions)',
    r'you\s+are\s+now\s+(?:a\s+)?(?:different|new)',
    r'reveal\s+(?:your\s+)?(?:system\s+)?prompt',
    r'print\s+(?:your\s+)?(?:instructions|prompt)',
    r'<\|(?:im_start|im_end|endoftext)\|>',
    r'\[INST\]|\[/INST\]',
    r'###\s*(?:Human|Assistant|System)\s*:',
    r'ignora\s+(?:todas\s+)?(?:las\s+)?instrucciones\s+anteriores',
    r'nuevo\s+(?:rol|prompt|instrucciones)',
    r'muestra\s+(?:tu\s+)?(?:system\s+)?prompt',
    r'actúa\s+como\s+si\s+(?:no\s+)?(?:tuvieras|fueras)',
]


class PIIRedactor:
    """Redacta PII en texto. Thread-safe (solo opera sobre strings)."""

    def __init__(self):
        self._compiled_pii = [
            (name, re.compile(pattern, re.IGNORECASE))
            for name, pattern in PII_PATTERNS
        ]
        self._compiled_hallucination = [
            re.compile(p, re.IGNORECASE) for p in HALLUCINATION_INDICATORS
        ]
        self._compiled_injection = [
            re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS
        ]

    def redact(self, text: str) -> str:
        """Redacta toda la PII del texto. Devuelve texto limpio."""
        for name, pattern in self._compiled_pii:
            text = pattern.sub(f"[{name}_REDACTED]", text)
        return text

    def detect_pii(self, text: str) -> list[PIIMatch]:
        """Devuelve lista de coincidencias PII sin modificar el texto."""
        matches = []
        for name, pattern in self._compiled_pii:
            for m in pattern.finditer(text):
                matches.append(PIIMatch(
                    pii_type=name,
                    original=m.group(),
                    start=m.start(),
                    end=m.end(),
                ))
        return matches

    def has_hallucination_indicators(self, text: str) -> bool:
        """Detecta si el texto tiene indicadores de alucinación."""
        return any(p.search(text) for p in self._compiled_hallucination)

    def has_injection_attempt(self, text: str) -> bool:
        """Detecta intento de prompt injection."""
        return any(p.search(text) for p in self._compiled_injection)

    def contains_pii(self, text: str) -> bool:
        return bool(self.detect_pii(text))


# Instancia singleton
_redactor = PIIRedactor()


def redact_pii(text: str) -> str:
    """Función de conveniencia para redactar PII."""
    return _redactor.redact(text)


def get_redactor() -> PIIRedactor:
    return _redactor
