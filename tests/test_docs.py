"""Docs must match the code: settings, routes, Makefile targets, links, diagrams, excerpts."""

import re

from fastapi.testclient import TestClient

from config.settings import Settings
from src.app import create_app
from tests.conftest import ROOT

DOCS = ROOT / "docs"
BLOCKS = DOCS / "blocks"
MARKDOWN_FILES = [
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    *sorted(DOCS.glob("*.md")),
    *sorted(BLOCKS.glob("*.md")),
]
BLOCK_PAGES = sorted(BLOCKS.glob("[0-9][0-9]-*.md"))
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
NODE = re.compile(
    r"(?:^|-->|---|-\.->|-\.-|<--|<-->|--\s)\s*(?:\|[^|]*\|\s*)?([A-Za-z_]\w*)\s*[\[({>]", re.M
)
EXCERPT = re.compile(r"```(\w+)\n(?:# |// )([^\s(]+)(?: \([^)\n]*\))?\n(.*?)```", re.S)
SOURCE_PATH = re.compile(
    r"^[\w./-]+\.(?:py|ts|tsx|yml|yaml|template)$|^(?:Makefile|deployment/Dockerfile)$"
)
PROSE_PATH = re.compile(
    r"`((?:src|config|tests|scripts|deployment|frontend/src|frontend/scripts|docs|examples)/"
    r"[A-Za-z0-9_./-]*[A-Za-z0-9_/])`"
)
EXPECTED_DOCS = {
    "api.md",
    "config.md",
    "deployment.md",
    "features.md",
    "frontend.md",
    "graph.md",
    "installation.md",
    "llm.md",
    "prompts.md",
    "running.md",
    "utils.md",
    "voice.md",
}
REQUIRED_BLOCK_SECTIONS = ("## Try it", "## Check yourself", "## Read next")
MAX_DIAGRAM_NODES = 15
MAX_AGENTS_LINES = 60


def is_flowchart(block: str) -> bool:
    return block.lstrip().startswith("flowchart")


def test_all_documented_pages_exist():
    assert {path.name for path in DOCS.glob("*.md")} >= EXPECTED_DOCS
    assert (ROOT / "LICENSE").exists() and (ROOT / "uv.lock").exists()


def test_every_setting_is_documented_in_config_md():
    text = (DOCS / "config.md").read_text(encoding="utf-8")
    missing = [name for name in Settings.model_fields if f"`{name}`" not in text]
    assert missing == [], f"undocumented settings: {missing}"


def test_every_route_is_documented_in_api_md(settings):
    text = (DOCS / "api.md").read_text(encoding="utf-8")
    paths = TestClient(create_app(settings)).get("/openapi.json").json()["paths"]
    for path, operations in paths.items():
        for method in operations:
            assert f"`{path}`" in text, f"{method.upper()} {path} is not in docs/api.md"


def test_every_makefile_target_is_documented_in_deployment_md():
    text = (DOCS / "deployment.md").read_text(encoding="utf-8")
    targets = re.findall(
        r"^([a-zA-Z0-9_-]+):.*##", (ROOT / "Makefile").read_text(encoding="utf-8"), re.M
    )
    missing = [target for target in targets if target != "help" and f"`{target}`" not in text]
    assert missing == [], f"targets missing from docs/deployment.md: {missing}"


def test_relative_links_resolve():
    broken = []
    for path in MARKDOWN_FILES:
        for target in LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            file_part = target.split("#", 1)[0]
            if file_part and not (path.parent / file_part).resolve().exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert broken == [], f"broken links: {broken}"


def test_flowcharts_are_small_and_use_the_house_style():
    diagrams = [
        (path, block)
        for path in MARKDOWN_FILES
        for block in MERMAID.findall(path.read_text("utf-8"))
        if is_flowchart(block)
    ]
    assert len(diagrams) >= 20
    for path, block in diagrams:
        nodes = set(NODE.findall(block)) - {"classDef", "flowchart"}
        assert 1 < len(nodes) <= MAX_DIAGRAM_NODES, f"{path.name}: {len(nodes)} nodes"
        assert "classDef io fill:#FAFAFA" in block, f"{path.name}: house classDefs missing"
        assert "-.->" in block, f"{path.name}: no dashed error path"


def test_mermaid_node_ids_avoid_reserved_words():
    reserved = {"graph", "end", "subgraph", "class", "style", "default", "click", "call"}
    for path in MARKDOWN_FILES:
        for block in MERMAID.findall(path.read_text(encoding="utf-8")):
            assert not (set(NODE.findall(block)) & reserved), f"{path.name}: reserved node id"


def test_agents_md_stays_short():
    assert len((ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()) <= MAX_AGENTS_LINES


def test_readme_is_short_and_links_out():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) < 100
    assert "docs/installation.md" in text and "examples/" in text
    assert "docs/blocks/README.md" in text


# --- the study pages in docs/blocks ---------------------------------------------------------


def test_every_block_page_is_in_the_index_and_has_the_study_sections():
    assert len(BLOCK_PAGES) == 14
    index = (BLOCKS / "README.md").read_text(encoding="utf-8")
    for page in BLOCK_PAGES:
        assert f"]({page.name})" in index, f"{page.name} is not linked from docs/blocks/README.md"
        text = page.read_text(encoding="utf-8")
        for section in REQUIRED_BLOCK_SECTIONS:
            assert section in text, f"{page.name} lacks '{section}'"
        assert text.startswith("# "), f"{page.name} has no title"
        assert "**Assumes:**" in text, f"{page.name} does not say what it assumes"


def normalized(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def contains_run(haystack: list[str], needle: list[str]) -> bool:
    size = len(needle)
    return any(haystack[i : i + size] == needle for i in range(len(haystack) - size + 1))


def test_code_excerpts_are_verbatim_copies_of_their_source():
    checked = 0
    for page in BLOCK_PAGES:
        text = page.read_text(encoding="utf-8")
        markers = text.count("<!-- excerpt: ")
        checked_before = checked
        for language, path, body in EXCERPT.findall(text):
            if language == "mermaid" or not SOURCE_PATH.match(path):
                continue
            source = ROOT / path
            assert source.exists(), f"{page.name}: excerpt of missing file {path}"
            snippet = normalized(body)
            assert snippet, f"{page.name}: empty excerpt of {path}"
            assert contains_run(normalized(source.read_text(encoding="utf-8")), snippet), (
                f"{page.name}: the excerpt of {path} no longer matches the source; "
                "run: uv run python scripts/refresh_block_excerpts.py"
            )
            checked += 1
        assert markers == checked - checked_before, (
            f"{page.name}: every excerpt needs an '<!-- excerpt: ... -->' marker above it"
        )
    assert checked >= 60


def test_paths_mentioned_in_prose_exist():
    ignored = {"frontend/dist", "frontend/node_modules"}
    missing = []
    for path in MARKDOWN_FILES:
        for mentioned in PROSE_PATH.findall(path.read_text(encoding="utf-8")):
            if mentioned.rstrip("/") in ignored:
                continue
            if not (ROOT / mentioned.rstrip("/")).exists():
                missing.append(f"{path.relative_to(ROOT)}: {mentioned}")
    assert missing == [], f"documents mention files that do not exist: {missing}"
