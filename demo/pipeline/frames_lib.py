"""Helpers over a recorded clip: timeline lookup, contact sheets, constant-rate encoding."""

import bisect
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FFMPEG = "C:/ffmpeg/bin/ffmpeg.exe"
HERE = Path(__file__).parent


class Clip:
    def __init__(self, name: str) -> None:
        self.name = name
        self.dir = HERE / "clips" / name
        meta = json.loads((self.dir / "frames.json").read_text())
        self.timestamps: list[float] = meta["timestamps"]
        self.marks: dict[str, float] = meta["marks"]
        self.t0 = self.timestamps[0]
        self.duration = self.timestamps[-1] - self.t0

    def mark(self, label: str) -> float:
        """Video time (seconds from the first frame) of a recorded mark."""
        return self.marks[label] - self.t0

    def index_at(self, t: float) -> int:
        i = bisect.bisect_right(self.timestamps, self.t0 + t) - 1
        return max(0, min(i, len(self.timestamps) - 1))

    def frame_path(self, t: float) -> Path:
        return self.dir / "frames" / f"{self.index_at(t):06d}.jpg"

    def contact_sheet(self, step: float = 1.0, cols: int = 8, thumb: int = 240, start: float = 0.0) -> Path:
        times = []
        t = start
        while t < self.duration:
            times.append(t)
            t += step
        rows = (len(times) + cols - 1) // cols
        th = int(thumb * 9 / 16)
        sheet = Image.new("RGB", (cols * thumb, rows * th), (10, 10, 14))
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 16)
        for n, t in enumerate(times):
            img = Image.open(self.frame_path(t)).convert("RGB").resize((thumb, th))
            x, y = (n % cols) * thumb, (n // cols) * th
            sheet.paste(img, (x, y))
            draw.rectangle([x, y, x + 62, y + 20], fill=(0, 0, 0))
            draw.text((x + 4, y + 2), f"{t:5.1f}s", fill=(255, 220, 80), font=font)
        out = self.dir / "contact.jpg"
        sheet.save(out, quality=85)
        return out

    def encode(self, segments: list[tuple[float, float, float]], out: Path, fps: int = 30) -> Path:
        """Encode (start, end, speed) ranges, in order, as one constant-rate video."""
        lines: list[str] = []
        step = 1 / fps
        for start, end, speed in segments:
            t = start
            while t < end - 1e-6:
                lines.append(f"file '{self.frame_path(t).as_posix()}'\nduration {step:.6f}")
                t += step * speed
        lines.append(lines[-1].split("\n")[0])  # concat demuxer needs the last file repeated
        listing = out.with_suffix(".txt")
        listing.write_text("\n".join(lines))
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-vf", f"fps={fps},scale=in_range=pc:out_range=tv:out_color_matrix=bt709:flags=bicubic,format=yuv420p",
             "-c:v", "libx264", "-preset", "medium", "-crf", "17",
             "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", str(out)],
            check=True,
        )
        return out
