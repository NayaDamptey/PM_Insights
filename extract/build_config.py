"""Generate ``config/sources.yaml`` from the data dictionary.

The dictionary says, per table, which endpoint the data comes from and, per field,
where it sits in the JSON response. This script turns that into instructions the
extractors can follow: how to page through each endpoint, which parent ids a child
endpoint needs, and which JSON path fills each CSV column.

Endpoint text in the dictionary is free text, so it is interpreted with a few rules:

* Qube / Engage ``.../resource/{Key}``          -> list the collection ``.../resource``
* Qube / Engage ``.../resource/{Key}/child``    -> call ``child`` once per parent record
* MRI API Services ``$api=name[&PARAM={x}]``    -> one call, or one call per parent
* FixFlo endpoints are matched one by one (each has its own paging style).

Run:  python -m extract.build_config [--dictionary PATH] [--out config/sources.yaml]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DICTIONARY = PROJECT_ROOT.parent / "Data_Dictionary_Source_and_Silver.xlsx"
DEFAULT_OUT = PROJECT_ROOT / "config" / "sources.yaml"

SYSTEMS: dict[str, dict[str, Any]] = {
    "qube": {
        "dictionary_system": "MRI Qube PM",
        "base_url_env": "MRI_BASE_URL",
        "auth": "mri_basic",
        "page_size": 1000,  # Qube's $top limit
    },
    "fixflo": {
        "dictionary_system": "FixFlo",
        "base_url_env": "FIXFLO_BASE_URL",
        "auth": "bearer",
        "token_env": "FIXFLO_API_TOKEN",
        "page_size": 100,  # /Property/Search pgsz limit
    },
    "engage": {
        "dictionary_system": "MRI Engage CRM",
        "base_url_env": "ENGAGE_BASE_URL",
        "auth": "bearer",
        "token_env": "ENGAGE_API_TOKEN",
        "page_size": 1000,
    },
}

# A placeholder in an MRI API Services URL names the parent it iterates over.
SERVICE_PARENTS = {"property": ("qube_properties", "PropertyRef")}

# Columns that record when a source row last changed, in order of preference.
WATERMARK_COLUMNS = (
    "StatusChanged",
    "UpdateDate",
    "LastUpdate",
    "LastUpdatedDate",
    "ModifiedAt",
    "ModifiedDate",
)

# Only FixFlo /Issues can filter on change time at the source (UpdatedSince).
# Every other endpoint has to be pulled in full each run.
SOURCE_FILTERS = {"fixflo_issues": "UpdatedSince"}


def _system_of(dictionary_system: str) -> str | None:
    for key, cfg in SYSTEMS.items():
        if cfg["dictionary_system"] == dictionary_system:
            return key
    return None


def _column(field: str, json_path: str) -> dict[str, str]:
    """Turn a dictionary JSON path into a dot path inside one record."""
    path = json_path.strip()
    match = re.fullmatch(r"\$\.(\w+) \(added from the URL\)", path)
    if match:
        # Not in the response body: the value is the id used in the request URL.
        return {"name": field, "from_url": match.group(1)}
    if not path.startswith("$."):
        raise ValueError(f"unexpected JSON path for {field}: {json_path!r}")
    path = path[2:]
    # MRI API Services wraps records in "entry"; paths are taken per record.
    path = path.removeprefix("entry.")
    return {"name": field, "path": path}


def _fixflo_fetch(table: str, endpoint: str) -> dict[str, Any]:
    """FixFlo endpoints, matched individually because each pages differently."""
    if endpoint.startswith("GET /Property/Search"):
        return {
            "method": "fixflo_pager",
            "path": "/Property/Search",
            "page_param": "pg",
            "size_param": "pgsz",
        }
    if endpoint.startswith("GET /Issues?"):
        # /Issues returns issue URLs only; each URL is then fetched for the full issue.
        return {"method": "fixflo_issue_urls", "path": "/Issues", "page_param": "page"}
    if endpoint.startswith("GET /Job/{id}"):
        # The job id is on the issue (Job.id); issues without a job are skipped.
        return {
            "method": "per_parent",
            "parent": "fixflo_issues",
            "path": "/Job/{Job.id}",
            "response": "object",
            "only_if": "Job.id",
        }
    if endpoint.startswith("GET /Issue/{issueid}/jobcompletiondetails"):
        # Completion details only exist once a job exists, so skip issues without one.
        return {
            "method": "per_parent",
            "parent": "fixflo_issues",
            "path": "/Issue/{Id}/jobcompletiondetails",
            "response": "object",
            "only_if": "Job.id",
        }
    if endpoint.startswith("GET /Issue/{issueId}/quotes"):
        # The issue lists its quotes, so only issues with a non-empty list are called.
        return {
            "method": "per_parent",
            "parent": "fixflo_issues",
            "path": "/Issue/{Id}/quotes",
            "response": "list",
            "only_if": "Quotes",
        }
    match = re.match(r"GET (/(?:Contractors|Blocks|Agents))\b", endpoint)
    if match:
        return {"method": "list", "path": match.group(1)}
    raise ValueError(f"{table}: no rule for FixFlo endpoint {endpoint!r}")


def build(dictionary: Path) -> dict[str, Any]:
    tables_df = pd.read_excel(dictionary, sheet_name="Tables")
    fields_df = pd.read_excel(dictionary, sheet_name="Fields")
    tables_df = tables_df[tables_df["Layer"] == "Source"]
    fields_df = fields_df[fields_df["Layer"] == "Source"]

    collections: dict[str, tuple[str, str]] = {}  # "/qube/api/v1/staff/{StaffCode}" -> table, key
    tables: dict[str, dict[str, Any]] = {}

    # First pass: collection endpoints, so child endpoints can find their parent.
    for row in tables_df.itertuples(index=False):
        endpoint = str(row[5])
        match = re.fullmatch(r"GET https://\[\w+\](/\S+)/\{(\w+)\}", endpoint.strip())
        if match:
            collections[f"{match.group(1)}/{{{match.group(2)}}}"] = (row.Table, match.group(2))

    for row in tables_df.itertuples(index=False):
        table, endpoint = row.Table, str(row[5]).strip()
        system = _system_of(row.System)
        entry: dict[str, Any] = {
            "system": system,
            "source_endpoint": endpoint,
            "expected_rows": int(row.Rows),
        }
        if system is None:
            entry["fetch"] = {"method": "none", "reason": endpoint}
        elif "MRIAPIServices" in endpoint:
            api = re.search(r"\$api=([\w-]+)", endpoint).group(1)  # type: ignore[union-attr]
            fetch: dict[str, Any] = {"method": "mri_service", "api": api}
            param = re.search(r"&(\w+)=\{(\w+)\}", endpoint)
            if param:
                parent, parent_key = SERVICE_PARENTS[param.group(2)]
                fetch.update(parent=parent, parent_field=parent_key, param=param.group(1))
            entry["fetch"] = fetch
        elif system == "fixflo":
            entry["fetch"] = _fixflo_fetch(table, endpoint)
        else:
            path = re.match(r"GET https://\[\w+\](/\S+)", endpoint).group(1)  # type: ignore[union-attr]
            if path in collections:
                entry["fetch"] = {"method": "collection", "path": path.rsplit("/", 1)[0]}
                entry["key"] = collections[path][1]
            else:
                parent_path, child = path.rsplit("/", 1)
                parent, parent_key = collections[parent_path]
                entry["fetch"] = {
                    "method": "per_parent",
                    "parent": parent,
                    "path": path,
                    "response": "mri_v1",
                }
                del child, parent_key

        fields = fields_df[fields_df["Table"] == table]
        columns = [
            _column(f.Field, f[7]) for f in fields.itertuples(index=False) if isinstance(f[7], str)
        ]
        # A column "added from the URL" takes the id used to build the request URL, which
        # the endpoint names differently (IssueId comes from the {Id} in /Issue/{Id}/quotes).
        url_ids = re.findall(r"\{([\w.]+)\}", entry["fetch"].get("path", ""))
        for col in columns:
            if "from_url" in col:
                if len(url_ids) != 1:
                    raise ValueError(f"{table}.{col['name']}: cannot tell which URL id it is")
                col["from_url"] = url_ids[0]
        entry["columns"] = columns
        names = [c["name"] for c in columns]
        entry["watermark_column"] = next((c for c in WATERMARK_COLUMNS if c in names), None)
        entry["source_filter"] = SOURCE_FILTERS.get(table)
        tables[table] = entry

    # Children of a source-filtered parent are incremental too: they follow its delta.
    for entry in tables.values():
        parent = entry["fetch"].get("parent")
        entry["incremental"] = bool(entry["source_filter"]) or bool(
            parent and tables[parent]["source_filter"]
        )

    systems = {
        k: {kk: vv for kk, vv in v.items() if kk != "dictionary_system"} for k, v in SYSTEMS.items()
    }
    return {"systems": systems, "tables": tables}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    config = build(args.dictionary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Generated from {args.dictionary.name} by `python -m extract.build_config`.\n"
        "# Do not edit by hand: change the dictionary or the rules in build_config.py.\n"
    )
    body = yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=120)
    args.out.write_text(header + body, encoding="utf-8")
    print(f"wrote {args.out} ({len(config['tables'])} tables)")


if __name__ == "__main__":
    main()
