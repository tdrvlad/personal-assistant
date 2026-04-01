"""
Generate placeholder audio cue .wav files using pure Python.
Run once: python generate_sounds.py
Replace with real chimes/sounds as desired.
"""
import math
import struct
import wave
import os

SAMPLE_RATE = 16000

def write_wav(filename: str, samples: list[float]):
    path = os.path.join(os.path.dirname(__file__), filename)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        for s in samples:
            wf.writeframes(struct.pack("<h", int(max(-32768, min(32767, s * 32767)))))
    print(f"Written: {path}")


def tone(freq: float, duration: float, volume: float = 0.5, fade_ms: int = 10) -> list[float]:
    n = int(SAMPLE_RATE * duration)
    fade_samples = int(SAMPLE_RATE * fade_ms / 1000)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        s = volume * math.sin(2 * math.pi * freq * t)
        # Fade in/out
        if i < fade_samples:
            s *= i / fade_samples
        elif i > n - fade_samples:
            s *= (n - i) / fade_samples
        samples.append(s)
    return samples


def silence(duration: float) -> list[float]:
    return [0.0] * int(SAMPLE_RATE * duration)


# wake.wav — rising two-tone chime
wake = tone(660, 0.12) + silence(0.04) + tone(880, 0.18)
write_wav("wake.wav", wake)

# click.wav — soft click (short mid tone)
click = tone(440, 0.06, volume=0.3)
write_wav("click.wav", click)

# cooldown.wav — falling tone
cooldown = tone(660, 0.12) + silence(0.04) + tone(440, 0.18)
write_wav("cooldown.wav", cooldown)

# error.wav — low buzz (two low pulses)
error = tone(180, 0.1, volume=0.4) + silence(0.05) + tone(180, 0.1, volume=0.4)
write_wav("error.wav", error)

print("Done. Replace these placeholders with real audio files as desired.")
