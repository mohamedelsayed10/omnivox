"""Render every section with visual effects.

Per output frame: smooth camera push-ins, spotlight with glowing outline and label chip, animated
cursor with click ripples, bloom on bright areas (the orb), vignette, RGB split at the section
edges, animated captions and a fast-forward badge on sped-up spans.

    python fx_render.py                    # all sections, in parallel
    python fx_render.py voice_en chat      # some sections
    python fx_render.py --still voice_en 23.4 still.png   # one frame, for inspection
"""

import math
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from compose import SECTIONS
from frames_lib import FFMPEG, Clip

W, H, FPS = 1920, 1080, 30
HERE = Path(__file__).parent
CAPS = HERE / "captions"
BUILD = HERE / "build"
EDGE = 0.5  # seconds of RGB split at the start and end of a section


def smoother(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return x * x * x * (x * (x * 6 - 15) + 10)


def ease_out(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


@dataclass
class Focus:
    t0: float
    t1: float
    t2: float
    t3: float
    zoom: float
    cx: float
    cy: float
    rect: tuple[float, float, float, float] | None = None
    label: str | None = None
    side: str = "auto"  # where the label chip goes: auto (above, else below) or left
    dim: float = 0.42

    def weight(self, t: float) -> float:
        if t <= self.t0 or t >= self.t3:
            return 0.0
        return smoother((t - self.t0) / (self.t1 - self.t0)) * (1 - smoother((t - self.t2) / (self.t3 - self.t2)))


@dataclass
class Click:
    t: float
    x: float
    y: float
    sx: float
    sy: float
    travel: float = 0.6


@dataclass
class Plan:
    focuses: list[Focus] = field(default_factory=list)
    clicks: list[Click] = field(default_factory=list)
    caps: list[tuple[str, float, float]] = field(default_factory=list)
    card: bool = False


PLANS: dict[str, Plan] = {
    "title": Plan(card=True),
    "voice_en": Plan(
        focuses=[
            Focus(2.6, 3.4, 7.2, 8.2, 1.5, 781, 255),
            Focus(12.9, 13.7, 15.0, 15.7, 1.6, 1000, 780, (978, 748, 1430, 798), "lbl_transcript"),
            Focus(16.1, 16.9, 20.8, 21.6, 1.55, 780, 850, (133, 820, 778, 892), "lbl_reply"),
            Focus(22.5, 23.2, 25.3, 26.0, 2.0, 1690, 400, (1477, 378, 1893, 562), "lbl_latency", side="left"),
        ],
        clicks=[Click(0.38, 591, 533, 1040, 820, 0.38)],
        caps=[("cap_en1", 1.0, 4.6), ("cap_en2", 22.45, 3.4)],
    ),
    "voice_ar": Plan(
        focuses=[
            Focus(4.6, 5.4, 6.8, 7.4, 1.7, 1050, 775, (1125, 748, 1430, 798), "lbl_arabic"),
            Focus(7.6, 8.3, 10.2, 10.9, 1.9, 1700, 500, (1618, 466, 1890, 534), "lbl_tool_ar"),
            Focus(11.0, 11.7, 13.0, 13.6, 1.6, 700, 850, (133, 820, 778, 892), "lbl_ar_reply"),
        ],
        caps=[("cap_ar", 0.4, 4.2)],
    ),
    "chat": Plan(
        focuses=[
            Focus(4.6, 5.3, 7.4, 8.1, 1.8, 750, 260, (385, 198, 1115, 312), "lbl_docsearch"),
            Focus(12.7, 13.4, 15.0, 15.55, 1.8, 750, 445, (385, 400, 1105, 492), "lbl_web"),
        ],
        clicks=[Click(2.85, 1389, 1029, 900, 760, 0.55), Click(10.45, 1389, 1029, 900, 760, 0.55)],
        caps=[("cap_chat", 1.0, 5.2)],
    ),
    "knowledge": Plan(
        focuses=[
            Focus(1.0, 1.7, 3.6, 4.3, 1.7, 430, 470, (133, 384, 727, 458), "lbl_indexed"),
            Focus(7.2, 7.9, 9.6, 10.0, 1.6, 1100, 420, (775, 220, 1430, 548), "lbl_scores"),
        ],
        clicks=[
            Click(0.4, 429, 213, 1000, 520, 0.4),
            Click(6.5, 1375, 153, 1000, 420, 0.6),
            Click(10.2, 1886, 32, 1500, 300, 0.6),
        ],
        caps=[("cap_kb", 0.9, 4.2), ("cap_theme", 10.0, 2.3)],
    ),
    "models": Plan(card=True),
    "outro": Plan(card=True),
}


def section_info(sid: str) -> tuple[str, list[tuple[float, float, float]], float]:
    for name, clip, segments in SECTIONS:
        if name == sid:
            return clip, segments, sum((e - s) / sp for s, e, sp in segments)
    raise KeyError(sid)


# ---------------------------------------------------------------- sprites and overlays
_png_cache: dict[str, tuple[Image.Image, tuple[int, int]]] = {}


def png(name: str) -> tuple[Image.Image, tuple[int, int]]:
    """Cropped RGBA overlay and the (x, y) where the crop sits in the full frame."""
    if name not in _png_cache:
        full = Image.open(CAPS / f"{name}.png").convert("RGBA")
        box = full.getbbox() or (0, 0, 1, 1)
        _png_cache[name] = (full.crop(box), (box[0], box[1]))
    return _png_cache[name]


def blit(base: Image.Image, patch: Image.Image, x: int, y: int, alpha: float = 1.0) -> None:
    """Alpha-composite an RGBA patch onto an RGB image, clipped to the frame."""
    if alpha <= 0.004:
        return
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + patch.width, base.width), min(y + patch.height, base.height)
    if x1 <= x0 or y1 <= y0:
        return
    piece = patch.crop((x0 - x, y0 - y, x1 - x, y1 - y))
    mask = piece.getchannel("A")
    if alpha < 0.996:
        mask = mask.point(lambda v, k=alpha: int(v * k))
    base.paste(piece.convert("RGB"), (x0, y0), mask)


def make_cursor() -> tuple[Image.Image, tuple[float, float]]:
    s, pad, scale = 4, 8, 1.55
    pts = [(0, 0), (0, 17), (4.4, 13.2), (7.4, 20.6), (10.3, 19.4), (7.3, 12.2), (12.8, 12.2)]
    size = (int(18 * s) + 2 * pad * s, int(24 * s) + 2 * pad * s)
    poly = [(pad * s + x * s, pad * s + y * s) for x, y in pts]
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon([(x + 2 * s, y + 3 * s) for x, y in poly], fill=(0, 0, 0, 150))
    base = Image.alpha_composite(Image.new("RGBA", size, (0, 0, 0, 0)), shadow.filter(ImageFilter.GaussianBlur(2.6 * s)))
    draw = ImageDraw.Draw(base)
    draw.polygon(poly, fill=(255, 255, 255, 255))
    draw.line(poly + [poly[0]], fill=(18, 20, 38, 255), width=int(1.7 * s), joint="curve")
    final = base.resize((int(size[0] * scale / s), int(size[1] * scale / s)), Image.LANCZOS)
    return final, (pad * scale, pad * scale)


CURSOR, HOT = make_cursor()

_vig_cache: dict[float, np.ndarray] = {}


def vignette(strength: float) -> np.ndarray:
    key = round(strength, 2)
    if key not in _vig_cache:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        _vig_cache[key] = (1 - key * r**2.4)[..., None].astype(np.float32)
    return _vig_cache[key]


# ---------------------------------------------------------------- the per-frame pipeline
def camera(tau: float, dur: float, plan: Plan) -> tuple[float, float, float, Focus | None, float]:
    z = 1.0 + (0.05 if plan.card else 0.035) * tau / dur
    cx, cy = W / 2, H / 2
    best, best_w = None, 0.0
    for f in plan.focuses:
        w = f.weight(tau)
        if w > 0:
            z, cx, cy = z + (f.zoom - z) * w, cx + (f.cx - cx) * w, cy + (f.cy - cy) * w
            if w > best_w:
                best, best_w = f, w
    return z, cx, cy, best, best_w


def to_out(x: float, y: float, box: tuple[float, float, float], ) -> tuple[float, float]:
    x0, y0, z = box
    return (x - x0) * z, (y - y0) * z


def spotlight(arr: np.ndarray, rect: tuple[float, float, float, float], strength: float, radius: float) -> None:
    small = Image.new("L", (W // 4, H // 4), 0)
    ImageDraw.Draw(small).rounded_rectangle([v / 4 for v in rect], radius=radius / 4, fill=255)
    mask = np.asarray(small.filter(ImageFilter.GaussianBlur(3.5)).resize((W, H), Image.BILINEAR), dtype=np.float32) / 255
    arr *= (1 - strength * (1 - mask))[..., None]


def bloom(arr: np.ndarray, small_luma: np.ndarray) -> np.ndarray:
    if small_luma.mean() > 0.42:  # light theme: nothing to glow
        return arr
    gate = np.clip((small_luma - 0.60) / 0.40, 0, 1)
    if gate.max() < 0.05:
        return arr
    bright = (np.asarray(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).resize((384, 216), Image.BILINEAR), dtype=np.float32) * gate[..., None])
    glow = Image.fromarray(bright.astype(np.uint8)).filter(ImageFilter.GaussianBlur(7)).resize((W, H), Image.BICUBIC)
    glow_arr = np.asarray(glow, dtype=np.float32)
    return 255 - (255 - arr) * (255 - glow_arr * 0.62) / 255


def render_frame(img: Image.Image, tau: float, dur: float, plan: Plan, first: bool, last: bool, fast: bool) -> Image.Image:
    z, cx, cy, focus, w = camera(tau, dur, plan)
    bw, bh = W / z, H / z
    x0 = min(max(cx - bw / 2, 0), W - bw)
    y0 = min(max(cy - bh / 2, 0), H - bh)
    box = (x0, y0, z)
    frame = img.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + bw, y0 + bh)) if z > 1.0004 else img
    arr = np.asarray(frame, dtype=np.float32).copy()

    rect_out = None
    if focus is not None and focus.rect is not None and w > 0.02:
        a, b = to_out(focus.rect[0] - 8, focus.rect[1] - 8, box), to_out(focus.rect[2] + 8, focus.rect[3] + 8, box)
        rect_out = (a[0], a[1], b[0], b[1])
        spotlight(arr, rect_out, focus.dim * w, 16 * z)

    luma = np.asarray(frame.resize((384, 216), Image.BILINEAR), dtype=np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32) / 255
    arr = bloom(arr, luma)
    arr *= vignette(0.30 if luma.mean() < 0.42 else 0.09)

    dx = 0.0
    if not first:
        dx = max(dx, 7 * (1 - smoother(tau / EDGE)))
    if not last:
        dx = max(dx, 7 * smoother((tau - (dur - EDGE)) / EDGE))
    if dx > 0.4:
        shift = int(round(dx))
        arr[:, :, 0] = np.roll(arr[:, :, 0], shift, axis=1)
        arr[:, :, 2] = np.roll(arr[:, :, 2], -shift, axis=1)

    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # glowing outline and label chip around the focused area
    if rect_out is not None and focus is not None:
        pulse = 0.78 + 0.22 * math.sin(tau * 2 * math.pi * 1.3)
        m = 46
        px0, py0 = int(max(rect_out[0] - m, 0)), int(max(rect_out[1] - m, 0))
        px1, py1 = int(min(rect_out[2] + m, W)), int(min(rect_out[3] + m, H))
        if px1 > px0 and py1 > py0:
            patch = Image.new("RGBA", (px1 - px0, py1 - py0), (0, 0, 0, 0))
            local = [rect_out[0] - px0, rect_out[1] - py0, rect_out[2] - px0, rect_out[3] - py0]
            d = ImageDraw.Draw(patch)
            d.rounded_rectangle(local, radius=16 * z, outline=(139, 123, 255, 210), width=7)
            glow = patch.filter(ImageFilter.GaussianBlur(11))
            d.rounded_rectangle(local, radius=16 * z, outline=(205, 195, 255, 255), width=3)
            blit(out, glow, px0, py0, w * pulse)
            blit(out, patch, px0, py0, min(1.0, w * 1.4))
        if focus.label:
            lab, (lx, ly) = png(focus.label)
            pill_h = lab.height - 88
            lx0 = int(min(max(rect_out[0] - 44, 0), W - lab.width))
            above = rect_out[1] - 14 - pill_h
            if focus.side == "left":
                lx0 = int(max(rect_out[0] - lab.width + 30 - 12 * (1 - w), 0))
                ly0 = int(rect_out[1] - 44 + 6)
            elif above < 4:
                ly0 = int(rect_out[3] + 14 - 44 + 12 * (1 - w))
            else:
                ly0 = int(rect_out[1] - 14 - lab.height + 44 - 12 * (1 - w))
            blit(out, lab, lx0, ly0, min(1.0, w * 1.6))

    # cursor and click ripples
    for click in plan.clicks:
        start = click.t - click.travel
        if tau < start - 0.05 or tau > click.t + 0.9:
            continue
        u = (tau - start) / click.travel
        e = smoother(u)
        px, py = click.sx + (click.x - click.sx) * e, click.sy + (click.y - click.sy) * e
        dist = math.hypot(click.x - click.sx, click.y - click.sy)
        nx, ny = -(click.y - click.sy) / (dist + 1e-6), (click.x - click.sx) / (dist + 1e-6)
        bend = math.sin(math.pi * min(max(u, 0), 1)) * 0.07 * dist
        ox, oy = to_out(px + nx * bend, py + ny * bend, box)
        fade_in = min(1.0, (tau - (start - 0.05)) / 0.15)
        fade_out = 1.0 - smoother((tau - (click.t + 0.55)) / 0.3)
        press = 1 - 0.2 * math.exp(-(((tau - click.t) / 0.07) ** 2))
        tx, ty = to_out(click.x, click.y, box)
        for k in range(3):
            v = (tau - click.t - 0.10 * k) / 0.6
            if 0 <= v <= 1:
                r = (12 + 72 * ease_out(v)) * min(max(z, 1.0), 1.7)
                size = int(2 * r + 12)
                ring = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
                dd = ImageDraw.Draw(ring)
                a = int(255 * (1 - v) ** 1.3)
                dd.ellipse([size - r * 2, size - r * 2, size + r * 2, size + r * 2], outline=(150, 175, 255, a), width=8)
                dd.ellipse([size - r * 2, size - r * 2, size + r * 2, size + r * 2], fill=(139, 123, 255, int(a * 0.14)))
                ring = ring.resize((size, size), Image.LANCZOS)
                blit(out, ring, int(tx - size / 2), int(ty - size / 2), 0.9)
        spr = CURSOR if abs(press - 1) < 0.01 else CURSOR.resize(
            (max(1, int(CURSOR.width * press)), max(1, int(CURSOR.height * press))), Image.LANCZOS
        )
        blit(out, spr, int(ox - HOT[0] * press), int(oy - HOT[1] * press), max(0.0, min(fade_in, fade_out)))

    # animated captions
    for name, begin, length in plan.caps:
        t = tau - begin
        if -0.02 <= t <= length + 0.02:
            cap, (cx0, cy0) = png(name)
            fade_in = smoother(t / 0.45)
            fade_out = 1 - smoother((t - (length - 0.4)) / 0.4)
            rise = 30 * (1 - fade_in) + 10 * (1 - fade_out)
            blit(out, cap, cx0, int(cy0 + rise), min(fade_in, fade_out))

    if fast:
        badge, (bx, by) = png("badge_fast")
        blit(out, badge, 1255, 930, 0.95)
    return out


def source_at(tau: float, segments: list[tuple[float, float, float]]) -> tuple[float, float, bool]:
    acc = 0.0
    for i, (cs, ce, sp) in enumerate(segments):
        length = (ce - cs) / sp
        if tau < acc + length or i == len(segments) - 1:
            return min(cs + (tau - acc) * sp, ce), sp, sp > 1
        acc += length
    raise AssertionError


def frame_for(clip: Clip, tau: float, segments: list[tuple[float, float, float]]) -> tuple[Image.Image, bool]:
    t, speed, fast = source_at(tau, segments)
    img = Image.open(clip.frame_path(t)).convert("RGB")
    if speed > 1:  # motion blur on sped-up spans: blend with the frame half a step later
        other = Image.open(clip.frame_path(t + speed / FPS * 0.5)).convert("RGB")
        img = Image.blend(img, other, 0.5)
    return img, fast


def render_section(sid: str) -> str:
    clip_name, segments, dur = section_info(sid)
    clip, plan = Clip(clip_name), PLANS[sid]
    order = [s for s, _c, _g in SECTIONS]
    first, last = sid == order[0], sid == order[-1]
    BUILD.mkdir(exist_ok=True)
    out = BUILD / f"fx_{sid}.mp4"
    proc = subprocess.Popen(
        [FFMPEG, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-vf", "scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=bicubic,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-threads", "2",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", str(out)],
        stdin=subprocess.PIPE,
    )
    for n in range(round(dur * FPS)):
        tau = n / FPS
        img, fast = frame_for(clip, tau, segments)
        proc.stdin.write(render_frame(img, tau, dur, plan, first, last, fast).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {sid}")
    return f"{sid}: {round(dur * FPS)} frames -> {out.name}"


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "--still":
        sid, tau, dest = args[1], float(args[2]), args[3]
        clip_name, segments, dur = section_info(sid)
        order = [s for s, _c, _g in SECTIONS]
        img, fast = frame_for(Clip(clip_name), tau, segments)
        render_frame(img, tau, dur, PLANS[sid], sid == order[0], sid == order[-1], fast).save(dest)
        print("saved", dest)
        return
    wanted = args or [s for s, _c, _g in SECTIONS]
    with ProcessPoolExecutor(max_workers=min(len(wanted), 12)) as pool:
        for line in pool.map(render_section, wanted):
            print(line)


if __name__ == "__main__":
    main()
