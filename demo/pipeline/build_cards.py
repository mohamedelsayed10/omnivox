"""Generate the animated HTML cards (title, models, outro) and the transparent caption PNGs."""

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
CARDS = HERE / "cards"
CAPS = HERE / "captions"
CARDS.mkdir(exist_ok=True)
CAPS.mkdir(exist_ok=True)

# The GUI's self-hosted fonts, so the cards use the same typefaces (run `npm ci` in frontend/ first).
FONTS = (HERE.parents[1] / "frontend" / "node_modules" / "@fontsource-variable").as_uri()

BASE_CSS = """
@font-face{font-family:"Inter";src:url(%FONTS%/inter/files/inter-latin-wght-normal.woff2) format("woff2");font-weight:100 900}
@font-face{font-family:"JB";src:url(%FONTS%/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2) format("woff2");font-weight:100 800}
*{box-sizing:border-box}
html,body{margin:0;width:1920px;height:1080px;background:#07080d;overflow:hidden;font-family:Inter,sans-serif;color:#eef0ff}
body::before{content:"";position:absolute;inset:-20%;background:
 radial-gradient(40% 40% at 25% 30%, rgba(124,108,255,.30), transparent 70%),
 radial-gradient(35% 35% at 75% 25%, rgba(34,211,238,.20), transparent 70%),
 radial-gradient(40% 40% at 60% 80%, rgba(244,114,182,.16), transparent 70%);
 animation:drift 14s ease-in-out infinite alternate}
@keyframes drift{from{transform:translate(-3%,-2%) scale(1)}to{transform:translate(3%,2%) scale(1.08)}}
.stage{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center}
.up{opacity:0;transform:translateY(26px);animation:up .9s cubic-bezier(.2,.7,.2,1) forwards}
@keyframes up{to{opacity:1;transform:none}}
.grad{background:linear-gradient(135deg,#8b7bff 0%,#5b8cff 55%,#36d4ee 100%);-webkit-background-clip:text;background-clip:text;color:transparent}
.orb{position:relative;width:300px;height:300px;border-radius:50%;
 background:radial-gradient(circle at 35% 28%,#fff 0%,#c9d4ff 14%,#8b7bff 42%,#4a3fd0 72%,#1a1550 100%);
 box-shadow:0 0 120px 30px rgba(139,123,255,.45),0 0 240px 80px rgba(54,212,238,.18);
 animation:float 6s ease-in-out infinite,hue 8s linear infinite}
.orb.small{width:170px;height:170px;box-shadow:0 0 80px 18px rgba(139,123,255,.4),0 0 160px 50px rgba(54,212,238,.16)}
.ring{position:absolute;inset:0;border-radius:50%;border:2px solid rgba(139,123,255,.55);animation:ring 3.2s ease-out infinite}
.ring:nth-child(2){animation-delay:1.05s}.ring:nth-child(3){animation-delay:2.1s}
@keyframes ring{0%{transform:scale(1);opacity:.7}100%{transform:scale(2.7);opacity:0}}
@keyframes float{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-14px) scale(1.04)}}
@keyframes hue{0%{filter:hue-rotate(0)}50%{filter:hue-rotate(-70deg)}100%{filter:hue-rotate(0)}}
.chips{display:flex;gap:16px;justify-content:center}
.chip{font:600 24px JB,monospace;letter-spacing:.06em;color:#b9afff;border:1px solid rgba(185,175,255,.35);
 background:rgba(139,123,255,.10);padding:10px 22px;border-radius:999px}
.pt{position:absolute;bottom:-30px;border-radius:50%;background:radial-gradient(circle,#fff 0%,rgba(150,160,255,.55) 40%,rgba(139,123,255,0) 72%);
 opacity:0;animation:rise linear infinite}
@keyframes rise{0%{transform:translateY(0) scale(.6);opacity:0}15%{opacity:.85}100%{transform:translateY(-1180px) scale(1.25);opacity:0}}
.shine{opacity:0;transform:translateY(26px);
 background-image:linear-gradient(105deg,rgba(255,255,255,0) 40%,rgba(255,255,255,.95) 50%,rgba(255,255,255,0) 60%),linear-gradient(135deg,#8b7bff 0%,#5b8cff 55%,#36d4ee 100%);
 background-size:260% 100%,100% 100%;background-repeat:no-repeat;background-position:150% 0,0 0;
 -webkit-background-clip:text;background-clip:text;color:transparent;
 animation:up .9s cubic-bezier(.2,.7,.2,1) .8s forwards,sweep 1.5s ease-in-out 2.0s forwards}
.shine.o{animation:up .9s cubic-bezier(.2,.7,.2,1) .6s forwards,sweep 1.5s ease-in-out 1.7s forwards}
@keyframes sweep{to{background-position:-60% 0,0 0}}
""".replace("%FONTS%", FONTS)

PARTICLES_JS = """<script>
for (let i = 0; i < 70; i++) {
  const d = document.createElement('div'), s = 4 + Math.random() * 9, dur = 6 + Math.random() * 6;
  d.className = 'pt';
  d.style.cssText = `left:${Math.random() * 1920}px;width:${s}px;height:${s}px;animation-duration:${dur}s;animation-delay:${-Math.random() * dur}s`;
  document.body.appendChild(d);
}
</script>"""


def page(body: str, extra_css: str = "") -> str:
    return f"<!doctype html><meta charset='utf-8'><style>{BASE_CSS}{extra_css}</style>{body}{PARTICLES_JS}"


TITLE = page(
    """
<div class="stage">
  <div class="up" style="animation-delay:.1s"><div class="orb"><div class="ring"></div><div class="ring"></div><div class="ring"></div></div></div>
  <h1 class="shine" style="font-size:172px;font-weight:800;letter-spacing:-.035em;margin:70px 0 0;line-height:1">OmniVox</h1>
  <p class="up" style="animation-delay:1.4s;font-size:48px;font-weight:500;color:#b8bdd9;margin:22px 0 46px">Real-time voice agent</p>
  <div class="chips up" style="animation-delay:2s"><span class="chip">LiveKit</span><span class="chip">LangGraph</span><span class="chip">Qdrant</span><span class="chip">RAG + web search</span></div>
</div>"""
)

MODELS_CSS = """
.grid{display:grid;grid-template-columns:820px 820px;gap:32px;margin-top:64px}
.card{border-radius:30px;border:1px solid rgba(255,255,255,.13);background:rgba(255,255,255,.055);
 padding:38px 44px;text-align:left;box-shadow:0 30px 80px -30px rgba(0,0,0,.7),inset 0 1px 0 rgba(255,255,255,.08)}
.tag{display:inline-block;font:700 22px JB,monospace;letter-spacing:.14em;color:#36d4ee;border:1px solid rgba(54,212,238,.4);
 background:rgba(54,212,238,.08);padding:6px 16px;border-radius:999px}
.name{font-size:54px;font-weight:750;letter-spacing:-.02em;margin:22px 0 8px}
.desc{font-size:30px;color:#aab0cc;line-height:1.35}
.card.up{animation-name:pop;animation-duration:1s;animation-timing-function:cubic-bezier(.2,.8,.2,1)}
@keyframes pop{0%{opacity:0;transform:translateY(34px) scale(.93)}60%{opacity:1;transform:translateY(-6px) scale(1.012)}100%{opacity:1;transform:none}}
"""

MODELS = page(
    """
<div class="stage">
  <h2 class="up" style="animation-delay:.1s;font-size:88px;font-weight:800;letter-spacing:-.03em;margin:0">Runs on <span class="grad">your own models</span></h2>
  <p class="up" style="animation-delay:.5s;font-size:34px;color:#b8bdd9;margin:20px 0 0">Four OpenAI-compatible servers on the local network</p>
  <div class="grid">
    <div class="card up" style="animation-delay:1.0s"><span class="tag">LLM</span><div class="name">Language model</div><div class="desc">Tool calling, with thinking switched off for fast replies</div></div>
    <div class="card up" style="animation-delay:1.7s"><span class="tag">SPEECH TO TEXT</span><div class="name">Speech recognition</div><div class="desc">English and Arabic, language detected automatically</div></div>
    <div class="card up" style="animation-delay:2.4s"><span class="tag">TEXT TO SPEECH</span><div class="name">Voice synthesis</div><div class="desc">Streams audio, first sound in about 0.45 seconds</div></div>
    <div class="card up" style="animation-delay:3.1s"><span class="tag">EMBEDDINGS</span><div class="name">Document search</div><div class="desc">Finds the right passage in your documents</div></div>
  </div>
</div>""",
    MODELS_CSS,
)

OUTRO = page(
    """
<div class="stage">
  <div class="up" style="animation-delay:.1s"><div class="orb small"><div class="ring"></div><div class="ring"></div></div></div>
  <h1 class="shine o" style="font-size:132px;font-weight:800;letter-spacing:-.03em;margin:56px 0 0;line-height:1">OmniVox</h1>
  <p class="up" style="animation-delay:1.1s;font-size:50px;font-weight:600;margin:26px 0 0">Real-time voice. Your documents. Your models.</p>
  <div class="chips up" style="animation-delay:1.7s;margin-top:48px"><span class="chip">LiveKit</span><span class="chip">LangGraph</span><span class="chip">Qdrant</span></div>
  <p class="up" style="animation-delay:2.3s;font:500 24px JB,monospace;color:#7d84a6;margin-top:56px">measured on a local network: LLM first token about 75 ms, TTS first audio about 0.45 s</p>
</div>""",
)

CAPTIONS = {
    "cap_en1": ("Talk to it. It answers from your documents.", 950),
    "cap_en2": ("Every step is traced, down to the millisecond.", 950),
    "cap_ar": ("English or Arabic, detected automatically.", 950),
    "cap_chat": ("Chat too, with document search and live web search.", 860),
    "cap_kb": ("Drop in files. Search them in seconds.", 900),
    "cap_theme": ("Dark and light themes.", 900),
}
CAP_X = 781  # centre of the main column in the GUI


def caption_html(text: str, y: int) -> str:
    return f"""<!doctype html><meta charset='utf-8'><style>{BASE_CSS}
html,body{{background:transparent}} body::before{{display:none}}
.pill{{position:absolute;left:{CAP_X}px;top:{y}px;transform:translate(-50%,-50%);display:flex;align-items:center;gap:18px;
 padding:20px 38px;border-radius:999px;background:rgba(10,11,18,.88);border:1px solid rgba(185,175,255,.38);
 box-shadow:0 18px 50px -12px rgba(0,0,0,.8),0 0 40px -6px rgba(139,123,255,.45);font:650 38px Inter,sans-serif;white-space:nowrap}}
.dot{{width:16px;height:16px;border-radius:50%;background:linear-gradient(135deg,#8b7bff,#36d4ee);box-shadow:0 0 16px #8b7bff}}
</style><div class="pill"><span class="dot"></span><span>{text}</span></div>"""


LABELS = {
    "lbl_orb": "Listens, thinks, speaks",
    "lbl_transcript": "Live transcript",
    "lbl_reply": "The answer streams in",
    "lbl_latency": "Every stage, in milliseconds",
    "lbl_arabic": "Arabic, right to left",
    "lbl_tool_ar": "It searches in Arabic too",
    "lbl_ar_reply": "Answers in Arabic",
    "lbl_docsearch": "Searches your documents",
    "lbl_web": "Live web search",
    "lbl_indexed": "Indexed in seconds",
    "lbl_scores": "Passages ranked by score",
}

CHEVRONS = (
    "<svg width='34' height='24' viewBox='0 0 34 24'><path d='M2 2 L14 12 L2 22 Z' fill='#36d4ee'/>"
    "<path d='M18 2 L30 12 L18 22 Z' fill='#8b7bff'/></svg>"
)


def small_pill_html(inner: str) -> str:
    return f"""<!doctype html><meta charset='utf-8'><style>{BASE_CSS}
html,body{{background:transparent;width:900px;height:200px}} body::before{{display:none}}
.wrap{{display:inline-block;padding:44px}}
.pill{{display:inline-flex;align-items:center;gap:14px;padding:13px 28px;border-radius:999px;background:rgba(10,11,18,.9);
 border:1.5px solid rgba(185,175,255,.55);box-shadow:0 0 34px -4px rgba(139,123,255,.65),0 14px 34px -10px rgba(0,0,0,.8);
 font:650 30px Inter,sans-serif;white-space:nowrap;color:#f3f4ff}}
.dot{{width:13px;height:13px;border-radius:50%;background:linear-gradient(135deg,#8b7bff,#36d4ee);box-shadow:0 0 14px #8b7bff}}
</style><div class="wrap"><div class="pill">{inner}</div></div>"""


def main() -> None:
    for name, html in {"title": TITLE, "models": MODELS, "outro": OUTRO}.items():
        (CARDS / f"{name}.html").write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page_ = browser.new_page(viewport={"width": 1920, "height": 1080})
        pills = {name: f"<span class='dot'></span><span>{text}</span>" for name, text in LABELS.items()}
        pills["badge_fast"] = f"{CHEVRONS}<span>2×</span>"
        for name, inner in pills.items():
            (CAPS / f"{name}.html").write_text(small_pill_html(inner), encoding="utf-8")
            page_.goto((CAPS / f"{name}.html").as_uri())
            page_.wait_for_timeout(300)
            page_.locator(".wrap").screenshot(path=str(CAPS / f"{name}.png"), omit_background=True)
            print("label", name)
        for name, (text, y) in CAPTIONS.items():
            (CAPS / f"{name}.html").write_text(caption_html(text, y), encoding="utf-8")
            page_.goto((CAPS / f"{name}.html").as_uri())
            page_.wait_for_timeout(400)
            page_.screenshot(path=str(CAPS / f"{name}.png"), omit_background=True)
            print("caption", name)
        browser.close()
    print("cards:", sorted(p.name for p in CARDS.glob("*.html")))


if __name__ == "__main__":
    main()
