"""Read notebook sources written as Python files with ``# %%`` cell markers.

Notebooks are kept as .py so they can be read, diffed and linted like any other code;
build_notebooks.py turns each one into the ``.ipynb`` that is imported into Fabric.

Markers:
    # %%                        code cell
    # %% tags=["parameters"]    the parameters cell (Fabric/pipelines override its values)
    # %% [markdown]             markdown cell; each line's leading "# " is removed
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

NOTEBOOK_SRC = Path(__file__).resolve().parent / "notebooks" / "src"

_MARKER = re.compile(r"^# %%(?P<rest>.*)$")


@dataclass
class Cell:
    kind: str  # "code" or "markdown"
    source: str
    tags: list[str] = field(default_factory=list)


def parse(path: Path) -> list[Cell]:
    cells: list[Cell] = []
    current: Cell | None = None
    lines: list[str] = []

    def close() -> None:
        if current is not None:
            text = "\n".join(lines).strip("\n")
            if current.kind == "markdown":
                text = "\n".join(re.sub(r"^# ?", "", ln) for ln in text.splitlines())
            current.source = text
            cells.append(current)

    for line in path.read_text(encoding="utf-8").splitlines():
        match = _MARKER.match(line)
        if match:
            close()
            rest = match.group("rest").strip()
            kind = "markdown" if rest.startswith("[markdown]") else "code"
            tags_match = re.search(r"tags=(\[.*\])", rest)
            current = Cell(kind, "", json.loads(tags_match.group(1)) if tags_match else [])
            lines = []
        else:
            lines.append(line)
    close()
    return cells


def notebook_names() -> list[str]:
    return sorted(p.stem for p in NOTEBOOK_SRC.glob("*.py"))
