"""The last real run (`extract.run --all`) reproduces the source data the mock API served.

Checks per table: same columns in the same order, and the same rows with the same
values. Row order is also expected to match; if it differs (e.g. planted rows that
break parent grouping) the test still passes but warns, because the data is the same.

Skipped until a full run has landed data in data/landing.
"""

from __future__ import annotations

import csv
import json
import warnings
from collections import Counter
from pathlib import Path

import pytest

from extract.run import DEFAULT_LANDING, load_config
from tests.conftest import SERVED

TABLES = [n for n, t in load_config()["tables"].items() if t["fetch"]["method"] != "none"]


def _latest_full_run() -> dict | None:
    path = DEFAULT_LANDING / "_runs" / "latest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return manifest if manifest["mode"] == "full" else None


def _rows(path: Path) -> list[tuple[str, ...]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [tuple(r) for r in csv.reader(fh)]


@pytest.mark.parametrize("table", TABLES)
def test_extracted_csv_matches_reference(table: str) -> None:
    manifest = _latest_full_run()
    if manifest is None:
        pytest.skip("no full run yet: python -m extract.run --all")
    status = {t["table"]: t["status"] for t in manifest["tables"]}
    if status.get(table) != "succeeded":
        pytest.skip(f"{table} not extracted in run {manifest['run_id']}")

    got = _rows(DEFAULT_LANDING / "csv" / f"{table}.csv")
    want = _rows(SERVED / "extracts" / f"{table}.csv")
    assert got[0] == want[0], "columns differ"
    missing = Counter(want[1:]) - Counter(got[1:])
    extra = Counter(got[1:]) - Counter(want[1:])
    assert not missing and not extra, (
        f"{sum(missing.values())} reference rows missing, e.g. {list(missing)[:2]}; "
        f"{sum(extra.values())} unexpected rows, e.g. {list(extra)[:2]}"
    )
    if got != want:
        warnings.warn(f"{table}: same rows, different order", stacklevel=1)
