import os

# IPC
SOCKET_PATH = "/tmp/pi-assistant/orchestrator.sock"

# Audio capture
SAMPLE_RATE = 16000           # Hz — required by openWakeWord and Whisper
CHANNELS = 1
CHUNK_SIZE = 1280             # 80ms at 16kHz — openWakeWord frame size

# Recording
SILENCE_THRESHOLD_SEC = 1.5  # seconds of silence to end recording
MAX_RECORD_SEC = 30           # hard cap
VAD_AGGRESSIVENESS = 2        # webrtcvad 0–3

# Hot session
HOT_WINDOW_SEC = 30

# Model paths — override via environment variables
WAKE_MODEL_DIR = os.getenv(
    "WAKE_MODEL_DIR",
    os.path.expanduser("~/.local/share/pi-assistant/wake_word"),
)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")

PIPER_EN_MODEL = os.getenv(
    "PIPER_EN_MODEL",
    os.path.expanduser("~/.local/share/pi-assistant/tts/en_US-amy-medium.onnx"),
)
PIPER_RO_MODEL = os.getenv(
    "PIPER_RO_MODEL",
    os.path.expanduser("~/.local/share/pi-assistant/tts/ro_RO-mihai-medium.onnx"),
)

# TTS sample rate (piper output)
PIPER_SAMPLE_RATE = 22050

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")
