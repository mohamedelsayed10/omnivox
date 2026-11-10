"""Assemble the demo video: sections -> crossfades, captions, speech + ducked music -> MP4.

    python compose.py            # build everything
    python compose.py --plan     # only print the timeline
"""

import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

from frames_lib import FFMPEG, Clip

HERE = Path(__file__).parent
BUILD = HERE / "build"
BUILD.mkdir(exist_ok=True)
SR = 48_000
FPS = 30
XFADE = 0.5
OUT = HERE.parent / "omnivox-demo.mp4"

# (id, clip, [(clip_start, clip_end, speed)])  all times in seconds on the clip's own timeline.
SECTIONS = [
    ("title", "card_title", [(0.0, 5.5, 1)]),
    ("voice_en", "voice_en", [(2.6, 10.9, 1), (11.0, 16.0, 1), (16.0, 20.3, 2), (20.3, 27.2, 1), (31.2, 35.2, 1)]),
    ("voice_ar", "voice_ar", [(11.0, 16.0, 1), (16.0, 20.3, 2), (20.3, 27.2, 1)]),
    ("chat", "chat", [(2.6, 10.8, 1), (13.0, 20.4, 1)]),
    ("knowledge", "knowledge", [(2.2, 14.8, 1)]),
    ("models", "card_models", [(0.0, 8.0, 1)]),
    ("outro", "card_outro", [(0.0, 5.7, 1)]),
]
# caption id -> (section id, offset inside the section, length)
CAPTIONS = [
    ("cap_en1", "voice_en", 1.0, 4.6),
    ("cap_en2", "voice_en", "end-3.9", 3.4),
    ("cap_ar", "voice_ar", 0.4, 4.2),
    ("cap_chat", "chat", 1.0, 5.2),
    ("cap_kb", "knowledge", 0.9, 4.2),
    ("cap_theme", "knowledge", "end-2.6", 2.3),
]


def section_duration(segments: list[tuple[float, float, float]]) -> float:
    return sum((end - start) / speed for start, end, speed in segments)


def timeline() -> tuple[dict[str, float], dict[str, float], float]:
    starts: dict[str, float] = {}
    durs: dict[str, float] = {}
    cursor = 0.0
    for sid, _clip, segments in SECTIONS:
        starts[sid] = cursor
        durs[sid] = section_duration(segments)
        cursor += durs[sid] - XFADE
    total = cursor + XFADE
    return starts, durs, total


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def fade_edges(x: np.ndarray, ms: float = 14) -> np.ndarray:
    n = min(int(SR * ms / 1000), len(x) // 2)
    if n:
        ramp = np.linspace(0, 1, n)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
    return x


def build_speech(starts: dict[str, float], total: float) -> np.ndarray:
    """Agent speech and the caller's question, cut and placed exactly like the video."""
    speech = np.zeros(int((total + 1) * SR))
    for sid, clip_name, segments in SECTIONS:
        if not clip_name.startswith("voice"):
            continue
        clip = Clip(clip_name)
        agent = decode(clip.dir / "agent_audio.webm")
        mic = decode(HERE / "assets" / ("mic_en.wav" if clip_name.endswith("en") else "mic_ar.wav"))
        sources = [
            (agent, clip.marks["audio_t0"] - clip.t0, 1.0),
            (mic, clip.marks["mic_start"] - clip.t0, 0.85),
        ]
        out_t = starts[sid]
        for start, end, speed in segments:
            length = (end - start) / speed
            if speed == 1:
                for samples, origin, gain in sources:
                    i0 = int(round((start - origin) * SR))
                    n = int(round((end - start) * SR))
                    piece = np.zeros(n)
                    lo, hi = max(i0, 0), min(i0 + n, len(samples))
                    if hi > lo:
                        piece[lo - i0 : hi - i0] = samples[lo:hi]
                    o = int(round(out_t * SR))
                    speech[o : o + n] += fade_edges(piece) * gain
            out_t += length
    return speech


def duck_envelope(speech: np.ndarray) -> np.ndarray:
    hop = int(0.02 * SR)
    frames = len(speech) // hop
    rms = np.sqrt(np.mean(speech[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    level = np.clip((20 * np.log10(rms) + 52) / 12, 0, 1)
    smooth = np.zeros(frames)
    attack, release = 1 - np.exp(-hop / SR / 0.10), 1 - np.exp(-hop / SR / 0.55)
    cur = 0.0
    for i, v in enumerate(level):
        cur += (attack if v > cur else release) * (v - cur)
        smooth[i] = cur
    return np.repeat(smooth, hop)[: len(speech)] if len(speech) % hop == 0 else np.concatenate(
        [np.repeat(smooth, hop), np.full(len(speech) - frames * hop, smooth[-1])]
    )


def build_audio(starts: dict[str, float], total: float) -> Path:
    speech = build_speech(starts, total)
    active = np.abs(speech) > 0.01
    rms = np.sqrt(np.mean(speech[active] ** 2)) if active.any() else 1.0
    speech *= 10 ** (-17 / 20) / rms  # speech about -17 dBFS RMS while talking
    peak = np.abs(speech).max()
    if peak > 0.85:
        speech *= 0.85 / peak

    with wave.open(str(HERE / "assets" / "music.wav")) as f:
        music = np.frombuffer(f.readframes(f.getnframes()), "<i2").reshape(-1, 2).astype(np.float64) / 32768
    n = len(speech)
    if len(music) < n:
        music = np.vstack([music, np.zeros((n - len(music), 2))])
    music = music[:n]

    env = duck_envelope(speech)
    gain = 0.72 * (1 - (1 - 0.30) * env)  # music about -3 dB alone, ducked to about -13 dB under speech
    mix = music * gain[:, None] + speech[:, None] * 0.95
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)  # soft limiter
    mix *= 0.74 / max(np.abs(mix).max(), 1e-9)  # leaves headroom: about -15.5 LUFS, true peak under -2 dB
    end = int((total) * SR)
    mix = mix[:end]
    out = BUILD / "mix.wav"
    with wave.open(str(out), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(mix, -1, 1) * 32767).astype("<i2").tobytes())
    print(f"audio: speech rms {20 * np.log10(rms):.1f} dBFS before gain, mix peak {np.abs(mix).max():.2f}")
    return out


def encode_sections() -> list[Path]:
    files = []
    for sid, clip_name, segments in SECTIONS:
        out = BUILD / f"sec_{sid}.mp4"
        Clip(clip_name).encode(segments, out, FPS)
        print(f"  section {sid}: {section_duration(segments):.2f}s -> {out.name}")
        files.append(out)
    return files


def final_encode(files: list[Path], audio: Path, starts: dict[str, float], durs: dict[str, float], total: float) -> None:
    cmd = [FFMPEG, "-y", "-loglevel", "error"]
    for f in files:
        cmd += ["-i", str(f)]
    caption_inputs = []
    for cid, sid, offset, length in CAPTIONS:
        begin = starts[sid] + (durs[sid] - float(offset.split("-")[1]) if isinstance(offset, str) else offset)
        caption_inputs.append((cid, begin, length))
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{length + 0.1:.2f}", "-i", str(HERE / "captions" / f"{cid}.png")]
    cmd += ["-i", str(audio)]
    audio_index = len(files) + len(caption_inputs)

    parts = []
    last = "[0:v]"
    cumulative = durs[SECTIONS[0][0]]
    for k in range(1, len(files)):
        offset = cumulative - XFADE
        label = f"[x{k}]"
        parts.append(f"{last}[{k}:v]xfade=transition=fade:duration={XFADE}:offset={offset:.3f}{label}")
        last = label
        cumulative += durs[SECTIONS[k][0]] - XFADE
    for n, (cid, begin, length) in enumerate(caption_inputs):
        idx = len(files) + n
        parts.append(
            f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.4:alpha=1,fade=t=out:st={length - 0.4:.2f}:d=0.4:alpha=1,"
            f"setpts=PTS+{begin:.3f}/TB[c{n}]"
        )
        parts.append(f"{last}[c{n}]overlay=0:0:enable='between(t,{begin:.3f},{begin + length:.3f})'[o{n}]")
        last = f"[o{n}]"
    parts.append(f"{last}fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.2:.2f}:d=1.2,format=yuv420p[vout]")
    parts.append(f"[{audio_index}:a]afade=t=out:st={total - 1.6:.2f}:d=1.6[aout]")
    cmd += [
        "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total:.2f}", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(OUT),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    starts, durs, total = timeline()
    print(f"total {total:.2f}s")
    for sid in starts:
        print(f"  {sid:10} start {starts[sid]:6.2f}  length {durs[sid]:6.2f}")
    if "--plan" in sys.argv:
        return
    files = encode_sections() if "--reuse" not in sys.argv else [BUILD / f"sec_{s}.mp4" for s, _, _ in SECTIONS]
    audio = build_audio(starts, total)
    final_encode(files, audio, starts, durs, total)
    print("video:", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
