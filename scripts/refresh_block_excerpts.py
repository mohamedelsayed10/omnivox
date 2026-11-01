"""Refresh the code excerpts in docs/blocks/ from the source files they quote.

Every excerpt in a study page sits under a hidden marker that names its source::

    <!-- excerpt: src/api/deps.py::build_container -->      a Python function, class or method
    <!-- excerpt: frontend/src/App.tsx#Shell -->            a TypeScript symbol
    <!-- excerpt: deployment/Dockerfile:L1-30 -->           an exact line range

``uv run python scripts/refresh_block_excerpts.py`` rewrites each excerpt in place;
``--check`` lists the pages whose excerpts differ from their source and exits non-zero.
Prose is never touched.
"""

import argparse
import ast
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = ROOT / "docs" / "blocks"
SPEC = re.compile(
    r"^(?P<path>[^:#\s]+)(?:::(?P<sym>[\w.]+)|#(?P<ts>\w+)|:L(?P<first>\d+)-(?P<last>\d+))$"
)
BLOCK = re.compile(r"<!-- excerpt: (?P<spec>\S+) -->\n```(?P<lang>\w+)\n.*?\n```", re.S)
FENCE_LANGUAGES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".yml": "yaml",
    ".yaml": "yaml",
}
TS_CLOSERS = ("}", "};", "},", "});")


def python_symbol(source: str, symbol: str) -> str:
    """Source text of a Python def, class, method (dotted) or module-level constant."""
    nodes: list[ast.AST] = list(ast.parse(source).body)
    found: ast.AST | None = None
    for part in symbol.split("."):
        found = None
        for node in nodes:
            names: list[str] = []
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names = [node.target.id]
            if part in names:
                found = node
                break
        if found is None:
            raise LookupError(f"symbol not found: {symbol} (stuck at {part})")
        nodes = list(getattr(found, "body", []))
    segment = ast.get_source_segment(source, found)
    if segment is None:
        raise LookupError(f"no source for {symbol}")
    lines = segment.splitlines()
    lines[0] = " " * found.col_offset + lines[0]  # the segment starts at the node, not the line
    return textwrap.dedent("\n".join(lines))


def ts_symbol(source: str, name: str) -> str:
    """Source text of a TypeScript function, class, const, interface or method."""
    lines = source.splitlines()
    start = re.compile(
        rf"^(\s*)(export\s+)?(default\s+)?(async\s+)?((function|class|const|interface|type|let)\s+)?"
        rf"{re.escape(name)}\b"
    )
    method = re.compile(rf"^\s*(async\s+)?{re.escape(name)}\s*[(<]")
    for index, line in enumerate(lines):
        match = start.match(line)
        if not match or (match.group(5) is None and not method.match(line)):
            continue
        indent = len(match.group(1))
        for end in range(index + 1, len(lines)):
            current = lines[end]
            if current.strip() in TS_CLOSERS and len(current) - len(current.lstrip()) == indent:
                return textwrap.dedent("\n".join(lines[index : end + 1]))
        break
    raise LookupError(f"TypeScript symbol not found: {name}")


def render_excerpt(spec: str) -> str:
    """The fenced code block (with its path header line) for one excerpt spec."""
    match = SPEC.match(spec)
    if match is None:
        raise ValueError(f"bad excerpt spec: {spec}")
    relative = match["path"]
    path = ROOT / relative
    source = path.read_text(encoding="utf-8")
    if match["sym"]:
        body = python_symbol(source, match["sym"])
    elif match["ts"]:
        body = ts_symbol(source, match["ts"])
    else:
        first, last = int(match["first"]), int(match["last"])
        body = textwrap.dedent("\n".join(source.splitlines()[first - 1 : last]))
    suffix = path.suffix.lower()
    comment = "//" if suffix in (".ts", ".tsx") else "#"
    symbol = match["sym"] or match["ts"]
    label = f"{relative} ({symbol})" if symbol and ("." in symbol or match["ts"]) else relative
    language = FENCE_LANGUAGES.get(suffix, "text")
    return f"<!-- excerpt: {spec} -->\n```{language}\n{comment} {label}\n{body}\n```"


def refreshed(text: str) -> str:
    """``text`` with every marked excerpt regenerated from its source."""
    return BLOCK.sub(lambda match: render_excerpt(match["spec"]), text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when excerpts are out of date")
    args = parser.parse_args()
    stale: list[str] = []
    for page in sorted(BLOCKS.glob("*.md")):
        old = page.read_text(encoding="utf-8")
        new = refreshed(old)
        if new == old:
            continue
        stale.append(page.name)
        if not args.check:
            page.write_text(new, encoding="utf-8", newline="\n")
            print(f"refreshed {page.relative_to(ROOT)}")
    if args.check and stale:
        print("stale excerpts in: " + ", ".join(stale) + " (run scripts/refresh_block_excerpts.py)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
