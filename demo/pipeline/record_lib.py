"""Shared recording helpers: Edge with a fake microphone, DevTools screencast frames, audio capture.

Frames are JPEGs with epoch timestamps (frames.json). compose.py turns them into constant-rate video.
"""

import base64
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

W, H = 1920, 1080

CAPTURE_JS = """
(() => {
  const gum = navigator.mediaDevices && navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  if (gum) {
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await gum(constraints);
      if (constraints && constraints.audio && window.pyMic) window.pyMic(Date.now());
      return stream;
    };
  }
  const seen = new WeakSet();
  const start = (el) => {
    const stream = el.srcObject;
    if (!stream || seen.has(el) || !stream.getAudioTracks().length) return;
    seen.add(el);
    const rec = new MediaRecorder(new MediaStream(stream.getAudioTracks()), {mimeType: 'audio/webm;codecs=opus'});
    const t0 = Date.now();
    rec.ondataavailable = async (e) => {
      if (!e.data.size) return;
      const buf = new Uint8Array(await e.data.arrayBuffer());
      let bin = ''; for (const b of buf) bin += String.fromCharCode(b);
      window.pyChunk(btoa(bin), t0);
    };
    rec.start(500);
  };
  setInterval(() => document.querySelectorAll('audio').forEach(start), 200);
})();
"""


class Recorder:
    """One browser session: screencast frames, optional fake microphone, agent audio capture."""

    def __init__(self, out: Path, mic_wav: str | None = None, color_scheme: str = "dark") -> None:
        self.out = out
        self.frames_dir = out / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        for old in self.frames_dir.glob("*.jpg"):
            old.unlink()
        self.mic_wav = mic_wav
        self.color_scheme = color_scheme
        self.timestamps: list[float] = []
        self.marks: dict[str, float] = {}
        self.chunks: list[bytes] = []
        self.audio_t0: float | None = None
        self.errors: list[str] = []

    def __enter__(self) -> "Recorder":
        self._pw = sync_playwright().start()
        args = ["--autoplay-policy=no-user-gesture-required"]
        if self.mic_wav:
            args += [
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                f"--use-file-for-fake-audio-capture={self.mic_wav}%noloop",
            ]
        self.browser = self._pw.chromium.launch(channel="msedge", headless=True, args=args)
        self.context = self.browser.new_context(
            viewport={"width": W, "height": H},
            permissions=["microphone"],
            color_scheme=self.color_scheme,
        )
        self.context.expose_function("pyChunk", self._on_chunk)
        self.context.expose_function("pyMic", self._on_mic)
        self.context.add_init_script(CAPTURE_JS)
        self.page = self.context.new_page()
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.cdp = self.context.new_cdp_session(self.page)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        return self

    def _on_mic(self, epoch_ms: float) -> None:
        self.marks.setdefault("mic_start", epoch_ms / 1000)
        print("  mic stream opened")

    def _on_chunk(self, data: str, t0_ms: float) -> None:
        if self.audio_t0 is None:
            self.audio_t0 = t0_ms / 1000
        self.chunks.append(base64.b64decode(data))

    def _on_frame(self, params: dict) -> None:
        stamp = params["metadata"]["timestamp"]
        index = len(self.timestamps)
        (self.frames_dir / f"{index:06d}.jpg").write_bytes(base64.b64decode(params["data"]))
        self.timestamps.append(stamp)
        self.cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

    def start_capture(self) -> None:
        self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 92, "maxWidth": W, "maxHeight": H, "everyNthFrame": 1},
        )
        self.mark("capture start")

    def mark(self, label: str) -> float:
        now = time.time()
        self.marks[label] = now
        print(f"  {label}")
        return now

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)

    def shot(self, label: str) -> None:
        self.page.screenshot(path=str(self.out / f"{label}.png"))
        self.mark(f"screenshot {label}")

    def __exit__(self, *exc: object) -> None:
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        self.marks["audio_t0"] = self.audio_t0 or -1
        meta = {
            "timestamps": self.timestamps,
            "marks": self.marks,
            "errors": self.errors[:10],
            "agent_audio_bytes": sum(map(len, self.chunks)),
        }
        (self.out / "frames.json").write_text(json.dumps(meta))
        (self.out / "agent_audio.webm").write_bytes(b"".join(self.chunks))
        self.context.close()
        self.browser.close()
        self._pw.stop()
        span = (self.timestamps[-1] - self.timestamps[0]) if self.timestamps else 0
        print(f"frames: {len(self.timestamps)} over {span:.1f}s ({len(self.timestamps) / max(span, 1):.1f} fps)")
        print("agent audio bytes:", meta["agent_audio_bytes"], "| console errors:", self.errors[:3])
