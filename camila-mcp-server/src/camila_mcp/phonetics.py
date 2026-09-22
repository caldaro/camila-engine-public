"""Módulo de Dicción Fonética y Reglas de Marca para Camila MCP.

Asegura pronunciación bilingüe natural en modelos TTS en español (XTTS-v2 y Edge-TTS),
evitando que nombres de marcas o ubicaciones de Virginia/DMV se pronuncien con fonética
literal incorrecta.
"""

import re
from typing import Dict, List, Tuple

# Diccionario estricto de reemplazo fonético para marcas y ubicaciones DMV
PHONETIC_REPLACEMENTS: List[Tuple[re.Pattern, str]] = [
    # 1. Marcas solicitadas expresamente por directriz
    (re.compile(r"\bLoudoun\s+Cabs\b", re.IGNORECASE), "Laudun Cabs"),
    (re.compile(r"\bFairfax\b", re.IGNORECASE), "Férfax"),
    (re.compile(r"\bChantilly\b", re.IGNORECASE), "Chantillí"),
    (re.compile(r"\bBizWorx\b", re.IGNORECASE), "Bisworks"),

    # 2. Reemplazos complementarios de geografía y portafolio DMV
    (re.compile(r"\bLoudoun\b", re.IGNORECASE), "Laudun"),
    (re.compile(r"\bDulles\b", re.IGNORECASE), "Dales"),
    (re.compile(r"\bSedan\b", re.IGNORECASE), "Sedán"),
    (re.compile(r"\bIAD\b"), "I A D"),
    (re.compile(r"\bDCA\b"), "D C A"),
    (re.compile(r"\bBWI\b"), "B W I"),
]


def apply_phonetic_rules(text: str) -> str:
    """Aplica las reglas de dicción fonética y limpia artefactos antes de enviar al TTS.
    
    Args:
        text: Texto original generado por el LLM o usuario.
        
    Returns:
        Texto transformado fonéticamente para una pronunciación bilingüe natural.
    """
    if not text:
        return ""

    processed = text

    # Limpiar tokens de ánimo si vinieron en el cuerpo del texto: [animo: ...] o [mood: ...]
    processed = re.sub(r"\[(?:animo|humor|mood):\s*[^\]]+\]", "", processed, flags=re.IGNORECASE)

    # Limpiar directivas de archivo si vinieron en el texto: [[ENVIAR: ...]]
    processed = re.sub(r"\[\[(?:ENVIAR|FILE|ADJUNTO):\s*[^\]]+\]\]", "", processed, flags=re.IGNORECASE)

    # Eliminar símbolos de markdown que ensucian la síntesis de voz (*, _, `, #, ~, |)
    for ch in ("*", "_", "`", "#", "~", "|", "{", "}"):
        processed = processed.replace(ch, "")

    # Normalizar pausas telefónicas para dicción fluida: 571-233-8828 -> 5 7 1, 2 3 3, 8 8 2 8
    processed = re.sub(r"\b(\d{3})[-.\s](\d{3})[-.\s](\d{4})\b", r"\1, \2, \3", processed)

    # Aplicar diccionario de reemplazo fonético de marcas
    for pattern, replacement in PHONETIC_REPLACEMENTS:
        processed = pattern.sub(replacement, processed)

    # Normalizar espacios en blanco y saltos de línea repetidos
    processed = re.sub(r"[ \t]+", " ", processed)
    processed = re.sub(r"\n\s*\n+", ". ", processed)
    processed = re.sub(r"\n", ", ", processed)
    processed = re.sub(r"\s+([.,;:!?])", r"\1", processed)
    processed = re.sub(r"\.{2,}", "...", processed)

    return processed.strip()
