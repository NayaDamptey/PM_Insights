"""Everything the extractors write to ``data/landing``.

Layout:
    json/<system>/<table>/<run_date>/page_00001.json   raw API responses, as received
    csv/<table>.csv                                    flattened output of the latest run
    _watermarks.json                                   last change time seen per table
    _runs/<run_id>.json, _runs/<run_id>.log           one manifest and log per run
    _runs/latest.json                                  copy of the newest manifest

Writes are idempotent: a table's raw folder for the run date is emptied before it
is written again, and files are written to a temp name and then renamed, so a
failed run never leaves a half-written CSV behind.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class RawWriter:
    """Saves raw responses, ``bundle`` responses per page file.

    Paged endpoints use bundle=1 so each API page is one file. Per-record
    endpoints (one call per issue, per tenancy...) are bundled so a full run
    writes hundreds of files rather than hundreds of thousands.
    """

    def __init__(self, folder: Path, bundle: int) -> None:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        self.folder = folder
        self.bundle = bundle
        self.files = 0
        self.responses = 0
        self._buffer: list[dict[str, Any]] = []

    def add(self, url: str, body: Any) -> None:
        self._buffer.append({"url": url, "body": body})
        self.responses += 1
        if len(self._buffer) >= self.bundle:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self.files += 1
        path = self.folder / f"page_{self.files:05d}.json"
        text = json.dumps({"responses": self._buffer}, ensure_ascii=False, separators=(",", ":"))
        path.write_text(text, encoding="utf-8")
        self._buffer = []


class CsvSink:
    """Writes one table's CSV to a temp file; ``commit`` swaps it into place."""

    def __init__(self, path: Path, header: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._tmp = path.with_name(path.name + ".tmp")
        # newline="" + "\r\n" reproduces the reference files' line endings exactly.
        self._fh = self._tmp.open("w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._fh, lineterminator="\r\n")
        self._writer.writerow(header)
        self.rows = 0

    def write(self, row: list[str]) -> None:
        self._writer.writerow(row)
        self.rows += 1

    def commit(self) -> None:
        self._fh.close()
        os.replace(self._tmp, self.path)

    def abort(self) -> None:
        self._fh.close()
        self._tmp.unlink(missing_ok=True)


class Watermarks:
    """Highest change timestamp seen per table, kept between runs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, dict[str, Any]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        )

    def value(self, table: str) -> str | None:
        return self.data.get(table, {}).get("value")

    def update(
        self, table: str, column: str, value: str, source_filter: str | None, run_id: str
    ) -> None:
        old = self.value(table)
        if old is not None and parse_ts(old) >= parse_ts(value):
            value = old  # never move a watermark backwards
        self.data[table] = {
            "column": column,
            "value": value,
            "source_filter": source_filter,
            "run_id": run_id,
            "updated_at": now_iso(),
        }

    def save(self) -> None:
        _atomic_write_text(self.path, json.dumps(self.data, indent=2, sort_keys=True))


def parse_ts(text: str) -> datetime:
    """Parse the source's ISO timestamps (with or without 'Z', 7-digit fractions)."""
    value = text.strip()
    if "." in value:  # MRI writes 7 fractional digits; Python accepts at most 6
        head, frac = value.split(".", 1)
        digits = "".join(ch for ch in frac if ch.isdigit())
        tail = frac[len(digits) :]
        value = f"{head}.{digits[:6]}{tail}"
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_manifest(runs_dir: Path, manifest: dict[str, Any], csv_dir: Path | None = None) -> Path:
    """Keep every run's manifest in _runs/, and a copy as csv/_manifest.json.

    The copy makes the csv folder self-contained: uploaded to Fabric as it is, it tells the
    Bronze notebook the run id, the load mode and how many rows to expect per table.
    """
    text = json.dumps(manifest, indent=2)
    path = runs_dir / f"{manifest['run_id']}.json"
    _atomic_write_text(path, text)
    _atomic_write_text(runs_dir / "latest.json", text)
    if csv_dir is not None:
        csv_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(csv_dir / "_manifest.json", text)
    return path
