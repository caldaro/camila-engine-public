# 🎭 Camila MCP Server (FastMCP)

Servidor de Protocolo de Contexto de Modelo (**Model Context Protocol — MCP**) para la integración de la voz emocional de **Camila**, control de inferencia en **Google Colab (GPU T4 / XTTS-v2)** y orquestación creativa para el **Taxi Marketing OS**.

Desarrollado en Python utilizando el framework **FastMCP**.

---

## 🚀 Características Principales

* **Framework FastMCP:** Implementación moderna, asíncrona y tipada según la especificación oficial MCP.
* **Enrutamiento Emocional Estricto (Actor de Doblaje Disciplinado):**
  * Mapeo duro hacia los cortes de referencia del archivo maestro de Camila:
    * `sereno` $\rightarrow$ `sereno.wav`
    * `alegre` $\rightarrow$ `alegre.wav`
    * `sarcastico` $\rightarrow$ `sarcastico.wav` (y `tierno` $\rightarrow$ `tierno.wav`)
  * **Fallback Automático:** Si se recibe un token no reconocido (ej. `[animo: pensativa]`), se redirige a `sereno` (`sereno.wav`) evitando cualquier interrupción.
* **Dicción Fonética de Marcas (Bilingüismo Natural):**
  * Pre-procesamiento de texto antes de enviar al TTS para pronunciación correcta en español:
    * **Loudoun Cabs** $\rightarrow$ `Laudun Cabs` (y **Loudoun** $\rightarrow$ `Laudun`)
    * **Fairfax** $\rightarrow$ `Férfax`
    * **Chantilly** $\rightarrow$ `Chantillí`
    * **BizWorx** $\rightarrow$ `Bisworks`
    * **Dulles** $\rightarrow$ `Dales` / **Sedan** $\rightarrow$ `Sedán`
  * Formateo de teléfonos para locución fluida: `571-233-8828` $\rightarrow$ `5 7 1, 2 3 3, 8 8 2 8`.
* **Herramientas Expuestas en MCP:**
  * `synthesize_emotional_audio`: Síntesis completa con dicción fonética, guardado opcional y selección de corte.
  * `preview_phonetic_text`: Previsualización en texto de los reemplazos fonéticos para auditoría.
  * `get_worker_status`: Diagnóstico en vivo de conectividad con Colab y fallback.
* **Alta Disponibilidad (Fail-Safe Automatic Fallback):** Si Colab no está activo o supera el timeout (6.5s), conmuta al motor local Edge-TTS (`es-CO-SalomeNeural`) con prosodia adaptativa.

---

## 📁 Estructura del Repositorio

```text
camila-mcp-server/
├── .env.example              # Plantilla de variables de entorno
├── .gitignore                # Reglas de exclusión para Git
├── README.md                 # Documentación técnica
├── pyproject.toml            # Definición del paquete y metadata
├── requirements.txt          # Dependencias de Python
├── audio_output/             # Directorio de salida para audios generados
├── src/
│   └── camila_mcp/
│       ├── __init__.py
│       ├── config.py         # Configuración y resolución de entorno
│       ├── phonetics.py      # Diccionario y reglas de dicción fonética de marcas
│       ├── colab_client.py   # Enrutamiento emocional duro y cliente HTTP Colab / Fallback
│       └── server.py         # Servidor FastMCP y definición de herramientas
└── tests/
    └── test_server.py        # Suite de pruebas unitarias y de integración
```

---

## 🛠️ Instalación Rápida

1. **Clonar o entrar al directorio:**
   ```bash
   cd E:\taxis\camila-mcp-server
   ```

2. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configurar el entorno:**
   Copia `.env.example` a `.env` y configura la URL de tu worker en Colab:
   ```bash
   cp .env.example .env
   ```

---

## ⚙️ Variables de Entorno

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :--- |
| `COLAB_TTS_URL` | URL pública de ngrok o Cloudflare hacia el worker Colab | `""` |
| `COLAB_API_TOKEN` | Token de seguridad Bearer para el endpoint en Colab | `camila-gpu-2026` |
| `COLAB_TIMEOUT_SECONDS` | Tiempo límite antes de saltar al fallback local | `6.5` |
| `FALLBACK_TTS_ENABLED` | Si se permite generar voz local cuando Colab esté apagado | `true` |
| `FALLBACK_VOICE` | Voz neuronal colombiana para fallback | `es-CO-SalomeNeural` |
| `AUDIO_OUTPUT_DIR` | Carpeta para guardar archivos generados | `./audio_output` |

*Nota: En entornos Windows, si una variable no se encuentra en `.env`, el servidor buscará automáticamente en el Registro de Usuario (`HKCU\Environment`).*

---

## 🔌 Configuración en Clientes MCP

### 1. Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "camila-voice": {
      "command": "python",
      "args": ["-m", "camila_mcp.server"],
      "cwd": "E:\\taxis\\camila-mcp-server",
      "env": {
        "COLAB_TTS_URL": "https://your-tunnel.trycloudflare.com",
        "COLAB_API_TOKEN": "camila-gpu-2026"
      }
    }
  }
}
```

### 2. OpenCode (`E:/taxis/.opencode/opencode.json`)
```json
{
  "mcp": {
    "camila-voice": {
      "type": "local",
      "enabled": true,
      "command": [
        "python",
        "E:/taxis/camila-mcp-server/src/camila_mcp/server.py"
      ],
      "environment": {
        "PYTHONPATH": "E:/taxis/camila-mcp-server/src"
      }
    }
  }
}
```

### 3. Telegram Bridge (`tools/telegram-camila-bridge.py`)
El puente de Telegram importa directamente `apply_phonetic_rules` de `camila_mcp.phonetics` en su pipeline `clean_text_for_speech`, garantizando dicción fonética de marcas y pausas de locución telefónicas en todas las notas de voz generadas.

---

## 🧪 Ejecutar Pruebas

Para validar el enrutamiento y la síntesis:
```bash
python tests/test_server.py
```

---

## 🤖 Herramientas Disponibles

### `synthesize_emotional_audio`
* **Parámetros:**
  * `text` (str, requerido): Texto a sintetizar.
  * `mood_token` (str, opcional): `sereno` (default), `alegre`, `sarcastico`, `tierno`.
  * `output_filename` (str, opcional): Nombre del archivo donde guardar el audio.
* **Retorna:**
  * `status`: `"success"` o `"error"`.
  * `audio_base64`: Contenido del audio codificado.
  * `source`: `"colab_xtts_v2"` o `"fallback_edge_tts"`.
  * `emotion_used`: Emoción canónica aplicada.

### `get_worker_status`
* Consulta la conectividad en vivo con el worker en Colab y los estados de fallback activos.
