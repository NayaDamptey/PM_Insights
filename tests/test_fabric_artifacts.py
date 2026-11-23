"""Fabric notebooks: built from their current sources, and Silver matches the dictionary."""

from __future__ import annotations

import re

import nbformat
import pytest

from fabric import build_notebooks, silver_contract
from fabric.notebook_source import NOTEBOOK_SRC, notebook_names, parse

# --- notebooks ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", notebook_names())
def test_ipynb_is_built_from_current_source(name: str) -> None:
    built = nbformat.read(str(NOTEBOOK_SRC.parent / f"{name}.ipynb"), as_version=4)
    cells = [c for c in parse(NOTEBOOK_SRC / f"{name}.py")]
    assert [c.source for c in built.cells] == [
        c.source for c in cells
    ], "re-run: python -m fabric.build_notebooks"
    params = [c for c in built.cells if "parameters" in c.metadata.get("tags", [])]
    assert len(params) == 1
    assert built.metadata["kernel_info"]["name"] == "synapse_pyspark"
    assert dict(built.metadata) == build_notebooks.FABRIC_METADATA


METADATA = ("source_system", "source_table", "loaded_at")

# --- silver ----------------------------------------------------------------------------------


def _staging_queries() -> dict[str, str]:
    """The STAGING dict from 02_silver, without running anything that needs Spark."""
    namespace: dict = {}
    for cell in parse(NOTEBOOK_SRC / "02_silver.py"):
        if cell.kind == "code" and "STAGING" in cell.source and "spark" not in cell.source:
            exec(cell.source, namespace)  # noqa: S102 - plain string assignments
    return namespace["STAGING"]


def test_generated_blocks_are_up_to_date() -> None:
    for name in notebook_names():
        text = (NOTEBOOK_SRC / f"{name}.py").read_text(encoding="utf-8")
        fresh = build_notebooks._BLOCK.sub(lambda m: build_notebooks.render_block(m.group(1)), text)
        assert text == fresh, f"{name}: re-run python -m fabric.build_notebooks"


def test_every_silver_table_has_a_staging_query_returning_its_columns() -> None:
    contract = silver_contract.build()
    staging = _staging_queries()
    assert set(staging) == set(contract)
    for table, sql in staging.items():
        final_select = sql[sql.rindex("\nSELECT ") :]
        aliases = re.findall(r"\bAS\s+(\w+)\s*(?:,|\n|$)", final_select)
        expected = [c for c, _ in contract[table]["columns"] if c not in METADATA]
        assert aliases == expected, table


def test_silver_keys_are_columns_of_their_table() -> None:
    for table, spec in silver_contract.build().items():
        names = [c for c, _ in spec["columns"]]
        assert spec["key"] and set(spec["key"]) <= set(names), table


# --- data quality rules ----------------------------------------------------------------------

CHECK_SETTINGS = {
    "primary_key": [],
    "foreign_key": [],
    "type_converts": [],
    "freshness": ["max_age_hours"],
    "not_null": ["columns"],
    "pattern": ["regex"],
    "allowed_values": ["values"],
    "range": ["min", "max"],
    "date_window": ["columns", "min"],
    "sql": ["sql"],
}


def test_dq_rules_are_complete_and_point_at_real_columns() -> None:
    rules = build_notebooks.load_dq_rules()
    contract = silver_contract.build()
    owners = {d["owner"] for d in rules["domains"].values()} | {"table owner"}
    ids = [r["id"] for r in rules["rules"]]
    assert len(ids) == len(set(ids))
    for r in rules["rules"]:
        for field in ("id", "name", "dimension", "severity", "owner", "table", "column", "check"):
            assert r.get(field) is not None, (r["id"], field)
        assert r["dimension"] in {
            "completeness",
            "uniqueness",
            "validity",
            "consistency",
            "timeliness",
            "referential integrity",
        }, r["id"]
        assert r["severity"] in {"high", "medium", "low"}, r["id"]
        assert r["owner"] in owners, r["id"]
        assert all(k in r for k in CHECK_SETTINGS[r["check"]]), r["id"]
        if r["table"] == "all":
            continue
        names = [c for c, _ in contract[r["table"]]["columns"]]
        if r["check"] in ("pattern", "allowed_values", "range", "freshness"):
            assert r["column"] in names, r["id"]
        for c in r.get("columns", []):
            assert c in names, (r["id"], c)
        if r["check"] == "sql":
            assert "{db}." in r["sql"] and "record_key" in r["sql"], r["id"]


def test_every_silver_table_has_one_owner() -> None:
    rules = build_notebooks.load_dq_rules()
    assigned = [t for d in rules["domains"].values() for t in d["tables"]]
    assert sorted(assigned) == sorted(silver_contract.build())


def test_governance_documents_are_up_to_date() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_docs", build_notebooks.PROJECT_ROOT / "governance" / "build_docs.py"
    )
    build_docs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_docs)
    for name, text in build_docs.documents().items():
        saved = (build_notebooks.PROJECT_ROOT / "governance" / name).read_text(encoding="utf-8")
        assert saved == text, f"{name}: re-run python governance/build_docs.py"
    classified = build_docs.classification()
    contract = silver_contract.build()
    for table, field in classified:
        assert field in [c for c, _ in contract[table]["columns"]], (table, field)
