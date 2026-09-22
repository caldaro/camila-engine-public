#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Módulo de Análisis Acústico y Speech Emotion Recognition (SER) para Camila.

Analiza el archivo de audio (.ogg, .wav, .mp3) recibido por Telegram,
extrayendo características prosódicas fundamentales (Pitch F0, variabilidad tonal,
energía RMS, velocidad de habla) para determinar el estado anímico y la cadencia
del usuario sin depender exclusivamente del texto de Whisper.
"""

import os
import subprocess
import tempfile
import numpy as np
import scipy.io.wavfile as wavfile


def _convert_to_wav(audio_path: str, target_sr: int = 16000) -> str:
    """Convierte cualquier formato de audio a un archivo WAV PCM 16kHz mono temporal."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-ar", str(target_sr), "-ac", "1",
        tmp.name
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return tmp.name


def _estimate_f0_autocorr(frame: np.ndarray, sr: int, fmin: float = 65.0, fmax: float = 400.0) -> float:
    """Estima la frecuencia fundamental (F0) en Hz usando autocorrelación normalizada."""
    if np.max(np.abs(frame)) < 1e-4:
        return 0.0

    min_lag = int(sr / fmax)
    max_lag = int(sr / fmin)

    # Autocorrelación via FFT
    n = len(frame)
    n_padded = 2 ** int(np.ceil(np.log2(2 * n - 1)))
    fx = np.fft.fft(frame, n_padded)
    rx = np.fft.ifft(fx * np.conj(fx)).real[:n]

    if rx[0] <= 0:
        return 0.0

    rx_norm = rx / rx[0]
    search_region = rx_norm[min_lag:max_lag]
    if len(search_region) == 0:
        return 0.0

    peak_idx = np.argmax(search_region) + min_lag
    peak_val = rx_norm[peak_idx]

    # Umbral de sonoridad armónica
    if peak_val > 0.35:
        return float(sr / peak_idx)
    return 0.0


def analyze_speech_emotion(audio_path: str, transcribed_text: str = "") -> dict:
    """Analiza prosodia acústica y estima la emoción / energía de la voz del usuario.

    Args:
        audio_path: Ruta al archivo de audio (.ogg, .wav, etc.).
        transcribed_text: Texto reconocido por Whisper (opcional, para calcular habla/segundo).

    Returns:
        Dict con métricas acústicas y resumen descriptivo para inyección de contexto.
    """
    if not os.path.exists(audio_path):
        return {
            "primary_emotion": "sereno",
            "confidence": 0.5,
            "prompt_context": "",
            "metrics": {}
        }

    wav_path = None
    try:
        wav_path = _convert_to_wav(audio_path, target_sr=16000)
        sr, raw_data = wavfile.read(wav_path)
        if raw_data.ndim > 1:
            raw_data = raw_data[:, 0]

        data = raw_data.astype(np.float32)
        if np.max(np.abs(data)) > 0:
            data = data / np.max(np.abs(data))  # Normalizar [-1.0, 1.0]

        total_duration = len(data) / sr
        if total_duration < 0.5:
            return {
                "primary_emotion": "sereno",
                "confidence": 0.5,
                "prompt_context": "[Contexto auditivo: Audio muy breve, tono neutro]",
                "metrics": {"duration": total_duration}
            }

        # Ventaneo de 40ms con salto de 20ms
        frame_size = int(sr * 0.040)
        hop_size = int(sr * 0.020)
        num_frames = (len(data) - frame_size) // hop_size

        f0_list = []
        energy_list = []

        for i in range(max(0, num_frames)):
            start = i * hop_size
            frame = data[start:start + frame_size]
            rms = np.sqrt(np.mean(frame ** 2))
            energy_list.append(rms)

            if rms > 0.03:  # Solo estimar F0 si hay suficiente energía acústica
                f0 = _estimate_f0_autocorr(frame, sr)
                if f0 > 0:
                    f0_list.append(f0)

        voiced_frames = len(f0_list)
        f0_mean = float(np.mean(f0_list)) if f0_list else 120.0
        f0_std = float(np.std(f0_list)) if len(f0_list) > 1 else 10.0
        f0_min = float(np.percentile(f0_list, 10)) if len(f0_list) > 4 else f0_mean
        f0_max = float(np.percentile(f0_list, 90)) if len(f0_list) > 4 else f0_mean
        f0_range = f0_max - f0_min

        rms_mean = float(np.mean(energy_list)) if energy_list else 0.05
        rms_std = float(np.std(energy_list)) if energy_list else 0.01

        # Velocidad de habla
        words_count = len(transcribed_text.strip().split()) if transcribed_text else 0
        speech_rate = (words_count / total_duration) if total_duration > 0 and words_count > 0 else 0.0

        # Lógica de Clasificación Heurística Prosódica
        # 1. Cansado / Desanimado / Voz baja:
        #    Poca energía, variabilidad tonal baja (pitch plano), habla lenta o tono descendente
        # 2. Alegre / Entusiasta:
        #    Tono medio-alto, alta variabilidad melódica (f0_std > 30), energía viva
        # 3. Cariñoso / Íntimo:
        #    Energía suave/moderada, tono cálido, pausas suaves
        # 4. Agitado / Apurado:
        #    Speech rate elevado (> 3.3 pal/s) con energía alta o tono acelerado
        # 5. Serio / Firme:
        #    Energía constante, f0 medio, baja dispersión

        emotion = "sereno"
        confidence = 0.70
        descriptor = "tono pausado y sereno"

        if speech_rate > 3.4 and rms_mean > 0.12:
            emotion = "apurado"
            confidence = 0.82
            descriptor = "tono agitado y con prisa (habla muy rápida)"
        elif rms_mean < 0.07 and f0_std < 18.0 and (speech_rate == 0 or speech_rate < 2.2):
            emotion = "cansado"
            confidence = 0.85
            descriptor = "tono de voz bajo, cansado o con poca energía"
        elif f0_std > 32.0 and rms_mean > 0.10:
            emotion = "alegre"
            confidence = 0.84
            descriptor = "tono alegre, despierto y con entonación expresiva"
        elif rms_mean < 0.09 and f0_mean < 140 and f0_std < 22.0:
            emotion = "intimo"
            confidence = 0.78
            descriptor = "tono suave, cercano y confidencial"
        elif f0_std < 16.0 and rms_mean >= 0.09:
            emotion = "serio"
            confidence = 0.76
            descriptor = "tono directo, sobrio y firme"
        else:
            emotion = "sereno"
            confidence = 0.70
            descriptor = "tono calmado y conversacional natural"

        prompt_context = f"[Contexto auditivo de la voz del usuario: {descriptor} (energía {rms_mean:.2f}, modulación {f0_std:.1f}Hz, velocidad {speech_rate:.1f} palabras/s)]"

        return {
            "primary_emotion": emotion,
            "confidence": confidence,
            "descriptor": descriptor,
            "prompt_context": prompt_context,
            "metrics": {
                "duration_seconds": round(total_duration, 2),
                "f0_mean_hz": round(f0_mean, 1),
                "f0_std_hz": round(f0_std, 1),
                "f0_range_hz": round(f0_range, 1),
                "rms_mean": round(rms_mean, 3),
                "speech_rate_wps": round(speech_rate, 2),
            }
        }

    except Exception as exc:
        return {
            "primary_emotion": "sereno",
            "confidence": 0.5,
            "prompt_context": "",
            "metrics": {"error": str(exc)}
        }
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
            except OSError:
                pass


if __name__ == "__main__":
    import sys
    test_file = sys.argv[1] if len(sys.argv) > 1 else r"E:\taxis\tools\colab\samples\toneca.wav"
    result = analyze_speech_emotion(test_file, "Papacito buenos días ya es hora de despertarse")
    print("=== RESULTADO SER ===")
    print(f"Emoción detectada: {result['primary_emotion']} (confianza: {result['confidence']*100:.0f}%)")
    print(f"Contexto: {result['prompt_context']}")
    print("Métricas:", result["metrics"])
