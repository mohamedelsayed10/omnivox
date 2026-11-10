"""Record the text chat view with a document question and a web search question."""

from pathlib import Path

from record_lib import Recorder

OUT = Path(__file__).parent / "clips" / "chat"
OUT.mkdir(parents=True, exist_ok=True)

with Recorder(OUT) as rec:
    page = rec.page
    page.goto("http://localhost:5173/#/chat")
    box = page.get_by_placeholder("Message OmniVox")
    box.wait_for()
    show = page.get_by_role("button", name="Show Inspector")
    if show.count():
        show.click()
    rec.wait(1000)
    rec.start_capture()
    rec.wait(2200)
    rec.shot("chat_empty")

    def ask(text: str, wait_ms: int, label: str) -> None:
        box.click()
        box.type(text, delay=38)
        rec.wait(500)
        rec.mark(f"send: {label}")
        page.get_by_role("button", name="Send message").click()
        rec.wait(wait_ms)
        rec.shot(label)

    ask("What are the support hours according to our handbook?", 7000, "chat_docs")
    ask("Search the web: who is the CEO of NVIDIA?", 14000, "chat_web")
    rec.wait(1500)
