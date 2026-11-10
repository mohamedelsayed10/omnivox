"""Synthesize an original ambient/electronic backing track with NumPy: python make_music.py <seconds>"""

import sys
import wave
from pathlib import Path

import numpy as np

SR = 48_000
TOTAL = float(sys.argv[1]) if len(sys.argv) > 1 else 92.0
BPM = 100
BEAT = 60 / BPM
BAR = 4 * BEAT
N = int(TOTAL * SR)
rng = np.random.default_rng(7)

# A minor loop: Am - F - C - G, two bars each. (root, [triad frequencies])
CHORDS = [
    (110.00, [220.00, 261.63, 329.63]),
    (87.31, [174.61, 220.00, 261.63]),
    (130.81, [261.63, 329.63, 392.00]),
    (98.00, [196.00, 246.94, 293.66]),
]


def chord_at(t: float) -> int:
    return int(t // (2 * BAR)) % 4


def ramp(t: np.ndarray, start: float, end: float) -> np.ndarray:
    """0 before start, rising to 1 at end, 1 after."""
    return np.clip((t - start) / max(end - start, 1e-6), 0, 1)


def place(buf: np.ndarray, sound: np.ndarray, at: float, pan: float = 0.0, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= buf.shape[1]:
        return
    j = min(i + len(sound), buf.shape[1])
    seg = sound[: j - i] * gain
    buf[0, i:j] += seg * (1 - max(pan, 0))
    buf[1, i:j] += seg * (1 + min(pan, 0))


def tone(freq: float, dur: float, harmonics: list[float], attack: float, release: float, decay: float = 0.0) -> np.ndarray:
    t = np.arange(int(dur * SR)) / SR
    wave_ = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harmonics))
    env = np.minimum(1, t / max(attack, 1e-4)) * np.minimum(1, (dur - t) / max(release, 1e-4))
    if decay:
        env *= np.exp(-t / decay)
    return wave_ * env


pad = np.zeros((2, N))
arp = np.zeros((2, N))
bass = np.zeros((2, N))
drums = np.zeros((2, N))

# Pad: one slow chord per two bars, slightly detuned left/right for width.
t = 0.0
while t < TOTAL:
    root, notes = CHORDS[chord_at(t)]
    dur = 2 * BAR + 1.6
    for f in notes + [notes[0] / 2]:
        place(pad, tone(f * 0.997, dur, [1, 0.35, 0.18, 0.08], 1.3, 1.8), t, pan=-0.45, gain=0.11)
        place(pad, tone(f * 1.003, dur, [1, 0.35, 0.18, 0.08], 1.3, 1.8), t, pan=0.45, gain=0.11)
    t += 2 * BAR

# Arpeggio: eighth-note plucks through the chord, alternating sides.
step = BEAT / 2
pattern = [0, 1, 2, 3, 2, 1, 2, 1]
k = 0
t = 0.0
while t < TOTAL - 0.5:
    root, notes = CHORDS[chord_at(t)]
    tones = notes + [notes[0] * 2]
    f = tones[pattern[k % len(pattern)]] * 2
    place(arp, tone(f, 0.9, [1, 0.5, 0.25, 0.12], 0.004, 0.2, decay=0.28), t, pan=-0.5 if k % 2 else 0.5, gain=0.13)
    k += 1
    t += step

# Bass: a long root note each bar with a soft pulse on the "and" of beat two.
t = 0.0
while t < TOTAL - 0.5:
    root, _ = CHORDS[chord_at(t)]
    place(bass, tone(root, BAR * 0.95, [1, 0.25], 0.02, 0.25), t, gain=0.30)
    place(bass, tone(root, BEAT * 0.9, [1, 0.2], 0.01, 0.2, decay=0.4), t + 1.5 * BEAT, gain=0.18)
    t += BAR


def kick() -> np.ndarray:
    tt = np.arange(int(0.34 * SR)) / SR
    freq = 48 + 90 * np.exp(-tt * 28)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    return np.sin(phase) * np.exp(-tt * 11)


def hat() -> np.ndarray:
    tt = np.arange(int(0.05 * SR)) / SR
    noise = rng.standard_normal(len(tt))
    noise = np.diff(noise, prepend=0)  # crude high-pass
    return noise * np.exp(-tt * 90)


def clap() -> np.ndarray:
    tt = np.arange(int(0.22 * SR)) / SR
    noise = rng.standard_normal(len(tt))
    noise = noise - np.convolve(noise, np.ones(8) / 8, mode="same")  # band emphasis
    return noise * np.exp(-tt * 24)


KICK, HAT, CLAP = kick(), hat(), clap()
t = 0.0
bar_index = 0
while t < TOTAL - BAR:
    for beat in range(4):
        at = t + beat * BEAT
        if beat in (0, 2):
            place(drums, KICK, at, gain=0.55)
        if beat in (1, 3):
            place(drums, CLAP, at, gain=0.20)
        place(drums, HAT, at + BEAT / 2, pan=0.2, gain=0.10)
        if bar_index % 4 == 3 and beat == 3:  # little fill
            place(drums, HAT, at + BEAT * 0.25, gain=0.10)
            place(drums, HAT, at + BEAT * 0.75, gain=0.12)
    t += BAR
    bar_index += 1

# Arrangement: layers fade in and out over time.
tt = np.arange(N) / SR
arp *= (ramp(tt, 3.5, 9.0) * 0.8 + 0.2 * ramp(tt, 9.0, 16.0))[None, :]
bass *= (ramp(tt, 8.0, 12.0) * (1 - ramp(tt, TOTAL - 9, TOTAL - 5)))[None, :]
drums *= (ramp(tt, 12.0, 16.0) * (1 - ramp(tt, TOTAL - 14, TOTAL - 10)))[None, :]


def echo(x: np.ndarray, delay: float, feedback: float, wet: float) -> np.ndarray:
    d = int(delay * SR)
    out = x.copy()
    for ch in (0, 1):  # ping-pong: each channel echoes into the other
        src = x[1 - ch]
        buf = np.zeros(N)
        gain = wet
        for n in range(1, 6):
            shift = d * n
            if shift >= N:
                break
            buf[shift:] += src[: N - shift] * gain
            gain *= feedback
        out[ch] += buf
    return out


arp = echo(arp, BEAT * 0.75, 0.55, 0.45)

# Reverb: convolve with decaying stereo noise, mixed in on the pad and arp bus.
ir_len = int(2.2 * SR)
decay = np.exp(-np.arange(ir_len) / SR / 0.55)
ir = [rng.standard_normal(ir_len) * decay for _ in range(2)]
bus = pad + arp
size = 1 << (N + ir_len - 1).bit_length()
wet = np.stack([np.fft.irfft(np.fft.rfft(bus[c], size) * np.fft.rfft(ir[c], size), size)[:N] for c in (0, 1)])
wet *= 0.020

mix = pad * 0.9 + arp * 1.0 + wet + bass + drums
fade_in = np.minimum(1, tt / 1.5)
fade_out = np.minimum(1, (TOTAL - tt) / 3.5)
mix *= (fade_in * fade_out)[None, :]
mix *= 0.88 / np.max(np.abs(mix))

out = Path(__file__).parent / "assets" / "music.wav"
data = (np.clip(mix.T, -1, 1) * 32767).astype("<i2")
with wave.open(str(out), "wb") as f:
    f.setnchannels(2)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes(data.tobytes())
rms = 20 * np.log10(np.sqrt(np.mean(mix**2)))
print(f"music: {TOTAL:.1f}s, rms {rms:.1f} dBFS ->", out)
