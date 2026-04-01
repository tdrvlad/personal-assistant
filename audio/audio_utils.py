import io
import logging
import os
import subprocess
import wave

import numpy as np
import sounddevice as sd
import webrtcvad

from config import SOUNDS_DIR

logger = logging.getLogger(__name__)


def play_sound(filename: str) -> None:
    """Play a .wav file from the sounds/ directory. Non-blocking."""
    path = os.path.join(SOUNDS_DIR, filename)
    if not os.path.exists(path):
        logger.warning("Sound file not found: %s", path)
        return
    subprocess.Popen(
        ["aplay", path],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record_until_silence(
    vad: webrtcvad.Vad,
    sample_rate: int,
    silence_sec: float,
    max_sec: float,
    chunk_size: int,
) -> bytes:
    """
    Record from the default microphone until silence_sec of continuous silence
    or max_sec total duration. Returns raw 16-bit mono PCM bytes.
    """
    frames_per_chunk = chunk_size  # samples
    bytes_per_chunk = frames_per_chunk * 2  # 16-bit = 2 bytes per sample

    silence_chunks_needed = int(silence_sec * sample_rate / frames_per_chunk)
    max_chunks = int(max_sec * sample_rate / frames_per_chunk)

    recorded: list[bytes] = []
    silent_chunks = 0

    with sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=frames_per_chunk,
        dtype="int16",
        channels=1,
    ) as stream:
        for _ in range(max_chunks):
            chunk_bytes, _ = stream.read(frames_per_chunk)
            recorded.append(bytes(chunk_bytes))

            try:
                is_speech = vad.is_speech(bytes(chunk_bytes), sample_rate)
            except Exception:
                is_speech = True  # on error, assume speech to avoid cutting off

            if is_speech:
                silent_chunks = 0
            else:
                silent_chunks += 1
                if silent_chunks >= silence_chunks_needed:
                    logger.debug("Silence detected after %d chunks", len(recorded))
                    break

    return b"".join(recorded)


def pcm_to_wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM in a WAV container. Returns bytes."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def play_pcm(pcm_bytes: bytes, sample_rate: int) -> None:
    """Play raw 16-bit mono PCM through the default output device. Blocks."""
    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(audio, samplerate=sample_rate)
    sd.wait()


def detect_language_heuristic(text: str) -> str:
    """
    Heuristic fallback: check for Romanian diacritics or common RO words.
    Returns 'ro' or 'en'.
    """
    ro_markers = set("ăâîșțĂÂÎȘȚ")
    ro_words = {"și", "sau", "dar", "că", "să", "nu", "da", "cu", "de", "la", "în", "pe"}
    words = set(text.lower().split())
    if any(c in ro_markers for c in text):
        return "ro"
    if len(words & ro_words) >= 2:
        return "ro"
    return "en"
