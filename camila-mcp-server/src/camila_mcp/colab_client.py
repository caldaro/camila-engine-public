"""Cliente asíncrono para interactuar con el worker XTTS-v2 en Google Colab y fallback local."""

import base64
import logging
from typing import Tuple, Dict, Any
from pathlib import Path
import httpx

from camila_mcp.config import settings

logger = logging.getLogger("camila_mcp.client")

# ═════════════════════════════════════════════════════════════════════════════
# 1. ENRUTAMIENTO EMOCIONAL ESTRICTO (Audios de Referencia del Master Audio)
# ═════════════════════════════════════════════════════════════════════════════
# El MCP actúa como un actor de doblaje disciplinado. Cada token debe apuntar
# milimétricamente a los cortes extraídos del audio maestro de Camila.
HARD_EMOTION_ROUTING: Dict[str, Dict[str, str]] = {
    # Corte 1: Sereno (sereno.wav) — Pausada, centrada, bajo control
    "sereno":     {"file": "sereno.wav",     "endpoint_token": "sereno",     "rate": "+10%", "pitch": "+0Hz"},
    "serena":     {"file": "sereno.wav",     "endpoint_token": "sereno",     "rate": "+10%", "pitch": "+0Hz"},
    "calma":      {"file": "sereno.wav",     "endpoint_token": "sereno",     "rate": "+10%", "pitch": "+0Hz"},
    "empatico":   {"file": "sereno.wav",     "endpoint_token": "sereno",     "rate": "+7%",  "pitch": "-1Hz"},
    "empático":   {"file": "sereno.wav",     "endpoint_token": "sereno",     "rate": "+7%",  "pitch": "-1Hz"},

    # Corte 2: Alegre (alegre.wav) — Enérgica, luminosa, contagiando el día
    "alegre":     {"file": "alegre.wav",     "endpoint_token": "alegre",     "rate": "+15%", "pitch": "+3Hz"},
    "feliz":      {"file": "alegre.wav",     "endpoint_token": "alegre",     "rate": "+15%", "pitch": "+3Hz"},
    "entusiasta": {"file": "alegre.wav",     "endpoint_token": "alegre",     "rate": "+15%", "pitch": "+3Hz"},

    # Corte 3: Sarcástico (sarcastico.wav) — Mordaz, incisiva, media sonrisa
    "sarcastico": {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},
    "sarcástico": {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},
    "picara":     {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},
    "pícara":     {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},
    "ironica":    {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},
    "irónica":    {"file": "sarcastico.wav", "endpoint_token": "sarcastico", "rate": "+6%",  "pitch": "-3Hz"},

    # Corte 4: Tierno (tierno.wav) — Suave, pausada, íntima y dulce
    "tierno":     {"file": "tierno.wav",     "endpoint_token": "tierno",     "rate": "-3%",  "pitch": "+2Hz"},
    "tierna":     {"file": "tierno.wav",     "endpoint_token": "tierno",     "rate": "-3%",  "pitch": "+2Hz"},
    "dulce":      {"file": "tierno.wav",     "endpoint_token": "tierno",     "rate": "-3%",  "pitch": "+2Hz"},
    "cariñosa":   {"file": "tierno.wav",     "endpoint_token": "tierno",     "rate": "-3%",  "pitch": "+2Hz"},
    "amorosa":    {"file": "tierno.wav",     "endpoint_token": "tierno",     "rate": "-3%",  "pitch": "+2Hz"},

    # Corte 5: Toñeca / Paisa (toneca.wav) — Consentidora, cadencia paisa, dulce complicidad
    "toneca":       {"file": "toneca.wav",   "endpoint_token": "toneca",     "rate": "-2%",  "pitch": "+1Hz"},
    "toñeca":       {"file": "toneca.wav",   "endpoint_token": "toneca",     "rate": "-2%",  "pitch": "+1Hz"},
    "consentidora": {"file": "toneca.wav",   "endpoint_token": "toneca",     "rate": "-2%",  "pitch": "+1Hz"},
    "paisa":        {"file": "toneca.wav",   "endpoint_token": "toneca",     "rate": "-2%",  "pitch": "+1Hz"},

    # Corte 6: Regaño (regano.wav) — Firme, autoritaria, disciplina antioqueña
    "regano":       {"file": "regano.wav",   "endpoint_token": "regano",     "rate": "+8%",  "pitch": "-2Hz"},
    "regaño":       {"file": "regano.wav",   "endpoint_token": "regano",     "rate": "+8%",  "pitch": "-2Hz"},
    "autoridad":    {"file": "regano.wav",   "endpoint_token": "regano",     "rate": "+8%",  "pitch": "-2Hz"},
    "firme":        {"file": "regano.wav",   "endpoint_token": "regano",     "rate": "+8%",  "pitch": "-2Hz"},
}

DEFAULT_FALLBACK_ROUTING = HARD_EMOTION_ROUTING["sereno"]


def resolve_emotion_routing(raw_token: str) -> Tuple[str, str, Dict[str, str]]:
    """Resuelve con precisión militar el token de ánimo recibido hacia el corte de referencia.
    
    Si Camila envía un token no reconocido (ej. [animo: pensativa]), realiza un
    fallback automático e imperceptible a 'sereno' (sereno.wav) sin romper el flujo.

    Returns:
        Tuple de (endpoint_token, reference_file, prosody_dict)
    """
    token = (raw_token or "").strip().lower()
    # Limpieza de corchetes y prefijos si viene en formato [animo: ...]
    token = token.replace("[", "").replace("]", "").replace("animo:", "").replace("mood:", "").replace("humor:", "").strip()

    if token in HARD_EMOTION_ROUTING:
        cfg = HARD_EMOTION_ROUTING[token]
        return cfg["endpoint_token"], cfg["file"], cfg

    # Búsqueda semántica de segundo nivel antes del fallback
    if any(k in token for k in ("sarcas", "picar", "ironi", "burla")):
        cfg = HARD_EMOTION_ROUTING["sarcastico"]
        return cfg["endpoint_token"], cfg["file"], cfg
    elif any(k in token for k in ("tiern", "dulce", "carin", "amor")):
        cfg = HARD_EMOTION_ROUTING["tierno"]
        return cfg["endpoint_token"], cfg["file"], cfg
    elif any(k in token for k in ("alegr", "feliz", "entusias")):
        cfg = HARD_EMOTION_ROUTING["alegre"]
        return cfg["endpoint_token"], cfg["file"], cfg
    elif any(k in token for k in ("seren", "calm", "tranquil", "empat")):
        cfg = HARD_EMOTION_ROUTING["sereno"]
        return cfg["endpoint_token"], cfg["file"], cfg

    # Token no reconocido: Fallback automático y seguro a 'sereno' (sereno.wav)
    logger.info(f"Token de ánimo '{raw_token}' no reconocido. Aplicando fallback automático a 'sereno' (sereno.wav).")
    return DEFAULT_FALLBACK_ROUTING["endpoint_token"], DEFAULT_FALLBACK_ROUTING["file"], DEFAULT_FALLBACK_ROUTING


async def synthesize_via_colab(text: str, emotion_token: str, ref_file: str) -> Dict[str, Any]:
    """Envía la solicitud de síntesis al endpoint del worker XTTS-v2 en Google Colab."""
    colab_base = settings.colab_url
    if not colab_base:
        raise ValueError("COLAB_TTS_URL no está configurada")

    url = f"{colab_base}/synthesize"
    headers = {
        "Authorization": f"Bearer {settings.COLAB_API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "emotion": emotion_token
    }

    async with httpx.AsyncClient(timeout=settings.COLAB_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if "audio" not in data:
            raise RuntimeError("Respuesta de Colab no contiene payload de audio")
            
        return {
            "source": "colab_xtts_v2",
            "audio_base64": data["audio"],
            "format": data.get("format", "wav"),
            "emotion_used": emotion_token,
            "conditioning_file": ref_file,
            "inference_ms": data.get("inference_ms", 0),
            "status": "success"
        }


async def synthesize_via_fallback(text: str, prosody_cfg: Dict[str, str], emotion_token: str, ref_file: str) -> Dict[str, Any]:
    """Fallback local transparente usando Edge-TTS (es-CO-SalomeNeural) con prosodia adaptativa."""
    import edge_tts
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_file:
        tmp_path = tmp_file.name

    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=settings.FALLBACK_VOICE,
            rate=prosody_cfg["rate"],
            pitch=prosody_cfg["pitch"]
        )
        await communicate.save(tmp_path)

        with open(tmp_path, "rb") as fh:
            audio_bytes = fh.read()

        return {
            "source": "fallback_edge_tts",
            "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
            "format": "mp3",
            "emotion_used": emotion_token,
            "conditioning_file": ref_file,
            "voice": settings.FALLBACK_VOICE,
            "status": "success",
            "note": "Generado vía fallback local de alta disponibilidad"
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


async def synthesize_audio(text: str, mood_token: str, save_path: Path | None = None) -> Dict[str, Any]:
    """Orquestador de síntesis: resuelve enrutamiento estricto y gestiona el envío a Colab / Fallback."""
    canonical_token, ref_file, prosody = resolve_emotion_routing(mood_token)
    
    # 1. Intentar con Colab XTTS-v2 si está configurado
    if settings.colab_url:
        try:
            res = await synthesize_via_colab(text, canonical_token, ref_file)
            if save_path:
                audio_bytes = base64.b64decode(res["audio_base64"])
                save_path.write_bytes(audio_bytes)
                res["saved_to"] = str(save_path.resolve())
            return res
        except Exception as exc:
            logger.warning(f"Worker Colab XTTS no respondió ({exc}). Activando fallback local automático...")

    # 2. Si Colab no está configurado o falla, ejecutar fallback local
    if settings.FALLBACK_TTS_ENABLED:
        res = await synthesize_via_fallback(text, prosody, canonical_token, ref_file)
        if save_path:
            audio_bytes = base64.b64decode(res["audio_base64"])
            save_path.write_bytes(audio_bytes)
            res["saved_to"] = str(save_path.resolve())
        return res

    raise RuntimeError("No fue posible sintetizar el audio: Colab inaccesible y fallback deshabilitado.")
