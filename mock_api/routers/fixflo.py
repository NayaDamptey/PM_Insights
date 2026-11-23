"""FixFlo API v2. Live base: https://{subdomain}.fixflo.com/api/v2

Only the endpoints the extractors call are implemented. Note the two paging styles:
/Issues uses ``page`` and returns issue URLs, /Property/Search uses ``pg``/``pgsz``
and returns full objects.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from mock_api.auth import require_fixflo_bearer
from mock_api.data import Table
from mock_api.routers.common import (
    bad_request,
    fixflo_pager,
    int_param,
    json_response,
    not_found,
    records,
    table,
)

PREFIX = "/fixflo/api/v2"
ISSUES_PAGE_SIZE = 100  # sample: 56,756 issues over 568 pages
PROPERTY_DEFAULT_PGSZ = 50  # sample: 3,935 properties over 79 pages
PROPERTY_MAX_PGSZ = 100

router = APIRouter(prefix=PREFIX, tags=["FixFlo"], dependencies=[Depends(require_fixflo_bearer)])

_status_changed_cache: dict[int, list[datetime | None]] = {}
_filter_cache: dict[tuple[int, datetime | None], list[int]] = {}
_cache_lock = threading.Lock()


def parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.strip().replace(" ", "+"))
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _status_changed(issues: Table) -> list[datetime | None]:
    key = id(issues)
    cached = _status_changed_cache.get(key)
    if cached is None:
        pos = issues.col("StatusChanged")
        cached = [parse_utc(r[pos]) if r[pos] else None for r in issues.rows]
        _status_changed_cache[key] = cached
    return cached


def _issue_positions(issues: Table, since: datetime | None) -> list[int]:
    """Issues in created (Id) order, optionally with StatusChanged >= since."""
    key = (id(issues), since)
    with _cache_lock:
        hit = _filter_cache.get(key)
        if hit is None:
            if since is None:
                hit = list(range(len(issues.rows)))
            else:
                changed = _status_changed(issues)
                hit = [i for i, ts in enumerate(changed) if ts is not None and ts >= since]
            if len(_filter_cache) > 64:
                _filter_cache.clear()
            _filter_cache[key] = hit
    return hit


def _one(tbl: Table, column: str, value: str, what: str) -> int:
    hits = tbl.rows_where(column, value)
    if not hits:
        raise not_found(f"{what} '{value}'")
    return hits[0]


@router.get("/Issues")
def list_issues(request: Request) -> JSONResponse:
    """PrevNextPager of issue URLs. ``UpdatedSince`` filters on status change (UTC)."""
    since_raw = request.query_params.get("UpdatedSince")
    try:
        since = parse_utc(since_raw) if since_raw else None
    except ValueError as exc:
        raise bad_request("UpdatedSince must be an ISO 8601 date time") from exc
    page = int_param(request, "page", 1, minimum=1)
    issues = table(request, "fixflo_issues")
    positions = _issue_positions(issues, since)
    start = (page - 1) * ISSUES_PAGE_SIZE
    id_col = issues.col("Id")
    base = str(request.url).split("/Issues")[0]
    items = [
        f"{base}/Issue/{issues.rows[i][id_col]}"
        for i in positions[start : start + ISSUES_PAGE_SIZE]
    ]
    return fixflo_pager(request, items, len(positions), page, ISSUES_PAGE_SIZE, "page")


@router.get("/Issue/{issue_id}")
def get_issue(issue_id: str, request: Request) -> JSONResponse:
    issues = table(request, "fixflo_issues")
    return json_response(issues.record(_one(issues, "Id", issue_id, "Issue")))


@router.get("/Issue/{issue_id}/quotes")
def get_issue_quotes(issue_id: str, request: Request) -> JSONResponse:
    _one(table(request, "fixflo_issues"), "Id", issue_id, "Issue")
    quotes = table(request, "fixflo_quotes")
    # The real response has no IssueId; the extractor adds it from the URL.
    return json_response(
        records(quotes, quotes.rows_where("IssueId", issue_id), exclude=frozenset({"IssueId"}))
    )


@router.get("/Issue/{issue_id}/jobcompletiondetails")
def get_job_completion(issue_id: str, request: Request) -> JSONResponse:
    _one(table(request, "fixflo_issues"), "Id", issue_id, "Issue")
    details = table(request, "fixflo_job_completion_details")
    hits = details.rows_where("IssueId", issue_id)
    if not hits:
        raise not_found(f"Job completion details for issue '{issue_id}'")
    return json_response(details.record(hits[0]))


@router.get("/Job/{job_id}")
def get_job(job_id: str, request: Request) -> JSONResponse:
    jobs = table(request, "fixflo_jobs")
    return json_response(jobs.record(_one(jobs, "id", job_id, "Job")))


@router.get("/Property/Search")
def search_properties(request: Request) -> JSONResponse:
    """PrevNextPager of Property objects; ``pg`` (page) and ``pgsz`` (capped at 100)."""
    page = int_param(request, "pg", 1, minimum=1)
    size = min(int_param(request, "pgsz", PROPERTY_DEFAULT_PGSZ, minimum=1), PROPERTY_MAX_PGSZ)
    props = table(request, "fixflo_properties")
    total = len(props.rows)
    start = (page - 1) * size
    items = records(props, range(start, min(start + size, total)))
    return fixflo_pager(request, items, total, page, size, "pg")


@router.get("/Property")
def get_property(request: Request) -> JSONResponse:
    props = table(request, "fixflo_properties")
    params = request.query_params
    if "Id" in params:
        return json_response(props.record(_one(props, "id", params["Id"], "Property")))
    if "ExternalPropertyRef" in params:
        ref = params["ExternalPropertyRef"]
        return json_response(props.record(_one(props, "ExternalPropertyRef", ref, "Property")))
    raise HTTPException(status_code=400, detail="Id or ExternalPropertyRef is required")


def _all(request: Request, name: str) -> JSONResponse:
    tbl = table(request, name)
    return json_response(records(tbl, range(len(tbl.rows))))


@router.get("/Contractors")
def list_contractors(request: Request) -> JSONResponse:
    return _all(request, "fixflo_contractors")


@router.get("/Contractor/{contractor_id}")
def get_contractor(contractor_id: str, request: Request) -> JSONResponse:
    tbl = table(request, "fixflo_contractors")
    return json_response(tbl.record(_one(tbl, "Id", contractor_id, "Contractor")))


@router.get("/Blocks")
def list_blocks(request: Request) -> JSONResponse:
    return _all(request, "fixflo_blocks")


@router.get("/Block")
def get_block(request: Request) -> JSONResponse:
    tbl = table(request, "fixflo_blocks")
    block_id = request.query_params.get("Id")
    if not block_id:
        raise bad_request("Id is required")
    return json_response(tbl.record(_one(tbl, "Id", block_id, "Block")))


@router.get("/Agents")
def list_agents(request: Request) -> JSONResponse:
    return _all(request, "fixflo_agents")


@router.get("/Agent")
def get_agent(request: Request) -> JSONResponse:
    tbl = table(request, "fixflo_agents")
    agent_id = request.query_params.get("Id")
    if not agent_id:
        raise bad_request("Id is required")
    return json_response(tbl.record(_one(tbl, "Id", agent_id, "Agent")))
