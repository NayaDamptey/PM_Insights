"""Shared helpers: data access and paging styles."""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from mock_api.data import DataStore, Table


def store(request: Request) -> DataStore:
    return request.app.state.store


def table(request: Request, name: str) -> Table:
    return store(request).table(name)


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)


def int_param(request: Request, name: str, default: int, minimum: int = 0) -> int:
    raw = request.query_params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise bad_request(f"{name} must be an integer") from exc
    if value < minimum:
        raise bad_request(f"{name} must be >= {minimum}")
    return value


def json_response(content: Any) -> JSONResponse:
    return JSONResponse(content=content)


def records(
    tbl: Table, positions: Sequence[int], exclude: frozenset[str] = frozenset()
) -> list[dict[str, Any]]:
    return [tbl.record(i, exclude) for i in positions]


# --- MRI v1 style (Qube, Engage): {"value": [...], "NextPageLink": url|null} ---------

MRI_DEFAULT_TOP = 500
MRI_MAX_TOP = 1000


def mri_v1_page(request: Request, tbl: Table, positions: Sequence[int]) -> JSONResponse:
    """Page with ``$top``/``$skip``; ``$top`` is capped at the API limit."""
    top = min(int_param(request, "$top", MRI_DEFAULT_TOP, minimum=1), MRI_MAX_TOP)
    skip = int_param(request, "$skip", 0)
    page = positions[skip : skip + top]
    next_link = None
    if skip + top < len(positions):
        next_link = str(request.url.include_query_params(**{"$top": top, "$skip": skip + top}))
    return json_response({"value": records(tbl, page), "NextPageLink": next_link})


# --- MRI API Services style: {"NextPageLink": url, "entry": [...]} ------------------

MRI_SERVICES_PAGE_SIZE = 500


def encode_token(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode().rstrip("=")


def decode_token(token: str) -> int:
    try:
        padded = token + "=" * (-len(token) % 4)
        kind, _, value = base64.urlsafe_b64decode(padded).decode().partition(":")
        if kind != "o":
            raise ValueError(token)
        return int(value)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Paging token expired or invalid") from exc


# --- FixFlo PrevNextPager: TotalItems, TotalPages, Items, NextURL, PreviousURL ----------


def fixflo_pager(
    request: Request,
    items: list[Any],
    total: int,
    page: int,
    size: int,
    page_param: str,
) -> JSONResponse:
    total_pages = (total + size - 1) // size if total else 0
    next_url = prev_url = None
    if page < total_pages:
        next_url = str(request.url.include_query_params(**{page_param: page + 1}))
    if page > 1:
        prev_url = str(request.url.include_query_params(**{page_param: page - 1}))
    return json_response(
        {
            "TotalItems": total,
            "TotalPages": total_pages,
            "Items": items,
            "NextURL": next_url,
            "PreviousURL": prev_url,
        }
    )
