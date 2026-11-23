"""MRI API Services: /MRIAPIServices/api.asp?$api=[APIName]&$format=json

Paging follows the MRI guide: ``NextPageLink`` sits at the top of each page and
is called with the same headers. Records are in ``entry`` (as in the samples).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from mock_api.auth import require_mri_basic
from mock_api.routers.common import (
    MRI_SERVICES_PAGE_SIZE,
    decode_token,
    encode_token,
    json_response,
    records,
    table,
)


@dataclass(frozen=True)
class ServiceApi:
    table: str
    filters: dict[str, str]  # query parameter -> column
    always_next_link: bool  # resident-contact sample shows "NextPageLink": null


APIS = {
    "resident-contact": ServiceApi(
        "qube_resident_contact", {"RMPROPID": "PropertyId"}, always_next_link=True
    ),
    "income-categories": ServiceApi("qube_income_categories", {}, always_next_link=False),
}

router = APIRouter(tags=["MRI API Services"], dependencies=[Depends(require_mri_basic)])


@router.get("/MRIAPIServices/api.asp")
def api_asp(request: Request) -> JSONResponse:
    params = request.query_params
    name = params.get("$api")
    if not name:
        raise HTTPException(status_code=400, detail="Missing $api")
    wants_json = params.get("$format", "").lower() == "json" or "application/json" in (
        request.headers.get("Accept", "")
    )
    if not wants_json:
        raise HTTPException(status_code=406, detail="Only $format=json is supported by the mock")
    api = APIS.get(name)
    if api is None:
        raise HTTPException(status_code=404, detail=f"API '{name}' not found")

    tbl = table(request, api.table)
    positions: list[int] | range = range(len(tbl.rows))
    for param, column in api.filters.items():
        value = params.get(param)
        if value is not None:
            positions = tbl.rows_where(column, value)

    offset = decode_token(params["$pagetoken"]) if "$pagetoken" in params else 0
    page = positions[offset : offset + MRI_SERVICES_PAGE_SIZE]
    body: dict[str, object] = {}
    if offset + MRI_SERVICES_PAGE_SIZE < len(positions):
        token = encode_token(offset + MRI_SERVICES_PAGE_SIZE)
        body["NextPageLink"] = str(request.url.include_query_params(**{"$pagetoken": token}))
    elif api.always_next_link:
        body["NextPageLink"] = None
    body["entry"] = records(tbl, page)
    return json_response(body)
