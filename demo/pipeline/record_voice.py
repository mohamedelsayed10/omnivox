"""Record one scripted voice call: python record_voice.py <name> <mic_wav> <seconds>"""

import sys
import time
from pathlib import Path

from record_lib import Recorder

NAME, MIC, SECONDS = sys.argv[1], sys.argv[2], float(sys.argv[3])
OUT = Path(__file__).parent / "clips" / NAME
OUT.mkdir(parents=True, exist_ok=True)

with Recorder(OUT, mic_wav=MIC) as rec:
    page = rec.page
    page.goto("http://localhost:5173/#/voice")
    page.get_by_role("button", name="Start conversation").wait_for()
    rec.wait(1200)
    show = page.get_by_role("button", name="Show Inspector")
    if show.count():
        show.click()
    rec.wait(1200)
    rec.start_capture()
    rec.wait(2000)
    rec.shot("before_call")
    page.get_by_role("button", name="Start conversation").click()
    rec.mark("clicked start")
    start = time.time()
    shots = {6: "greeting", 15: "asking", 20: "thinking", 27: "answer"}
    taken: set[int] = set()
    latency_done = False
    while time.time() - start < SECONDS:
        elapsed = time.time() - start
        for at, label in shots.items():
            if elapsed >= at and at not in taken:
                taken.add(at)
                rec.shot(label)
        if elapsed >= 27 and not latency_done:
            latency_done = True
            page.get_by_role("tab", name="Latency").click()
            rec.mark("opened latency tab")
        rec.wait(200)
    rec.shot("end")
