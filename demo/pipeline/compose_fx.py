"""Join the effect-rendered sections with varied transitions and speech-only audio (no music).

    python compose_fx.py            # needs build/fx_<section>.mp4 from fx_render.py
    python compose_fx.py --plan
"""

import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

import compose
from compose import SECTIONS, SR
from frames_lib import FFMPEG
from fx_render import section_info

HERE = Path(__file__).parent
BUILD = HERE / "build"
OUT = HERE.parent / "omnivox-demo-fx.mp4" if HERE.name == "pipeline" else HERE / "omnivox-demo-fx.mp4"
XFADE = 0.6
# One transition per join: title>en, en>ar, ar>chat, chat>knowledge, knowledge>models, models>outro
TRANSITIONS = ["circleopen", "smoothleft", "slideleft", "slideup", "fadewhite", "radial"]
TARGET_LUFS = -16.0


def timeline() -> tuple[dict[str, float], dict[str, float], float]:
    starts: dict[str, float] = {}
    durs: dict[str, float] = {}
    cursor = 0.0
    for sid, _clip, _segments in SECTIONS:
        starts[sid] = cursor
        durs[sid] = section_info(sid)[2]
        cursor += durs[sid] - XFADE
    return starts, durs, cursor + XFADE


def write_wav(path: Path, mono: np.ndarray) -> None:
    stereo = np.repeat(mono[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(stereo, -1, 1) * 32767).astype("<i2").tobytes())


def integrated_lufs(path: Path) -> float:
    run = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    return float(re.findall(r"I:\s+(-?\d+\.\d+) LUFS", run.stderr)[-1])


def soft_limit(x: np.ndarray, knee: float = 0.70, ceiling: float = 0.83) -> np.ndarray:
    over = np.abs(x) > knee
    out = x.copy()
    out[over] = np.sign(x[over]) * (knee + (ceiling - knee) * np.tanh((np.abs(x[over]) - knee) / (ceiling - knee)))
    return out


def write_wav_stereo(path: Path, stereo: np.ndarray) -> None:
    with wave.open(str(path), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes((np.clip(stereo.T, -1, 1) * 32767).astype("<i2").tobytes())


SFX_LEVEL = 0.95  # sound effects, relative to their own full scale
SFX_DUCK = 0.55  # how far effects drop while someone is talking (0 = not at all)
AMBIENT_DUCK = 0.70


def build_audio(starts: dict[str, float], total: float, with_sfx: bool = True) -> Path:
    """Speech is the anchor (-16 LUFS). Sound effects and a very quiet ambient bed sit under it."""
    speech = compose.build_speech(starts, total)[: int(total * SR)]
    raw = BUILD / "speech_raw.wav"
    write_wav(raw, speech)
    loud = integrated_lufs(raw)
    speech = speech * 10 ** ((TARGET_LUFS - loud) / 20)
    mix = np.stack([speech, speech])
    if with_sfx:
        import sfx

        events = sfx.build_events(starts)
        env = compose.duck_envelope(speech)
        effects = sfx.render(starts, total, events)[:, : len(speech)] * SFX_LEVEL * (1 - SFX_DUCK * env)
        bed = sfx.ambient(total)[:, : len(speech)] * (1 - AMBIENT_DUCK * env)
        mix = mix + effects + bed
        print(f"audio: {len(events)} sound effects, effects peak {np.abs(effects).max():.2f}")
    mix = np.stack([soft_limit(mix[0]), soft_limit(mix[1])])
    out = BUILD / "mix_fx.wav"
    write_wav_stereo(out, mix)
    print(f"audio: speech {loud:.1f} LUFS before gain; mix peak {np.abs(mix).max():.2f}, integrated {integrated_lufs(out):.1f} LUFS")
    return out


def final_encode(audio: Path, durs: dict[str, float], total: float) -> None:
    order = [s for s, _c, _g in SECTIONS]
    cmd = [FFMPEG, "-y", "-loglevel", "error"]
    for sid in order:
        cmd += ["-i", str(BUILD / f"fx_{sid}.mp4")]
    cmd += ["-i", str(audio)]
    parts, last, cumulative = [], "[0:v]", durs[order[0]]
    for k in range(1, len(order)):
        label = f"[x{k}]"
        parts.append(
            f"{last}[{k}:v]xfade=transition={TRANSITIONS[k - 1]}:duration={XFADE}:offset={cumulative - XFADE:.3f}{label}"
        )
        last = label
        cumulative += durs[order[k]] - XFADE
    parts.append(f"{last}fade=t=in:st=0:d=0.8,fade=t=out:st={total - 1.2:.2f}:d=1.2,format=yuv420p[vout]")
    parts.append(f"[{len(order)}:a]afade=t=out:st={total - 1.0:.2f}:d=1.0[aout]")
    cmd += [
        "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]", "-t", f"{total:.2f}", "-r", "30",
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
    audio = build_audio(starts, total, with_sfx="--no-sfx" not in sys.argv)
    final_encode(audio, durs, total)
    print("video:", OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
