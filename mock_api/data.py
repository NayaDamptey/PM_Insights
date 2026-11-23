"""In-memory store that serves the reference CSV extracts as API records.

Each CSV cell is text. To serve realistic JSON, every column gets one JSON type
(string, int, float, bool or nested JSON). A type is only used when converting
the *whole column* to it and back gives the exact original text, so an
extractor can always reproduce the reference CSV byte for byte.

Type hints come from the API samples in ``api_samples/``; columns without a
sample are inferred. Dot-named columns (``Address.Town``) are rebuilt into
nested objects; an object whose fields are all empty is served as ``null``.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_INT_RE = re.compile(r"-?(0|[1-9]\d{0,17})")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")

# Which API sample describes which table, and where the records sit in it.
# root: "object" = the file is one record, "list" = a JSON array of records,
# or a key name ("Items", "entry") holding the array.
SAMPLE_HINTS: dict[str, list[tuple[str, str]]] = {
    "fixflo_agents": [("fixflo/GET_Agents.json", "list")],
    "fixflo_blocks": [("fixflo/GET_Blocks.json", "list")],
    "fixflo_contractors": [("fixflo/GET_Contractors.json", "list")],
    "fixflo_issues": [
        ("fixflo/GET_Issue_FFI500044_Closed.json", "object"),
        ("fixflo/GET_Issue_FFI500051_AwaitingJobCompletion.json", "object"),
        ("fixflo/GET_Issue_FFI501661_Reported.json", "object"),
    ],
    "fixflo_jobs": [
        ("fixflo/GET_Job_J800028.json", "object"),
        ("fixflo/GET_Job_J800033.json", "object"),
    ],
    "fixflo_quotes": [("fixflo/GET_Issue_FFI500002_quotes.json", "list")],
    "fixflo_job_completion_details": [
        ("fixflo/GET_Issue_FFI500001_jobcompletiondetails.json", "object")
    ],
    "fixflo_properties": [("fixflo/GET_Property_Search_pg1.json", "Items")],
    "qube_income_categories": [("mri/GET_income-categories.json", "entry")],
    "qube_resident_contact": [("mri/GET_resident-contact_RMPROPID_QP000001.json", "entry")],
}


def dump_json_text(value: Any) -> str:
    """Canonical JSON text for array/object cells (same rule the extractor uses)."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _lossless(kind: str, values: Iterable[str]) -> bool:
    for v in values:
        if v == "":
            continue
        if kind == "bool":
            if v not in ("true", "false"):
                return False
        elif kind == "int":
            if not _INT_RE.fullmatch(v):
                return False
        elif kind == "float":
            if not _FLOAT_RE.fullmatch(v) or repr(float(v)) != v:
                return False
        elif kind == "json":
            if v[0] not in "[{":
                return False
            try:
                if dump_json_text(json.loads(v)) != v:
                    return False
            except ValueError:
                return False
        elif kind != "str":
            raise ValueError(kind)
    return True


def _sample_kind(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (list, dict)):
        return "json"
    return "str"


def _flatten_kinds(obj: Any, prefix: str, out: dict[str, str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _flatten_kinds(v, path, out)
                # A nested object can also be stored whole as one JSON column.
                out.setdefault(path, "json")
            else:
                kind = _sample_kind(v)
                if kind:
                    out.setdefault(path, kind)


def load_sample_hints(samples_dir: Path) -> dict[str, dict[str, str]]:
    hints: dict[str, dict[str, str]] = {}
    for table, files in SAMPLE_HINTS.items():
        out: dict[str, str] = {}
        for rel, root in files:
            path = samples_dir / rel
            if not path.exists():
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            if root == "object":
                records = [doc]
            elif root == "list":
                records = doc
            else:
                records = doc[root]
            for rec in records:
                _flatten_kinds(rec, "", out)
        hints[table] = out
    return hints


def choose_kind(values: list[str], hint: str | None) -> str:
    if hint is not None:
        if hint == "str" or _lossless(hint, values):
            return hint
        log.debug("sample hint %s not lossless, inferring", hint)
    if all(v == "" for v in values):
        return "str"
    for kind in ("bool", "int", "float", "json"):
        if _lossless(kind, values):
            return kind
    return "str"


def to_json_value(text: str, kind: str) -> Any:
    if text == "":
        return None
    if kind == "str":
        return text
    if kind == "int":
        return int(text)
    if kind == "float":
        return float(text)
    if kind == "bool":
        return text == "true"
    return json.loads(text)


@dataclass
class _Node:
    """Shape of a record: leaves point at a column, branches are nested objects."""

    children: dict[str, _Node | int] = field(default_factory=dict)


def _build_shape(columns: list[str]) -> _Node:
    root = _Node()
    for idx, col in enumerate(columns):
        parts = col.split(".")
        node = root
        for part in parts[:-1]:
            nxt = node.children.get(part)
            if nxt is None:
                nxt = _Node()
                node.children[part] = nxt
            if not isinstance(nxt, _Node):
                raise ValueError(f"column {col!r} nests under a scalar column")
            node = nxt
        node.children[parts[-1]] = idx
    return root


class Table:
    """One reference CSV, held as tuples of strings, with lookup indexes."""

    def __init__(self, name: str, path: Path, hints: dict[str, str]) -> None:
        self.name = name
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            self.columns: list[str] = next(reader)
            caches: list[dict[str, str]] = [{} for _ in self.columns]
            rows: list[tuple[str, ...]] = []
            for raw in reader:
                # Share repeated strings (dates, statuses) to keep memory down.
                rows.append(tuple(c.setdefault(v, v) for c, v in zip(caches, raw, strict=True)))
        self.rows = rows
        self.kinds = [
            choose_kind([r[i] for r in rows], hints.get(col)) for i, col in enumerate(self.columns)
        ]
        self._shape = _build_shape(self.columns)
        self._indexes: dict[str, dict[str, list[int]]] = {}
        self._lock = threading.Lock()

    def col(self, name: str) -> int:
        return self.columns.index(name)

    def index(self, column: str) -> dict[str, list[int]]:
        """Row positions per value of ``column`` (built once, in file order)."""
        idx = self._indexes.get(column)
        if idx is None:
            with self._lock:
                idx = self._indexes.get(column)
                if idx is None:
                    pos = self.col(column)
                    idx = {}
                    for i, row in enumerate(self.rows):
                        idx.setdefault(row[pos], []).append(i)
                    self._indexes[column] = idx
        return idx

    def rows_where(self, column: str, value: str) -> list[int]:
        return self.index(column).get(value, [])

    def record(self, i: int, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
        row = self.rows[i]

        def build(node: _Node, prefix: str) -> dict[str, Any] | None:
            out: dict[str, Any] = {}
            any_value = False
            for key, child in node.children.items():
                path = f"{prefix}{key}"
                if path in exclude:
                    continue
                if isinstance(child, _Node):
                    value = build(child, f"{path}.")
                else:
                    value = to_json_value(row[child], self.kinds[child])
                any_value = any_value or value is not None
                out[key] = value
            return out if any_value or not prefix else None

        rec = build(self._shape, "")
        assert rec is not None
        return rec


class DataStore:
    """Lazily loads reference tables; thread-safe."""

    def __init__(self, data_dir: Path) -> None:
        self.extracts_dir = data_dir / "extracts"
        self.samples_dir = data_dir / "api_samples"
        if not self.extracts_dir.is_dir():
            raise FileNotFoundError(f"reference extracts not found: {self.extracts_dir}")
        self._hints = load_sample_hints(self.samples_dir)
        self._tables: dict[str, Table] = {}
        self._lock = threading.Lock()

    def table_names(self) -> list[str]:
        return sorted(p.stem for p in self.extracts_dir.glob("*.csv"))

    def table(self, name: str) -> Table:
        tbl = self._tables.get(name)
        if tbl is None:
            with self._lock:
                tbl = self._tables.get(name)
                if tbl is None:
                    log.info("loading %s", name)
                    tbl = Table(name, self.extracts_dir / f"{name}.csv", self._hints.get(name, {}))
                    self._tables[name] = tbl
        return tbl

    def preload(self, names: Iterable[str]) -> None:
        for name in names:
            self.table(name)
