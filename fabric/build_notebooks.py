"""Write fabric/notebooks/<name>.ipynb from fabric/notebooks/src/<name>.py, ready to import.

    python -m fabric.build_notebooks

Some notebooks need things that only exist in this repo: the Silver contract (from the
data dictionary), the DQ rules (governance/dq_rules.yaml) and the model's measures
(powerbi/build_measures.py). Fabric can't read these, so they are written into the
notebook source as Python literals between marker lines:

    # --- generated: contract ---
    SILVER_CONTRACT = {...}
    # --- end generated ---

Running this refreshes those blocks first, then writes the .ipynb files. The .py
sources can be imported into Fabric as they are, too.
"""

from __future__ import annotations

import importlib.util
import pprint
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import nbformat
import yaml

from fabric import silver_contract
from fabric.notebook_source import NOTEBOOK_SRC, notebook_names, parse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = NOTEBOOK_SRC.parent
DQ_RULES_FILE = PROJECT_ROOT / "governance" / "dq_rules.yaml"

# Fabric runs .ipynb notebooks on its PySpark kernel when these are set.
FABRIC_METADATA = {
    "kernel_info": {"name": "synapse_pyspark"},
    "kernelspec": {
        "name": "synapse_pyspark",
        "display_name": "Synapse PySpark",
        "language": "Python",
    },
    "language_info": {"name": "python"},
    "microsoft": {"language": "python", "language_group": "synapse_pyspark"},
}


def load_dq_rules() -> dict[str, Any]:
    return yaml.safe_load(DQ_RULES_FILE.read_text(encoding="utf-8"))


# Measures renamed or retired since the model was first built; 06_model_measures deletes
# them so the model holds only what build_measures.py defines.
REMOVED_MEASURES = [
    ("fact_rent_transaction", "Revenue Charged"),
    ("fact_rent_transaction", "Revenue Charged FYTD"),
    ("fact_rent_transaction", "Revenue Charged LY"),
    ("fact_rent_transaction", "Avg Invoice Lag (days)"),
    ("fact_rent_transaction", "Net Cash Flow"),
    ("fact_rent_transaction", "Finance Insight"),
    ("fact_tenancy", "Homes Owned (year end)"),
    ("fact_tenancy", "Region Tenancy Rank"),
    ("fact_tenancy", "Property Insight"),
    ("fact_tenancy", "Avg Market Value"),
    ("fact_tenancy", "Gross Yield"),
    ("fact_tenancy", "Tenancy Journey (months)"),
    ("fact_tenancy", "Renewals"),
    ("fact_tenancy", "Tenancy Journey Rank"),
    ("fact_lettings_funnel", "Viewings"),
    ("fact_lettings_funnel", "Offers"),
    ("fact_lettings_funnel", "Achieved vs Asking %"),
    ("fact_lettings_funnel", "Rejected vs Accepted Offer %"),
    ("fact_lettings_funnel", "Avg Days Registration to Move-in"),
]


def load_model_measures() -> dict[str, Any]:
    """The report's measures from powerbi/build_measures.py, ready for semantic-link-labs."""
    spec = importlib.util.spec_from_file_location(
        "build_measures", PROJECT_ROOT / "powerbi" / "build_measures.py"
    )
    bm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bm)
    measures = [
        {
            "table": bm.HOME[folder],
            "name": name,
            "expression": dax.strip(),
            "format": fmt,
            "folder": folder,
            "description": desc,
            "data_category": "ImageUrl" if name in bm.IMAGE_MEASURES else "",
        }
        for folder, name, fmt, desc, dax in bm.MEASURES
    ]
    return {"measures": measures, "removed": REMOVED_MEASURES}


# block name -> (variable it defines, function returning its value)
GENERATED: dict[str, tuple[str, Callable[[], Any]]] = {
    "contract": ("SILVER_CONTRACT", silver_contract.build),
    "dq_rules": ("DQ_RULES", load_dq_rules),
    "measures": ("MODEL_MEASURES", load_model_measures),
}
_BLOCK = re.compile(r"# --- generated: (\w+) ---\n.*?# --- end generated ---", re.S)


def render_block(name: str) -> str:
    variable, value = GENERATED[name]
    body = pprint.pformat(value(), width=95, sort_dicts=False)
    return f"# --- generated: {name} ---\n{variable} = {body}\n# --- end generated ---"


def refresh_generated(path: Path) -> bool:
    """Rewrite the generated blocks in one notebook source. True if anything changed."""
    text = path.read_text(encoding="utf-8")
    new = _BLOCK.sub(lambda m: render_block(m.group(1)), text)
    if new != text:
        path.write_text(new, encoding="utf-8")
    return new != text


def build(name: str) -> str:
    nb = nbformat.v4.new_notebook(metadata=FABRIC_METADATA)
    for cell in parse(NOTEBOOK_SRC / f"{name}.py"):
        if cell.kind == "markdown":
            nb.cells.append(nbformat.v4.new_markdown_cell(cell.source))
        else:
            # "parameters" is the tag Fabric (and pipelines) use to find overridable values.
            meta = {"tags": cell.tags} if cell.tags else {}
            nb.cells.append(nbformat.v4.new_code_cell(cell.source, metadata=meta))
    # Stable ids keep the generated files identical between builds.
    for i, c in enumerate(nb.cells):
        c["id"] = f"{name}-{i:02d}"
    path = OUT_DIR / f"{name}.ipynb"
    nbformat.write(nb, str(path))
    return str(path)


def main() -> None:
    for name in notebook_names():
        if refresh_generated(NOTEBOOK_SRC / f"{name}.py"):
            print("refreshed generated blocks in", name)
        print("wrote", build(name))


if __name__ == "__main__":
    main()
