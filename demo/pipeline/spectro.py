"""Spectrogram helpers for checking synthesized audio by eye."""
import numpy as np
from PIL import Image, ImageDraw


def spectrogram(x: np.ndarray, sr: int, width: int, height: int, fmax: float = 10000, win: int = 1024, hop: int | None = None, floor_db: float = -80):
    n = len(x)
    hop = hop or max(1, (n - win) // width)
    frames = max(1, (n - win) // hop)
    w = np.hanning(win)
    cols = []
    for i in range(min(frames, width)):
        seg = x[i * hop : i * hop + win]
        if len(seg) < win:
            break
        cols.append(20 * np.log10(np.abs(np.fft.rfft(seg * w)) + 1e-9))
    mag = np.array(cols).T
    fr = np.fft.rfftfreq(win, 1 / sr)
    mag = mag[fr <= fmax][::-1]
    peak = mag.max()
    img = np.clip((mag - (peak + floor_db)) / -floor_db, 0, 1)
    # simple inferno-like colour ramp
    r = np.clip(img * 2.0, 0, 1); g = np.clip(img * 2.0 - 0.7, 0, 1); b = np.clip(0.4 + img * 1.2, 0, 1) * (img > 0.02) * np.clip(1.6 - img * 1.4, 0, 1)
    rgb = (np.stack([r, g, b], axis=-1) * 255).astype(np.uint8)
    return Image.fromarray(rgb).resize((width, height), Image.BILINEAR)
