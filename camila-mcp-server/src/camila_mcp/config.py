"""Módulo de configuración y resolución de variables de entorno para Camila MCP."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar .env si existe en la raíz del repositorio
repo_root = Path(__file__).resolve().parent.parent.parent
env_file = repo_root / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file)
else:
    load_dotenv()


def _get_env_smart(key: str, default: str = "") -> str:
    """Obtiene variable de entorno de os.environ y, si no existe en Windows, del Registro de Usuario."""
    val = os.environ.get(key, "").strip()
    if val:
        return val

    # Fallback inteligente en Windows para leer HKCU\Environment
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val, _ = winreg.QueryValueEx(k, key)
                return str(val).strip()
        except Exception:
            pass

    return default


class Settings:
    """Configuraciones centrales del servidor MCP."""

    COLAB_TTS_URL: str = _get_env_smart("COLAB_TTS_URL", "").rstrip("/")
    COLAB_API_TOKEN: str = _get_env_smart("COLAB_API_TOKEN", "camila-gpu-2026")
    COLAB_TIMEOUT_SECONDS: float = float(_get_env_smart("COLAB_TIMEOUT_SECONDS", "6.5"))
    FALLBACK_TTS_ENABLED: bool = _get_env_smart("FALLBACK_TTS_ENABLED", "true").lower() in ("true", "1", "yes")
    FALLBACK_VOICE: str = _get_env_smart("FALLBACK_VOICE", "es-CO-SalomeNeural")
    AUDIO_OUTPUT_DIR: Path = Path(_get_env_smart("AUDIO_OUTPUT_DIR", str(repo_root / "audio_output")))

    @property
    def colab_url(self) -> str:
        """Obtiene la URL viva de Colab desde colab_url.txt en caliente o del entorno."""
        candidates = [
            Path(r"E:\taxis\Taxi-Marketing-OS\_database\colab_url.txt"),
            repo_root.parent / "Taxi-Marketing-OS" / "_database" / "colab_url.txt",
            repo_root / "colab_url.txt",
        ]
        for c in candidates:
            if c.exists():
                try:
                    txt = c.read_text(encoding="utf-8").strip().rstrip("/")
                    if txt.startswith("http"):
                        return txt
                except Exception:
                    pass
        return self.COLAB_TTS_URL


settings = Settings()
settings.AUDIO_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
