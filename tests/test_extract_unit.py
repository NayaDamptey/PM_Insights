"""Extractor building blocks: HTTP retries, flattening, config generation, run planning."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from extract.build_config import DEFAULT_DICTIONARY, build
from extract.fetchers import FETCHERS, fill
from extract.flatten import flatten, get_path, render
from extract.http import ApiClient, ApiError, RequestStats, auth_headers, retry_after_seconds
from extract.run import later_of, load_config, plan
from tests.conftest import read_reference

# --- HTTP client -------------------------------------------------------------------------


def scripted_client(responses: list[httpx.Response | Exception]) -> tuple[ApiClient, list[float]]:
    """ApiClient whose transport replays ``responses`` in order and records sleeps."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    sleeps: list[float] = []
    client = ApiClient(
        "http://api.test",
        {"Authorization": "Bearer x"},
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    )
    return client, sleeps


def test_429_waits_for_retry_after_then_succeeds() -> None:
    client, sleeps = scripted_client(
        [httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"ok": 1})]
    )
    stats = RequestStats()
    assert client.get("/x", stats=stats) == {"ok": 1}
    assert sleeps == [3.0]
    assert stats.as_dict() == {"requests": 2, "retries": 1, "rate_limited": 1, "not_found": 0}


def test_server_errors_and_timeouts_back_off_exponentially() -> None:
    client, sleeps = scripted_client(
        [
            httpx.Response(503),
            httpx.ReadTimeout("slow"),
            httpx.Response(502),
            httpx.Response(200, json=[1]),
        ]
    )
    assert client.get("/x") == [1]
    # 0.5, 1, 2 seconds, each with +/-20% jitter
    for wait, base in zip(sleeps, [0.5, 1.0, 2.0], strict=True):
        assert base * 0.8 <= wait <= base * 1.2


def test_gives_up_after_max_attempts() -> None:
    client, _ = scripted_client([httpx.Response(503)] * 6)
    with pytest.raises(ApiError) as err:
        client.get("/x")
    assert err.value.status == 503


def test_404_returns_none_and_401_fails_fast() -> None:
    client, sleeps = scripted_client([httpx.Response(404), httpx.Response(401, text="no")])
    assert client.get("/missing") is None
    with pytest.raises(ApiError):
        client.get("/secret")
    assert sleeps == []


def test_retry_after_accepts_http_dates() -> None:
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    assert 8 <= retry_after_seconds(when, default=1) <= 10
    assert retry_after_seconds("nonsense", default=1.5) == 1.5


def test_absolute_paging_links_are_used_as_is() -> None:
    client, _ = scripted_client([])
    assert client.url("/a") == "http://api.test/a"
    assert client.url("https://other/b?x=1") == "https://other/b?x=1"


def test_auth_headers_from_env() -> None:
    env = {
        "MRI_CLIENT_ID": "c",
        "MRI_DATABASE": "d",
        "MRI_WEB_SERVICES_USER": "u",
        "MRI_PARTNER_KEY": "k",
        "MRI_PASSWORD": "p",
        "TOK": "t",
    }
    assert auth_headers({"auth": "mri_basic"}, env) == {"Authorization": "Basic Yy9kL3Uvazpw"}
    assert auth_headers({"auth": "bearer", "token_env": "TOK"}, env) == {
        "Authorization": "Bearer t"
    }
    with pytest.raises(RuntimeError):
        auth_headers({"auth": "bearer", "token_env": "MISSING"}, env)


# --- flattening ------------------------------------------------------------------------


def test_render_rules() -> None:
    assert render(None) == ""
    assert render(True) == "true"
    assert render(3) == "3"
    assert render(10.0) == "10.0"
    assert render([{"a": 1, "b": "é"}]) == '[{"a":1,"b":"é"}]'
    assert render("x") == "x"


def test_flatten_nested_paths_null_objects_and_url_values() -> None:
    record = {"id": "Q1", "Contractor": {"Id": 5, "Address": None}}
    columns = [
        {"name": "IssueId", "from_url": "Id"},
        {"name": "id", "path": "id"},
        {"name": "Contractor.Id", "path": "Contractor.Id"},
        {"name": "Contractor.Address.Town", "path": "Contractor.Address.Town"},
    ]
    assert flatten(record, columns, {"Id": "FFI1"}) == ["FFI1", "Q1", "5", ""]
    assert get_path(record, "missing.deeper") is None


def test_url_ids_are_escaped() -> None:
    assert fill("/Issue/{Id}/quotes", {"Id": "A B/1"}) == "/Issue/A%20B%2F1/quotes"


def test_watermark_ignores_unparseable_dates() -> None:
    assert later_of(None, "2025-01-01T00:00:00Z") == "2025-01-01T00:00:00Z"
    assert later_of("2025-01-01T00:00:00Z", "not a date") == "2025-01-01T00:00:00Z"
    assert later_of("2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z") == "2025-02-01T00:00:00Z"
    assert later_of("2025-02-01T00:00:00Z", "") == "2025-02-01T00:00:00Z"


# --- config -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config() -> dict:
    return load_config()


@pytest.mark.skipif(not DEFAULT_DICTIONARY.exists(), reason="data dictionary not found")
def test_sources_yaml_is_up_to_date_with_the_dictionary(config: dict) -> None:
    assert build(DEFAULT_DICTIONARY) == config, "re-run: python -m extract.build_config"


def test_config_columns_match_reference_headers(config: dict) -> None:
    for name, table in config["tables"].items():
        if table["fetch"]["method"] == "none":
            continue
        header, _ = read_reference(name)
        assert [c["name"] for c in table["columns"]] == header, name
        assert table["fetch"]["method"] in FETCHERS, name


def test_plan_pulls_parents_first(config: dict) -> None:
    assert plan(config, ["fixflo_jobs"]) == ["fixflo_issues", "fixflo_jobs"]
    assert plan(config, ["qube_transactions", "qube_staff"]) == [
        "qube_staff",
        "qube_tenancies",
        "qube_transactions",
    ]
    with pytest.raises(SystemExit):
        plan(config, ["nope"])
