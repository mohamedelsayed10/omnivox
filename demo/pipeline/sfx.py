"""Synthesized sound effects for the demo (no music, no voice): clicks, typing, whooshes, pops, chimes,
shimmer, and a very quiet ambient bed. Everything is generated with NumPy.

Event times come from the same plans as the visuals (fx_render.PLANS), and typing/toast timing is
detected from the recorded frames so each key tick lands on the character that appears.
"""

import numpy as np
from PIL import Image

from compose import SECTIONS
from frames_lib import Clip
from fx_render import PLANS, section_info

SR = 48_000
rng = np.random.default_rng(23)


def pan_gains(p):
    ang = (np.asarray(p) + 1) * np.pi / 4
    return np.cos(ang), np.sin(ang)


def stereo(mono: np.ndarray, pan: float = 0.0) -> np.ndarray:
    left, right = pan_gains(pan)
    return np.stack([mono * left, mono * right])


def svf_bp(x: np.ndarray, f0: float, f1: float, q: float, passes: int = 2) -> np.ndarray:
    """Band-pass whose centre frequency sweeps f0 -> f1. Two cascaded stages give steep skirts,
    so white noise does not leave a hissy top end."""
    for _ in range(passes):
        x = _svf_pass(x, f0, f1, q)
        x = x / (np.max(np.abs(x)) + 1e-12)
    return x


def _svf_pass(x: np.ndarray, f0: float, f1: float, q: float) -> np.ndarray:
    n = len(x)
    freq = np.clip(np.geomspace(max(f0, 40), max(f1, 40), n), 40, 4200)  # the filter is inaccurate higher up
    g = 2 * np.sin(np.pi * freq / SR)
    low = band = 0.0
    damp = 1.0 / q
    out = np.empty(n)
    for i in range(n):
        low += g[i] * band
        high = x[i] - low - damp * band
        band += g[i] * high
        out[i] = band
    return out


def norm(x: np.ndarray) -> np.ndarray:
    return x / (np.max(np.abs(x)) + 1e-12)


def whoosh(dur: float, f0: float, f1: float, pan0: float = 0.0, pan1: float = 0.0, q: float = 1.4, shape: float = 0.85) -> np.ndarray:
    n = int(dur * SR)
    sweep = svf_bp(rng.standard_normal(n), f0, f1, q)
    u = np.arange(n) / n
    mono = norm(sweep * np.sin(np.pi * u**shape) ** 2)
    left, right = pan_gains(np.linspace(pan0, pan1, n))
    return np.stack([mono * left, mono * right])


def click() -> np.ndarray:
    def tick(amp: float, f: float) -> np.ndarray:
        n = int(0.05 * SR)
        t = np.arange(n) / SR
        burst = svf_bp(rng.standard_normal(n), 2400, 2400, 1.6) * np.exp(-t / 0.003)
        return amp * (norm(burst) * 0.8 + np.sin(2 * np.pi * f * t) * np.exp(-t / 0.011) * 0.6)

    out = np.zeros(int(0.14 * SR))
    down, up = tick(1.0, 1900), tick(0.5, 1400)
    out[: len(down)] += down
    o = int(0.07 * SR)
    out[o : o + len(up)] += up
    return stereo(norm(out))


def key() -> np.ndarray:
    n = int(0.035 * SR)
    t = np.arange(n) / SR
    f = rng.uniform(1500, 3000)
    burst = norm(svf_bp(rng.standard_normal(n), f, f, 1.6)) * np.exp(-t / 0.0045)
    thock = np.sin(2 * np.pi * rng.uniform(150, 220) * t) * np.exp(-t / 0.009) * 0.5
    return stereo(norm(burst + thock) * rng.uniform(0.55, 1.0), rng.uniform(-0.2, 0.2))


def pop(f: float = 620) -> np.ndarray:
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    inst = f * (0.65 + 0.55 * (1 - np.exp(-t / 0.03)))
    sig = np.sin(2 * np.pi * np.cumsum(inst) / SR) * np.exp(-t / 0.05) * (1 - np.exp(-t / 0.002))
    return stereo(norm(sig))


def chime() -> np.ndarray:
    n = int(0.9 * SR)
    t = np.arange(n) / SR
    sig = np.zeros(n)
    for delay, freq, amp in ((0.0, 1318.5, 1.0), (0.13, 1760.0, 0.85)):
        d = int(delay * SR)
        tt = t[: n - d]
        note = np.sin(2 * np.pi * freq * tt) + 0.25 * np.sin(2 * np.pi * 2 * freq * tt)
        sig[d:] += amp * note * np.exp(-tt / 0.2) * (1 - np.exp(-tt / 0.003))
    return stereo(norm(sig))


def thump(dur: float = 0.6, f_hi: float = 85, f_lo: float = 48, tau: float = 0.17) -> np.ndarray:
    n = int(dur * SR)
    t = np.arange(n) / SR
    freq = f_lo + (f_hi - f_lo) * np.exp(-t / 0.08)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / tau) * (1 - np.exp(-t / 0.004))


def swell(dur: float = 1.2) -> np.ndarray:
    n = int(dur * SR)
    body = svf_bp(rng.standard_normal(n), 250, 2800, 1.1) * (np.arange(n) / n) ** 2.2
    mono = norm(body) * 0.8
    hit = thump(0.6)
    o = int(0.85 * dur * SR)
    out = np.zeros(max(n, o + len(hit)))
    out[:n] += mono
    out[o : o + len(hit)] += hit * 0.55
    return stereo(norm(out))


def riser(dur: float = 1.0) -> np.ndarray:
    n = int(dur * SR)
    body = svf_bp(rng.standard_normal(n), 300, 4200, 1.0) * (np.arange(n) / n) ** 1.8
    tail = int(0.5 * SR)
    shimmer = svf_bp(rng.standard_normal(tail), 3600, 3600, 1.0) * np.exp(-np.arange(tail) / SR / 0.14)
    out = np.zeros(n + tail)
    out[:n] += norm(body) * 0.8
    out[n:] += norm(shimmer) * 0.35
    hit = thump(0.6, 70, 45, 0.2) * 0.4
    start = n - int(0.02 * SR)
    end = min(start + len(hit), len(out))
    out[start:end] += hit[: end - start]
    return stereo(norm(out))


def shimmer(dur: float = 1.6) -> np.ndarray:
    n = int(dur * SR)
    u = np.arange(n) / n
    env = np.sin(np.pi * u) ** 2
    air = norm(svf_bp(rng.standard_normal(n), 3600, 3600, 1.0)) * env * 0.35
    out = np.stack([air, air * 0.9])
    for _ in range(16):
        t0 = rng.uniform(0, dur - 0.25)
        f = rng.uniform(3000, 6500)
        d = rng.uniform(0.08, 0.18)
        m = int(d * SR)
        t = np.arange(m) / SR
        ping = np.sin(2 * np.pi * f * t) * np.exp(-t / (d / 3)) * rng.uniform(0.15, 0.45) * env[int(t0 * SR)]
        i = int(t0 * SR)
        left, right = pan_gains(rng.uniform(-0.8, 0.8))
        out[0, i : i + m] += ping * left
        out[1, i : i + m] += ping * right
    return out / (np.max(np.abs(out)) + 1e-12)


def ambient(total: float) -> np.ndarray:
    """A very quiet bed of air: slowly breathing filtered noise, no pitch and no rhythm."""
    n = int(total * SR)
    f = np.fft.rfftfreq(n, 1 / SR)
    f[0] = 1
    t = np.arange(n) / SR
    out = np.zeros((2, n))
    for ch in range(2):
        spec = np.fft.rfft(rng.standard_normal(n))
        low = np.fft.irfft(spec / np.sqrt(f) / (1 + (f / 900) ** 2), n)
        air = np.fft.irfft(spec * ((f > 2500) & (f < 9000)) / np.sqrt(f), n)
        lfo1 = 0.65 + 0.35 * np.sin(2 * np.pi * 0.06 * t + rng.uniform(0, 6.28))
        lfo2 = 0.5 + 0.5 * np.sin(2 * np.pi * 0.11 * t + rng.uniform(0, 6.28))
        out[ch] = low / low.std() * 0.6 * lfo1 + air / air.std() * 0.22 * lfo2
    out *= 10 ** (-38 / 20) / np.sqrt(np.mean(out**2))
    fade = np.minimum(1, np.minimum(t / 1.5, (total - t) / 2.0))
    return out * fade


# ---------------------------------------------------------------- finding moments in the recordings
def _extent(path: str, box: tuple[int, int, int, int], thr: int) -> int:
    pix = np.asarray(Image.open(path).convert("L").crop(box), dtype=np.uint8)
    cols = np.where((pix > thr).any(axis=0))[0]
    return int(cols.max()) if len(cols) else -1


def typing_ticks(clip: str, box: tuple[int, int, int, int], span: tuple[float, float], thr: int = 175) -> list[float]:
    """Clip times at which the typed text grows by a character (rightmost bright pixel moves right)."""
    c = Clip(clip)
    times: list[float] = []
    last = -1
    t = span[0]
    while t < span[1]:
        x = _extent(str(c.frame_path(t)), box, thr)
        if x > last + 2 and last >= 0:
            times.append(round(t, 3))
        last = x if x >= 0 else -1
        t += 1 / 60
    return times


def toast_time(clip: str, box: tuple[int, int, int, int], start: float, end: float) -> float | None:
    c = Clip(clip)
    base = np.asarray(Image.open(c.frame_path(start)).convert("L").crop(box), dtype=np.float32)
    t = start
    while t < end:
        cur = np.asarray(Image.open(c.frame_path(t)).convert("L").crop(box), dtype=np.float32)
        if np.abs(cur - base).mean() > 2.5:
            return round(t, 3)
        t += 1 / 30
    return None


# ---------------------------------------------------------------- the event timeline
def clip_to_out(sid: str, clip_time: float) -> float | None:
    """Section-relative output time of a clip time, or None when that moment was cut."""
    _name, segments, _dur = section_info(sid)
    acc = 0.0
    for start, end, speed in segments:
        if start <= clip_time <= end:
            return acc + (clip_time - start) / speed
        acc += (end - start) / speed
    return None


def build_events(starts: dict[str, float]) -> list[tuple[float, str, float]]:
    """(global time, sound name, gain)."""
    ev: list[tuple[float, str, float]] = []
    order = [s for s, _c, _g in SECTIONS]

    ev += [(starts["title"] + 0.15, "swell", 0.55), (starts["title"] + 2.0, "shimmer", 0.42)]
    transitions = ["bloom", "whoosh_left_a", "whoosh_left_b", "whoosh_up", "riser", "whoosh_radial"]
    for k, name in enumerate(transitions, start=1):
        shift = {"riser": -0.75, "bloom": -0.2}.get(name, -0.12)
        ev.append((starts[order[k]] + shift, name, 0.75))

    for sid, plan in PLANS.items():
        for f in plan.focuses:
            ev.append((starts[sid] + f.t0 + 0.05, "swish_in", 0.42))
            if f.label:
                ev.append((starts[sid] + f.t0 + 0.5, "pop", 0.5))
            ev.append((starts[sid] + f.t2 + 0.1, "swish_out", 0.3))
        for c in plan.clicks:
            ev.append((starts[sid] + c.t, "click", 0.9))
        _clip, segments, _dur = section_info(sid)
        acc = 0.0
        for s, e, sp in segments:
            length = (e - s) / sp
            if sp > 1:
                ev += [(starts[sid] + acc, "zip_up", 0.45), (starts[sid] + acc + length - 0.1, "zip_down", 0.4)]
            acc += length

    # typing, matched to the characters that appear in the recordings
    for sid, clip, box, span in (
        ("chat", "chat", (130, 1012, 1330, 1048), (2.0, 15.4)),
        ("knowledge", "knowledge", (800, 138, 1215, 172), (2.2, 9.0)),
    ):
        thr = 175 if sid == "chat" else 150
        for t in typing_ticks(clip, box, span, thr):
            out = clip_to_out(sid, t)
            if out is not None:
                ev.append((starts[sid] + out, "key", 0.5))

    toast = toast_time("knowledge", (1700, 1035, 1915, 1078), 2.4, 6.5)
    if toast is not None and (out := clip_to_out("knowledge", toast)) is not None:
        ev.append((starts["knowledge"] + out, "chime", 0.5))
    ev.append((starts["knowledge"] + 10.2 + 0.04, "whoosh_switch", 0.4))

    for k, delay in enumerate((1.0, 1.7, 2.4, 3.1)):
        ev.append((starts["models"] + delay + 0.25, "pop_low", 0.5))
    ev += [(starts["outro"] + 0.6, "swish_in", 0.35), (starts["outro"] + 1.7, "shimmer", 0.35)]
    return sorted(ev)


def make(name: str) -> np.ndarray:
    return {
        "swell": swell,
        "shimmer": shimmer,
        "bloom": lambda: whoosh(1.0, 300, 5200, 0, 0, q=1.0),
        "whoosh_left_a": lambda: whoosh(0.9, 700, 2800, 0.8, -0.8),
        "whoosh_left_b": lambda: whoosh(0.8, 600, 3200, 0.8, -0.8),
        "whoosh_up": lambda: whoosh(0.8, 500, 3800, 0, 0, q=1.2),
        "riser": riser,
        "whoosh_radial": lambda: whoosh(0.9, 700, 3400, -0.7, 0.7, q=1.1),
        "whoosh_switch": lambda: whoosh(0.5, 1200, 5200, 0, 0, q=1.2),
        "swish_in": lambda: whoosh(0.7, 600, 2200, -0.3, 0.3),
        "swish_out": lambda: whoosh(0.55, 2200, 700, 0.3, -0.3),
        "zip_up": lambda: whoosh(0.22, 500, 4200),
        "zip_down": lambda: whoosh(0.22, 4200, 700),
        "pop": lambda: pop(620),
        "pop_low": lambda: pop(330),
        "click": click,
        "key": key,
        "chime": chime,
    }[name]()


def render(starts: dict[str, float], total: float, events: list[tuple[float, str, float]] | None = None) -> np.ndarray:
    """Stereo (2, n) track of every effect placed at its time."""
    n = int(total * SR)
    track = np.zeros((2, n))
    for time, name, gain in events or build_events(starts):
        snd = make(name) * gain
        i = int(time * SR)
        if i < 0:
            snd = snd[:, -i:]
            i = 0
        j = min(i + snd.shape[1], n)
        if j > i:
            track[:, i:j] += snd[:, : j - i]
    return track
