"""Servidor FastMCP de Camila — Herramientas para voz emocional, dicción fonética y control de Colab."""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from fastmcp import FastMCP
from camila_mcp.config import settings
from camila_mcp.colab_client import synthesize_audio, resolve_emotion_routing
from camila_mcp.phonetics import apply_phonetic_rules

import glob
import chromadb
from PIL import Image
from sentence_transformers import SentenceTransformer

# Configuración básica de logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("camila_mcp.server")

# Instancia central de FastMCP
mcp = FastMCP(
    name="Camila Voice & Marketing MCP",
    instructions="Servidor MCP para control de voz emocional, dicción fonética de marcas e inferencia en GPU Colab (XTTS-v2)"
)

# ==========================================
# LÓGICA DE VISION RAG (CLIP + ChromaDB)
# ==========================================
CHROMA_DB_DIR = r"E:\taxis\Taxi-Marketing-OS\_database\chroma_db"
ARTES_DIR = r"E:\taxis\2026\SALIDAS"

logger.info("Inicializando cliente ChromaDB...")
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_DIR)
collection = chroma_client.get_or_create_collection(name="flyers_history")

# LAZY LOADING: No cargamos el modelo pesado aquí para evitar timeout de OpenCode
clip_model = None

def get_clip_model():
    global clip_model
    if clip_model is None:
        logger.info("Cargando modelo CLIP (ViT-B-32) por primera vez...")
        clip_model = SentenceTransformer('clip-ViT-B-32')
    return clip_model

def init_vision_rag():
    """Lee la carpeta de artes y genera los embeddings iniciales si la DB está vacía."""
    if collection.count() == 0:
        logger.info("Base vectorial vacía. Indexando flyers existentes...")
        model = get_clip_model()
        image_paths = glob.glob(os.path.join(ARTES_DIR, "**", "*.jpg"), recursive=True) + \
                      glob.glob(os.path.join(ARTES_DIR, "**", "*.png"), recursive=True)
        
        for i, img_path in enumerate(image_paths):
            try:
                img = Image.open(img_path)
                embedding = model.encode(img).tolist()
                collection.add(
                    embeddings=[embedding],
                    ids=[f"flyer_id_{i}"],
                    metadatas=[{"path": img_path}]
                )
            except Exception as e:
                logger.error(f"Error al indexar {img_path}: {e}")
                
        logger.info(f"Vision RAG inicializado. Total de imágenes indexadas: {collection.count()}")

# Ejecutar inicialización persistente
init_vision_rag()

@mcp.tool()
def search_visual_history(query: str, n_results: int = 3) -> str:
    """Busca en el historial visual (Vision RAG) los flyers o artes que semánticamente coincidan con el query de texto."""
    try:
        model = get_clip_model()
        query_embedding = model.encode(query).tolist()
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        
        if not results['metadatas'] or not results['metadatas'][0]:
            return "No se encontraron artes coincidentes en el historial visual."
            
        response = "Resultados de la búsqueda visual en ChromaDB:\n"
        for metadata, distance in zip(results['metadatas'][0], results['distances'][0]):
            response += f"- Ruta: {metadata['path']} (Score/Distancia: {distance:.4f})\n"
            
        return response
    except Exception as e:
        return f"Error interno en búsqueda visual RAG: {str(e)}"


@mcp.tool()
async def synthesize_emotional_audio(
    text: str,
    mood_token: str = "sereno",
    output_filename: Optional[str] = None
) -> Dict[str, Any]:
    """Sintetiza audio con la voz y el perfil emocional exacto de Camila (español colombiano).
    
    Aplica pre-procesamiento fonético estricto para marcas en inglés (Loudoun Cabs -> Laudun Cabs,
    Fairfax -> Férfax, Chantilly -> Chantillí, BizWorx -> Bisworks) y enruta el token hacia los cortes
    de referencia en Colab (sereno.wav, alegre.wav, sarcastico.wav) con fallback a sereno si no es reconocido.

    Args:
        text: El texto que Camila debe pronunciar en audio (puede contener nombres de marcas o números).
        mood_token: Token de estado de ánimo que condiciona la expresividad acústica:
                    - 'sarcastico' : Mordaz, irónico, acento marcado y media sonrisa (sarcastico.wav).
                    - 'alegre'     : Enérgico, dinámico, brillante y motivador (alegre.wav).
                    - 'sereno'     : Calmo, profesional, centrado y seguro (sereno.wav).
                    - 'tierno'     : Suave, pausado, íntimo y cómplice (tierno.wav).
                    * Si se pasa un token no reconocido (ej. 'pensativa'), hace fallback automático a 'sereno'.
        output_filename: Nombre de archivo opcional para guardar el audio en disco (ej. 'anuncio_dmv.wav').
                         Si se especifica, se guardará dentro de audio_output/.

    Returns:
        Diccionario con estado, audio en base64, texto fonético procesado, emoción utilizada,
        archivo de conditioning asignado y ruta local si fue guardado.
    """
    logger.info(f"Petición de síntesis recibida: mood='{mood_token}', longitud original={len(text)} chars")
    
    # 1. Reglas de Marca: Pre-procesamiento de Dicción Fonética
    phonetic_text = apply_phonetic_rules(text)
    if phonetic_text != text:
        logger.info(f"Dicción fonética aplicada. Muestra: '{phonetic_text[:80]}...'")

    # 2. Resolución de ruta para guardado opcional
    save_path = None
    if output_filename:
        filename = output_filename.strip()
        if not (filename.endswith(".wav") or filename.endswith(".mp3")):
            filename += ".wav"
        save_path = settings.AUDIO_OUTPUT_DIR / filename

    # 3. Enrutamiento emocional y síntesis (Colab XTTS-v2 / Fallback Edge-TTS)
    result = await synthesize_audio(text=phonetic_text, mood_token=mood_token, save_path=save_path)
    result["original_text"] = text
    result["phonetic_text"] = phonetic_text
    
    return result


@mcp.tool()
def preview_phonetic_text(text: str) -> Dict[str, str]:
    """Previsualiza la transformación fonética de marcas sin generar audio (útil para auditoría de dicción).
    
    Aplica las reglas:
    - Loudoun Cabs -> Laudun Cabs
    - Fairfax -> Férfax
    - Chantilly -> Chantillí
    - BizWorx -> Bisworks
    - Dulles -> Dales / Sedan -> Sedán
    """
    processed = apply_phonetic_rules(text)
    return {
        "original": text,
        "phonetic_ready": processed
    }


@mcp.tool()
async def get_worker_status() -> Dict[str, Any]:
    """Consulta el estado de conectividad con el worker GPU en Google Colab y la configuración activa."""
    import httpx
    
    status_info = {
        "colab_configured": bool(settings.COLAB_TTS_URL),
        "colab_url": settings.COLAB_TTS_URL or "No configurada",
        "fallback_enabled": settings.FALLBACK_TTS_ENABLED,
        "fallback_voice": settings.FALLBACK_VOICE,
        "reference_audios": ["sereno.wav", "alegre.wav", "sarcastico.wav", "tierno.wav"],
        "phonetic_dictionary_active": True,
        "audio_output_dir": str(settings.AUDIO_OUTPUT_DIR.resolve()),
        "colab_online": False,
        "colab_details": None
    }
    
    if settings.COLAB_TTS_URL:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(
                    f"{settings.COLAB_TTS_URL}/health",
                    headers={"Authorization": f"Bearer {settings.COLAB_API_TOKEN}"}
                )
                if resp.status_code == 200:
                    status_info["colab_online"] = True
                    status_info["colab_details"] = resp.json()
        except Exception as exc:
            status_info["colab_error"] = str(exc)

    return status_info


@mcp.tool()
async def trigger_burst_job(script_content: str, language: str = "python", job_name: str = "burst_job") -> Dict[str, Any]:
    """Dispara un contenedor efímero en Freestyle.sh para ejecutar procesamiento pesado o scripts aislados en la nube.
    
    Uso: Cuando el sistema necesite ejecutar código complejo (procesamiento paralelo, FFmpeg, análisis 
    de datos masivos) que no deba bloquear el servidor local o requiera ráfagas de CPU. El contenedor
    se apaga automáticamente al terminar.
    
    Args:
        script_content: El código fuente a ejecutar en el contenedor efímero.
        language: Lenguaje del script ('python', 'node', 'bash').
        job_name: Nombre identificador para los logs.
        
    Returns:
        Diccionario con el resultado de la ejecución (stdout, stderr, exit_code).
    """
    logger.info(f"Disparando ráfaga en Freestyle.sh (Job: {job_name}, Lang: {language})")
    
    ext_map = {"python": ".py", "node": ".js", "bash": ".sh"}
    ext = ext_map.get(language.lower(), ".txt")
    
    import tempfile
    import asyncio
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False, encoding="utf-8") as temp_file:
        temp_file.write(script_content)
        temp_path = temp_file.name

    try:
        # Comando para enviar el payload al cluster de Freestyle.sh
        cmd = ["npx", "freestyle", "run", temp_path]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        return {
            "status": "success" if process.returncode == 0 else "error",
            "job_name": job_name,
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace").strip(),
            "stderr": stderr.decode("utf-8", errors="replace").strip(),
            "execution_engine": "freestyle.sh (ephemeral)"
        }
    except Exception as e:
        logger.error(f"Fallo al disparar contenedor efímero en Freestyle: {e}")
        return {
            "status": "error",
            "error_message": str(e),
            "execution_engine": "freestyle.sh (ephemeral)"
        }
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    """Punto de entrada para ejecutar el servidor MCP vía stdio."""
    logger.info("Iniciando Camila FastMCP Server...")
    mcp.run()


if __name__ == "__main__":
    main()
