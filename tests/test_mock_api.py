"""Mock API contract: auth, paging, errors and sample shapes match the vendor APIs,
and every record served can be flattened back to its exact reference CSV row.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from extract.flatten import get_path, render
from mock_api.app import create_app
from mock_api.config import Settings
from mock_api.data import DataStore
from tests.conftest import REFERENCE, read_reference, sample

FIXFLO = "/fixflo/api/v2"
QUBE = "/qube/api/v1"
ENGAGE = "/engage/api/v1"
MRI_SVC = "/MRIAPIServices/api.asp"


def follow_v1(client: TestClient, url: str, headers: dict[str, str]) -> tuple[list[Any], int]:
    rows: list[Any] = []
    pages = 0
    next_url: str | None = url
    while next_url:
        r = client.get(next_url, headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert list(body) == ["value", "NextPageLink"]
        rows += body["value"]
        next_url = body["NextPageLink"]
        pages += 1
    return rows, pages


# --- auth -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        f"{QUBE}/staff",
        f"{MRI_SVC}?$api=income-categories&$format=json",
        f"{FIXFLO}/Agents",
        f"{ENGAGE}/negotiators",
    ],
)
def test_requests_without_auth_are_rejected(client: TestClient, url: str) -> None:
    r = client.get(url)
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers


def test_wrong_credentials_are_rejected(client: TestClient) -> None:
    assert (
        client.get(f"{QUBE}/staff", headers={"Authorization": "Basic Zm9vOmJhcg=="}).status_code
        == 401
    )
    assert (
        client.get(f"{FIXFLO}/Agents", headers={"Authorization": "Bearer nope"}).status_code == 401
    )
    assert (
        client.get(f"{ENGAGE}/negotiators", headers={"Authorization": "Bearer nope"}).status_code
        == 401
    )


def test_health_needs_no_auth(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


# --- MRI v1 (Qube, Engage) ----------------------------------------------------------


def test_qube_collection_paging_returns_every_row(client: TestClient, mri_auth: dict) -> None:
    rows, pages = follow_v1(client, f"{QUBE}/staff?$top=50", mri_auth)
    _, ref = read_reference("qube_staff")
    assert len(rows) == len(ref) == 148
    assert pages == 3
    assert [r["StaffCode"] for r in rows] == [r[0] for r in ref]


def test_qube_page_size_is_capped(client: TestClient, mri_auth: dict) -> None:
    body = client.get(f"{QUBE}/properties?$top=5000", headers=mri_auth).json()
    assert len(body["value"]) == 1000
    assert "%24skip=1000" in body["NextPageLink"] or "$skip=1000" in body["NextPageLink"]


def test_qube_get_by_id_and_404(client: TestClient, mri_auth: dict) -> None:
    r = client.get(f"{QUBE}/staff/PM001", headers=mri_auth)
    assert r.status_code == 200 and r.json()["StaffCode"] == "PM001"
    assert client.get(f"{QUBE}/staff/NOPE", headers=mri_auth).status_code == 404
    assert client.get(f"{QUBE}/nothing", headers=mri_auth).status_code == 404


def test_qube_child_endpoint_returns_that_parents_rows(client: TestClient, mri_auth: dict) -> None:
    header, ref = read_reference("qube_transactions")
    tenancy = ref[0][header.index("TenancyRef")]
    expected = [r for r in ref if r[header.index("TenancyRef")] == tenancy]
    rows, _ = follow_v1(client, f"{QUBE}/tenancies/{tenancy}/transactions?$top=10", mri_auth)
    assert [r["TransactionId"] for r in rows] == [r[0] for r in expected]
    assert client.get(f"{QUBE}/tenancies/NOPE/transactions", headers=mri_auth).status_code == 404


def test_engage_listing_children(client: TestClient, engage_auth: dict) -> None:
    header, ref = read_reference("engage_viewings")
    listing = ref[0][header.index("ListingId")]
    expected = sum(1 for r in ref if r[header.index("ListingId")] == listing)
    rows, _ = follow_v1(client, f"{ENGAGE}/listings/{listing}/viewings", engage_auth)
    assert len(rows) == expected
    assert client.get(f"{ENGAGE}/listings/NOPE/offers", headers=engage_auth).status_code == 404


# --- MRI API Services -----------------------------------------------------------------


def test_income_categories_match_sample(client: TestClient, mri_auth: dict) -> None:
    r = client.get(f"{MRI_SVC}?$api=income-categories&$format=json", headers=mri_auth)
    assert r.json() == json.loads(sample("mri/GET_income-categories.json").read_text())


def test_resident_contact_shape_and_paging(client: TestClient, mri_auth: dict) -> None:
    body = client.get(
        f"{MRI_SVC}?$api=resident-contact&RMPROPID=QP000001&$format=json", headers=mri_auth
    ).json()
    smp = json.loads(sample("mri/GET_resident-contact_RMPROPID_QP000001.json").read_text())
    assert list(body) == list(smp) == ["NextPageLink", "entry"]
    assert list(body["entry"][0]) == list(smp["entry"][0])
    assert all(e["PropertyId"] == "QP000001" for e in body["entry"])

    # Unfiltered: follow NextPageLink across pages.
    seen, url = 0, f"{MRI_SVC}?$api=resident-contact&$format=json"
    while url:
        page = client.get(url, headers=mri_auth).json()
        seen += len(page["entry"])
        url = page["NextPageLink"]
    assert seen == len(read_reference("qube_resident_contact")[1])


def test_mri_services_errors(client: TestClient, mri_auth: dict) -> None:
    assert client.get(f"{MRI_SVC}?$api=income-categories", headers=mri_auth).status_code == 406
    assert client.get(f"{MRI_SVC}?$api=nope&$format=json", headers=mri_auth).status_code == 404
    assert client.get(f"{MRI_SVC}?$format=json", headers=mri_auth).status_code == 400


# --- FixFlo ---------------------------------------------------------------------------


def _shape(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _shape(v) for k, v in obj.items()}
    return None


@pytest.mark.parametrize(
    ("rel", "url", "exact"),
    [
        ("fixflo/GET_Agents.json", "/Agents", True),
        ("fixflo/GET_Issue_FFI500051_AwaitingJobCompletion.json", "/Issue/FFI500051", True),
        ("fixflo/GET_Issue_FFI501661_Reported.json", "/Issue/FFI501661", True),
        ("fixflo/GET_Issue_FFI500044_Closed.json", "/Issue/FFI500044", False),
        (
            "fixflo/GET_Issue_FFI500001_jobcompletiondetails.json",
            "/Issue/FFI500001/jobcompletiondetails",
            True,
        ),
        ("fixflo/GET_Issue_FFI500002_quotes.json", "/Issue/FFI500002/quotes", True),
        ("fixflo/GET_Job_J800033.json", "/Job/J800033", True),
        ("fixflo/GET_Job_J800028.json", "/Job/J800028", False),
    ],
)
def test_fixflo_responses_match_samples(
    client: TestClient, fixflo_auth: dict, rel: str, url: str, exact: bool
) -> None:
    smp = json.loads(sample(rel).read_text(encoding="utf-8"))
    body = client.get(f"{FIXFLO}{url}", headers=fixflo_auth).json()
    if exact:
        assert body == smp
    else:
        # Money that is a float in this sample is text in the extract ("96.10"), so it is
        # served as a string to stay lossless. Structure must still match.
        first = (lambda x: x[0]) if isinstance(smp, list) else (lambda x: x)
        assert _shape(first(body)) == _shape(first(smp))


@pytest.mark.parametrize(
    ("rel", "url"),
    [("fixflo/GET_Blocks.json", "/Blocks"), ("fixflo/GET_Contractors.json", "/Contractors")],
)
def test_fixflo_lists_start_with_sample_items(
    client: TestClient, fixflo_auth: dict, rel: str, url: str
) -> None:
    smp = json.loads(sample(rel).read_text(encoding="utf-8"))
    body = client.get(f"{FIXFLO}{url}", headers=fixflo_auth).json()
    assert body[: len(smp)] == smp  # samples are cut to the first 20 items


def test_fixflo_issues_pager_returns_urls(client: TestClient, fixflo_auth: dict) -> None:
    smp = json.loads(sample("fixflo/GET_Issues_page1.json").read_text())
    body = client.get(f"{FIXFLO}/Issues?page=1", headers=fixflo_auth).json()
    assert list(body) == ["TotalItems", "TotalPages", "Items", "NextURL", "PreviousURL"]
    assert (body["TotalItems"], body["TotalPages"]) == (smp["TotalItems"], smp["TotalPages"])
    assert [u.rsplit("/", 1)[1] for u in body["Items"]] == [
        u.rsplit("/", 1)[1] for u in smp["Items"]
    ]
    assert body["PreviousURL"] is None and body["NextURL"].endswith("page=2")
    # Each URL can be fetched as is.
    issue = client.get(body["Items"][0], headers=fixflo_auth).json()
    assert issue["Id"] == "FFI500001"


def test_fixflo_updated_since_filters_on_status_changed(
    client: TestClient, fixflo_auth: dict
) -> None:
    header, ref = read_reference("fixflo_issues")
    pos = header.index("StatusChanged")
    since = datetime(2026, 9, 1, tzinfo=UTC)
    expected = [r[0] for r in ref if r[pos] and datetime.fromisoformat(r[pos]) >= since]
    got: list[str] = []
    url: str | None = f"{FIXFLO}/Issues?UpdatedSince=2026-09-01T00:00:00Z"
    while url:
        body = client.get(url, headers=fixflo_auth).json()
        got += [u.rsplit("/", 1)[1] for u in body["Items"]]
        url = body["NextURL"]
    assert got == expected and 0 < len(got) < len(ref)
    bad = client.get(f"{FIXFLO}/Issues?UpdatedSince=yesterday", headers=fixflo_auth)
    assert bad.status_code == 400


def test_fixflo_property_search_paging(client: TestClient, fixflo_auth: dict) -> None:
    smp = json.loads(sample("fixflo/GET_Property_Search_pg1.json").read_text())
    body = client.get(f"{FIXFLO}/Property/Search?pg=1", headers=fixflo_auth).json()
    assert (body["TotalItems"], body["TotalPages"]) == (smp["TotalItems"], smp["TotalPages"])
    assert body["Items"] == smp["Items"]
    capped = client.get(f"{FIXFLO}/Property/Search?pg=1&pgsz=500", headers=fixflo_auth).json()
    assert len(capped["Items"]) == 100 and capped["TotalPages"] == 40
    one = client.get(f"{FIXFLO}/Property?ExternalPropertyRef=QP000001", headers=fixflo_auth)
    assert one.json()["id"] == 200001


def test_fixflo_404s(client: TestClient, fixflo_auth: dict) -> None:
    for url in [
        "/Issue/NOPE",
        "/Issue/NOPE/quotes",
        "/Job/NOPE",
        "/Contractor/NOPE",
        "/Property?Id=1",
        "/Block?Id=1",
        "/Agent?Id=1",
    ]:
        assert client.get(f"{FIXFLO}{url}", headers=fixflo_auth).status_code == 404, url


# --- rate limiting --------------------------------------------------------------------


def test_rate_limit_returns_429_with_retry_after(settings: Settings) -> None:
    noisy = replace(settings, chaos=True, chaos_rate=1.0, retry_after_seconds=2)
    with TestClient(create_app(noisy)) as c:
        r = c.get(f"{FIXFLO}/Agents")
        assert r.status_code == 429 and r.headers["Retry-After"] == "2"
        assert c.get("/health").status_code == 200


# --- lossless round trip ------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    sorted(p.stem for p in (REFERENCE / "extracts").glob("*.csv") if p.stem != "dim_calendar"),
)
def test_every_record_round_trips_to_the_reference_csv(table: str) -> None:
    """Serving a row as JSON and flattening it back with the extractor's own rules
    gives the exact CSV text."""
    tbl = DataStore(REFERENCE).table(table)
    for i, row in enumerate(tbl.rows):
        rec = json.loads(json.dumps(tbl.record(i)))  # through real JSON text
        assert [render(get_path(rec, c)) for c in tbl.columns] == list(row), (table, i)
