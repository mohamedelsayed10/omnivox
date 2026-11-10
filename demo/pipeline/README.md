# Demo video pipeline

Builds two versions of the demo (1080p, about 85 s) from the **live** GUI: a scripted Edge browser drives the real app
(its microphone is a WAV file, so the "caller" speaks a recorded question), a DevTools screencast captures the frames,
and the agent's spoken audio is captured from the page. Nothing here is part of the app, and `make test` /
`make lint` ignore this folder.

| Version | Made by | What it is |
| --- | --- | --- |
| `../omnivox-demo.mp4` | `compose.py` | Plain cuts and fades, captions, a synthesized music track that ducks under speech |
| `../omnivox-demo-fx.mp4` | `fx_render.py`, then `compose_fx.py` | Same footage with visual effects and **no music**: the spoken audio plus synthesized sound effects and a very quiet ambient bed. The end cards show no model names |

The effects version adds smooth camera push-ins with a spotlight, glowing outline and label chip, an animated cursor
with click ripples, bloom and vignette, motion blur and a `2×` badge on sped-up spans, animated captions, RGB split on
section edges, and a different transition at each join.

Its sound (`sfx.py`, no samples or downloads, everything is synthesized with NumPy) is: a click on every cursor click,
a key tick for every character that appears in the chat and search boxes (found by scanning the recorded frames), a
chime when the upload is indexed, a whoosh for each transition, a swish and a pop for each camera push-in and label,
a short zip on the `2×` spans, a swell and shimmer on the title, and an air-like ambient bed. Effects and the bed drop
while someone is talking. The GUI header bar still shows the model names, because that is the real interface.

## Needs

- The whole stack running, as for a normal call: LiveKit, Qdrant, the API (`make run`), the voice worker
  (`make agent`), the GUI (`cd frontend && npm run dev`) and the model servers in `.env`.
- Microsoft Edge, and `ffmpeg` (the path is set in `frames_lib.py`, `FFMPEG`).
- A separate Python environment for the tooling (kept out of the project's `.venv`):

```bash
uv venv --python 3.13 demo/pipeline/.venv
uv pip install --python demo/pipeline/.venv/Scripts/python.exe playwright pillow numpy
```

## Run (from `demo/pipeline`, with that Python)

```bash
# 1. the "microphone": each recorded question padded with silence so the greeting finishes first
ffmpeg -y -i assets/q_en.wav -af "adelay=8200|8200,apad=pad_dur=14" -ar 48000 -ac 2 -c:a pcm_s16le assets/mic_en.wav
ffmpeg -y -i assets/q_ar.wav -af "adelay=8200|8200,apad=pad_dur=14" -ar 48000 -ac 2 -c:a pcm_s16le assets/mic_ar.wav

# 2. title, models and outro cards, plus the caption images
python build_cards.py
python record_cards.py

# 3. the GUI clips (the mic path must be absolute)
python record_voice.py voice_en "<absolute path>/assets/mic_en.wav" 33
python record_voice.py voice_ar "<absolute path>/assets/mic_ar.wav" 33
python record_chat.py
python record_knowledge.py      # uploads assets/omnivox-demo-notes.md; delete it afterwards in the Knowledge view

# 4a. version with music (seconds = total length printed by `python compose.py --plan`)
python make_music.py 85
python compose.py

# 4b. version with visual effects and no music (sections render in parallel, about 4 minutes)
python fx_render.py
python compose_fx.py
python fx_render.py --still voice_en 23.4 still.png   # one finished frame, to check a look quickly
```

## Where to change things

| To change | Edit |
| --- | --- |
| Which parts of each clip are kept, speed-ups, section order | `SECTIONS` in `compose.py` (times are seconds on the clip's own timeline; use a contact sheet from `frames_lib.Clip.contact_sheet()` to pick them) |
| Caption text and position | `CAPTIONS` in `compose.py` for timing, `CAPTIONS` in `build_cards.py` for text and position |
| Title, models and outro cards | the HTML strings in `build_cards.py` |
| Music (key, tempo, layers), music version only | `make_music.py` |
| Camera moves, spotlights, labels, cursor clicks, caption timing, effects version | `PLANS` in `fx_render.py` (times are seconds inside each finished section) |
| Transitions between sections, loudness target | `TRANSITIONS` and `TARGET_LUFS` in `compose_fx.py` |
| Which sound effects play and when, and how they sound | `build_events` and the synthesizers in `sfx.py` |
| How loud the effects and ambient bed are, and how much they duck under speech | `SFX_LEVEL`, `SFX_DUCK`, `AMBIENT_DUCK` in `compose_fx.py`; the bed level is in `sfx.ambient` |
| A version with speech only (no effects, no bed) | `python compose_fx.py --no-sfx` |
| Label chip texts and the `2×` badge | `LABELS` in `build_cards.py` |
| What is typed or asked in the chat and Knowledge clips | `record_chat.py`, `record_knowledge.py` |

The questions the caller speaks (`assets/q_en.wav`, `assets/q_ar.wav`) were synthesized with the project's own TTS
server. The knowledge-base questions assume the sample handbook (`handbook.md`: free trial, support hours, call
recordings, pricing) is already indexed.
