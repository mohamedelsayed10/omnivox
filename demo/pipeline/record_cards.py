"""Record the animated cards with the screencast recorder.

    python record_cards.py              # title, models and outro
    python record_cards.py models outro # only some of them
"""

import sys
from pathlib import Path

from record_lib import Recorder

HERE = Path(__file__).parent
DURATIONS = {"title": 5.6, "models": 8.2, "outro": 5.8}

for name in sys.argv[1:] or list(DURATIONS):
    out = HERE / "clips" / f"card_{name}"
    out.mkdir(parents=True, exist_ok=True)
    with Recorder(out) as rec:
        rec.page.goto((HERE / "cards" / f"{name}.html").as_uri())
        rec.page.wait_for_timeout(300)
        rec.start_capture()
        rec.wait(int(DURATIONS[name] * 1000))
