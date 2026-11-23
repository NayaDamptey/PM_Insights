"""How to fetch one table, by the ``fetch.method`` named in sources.yaml.

Every fetcher yields ``Fetched`` items *in source order*: one per API response,
holding the raw body and the records found in it. Calls that are made once per
parent (per tenancy, per issue...) run on a thread pool, but results are still
yielded in parent order, so the CSV rows come out in the same order every run.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from extract.http import ApiClient, RequestStats

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{([\w.]+)\}")


@dataclass
class Fetched:
    url: str
    body: Any
    records: list[dict[str, Any]]
    url_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchContext:
    client: ApiClient
    stats: RequestStats
    workers: int
    page_size: int
    since: str | None = None  # watermark for source-filtered (incremental) pulls
    parents: Sequence[Mapping[str, Any]] = ()  # captured parent fields, in order
    progress_every: int = 5000


def placeholders(template: str) -> list[str]:
    return _PLACEHOLDER.findall(template)


def fill(template: str, values: Mapping[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: quote(str(values[m.group(1)]), safe=""), template)


def _ordered_parallel(
    items: Sequence[Any], fn: Callable[[Any], list[Fetched]], ctx: FetchContext, label: str
) -> Iterator[Fetched]:
    """Run ``fn`` over items on a thread pool and yield results in item order.

    Work is submitted in chunks so a slow call never makes the whole result set
    pile up in memory.
    """
    chunk = ctx.progress_every
    with ThreadPoolExecutor(max_workers=ctx.workers) as pool:
        for start in range(0, len(items), chunk):
            for results in pool.map(fn, items[start : start + chunk]):
                yield from results
            if len(items) > chunk:
                log.info("  %s: %d / %d calls", label, min(start + chunk, len(items)), len(items))


def _follow(
    ctx: FetchContext,
    url: str,
    params: Mapping[str, Any] | None,
    records_key: str | None,
    next_key: str,
) -> list[Fetched]:
    """Follow a chain of pages until the next-link is empty."""
    out: list[Fetched] = []
    next_url: str | None = url
    while next_url:
        body = ctx.client.get(next_url, params=params, stats=ctx.stats)
        if body is None:  # 404: the parent has no such resource
            break
        records = body.get(records_key, []) if records_key else body
        out.append(Fetched(ctx.client.url(next_url), body, list(records)))
        next_url = body.get(next_key)
        params = None  # next links already carry every query parameter
    return out


# --- one function per fetch.method ------------------------------------------------------


def fetch_collection(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """MRI v1 collection: {"value": [...], "NextPageLink": ...}."""
    yield from _follow(ctx, cfg["path"], {"$top": ctx.page_size}, "value", "NextPageLink")


def fetch_mri_service(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """MRI API Services: {"NextPageLink": ..., "entry": [...]}, once or once per parent."""
    base = {"$api": cfg["api"], "$format": "json"}
    path = "/MRIAPIServices/api.asp"
    if "parent" not in cfg:
        yield from _follow(ctx, path, base, "entry", "NextPageLink")
        return

    def one(parent: Mapping[str, Any]) -> list[Fetched]:
        params = {**base, cfg["param"]: parent[cfg["parent_field"]]}
        return _follow(ctx, path, params, "entry", "NextPageLink")

    yield from _ordered_parallel(
        _unique_parents(ctx.parents, [cfg["parent_field"]]), one, ctx, cfg["api"]
    )


def fetch_fixflo_pager(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """FixFlo PrevNextPager of full objects (Property/Search)."""
    params = {cfg["page_param"]: 1, cfg["size_param"]: ctx.page_size}
    yield from _follow(ctx, cfg["path"], params, "Items", "NextURL")


def fetch_list(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """Plain JSON array (FixFlo /Contractors, /Blocks, /Agents)."""
    body = ctx.client.get(cfg["path"], stats=ctx.stats) or []
    yield Fetched(ctx.client.url(cfg["path"]), body, list(body))


def fetch_fixflo_issue_urls(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """/Issues pages list issue URLs (optionally since a watermark); each is then fetched."""
    params: dict[str, Any] = {cfg["page_param"]: 1}
    if ctx.since:
        params["UpdatedSince"] = ctx.since
    urls: list[str] = []
    for page in _follow(ctx, cfg["path"], params, "Items", "NextURL"):
        urls += page.records  # type: ignore[arg-type]  # Items are URL strings here
        yield Fetched(page.url, page.body, [])  # keep the URL pages in the raw landing
    log.info("  /Issues listed %d issue URLs", len(urls))

    def one(url: str) -> list[Fetched]:
        body = ctx.client.get(url, stats=ctx.stats)
        return [] if body is None else [Fetched(url, body, [body])]

    yield from _ordered_parallel(urls, one, ctx, "Issue")


def fetch_per_parent(cfg: Mapping[str, Any], ctx: FetchContext) -> Iterator[Fetched]:
    """One call (or one page chain) per parent record, e.g. /tenancies/{TenancyRef}/transactions."""
    template = cfg["path"]
    keys = placeholders(template)
    parents = _unique_parents(ctx.parents, keys)
    if cfg.get("only_if"):
        parents = [p for p in parents if p.get(f"has:{cfg['only_if']}")]
    kind = cfg["response"]

    def one(parent: Mapping[str, Any]) -> list[Fetched]:
        url_values = {k: parent[k] for k in keys}
        path = fill(template, url_values)
        if kind == "mri_v1":
            pages = _follow(ctx, path, {"$top": ctx.page_size}, "value", "NextPageLink")
        else:
            body = ctx.client.get(path, stats=ctx.stats)
            if body is None:
                return []
            pages = [Fetched(ctx.client.url(path), body, [body] if kind == "object" else body)]
        for page in pages:
            page.url_values = url_values
        return pages

    yield from _ordered_parallel(parents, one, ctx, template)


def _unique_parents(parents: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[Mapping]:
    """Drop parents whose ids repeat (a duplicated parent row must not fetch its children twice)
    and parents with an empty id."""
    seen: set[tuple[Any, ...]] = set()
    out: list[Mapping[str, Any]] = []
    dupes = 0
    for p in parents:
        ident = tuple(p.get(k) for k in keys)
        if any(v is None or v == "" for v in ident):
            continue
        if ident in seen:
            dupes += 1
            continue
        seen.add(ident)
        out.append(p)
    if dupes:
        log.warning("  %d duplicate parent ids skipped for %s", dupes, ", ".join(keys))
    return out


FETCHERS: dict[str, Callable[[Mapping[str, Any], FetchContext], Iterator[Fetched]]] = {
    "collection": fetch_collection,
    "mri_service": fetch_mri_service,
    "fixflo_pager": fetch_fixflo_pager,
    "list": fetch_list,
    "fixflo_issue_urls": fetch_fixflo_issue_urls,
    "per_parent": fetch_per_parent,
}
