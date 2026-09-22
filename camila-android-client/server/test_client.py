"""Cliente de prueba del servidor de voz de Camila.

Genera una frase con edge-tts, la envia como PCM 16 kHz al servidor WebSocket
y guarda la respuesta de audio en test_reply.wav.

Uso:
    python test_client.py --url ws://127.0.0.1:8000/ws --text "Camila, responde solo: hola"
"""

from __future__ import annotations

import argparse
import asyncio
import wave
from pathlib import Path

import edge_tts
import websockets

CHUNK_BYTES = 8192


async def synth_input_pcm(text: str) -> bytes:
    import shutil
    import subprocess
    import tempfile

    communicate = edge_tts.Communicate(text, "es-CO-SalomeNeural")
    mp3 = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3.extend(chunk["data"])

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg no disponible")

    with tempfile.TemporaryDirectory() as tmp:
        mp3_path = Path(tmp) / "input.mp3"
        wav_path = Path(tmp) / "input.wav"
        mp3_path.write_bytes(bytes(mp3))
        subprocess.run(
            [ffmpeg, "-y", "-i", str(mp3_path), "-f", "s16le", "-acodec", "pcm_s16le",
             "-ar", "16000", "-ac", "1", str(wav_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return wav_path.read_bytes()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--text", default="Camila, responde solo con la palabra hola.")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--delay", type=float, default=5.0)
    args = parser.parse_args()

    pcm = await synth_input_pcm(args.text)
    print(f"Audio de entrada: {len(pcm)} bytes ({len(pcm) / 32000:.1f}s)")

    received = bytearray()
    got_audio = False
    sent_all = False

    async with websockets.connect(args.url, max_size=2**22) as ws:
        async def sender():
            nonlocal sent_all
            await asyncio.sleep(args.delay)
            for i in range(0, len(pcm), CHUNK_BYTES):
                await ws.send(pcm[i:i + CHUNK_BYTES])
                await asyncio.sleep(0.256)
            sent_all = True
            await asyncio.sleep(1.2)

        async def receiver():
            nonlocal got_audio
            while True:
                message = await ws.recv()
                if isinstance(message, bytes):
                    received.extend(message)
                    got_audio = True
                else:
                    print("Servidor:", message)
                    if '"listening"' in message and got_audio and sent_all:
                        return

        try:
            await asyncio.wait_for(asyncio.gather(sender(), receiver()), timeout=args.timeout)
        except asyncio.TimeoutError:
            print("Timeout esperando respuesta completa.")
        except websockets.ConnectionClosed:
            print("Conexion cerrada por el servidor.")

    out = Path(__file__).with_name("test_reply.wav")
    if received:
        with wave.open(str(out), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(bytes(received))
        print(f"Respuesta de audio: {len(received)} bytes -> {out}")
    else:
        print("No se recibio audio de respuesta.")


if __name__ == "__main__":
    asyncio.run(main())
