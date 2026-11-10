"""Record the Knowledge view: upload a document, search it, then flip to the light theme."""

from pathlib import Path

from record_lib import Recorder

HERE = Path(__file__).parent
OUT = HERE / "clips" / "knowledge"
OUT.mkdir(parents=True, exist_ok=True)
DOC = HERE / "assets" / "omnivox-demo-notes.md"

with Recorder(OUT) as rec:
    page = rec.page
    page.goto("http://localhost:5173/#/knowledge")
    upload = page.get_by_role("button", name="Upload documents: drop files here or press Enter to browse")
    upload.wait_for()
    show = page.get_by_role("button", name="Show Inspector")
    if show.count():
        show.click()
    rec.wait(1000)
    rec.start_capture()
    rec.wait(2500)
    rec.shot("kb_before")

    with page.expect_file_chooser() as chooser:
        upload.click()
    chooser.value.set_files(str(DOC))
    rec.mark("uploaded")
    rec.wait(3500)
    rec.shot("kb_uploaded")

    query = page.get_by_role("textbox", name="Search query")
    query.click()
    query.type("Which languages does it understand?", delay=45)
    rec.wait(500)
    page.get_by_role("button", name="Search", exact=True).click()
    rec.mark("searched")
    rec.wait(3500)
    rec.shot("kb_results")

    page.get_by_role("button", name="Switch to light theme").click()
    rec.mark("light theme")
    rec.wait(2500)
    rec.shot("kb_light")
