"""Servidor WebSocket de voz para la app Android Camila Assistant.

Puente en tiempo real: audio PCM del telefono -> STT (faster-whisper) -> Camila (opencode serve) -> TTS (edge-tts) -> PCM de vuelta.

Uso:
    python camila_ws_server.py
    python camila_ws_server.py --host 0.0.0.0 --port 8000

Variables de entorno:
    CAMILA_WS_HOST (0.0.0.0), CAMILA_WS_PORT (8000), CAMILA_WS_PATH (/ws)
    CAMILA_OC_URL (http://127.0.0.1:4096), CAMILA_OC_DIR (E:\\taxis), CAMILA_AGENT (camila)
    CAMILA_VOICE (es-CO-SalomeNeural), CAMILA_STT_MODEL (base)
    CAMILA_MAX_REPLY_CHARS (350), CAMILA_LLM_TIMEOUT (120)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

import numpy as np
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("camila_ws")

CHUNK_BYTES = 8192
SAMPLE_RATE = 16000
START_RMS = int(os.environ.get("CAMILA_VAD_START_RMS", "350"))
SILENCE_RMS = int(os.environ.get("CAMILA_VAD_SILENCE_RMS", "200"))
SILENCE_CHUNKS_TO_END = int(os.environ.get("CAMILA_VAD_SILENCE_CHUNKS", "4"))
MIN_UTTERANCE_CHUNKS = int(os.environ.get("CAMILA_VAD_MIN_CHUNKS", "3"))
MAX_UTTERANCE_CHUNKS = int(os.environ.get("CAMILA_VAD_MAX_CHUNKS", "60"))
PRE_ROLL_CHUNKS = 3
OUT_CHUNK_BYTES = 8192
OUT_PACE_SECONDS = float(os.environ.get("CAMILA_OUT_PACE_SECONDS", "0.16"))

OC_URL = os.environ.get("CAMILA_OC_URL", "http://127.0.0.1:4096").rstrip("/")
OC_DIR = os.environ.get("CAMILA_OC_DIR", os.getcwd())
AGENT = os.environ.get("CAMILA_AGENT", "camila")
VOICE = os.environ.get("CAMILA_VOICE", "es-CO-SalomeNeural")
STT_MODEL_NAME = os.environ.get("CAMILA_STT_MODEL", "base")
MAX_REPLY_CHARS = int(os.environ.get("CAMILA_MAX_REPLY_CHARS", "350"))
LLM_TIMEOUT = float(os.environ.get("CAMILA_LLM_TIMEOUT", "120"))
GREETING_TEXT = os.environ.get("CAMILA_GREETING", "Hola, soy Camila. Te escucho.")

_stt_model = None
_stt_lock = threading.Lock()


def mcp_phonetics_path() -> Path:
    return Path(__file__).resolve().parents[2] / "camila-mcp-server" / "src"


def apply_phonetic_rules(text: str) -> str:
    try:
        sys.path.insert(0, str(mcp_phonetics_path()))
        from camila_mcp.phonetics import apply_phonetic_rules as rules

        return rules(text)
    except Exception as exc:
        log.debug("Reglas foneticas no disponibles: %s", exc)
        return text


def load_stt():
    global _stt_model
    with _stt_lock:
        if _stt_model is None:
            from faster_whisper import WhisperModel

            log.info("Cargando modelo STT faster-whisper '%s' (CPU int8)...", STT_MODEL_NAME)
            _stt_model = WhisperModel(STT_MODEL_NAME, device="cpu", compute_type="int8")
            log.info("Modelo STT listo.")
        return _stt_model


def transcribe(pcm_bytes: bytes) -> str:
    if len(pcm_bytes) < SAMPLE_RATE:
        return ""
    model = load_stt()
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(
        samples,
        language="es",
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(segment.text.strip() for segment in segments).strip()


def http_json(url: str, payload=None, timeout: float = 30.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def oc_healthy() -> bool:
    try:
        http_json(f"{OC_URL}/global/health", timeout=4.0)
        return True
    except Exception:
        return False


def ensure_oc_server() -> None:
    if oc_healthy():
        return
    executable = shutil.which("opencode")
    if not executable:
        raise RuntimeError("opencode no esta disponible en PATH.")
    log.info("Levantando opencode serve en %s", OC_URL)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [executable, "serve", "--port", OC_URL.rsplit(":", 1)[-1], "--hostname", "127.0.0.1"],
        cwd=OC_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )
    for _ in range(60):
        if oc_healthy():
            return
        threading.Event().wait(1.0)
    raise RuntimeError("opencode serve no respondio.")


def create_oc_session() -> str:
    ensure_oc_server()
    session = http_json(f"{OC_URL}/session", {"agent": AGENT, "title": "Camila Phone"}, timeout=30.0)
    return session["id"]


def ask_camila(session_id: str, text: str) -> str:
    result = http_json(
        f"{OC_URL}/session/{session_id}/message",
        {"agent": AGENT, "parts": [{"type": "text", "text": text}]},
        timeout=LLM_TIMEOUT,
    )
    if result.get("info", {}).get("error"):
        raise RuntimeError("El agente devolvio un error.")
    chunks = [
        part.get("text", "")
        for part in result.get("parts", [])
        if part.get("type") == "text" and not part.get("synthetic") and not part.get("ignored")
    ]
    return "".join(chunks).strip()


def clean_for_speech(text: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_#>|~]", " ", text)
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    limited = " ".join(sentences[:2]).strip()
    if len(limited) > MAX_REPLY_CHARS:
        limited = limited[:MAX_REPLY_CHARS].rsplit(" ", 1)[0] + "."
    return apply_phonetic_rules(limited)


async def synthesize_pcm(text: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, VOICE, rate="+10%")
    mp3 = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])
    if not mp3:
        return b""

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg no esta disponible en PATH.")

    with tempfile.TemporaryDirectory() as tmp:
        mp3_path = Path(tmp) / "camila.mp3"
        wav_path = Path(tmp) / "camila.wav"
        mp3_path.write_bytes(bytes(mp3))
        process = await asyncio.create_subprocess_exec(
            ffmpeg,
            "-y",
            "-i",
            str(mp3_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            str(wav_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        if process.returncode != 0 or not wav_path.exists():
            raise RuntimeError("ffmpeg fallo al decodificar el audio TTS.")
        return wav_path.read_bytes()


def rms_of(chunk: bytes) -> float:
    samples = np.frombuffer(chunk, dtype=np.int16)
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))


class PhoneSession:
    def __init__(self, websocket):
        self.ws = websocket
        self.oc_session_id: str | None = None
        self.pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_CHUNKS)
        self.utterance = bytearray()
        self.in_speech = False
        self.silence_chunks = 0
        self.busy = False
        self.processing_task: asyncio.Task | None = None
        self.cooldown_until = 0.0

    async def send_json(self, payload: dict) -> None:
        try:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))
        except ConnectionClosed:
            pass

    async def run(self) -> None:
        await self.send_json({"type": "state", "value": "listening"})
        if GREETING_TEXT:
            try:
                self.busy = True
                await self.speak(GREETING_TEXT)
            except Exception as exc:
                log.error("Saludo inicial fallo: %s", exc)
            finally:
                self.busy = False
                await self.send_json({"type": "state", "value": "listening"})
        async for message in self.ws:
            if isinstance(message, bytes):
                await self.on_audio(message)
            else:
                log.info("Mensaje de texto del telefono: %s", message)

    async def speak(self, text: str) -> None:
        spoken = clean_for_speech(text) or text
        audio = await synthesize_pcm(spoken)
        if not audio:
            return
        log.info("Camila: %s", spoken)
        await self.send_json({"type": "reply", "text": spoken})
        await self.send_json({"type": "state", "value": "speaking"})
        for i in range(0, len(audio), OUT_CHUNK_BYTES):
            await self.ws.send(audio[i : i + OUT_CHUNK_BYTES])
            await asyncio.sleep(OUT_PACE_SECONDS)

    async def on_audio(self, chunk: bytes) -> None:
        if self.busy or time.monotonic() < self.cooldown_until:
            return
        level = rms_of(chunk)

        if not self.in_speech:
            self.pre_roll.append(chunk)
            if level >= START_RMS:
                self.in_speech = True
                self.silence_chunks = 0
                self.utterance = bytearray(b"".join(self.pre_roll))
                log.info("Voz detectada (rms=%.0f)", level)
            return

        self.utterance.extend(chunk)
        if level < SILENCE_RMS:
            self.silence_chunks += 1
        else:
            self.silence_chunks = 0

        duration_chunks = len(self.utterance) // CHUNK_BYTES
        enough_silence = self.silence_chunks >= SILENCE_CHUNKS_TO_END
        enough_speech = duration_chunks >= MIN_UTTERANCE_CHUNKS
        too_long = duration_chunks >= MAX_UTTERANCE_CHUNKS

        if (enough_silence and enough_speech) or too_long:
            pcm = bytes(self.utterance)
            self.in_speech = False
            self.silence_chunks = 0
            self.utterance = bytearray()
            self.busy = True
            self.processing_task = asyncio.create_task(self.process_utterance(pcm))

    async def ensure_oc_session(self) -> bool:
        if self.oc_session_id:
            return True
        try:
            self.oc_session_id = await asyncio.to_thread(create_oc_session)
            log.info("Sesion de Camila creada: %s", self.oc_session_id)
            return True
        except Exception as exc:
            log.error("No se pudo crear la sesion de Camila: %s", exc)
            await self.send_json({"type": "state", "value": "error"})
            return False

    async def process_utterance(self, pcm: bytes) -> None:
        try:
            await self.send_json({"type": "state", "value": "thinking"})
            user_text = await asyncio.to_thread(transcribe, pcm)
            if not user_text:
                log.info("STT sin texto util; se ignora el turno.")
                return
            log.info("Usuario: %s", user_text)
            await self.send_json({"type": "transcript", "text": user_text})

            if not await self.ensure_oc_session():
                return

            reply = await asyncio.to_thread(ask_camila, self.oc_session_id, user_text)
            spoken = clean_for_speech(reply) or "No pude generar una respuesta."
            await self.speak(spoken)
        except ConnectionClosed:
            log.info("Telefono desconectado durante el turno.")
        except Exception as exc:
            log.error("Error procesando el turno: %s", exc)
            await self.send_json({"type": "state", "value": "error"})
        finally:
            self.busy = False
            self.cooldown_until = time.monotonic() + 0.9
            await self.send_json({"type": "state", "value": "listening"})


async def handler(websocket) -> None:
    path = websocket.request.path
    expected_path = os.environ.get("CAMILA_WS_PATH", "/ws")
    if path != expected_path:
        await websocket.close(code=1008, reason="Ruta no valida")
        return
    peer = websocket.remote_address
    log.info("Telefono conectado desde %s", peer)
    session = PhoneSession(websocket)
    try:
        await session.run()
    except ConnectionClosed:
        pass
    finally:
        if session.processing_task:
            session.processing_task.cancel()
        log.info("Telefono desconectado: %s", peer)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor WebSocket de voz para Camila Assistant")
    parser.add_argument("--host", default=os.environ.get("CAMILA_WS_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("CAMILA_WS_PORT", "8000")))
    args = parser.parse_args()

    log.info("Camila WS escuchando en ws://%s:%s%s", args.host, args.port, os.environ.get("CAMILA_WS_PATH", "/ws"))
    log.info("Cerebro: %s (agente '%s') | Voz: %s", OC_URL, AGENT, VOICE)
    async with serve(handler, args.host, args.port, max_size=2**22):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Servidor detenido.")
