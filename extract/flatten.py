"""Turn one JSON record into one CSV row, using the column paths from sources.yaml.

Rendering rules decide the exact text written to the CSV, so they must stay in step
with how the source data is typed:

* missing / null          -> empty cell
* true / false            -> "true" / "false"
* numbers                 -> Python's shortest round-trip text (3.0 stays "3.0")
* arrays / objects        -> compact JSON text, keys in response order
* strings                 -> as is
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def get_path(record: Mapping[str, Any] | None, path: str) -> Any:
    """Value at a dot path such as ``Job.Contractor.Id``; None if any step is missing."""
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, Mapping):
            return None
        value = value.get(part)
    return value


def render(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):  # before int: bool is a subclass of int
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def flatten(
    record: Mapping[str, Any],
    columns: Sequence[Mapping[str, str]],
    url_values: Mapping[str, Any] | None = None,
) -> list[str]:
    """One CSV row in column order.

    ``url_values`` supplies columns that are not in the body but were part of the
    request URL (e.g. the IssueId in ``/Issue/{Id}/quotes``).
    """
    row: list[str] = []
    for col in columns:
        if "from_url" in col:
            value = (url_values or {}).get(col["from_url"])
        else:
            value = get_path(record, col["path"])
        row.append(render(value))
    return row
