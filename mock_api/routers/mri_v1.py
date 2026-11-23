"""Generic MRI v1 REST router, used for Qube PM and Engage CRM.

For each resource it serves:
  GET /{resource}                  collection, paged ({"value", "NextPageLink"})
  GET /{resource}/{id}             one record (404 if unknown)
  GET /{resource}/{id}/{child}     child records of that parent, paged

Qube and Engage only document get-by-id URLs, which assume you already know the
ids. The collection route is how a client discovers them; child routes then hang
off each parent id.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from mock_api.routers.common import json_response, mri_v1_page, not_found, table


@dataclass(frozen=True)
class Resource:
    table: str
    key: str


@dataclass(frozen=True)
class Child:
    table: str
    parent_key: str  # column in the child table that holds the parent id


def build_router(
    prefix: str,
    tag: str,
    resources: dict[str, Resource],
    children: dict[tuple[str, str], Child],
    auth: Callable[[Request], None],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag], dependencies=[Depends(auth)])

    def resource(name: str) -> Resource:
        res = resources.get(name)
        if res is None:
            raise not_found(f"Resource '{name}'")
        return res

    @router.get("/{resource_name}")
    def list_resource(resource_name: str, request: Request) -> JSONResponse:
        res = resource(resource_name)
        tbl = table(request, res.table)
        return mri_v1_page(request, tbl, range(len(tbl.rows)))

    @router.get("/{resource_name}/{key}")
    def get_one(resource_name: str, key: str, request: Request) -> JSONResponse:
        res = resource(resource_name)
        tbl = table(request, res.table)
        hits = tbl.rows_where(res.key, key)
        if not hits:
            raise not_found(f"{res.key} '{key}'")
        return json_response(tbl.record(hits[0]))

    @router.get("/{resource_name}/{key}/{child_name}")
    def get_children(
        resource_name: str, key: str, child_name: str, request: Request
    ) -> JSONResponse:
        res = resource(resource_name)
        child = children.get((resource_name, child_name))
        if child is None:
            raise not_found(f"Resource '{resource_name}/{{id}}/{child_name}'")
        if not table(request, res.table).rows_where(res.key, key):
            raise not_found(f"{res.key} '{key}'")
        ctbl = table(request, child.table)
        return mri_v1_page(request, ctbl, ctbl.rows_where(child.parent_key, key))

    return router
