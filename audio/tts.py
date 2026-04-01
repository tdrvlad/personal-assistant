import logging
import subprocess

from audio_utils import play_pcm
from config import PIPER_EN_MODEL, PIPER_RO_MODEL, PIPER_SAMPLE_RATE

logger = logging.getLogger(__name__)


def synthesize_and_play(text: str, language: str) -> None:
    """
    Synthesise text via piper and play through the speaker. Blocks until done.
    Selects EN or RO model based on language code.
    """
    model_path = _get_model_path(language)
    logger.info("TTS (lang=%s): %s", language, text[:80])
    try:
        pcm = _piper_synthesize(text, model_path)
        play_pcm(pcm, PIPER_SAMPLE_RATE)
    except Exception as e:
        logger.error("TTS failed: %s", e)


def _get_model_path(language: str) -> str:
    if language == "ro":
        return PIPER_RO_MODEL
    return PIPER_EN_MODEL


def _piper_synthesize(text: str, model_path: str) -> bytes:
    """
    Run piper via subprocess: echo text | piper --model <path> --output_raw
    Returns raw 16-bit PCM bytes at PIPER_SAMPLE_RATE.
    """
    result = subprocess.run(
        ["piper", "--model", model_path, "--output_raw"],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"piper exited {result.returncode}: {stderr}")
    return result.stdout
