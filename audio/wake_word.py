"""
Main audio pipeline for Pi Assistant.
Runs on the host (bare metal), not in Docker.

State machine:
  IDLE        - openWakeWord running, listening for trigger
  RECORDING   - capturing mic audio with VAD
  PROCESSING  - STT + HTTP POST to orchestrator in flight
  HOT_LISTEN  - no wake word needed, listening for follow-up
"""
import logging
import os
import sys
import time

import httpx
import numpy as np
import openwakeword
import sounddevice as sd
import webrtcvad

import stt
import tts
from audio_utils import (
    detect_language_heuristic,
    pcm_to_wav_bytes,
    play_sound,
    record_until_silence,
)
from config import (
    CHUNK_SIZE,
    HOT_WINDOW_SEC,
    MAX_RECORD_SEC,
    SAMPLE_RATE,
    SILENCE_THRESHOLD_SEC,
    SOCKET_PATH,
    VAD_AGGRESSIVENESS,
    WAKE_MODEL_DIR,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Detection threshold for openWakeWord
WAKE_THRESHOLD = float(os.getenv("WAKE_THRESHOLD", "0.5"))


class AudioPipeline:
    def __init__(self):
        self.state = "IDLE"  # IDLE | RECORDING | PROCESSING | HOT_LISTEN
        self.hot_until: float = 0.0

        logger.info("Loading openWakeWord model from %s", WAKE_MODEL_DIR)
        self.oww = openwakeword.Model(
            wakeword_models=[os.path.join(WAKE_MODEL_DIR, f) for f in os.listdir(WAKE_MODEL_DIR)
                             if f.endswith(".onnx")]
            if os.path.isdir(WAKE_MODEL_DIR)
            else [],
            inference_framework="onnx",
        )

        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        logger.info("Audio pipeline ready")

    def run(self):
        """Main loop. Runs forever."""
        logger.info("Starting audio loop (state=IDLE)")
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=CHUNK_SIZE,
            dtype="int16",
            channels=1,
        ) as mic_stream:
            while True:
                try:
                    self._tick(mic_stream)
                except KeyboardInterrupt:
                    logger.info("Shutting down")
                    sys.exit(0)
                except Exception as e:
                    logger.error("Unhandled error in main loop: %s", e, exc_info=True)
                    play_sound("error.wav")
                    time.sleep(1)

    def _tick(self, mic_stream):
        chunk_bytes, _ = mic_stream.read(CHUNK_SIZE)
        chunk_bytes = bytes(chunk_bytes)

        if self.state == "IDLE":
            self._check_wake_word(chunk_bytes)

        elif self.state == "HOT_LISTEN":
            self._check_hot_expiry()
            if self.state == "HOT_LISTEN":
                self._check_speech_in_hot(chunk_bytes)

    def _check_wake_word(self, chunk_bytes: bytes):
        audio = np.frombuffer(chunk_bytes, dtype=np.int16)
        scores = self.oww.predict(audio)

        # scores is a dict of {model_name: score}
        if scores and max(scores.values()) >= WAKE_THRESHOLD:
            logger.info("Wake word detected (score=%.2f)", max(scores.values()))
            self._handle_wake_detected()

    def _handle_wake_detected(self):
        play_sound("wake.wav")
        self.state = "RECORDING"
        wav_bytes = self._record_utterance()
        self.state = "PROCESSING"
        self._process_utterance(wav_bytes)

    def _check_speech_in_hot(self, chunk_bytes: bytes):
        """In HOT_LISTEN mode, detect any speech to start recording."""
        try:
            if self.vad.is_speech(chunk_bytes, SAMPLE_RATE):
                logger.info("Speech detected in hot session")
                self.state = "RECORDING"
                wav_bytes = self._record_utterance()
                self.state = "PROCESSING"
                self._process_utterance(wav_bytes)
        except Exception as e:
            logger.debug("VAD error: %s", e)

    def _record_utterance(self) -> bytes:
        logger.info("Recording...")
        pcm = record_until_silence(
            vad=self.vad,
            sample_rate=SAMPLE_RATE,
            silence_sec=SILENCE_THRESHOLD_SEC,
            max_sec=MAX_RECORD_SEC,
            chunk_size=CHUNK_SIZE,
        )
        play_sound("click.wav")
        return pcm_to_wav_bytes(pcm, SAMPLE_RATE)

    def _process_utterance(self, wav_bytes: bytes):
        # 1. Transcribe
        try:
            text, language = stt.transcribe(wav_bytes)
        except Exception as e:
            logger.error("STT failed: %s", e)
            play_sound("error.wav")
            self._return_to_idle_or_hot()
            return

        if not text.strip():
            logger.info("Empty transcription, ignoring")
            play_sound("error.wav")
            self._return_to_idle_or_hot()
            return

        # 2. Send to orchestrator
        try:
            response = self._post_to_orchestrator(text, language)
        except Exception as e:
            logger.error("Orchestrator call failed: %s", e)
            play_sound("error.wav")
            self.state = "IDLE"
            return

        # 3. Speak the response
        tts.synthesize_and_play(response["text_to_speak"], response["language"])

        # 4. Enter hot session or return to idle
        if response.get("hot_session"):
            duration = response.get("hot_duration_sec", HOT_WINDOW_SEC)
            self.hot_until = time.monotonic() + duration
            self.state = "HOT_LISTEN"
            logger.info("Entering hot session for %ds", duration)
        else:
            self.state = "IDLE"

    def _check_hot_expiry(self):
        if time.monotonic() >= self.hot_until:
            logger.info("Hot session expired")
            play_sound("cooldown.wav")
            self.state = "IDLE"

    def _return_to_idle_or_hot(self):
        """After an error, stay hot if we still are, else go idle."""
        if time.monotonic() < self.hot_until:
            self.state = "HOT_LISTEN"
        else:
            self.state = "IDLE"

    def _post_to_orchestrator(self, text: str, language: str) -> dict:
        transport = httpx.HTTPTransport(uds=SOCKET_PATH)
        with httpx.Client(transport=transport, timeout=60.0) as client:
            resp = client.post(
                "http://localhost/transcription",
                json={"text": text, "language": language},
            )
            resp.raise_for_status()
            return resp.json()


def main():
    pipeline = AudioPipeline()
    pipeline.run()


if __name__ == "__main__":
    main()
