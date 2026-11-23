"""Extractors run in-process against the mock API (no server needed).

The mock is run with a high 429 rate so every test also exercises retries.
Big per-record tables are covered by the incremental test (a small delta) and by
test_extracted_csvs.py, which checks the output of a real full run.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from extract.http import ApiClient, auth_headers
from extract.run import Extractor, load_config, plan
from mock_api.app import create_app
from mock_api.config import Settings
from tests.conftest import REFERENCE

SMALL_TABLES = [
    "qube_staff",
    "qube_blocks",
    "qube_income_categories",
    "qube_landlord_bank_accounts",
    "fixflo_properties",
    "fixflo_contractors",
    "fixflo_blocks",
    "fixflo_agents",
    "engage_negotiators",
]
SINCE = "2026-11-15T00:00:00Z"


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config()


@pytest.fixture(scope="module")
def flaky_api(settings: Settings) -> Iterator[TestClient]:
    noisy = replace(settings, chaos=True, chaos_rate=0.1, chaos_seed=7)
    with TestClient(create_app(noisy)) as client:
        yield client


def make_extractor(config: dict, landing: Path, mode: str, api: TestClient) -> Extractor:
    env = {
        "MRI_CLIENT_ID": api.app.state.settings.mri_client_id,
        "MRI_DATABASE": api.app.state.settings.mri_database,
        "MRI_WEB_SERVICES_USER": api.app.state.settings.mri_user,
        "MRI_PARTNER_KEY": api.app.state.settings.mri_partner_key,
        "MRI_PASSWORD": api.app.state.settings.mri_password,
        "FIXFLO_API_TOKEN": api.app.state.settings.fixflo_token,
        "ENGAGE_API_TOKEN": api.app.state.settings.engage_token,
    }
    bases = {
        "qube": "http://testserver",
        "fixflo": "http://testserver/fixflo/api/v2",
        "engage": "http://testserver",
    }
    clients = {
        name: ApiClient(bases[name], auth_headers(cfg, env), http=api, sleep=lambda _s: None)
        for name, cfg in config["systems"].items()
    }
    return Extractor(config, landing, "2026-11-21", mode, workers=4, clients=clients, env=env)


def read_rows(path: Path) -> list[list[str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))


def test_full_pull_reproduces_reference_csvs_despite_429s(
    config: dict, flaky_api: TestClient, tmp_path: Path
) -> None:
    manifest = make_extractor(config, tmp_path, "full", flaky_api).run(plan(config, SMALL_TABLES))

    assert manifest["status"] == "succeeded"
    assert sum(t["rate_limited"] for t in manifest["tables"]) > 0, "429s should have happened"
    for table in manifest["tables"]:
        name = table["table"]
        produced = (tmp_path / "csv" / f"{name}.csv").read_bytes()
        assert produced == (REFERENCE / "extracts" / f"{name}.csv").read_bytes(), name
        assert table["rows"] == config["tables"][name]["expected_rows"]
        assert list((tmp_path / "json").rglob(f"{name}/2026-11-21/page_00001.json"))

    saved = json.loads((tmp_path / "_runs" / "latest.json").read_text())
    assert saved["run_id"] == manifest["run_id"]


def test_rerun_is_idempotent(config: dict, flaky_api: TestClient, tmp_path: Path) -> None:
    for _ in range(2):
        make_extractor(config, tmp_path, "full", flaky_api).run(["fixflo_properties"])
    raw = list((tmp_path / "json" / "fixflo" / "fixflo_properties" / "2026-11-21").iterdir())
    assert len(raw) == 40  # same page files, not doubled
    assert not list((tmp_path / "csv").glob("*.tmp"))


def test_incremental_pulls_only_changed_issues_and_their_children(
    config: dict, flaky_api: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "_watermarks.json").write_text(
        json.dumps({"fixflo_issues": {"column": "StatusChanged", "value": SINCE}})
    )
    tables = plan(config, ["fixflo_jobs", "fixflo_quotes", "fixflo_job_completion_details"])
    manifest = make_extractor(config, tmp_path, "incremental", flaky_api).run(tables)
    assert manifest["status"] == "succeeded"

    since = datetime.fromisoformat(SINCE)
    ref_issues = read_rows(REFERENCE / "extracts" / "fixflo_issues.csv")
    pos = ref_issues[0].index("StatusChanged")
    expected = [ref_issues[0]] + [
        r for r in ref_issues[1:] if r[pos] and datetime.fromisoformat(r[pos]) >= since
    ]
    assert read_rows(tmp_path / "csv" / "fixflo_issues.csv") == expected
    changed = {r[0] for r in expected[1:]}

    for name, key in [
        ("fixflo_jobs", "IssueId"),
        ("fixflo_quotes", "IssueId"),
        ("fixflo_job_completion_details", "IssueId"),
    ]:
        ref = read_rows(REFERENCE / "extracts" / f"{name}.csv")
        k = ref[0].index(key)
        want = [ref[0]] + [r for r in ref[1:] if r[k] in changed]
        assert read_rows(tmp_path / "csv" / f"{name}.csv") == want, name

    marks = json.loads((tmp_path / "_watermarks.json").read_text())
    newest = max(datetime.fromisoformat(r[pos]) for r in expected[1:])
    assert datetime.fromisoformat(marks["fixflo_issues"]["value"]) == newest
    loads = {t["table"]: t["load"] for t in manifest["tables"]}
    assert loads["fixflo_issues"] == f"incremental since {SINCE}"
