import logging

from faster_whisper import WhisperModel

from config import WHISPER_MODEL
from audio_utils import detect_language_heuristic

logger = logging.getLogger(__name__)

# Lazy singleton — loaded on first call to avoid memory spike at startup
_model: WhisperModel | None = None


def _load_model() -> WhisperModel:
    logger.info("Loading Whisper model '%s' (int8)...", WHISPER_MODEL)
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    logger.info("Whisper model loaded")
    return model


def transcribe(wav_bytes: bytes) -> tuple[str, str]:
    """
    Transcribe WAV bytes. Returns (text, language_code).
    Language is an ISO 639-1 code ('en', 'ro', etc.).
    Model is lazy-loaded on first call.
    """
    global _model
    if _model is None:
        _model = _load_model()

    import io
    segments, info = _model.transcribe(io.BytesIO(wav_bytes), beam_size=5)

    text = " ".join(seg.text.strip() for seg in segments).strip()
    detected_lang = info.language if info.language else detect_language_heuristic(text)

    # Normalise to 'en' or 'ro'; fall back to 'en' for other languages
    if detected_lang not in ("en", "ro"):
        logger.debug("Whisper detected language '%s', falling back to heuristic", detected_lang)
        detected_lang = detect_language_heuristic(text)

    logger.info("Transcribed (lang=%s): %s", detected_lang, text[:80])
    return text, detected_lang
