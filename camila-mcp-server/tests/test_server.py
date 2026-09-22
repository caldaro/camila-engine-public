"""Pruebas unitarias para Camila FastMCP Server (Enrutamiento Estricto + Dicción Fonética)."""

import asyncio
import os
import sys
from pathlib import Path

# Añadir src al PATH para ejecución directa de pruebas
src_dir = Path(__file__).resolve().parent.parent / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from camila_mcp.colab_client import resolve_emotion_routing, HARD_EMOTION_ROUTING
from camila_mcp.phonetics import apply_phonetic_rules
from camila_mcp.server import mcp, synthesize_emotional_audio, preview_phonetic_text, get_worker_status


def test_hard_emotion_routing():
    """Verifica el enrutamiento duro a los cortes de referencia y el fallback automático a sereno."""
    # 1. Enrutamiento directo a los 3 cortes base
    token, ref_file, _ = resolve_emotion_routing("sereno")
    assert token == "sereno" and ref_file == "sereno.wav"

    token, ref_file, _ = resolve_emotion_routing("alegre")
    assert token == "alegre" and ref_file == "alegre.wav"

    token, ref_file, _ = resolve_emotion_routing("sarcastico")
    assert token == "sarcastico" and ref_file == "sarcastico.wav"

    # 2. Aliases explícitos con tilde o género
    assert resolve_emotion_routing("sarcástico")[1] == "sarcastico.wav"
    assert resolve_emotion_routing("picara")[1] == "sarcastico.wav"
    assert resolve_emotion_routing("feliz")[1] == "alegre.wav"
    assert resolve_emotion_routing("[animo: alegre]")[1] == "alegre.wav"
    assert resolve_emotion_routing("tierno")[1] == "tierno.wav"

    # 3. Requisito crítico: Token no reconocido debe hacer fallback automático a sereno (sereno.wav)
    token_unk, ref_unk, _ = resolve_emotion_routing("pensativa")
    assert token_unk == "sereno" and ref_unk == "sereno.wav"

    token_unk2, ref_unk2, _ = resolve_emotion_routing("[animo: filosofica]")
    assert token_unk2 == "sereno" and ref_unk2 == "sereno.wav"

    print("[OK] test_hard_emotion_routing: PASO (Mapeo estricto + Fallback automático a sereno.wav)")


def test_phonetic_brand_rules():
    """Verifica las reglas de dicción fonética para marcas en inglés."""
    # Loudoun Cabs -> Laudun Cabs
    res = apply_phonetic_rules("Viaja seguro con Loudoun Cabs al mejor precio.")
    assert "Laudun Cabs" in res
    assert "Loudoun Cabs" not in res

    # Fairfax -> Férfax
    res_ff = apply_phonetic_rules("Servicio disponible en Fairfax y alrededores.")
    assert "Férfax" in res_ff
    assert "Fairfax" not in res_ff

    # Chantilly -> Chantillí
    res_ch = apply_phonetic_rules("Llegamos a Chantilly en menos de diez minutos.")
    assert "Chantillí" in res_ch
    assert "Chantilly" not in res_ch

    # BizWorx -> Bisworks
    res_bw = apply_phonetic_rules("Facturación corporativa integrada con BizWorx.")
    assert "Bisworks" in res_bw
    assert "BizWorx" not in res_bw

    # Combinado completo con teléfono
    res_full = apply_phonetic_rules(
        "[animo: alegre] Hola, soy Camila de Chantilly Taxi Sedan. Cubrimos Fairfax, Dulles y Loudoun Cabs. Llama al 571-233-8828."
    )
    assert "Chantillí" in res_full
    assert "Sedán" in res_full
    assert "Férfax" in res_full
    assert "Dales" in res_full
    assert "Laudun Cabs" in res_full
    assert "571, 233, 8828" in res_full
    assert "[animo: alegre]" not in res_full

    print("[OK] test_phonetic_brand_rules: PASO (Dicción bilingüe perfecta para marcas)")


async def test_synthesize_pipeline_with_phonetics():
    """Prueba la síntesis completa de audio verificando la integración fonética."""
    raw_input = "Hola, viaja con Fairfax Taxi Sedan y Loudoun Cabs hacia Chantilly."
    result = await synthesize_emotional_audio(
        text=raw_input,
        mood_token="pensativa",  # Token desconocido para disparar fallback a sereno
        output_filename="test_phonetic_pipeline.mp3"
    )

    assert result["status"] == "success"
    assert result["emotion_used"] == "sereno"
    assert result["conditioning_file"] == "sereno.wav"
    assert "Férfax" in result["phonetic_text"]
    assert "Laudun Cabs" in result["phonetic_text"]
    assert "Chantillí" in result["phonetic_text"]
    assert os.path.exists(result["saved_to"])

    print(f"[OK] test_synthesize_pipeline_with_phonetics: PASO (Ref: {result['conditioning_file']}, Guardado: {result['saved_to']})")


def test_preview_tool():
    """Verifica la herramienta de previsualización fonética."""
    preview = preview_phonetic_text("Cuentas corporativas en BizWorx con Fairfax Taxi.")
    assert "Bisworks" in preview["phonetic_ready"]
    assert "Férfax" in preview["phonetic_ready"]
    print("[OK] test_preview_tool: PASO")


if __name__ == "__main__":
    test_hard_emotion_routing()
    test_phonetic_brand_rules()
    test_preview_tool()
    asyncio.run(test_synthesize_pipeline_with_phonetics())
    print("\n>>> TODAS LAS PRUEBAS DE ENRUTAMIENTO Y DICCIÓN FONÉTICA PASARON CON ÉXITO <<<")
