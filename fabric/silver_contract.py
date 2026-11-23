"""The Silver contract (tables, columns, types, keys, links) taken from the data dictionary.

The notebooks run in Fabric, where the dictionary isn't available, so build_notebooks.py
writes this contract into them as a Python literal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from extract.build_config import DEFAULT_DICTIONARY

# The dictionary marks only tenancy_ref as the key of silver_tenancy_tenant, but a joint
# tenancy has one row per tenant, so the row is identified by tenancy and tenant together.
KEY_OVERRIDES = {"silver_tenancy_tenant": ["tenancy_ref", "tenant_ref"]}


def build(dictionary: Path = DEFAULT_DICTIONARY) -> dict[str, dict[str, Any]]:
    """{table: {"key", "source_system", "source_table", "columns", "foreign_keys"}}.

    columns: [(name, type), ...]; foreign_keys: [(column, referenced_table), ...]
    """
    tables = pd.read_excel(dictionary, sheet_name="Tables", dtype=str)
    tables = tables[tables["Layer"] == "Silver"].set_index("Table")
    fields = pd.read_excel(dictionary, sheet_name="Fields", dtype=str)
    silver = fields[fields["Layer"] == "Silver"]
    contract: dict[str, dict[str, Any]] = {}
    for table, rows in silver.groupby("Table", sort=False):
        names = rows["Field"].tolist()
        types = rows["Data type"].str.strip().str.upper().tolist()
        keys = rows["Key"].fillna("").str.strip().tolist()
        contract[table] = {
            "key": KEY_OVERRIDES.get(
                table, [n for n, k in zip(names, keys, strict=True) if k == "PK"]
            ),
            "source_system": tables.loc[table, "System"],
            "source_table": tables.loc[table, "Source endpoint / built from"],
            "columns": list(zip(names, types, strict=True)),
            "foreign_keys": [
                (n, k.split("->")[1].strip())
                for n, k in zip(names, keys, strict=True)
                if k.startswith("FK")
            ],
        }
    return contract
