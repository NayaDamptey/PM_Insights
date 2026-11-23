"""Pull source tables from the APIs into ``data/landing``.

    python -m extract.run --all                       # full pull of every table
    python -m extract.run --all --mode incremental    # FixFlo issues since last watermark
    python -m extract.run --tables qube_staff fixflo_jobs

What happens per table:
1. Pick the fetcher named in config/sources.yaml and page through the API.
2. Save every raw response under landing/json/<system>/<table>/<run_date>/.
3. Flatten each record with the column paths from the config and write
   landing/csv/<table>.csv in the dictionary's column order.
4. Remember the ids its child tables need (e.g. TenancyRef for transactions).
5. Record rows, pages, requests, retries and timings in the run manifest, and move
   the watermark forward if the table has a change-time column.

A child table needs its parent's ids, so asking for a child also pulls its parent.
If a table fails, the run carries on with the others; its children are skipped and
the command exits with status 1.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from extract.fetchers import FETCHERS, FetchContext, placeholders
from extract.flatten import flatten, get_path
from extract.http import ApiClient, RequestStats, auth_headers
from extract.landing import (
    CsvSink,
    RawWriter,
    Watermarks,
    now_iso,
    parse_ts,
    write_manifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "sources.yaml"
DEFAULT_LANDING = PROJECT_ROOT / "data" / "landing"

# Per-record endpoints are bundled into raw files of this many responses.
RAW_BUNDLE = 500

log = logging.getLogger("extract")


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def plan(config: Mapping[str, Any], requested: Sequence[str]) -> list[str]:
    """Requested tables plus any parents they need, parents first, in dictionary order."""
    tables = config["tables"]
    unknown = [t for t in requested if t not in tables]
    if unknown:
        raise SystemExit(f"unknown table(s): {', '.join(unknown)}")
    needed: set[str] = set()

    def add(name: str) -> None:
        if name in needed:
            return
        needed.add(name)
        parent = tables[name]["fetch"].get("parent")
        if parent:
            add(parent)

    for name in requested:
        add(name)
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in ordered:
            return
        parent = tables[name]["fetch"].get("parent")
        if parent:
            visit(parent)
        ordered.append(name)

    for name in tables:  # dictionary order, parents pulled forward
        if name in needed:
            visit(name)
    return ordered


def later_of(current: str | None, candidate: str) -> str | None:
    """Keep the later timestamp. Values that are not valid timestamps are ignored here
    (the data is landed untouched; the DQ checks report bad dates later)."""
    if not candidate:
        return current
    try:
        cand = parse_ts(candidate)
    except ValueError:
        return current
    if current is None or cand > parse_ts(current):
        return candidate
    return current


def capture_fields(config: Mapping[str, Any], table: str) -> tuple[list[str], list[str]]:
    """Fields of ``table`` that its child tables need: url ids, and only_if flags."""
    ids: list[str] = []
    flags: list[str] = []
    for child in config["tables"].values():
        fetch = child["fetch"]
        if fetch.get("parent") != table:
            continue
        if fetch["method"] == "per_parent":
            ids += placeholders(fetch["path"])
        else:
            ids.append(fetch["parent_field"])
        if fetch.get("only_if"):
            flags.append(fetch["only_if"])
    return list(dict.fromkeys(ids)), list(dict.fromkeys(flags))


class Extractor:
    def __init__(
        self,
        config: Mapping[str, Any],
        landing_dir: Path,
        run_date: str,
        mode: str,
        workers: int,
        clients: Mapping[str, ApiClient] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self.landing = landing_dir
        self.run_date = run_date
        self.mode = mode
        self.workers = workers
        self.env = env if env is not None else os.environ
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self._clients: dict[str, ApiClient] = dict(clients or {})
        self._owned: list[ApiClient] = []
        self._parents: dict[str, list[dict[str, Any]]] = {}
        self.watermarks = Watermarks(landing_dir / "_watermarks.json")

    def client(self, system: str) -> ApiClient:
        if system not in self._clients:
            cfg = self.config["systems"][system]
            base = self.env.get(cfg["base_url_env"])
            if not base:
                raise RuntimeError(f"{cfg['base_url_env']} is not set (see .env.example)")
            client = ApiClient(base, auth_headers(cfg, self.env), pool_size=self.workers * 2)
            self._clients[system] = client
            self._owned.append(client)
        return self._clients[system]

    def run(self, tables: Sequence[str]) -> dict[str, Any]:
        started = now_iso()
        results: list[dict[str, Any]] = []
        failed: set[str] = set()
        for name in tables:
            parent = self.config["tables"][name]["fetch"].get("parent")
            if parent in failed:
                failed.add(name)
                results.append(
                    {"table": name, "status": "skipped", "error": f"parent {parent} failed"}
                )
                log.error("%s skipped: parent %s failed", name, parent)
                continue
            result = self.extract_table(name)
            if result["status"] == "failed":
                failed.add(name)
            results.append(result)
        for client in self._owned:
            client.close()
        manifest = {
            "run_id": self.run_id,
            "run_date": self.run_date,
            "mode": self.mode,
            "started_at": started,
            "ended_at": now_iso(),
            "status": "failed" if failed else "succeeded",
            "tables": results,
        }
        path = write_manifest(self.landing / "_runs", manifest, self.landing / "csv")
        log.info("manifest: %s", path)
        return manifest

    def extract_table(self, name: str) -> dict[str, Any]:
        cfg = self.config["tables"][name]
        fetch = cfg["fetch"]
        result: dict[str, Any] = {"table": name, "system": cfg["system"]}
        if fetch["method"] == "none":
            log.info("%s: no API (%s), skipped", name, fetch.get("reason"))
            return {**result, "status": "skipped", "error": fetch.get("reason")}

        since = None
        load = "full"
        if self.mode == "incremental":
            if cfg.get("source_filter"):
                since = self.watermarks.value(name)
                load = f"incremental since {since}" if since else "full (no watermark yet)"
            elif cfg.get("incremental"):
                load = "incremental (follows parent)"
            else:
                load = "full (no source filter)"

        stats = RequestStats()
        system = self.config["systems"][cfg["system"]]
        raw = RawWriter(
            self.landing / "json" / cfg["system"] / name / self.run_date,
            bundle=(
                RAW_BUNDLE
                if fetch["method"] in ("per_parent", "fixflo_issue_urls") or "parent" in fetch
                else 1
            ),
        )
        columns = cfg["columns"]
        sink = CsvSink(self.landing / "csv" / f"{name}.csv", [c["name"] for c in columns])
        id_fields, flag_fields = capture_fields(self.config, name)
        captured: list[dict[str, Any]] = []
        wm_col = cfg.get("watermark_column")
        wm_idx = [c["name"] for c in columns].index(wm_col) if wm_col else None
        wm_max: str | None = None

        t0 = time.monotonic()
        log.info("%s: %s load via %s", name, load, fetch["method"])
        try:
            ctx = FetchContext(
                client=self.client(cfg["system"]),
                stats=stats,
                workers=self.workers,
                page_size=system["page_size"],
                since=since,
                parents=self._parents.get(fetch.get("parent", ""), ()),
            )
            for item in FETCHERS[fetch["method"]](fetch, ctx):
                raw.add(item.url, item.body)
                for record in item.records:
                    row = flatten(record, columns, item.url_values)
                    sink.write(row)
                    if wm_idx is not None:
                        wm_max = later_of(wm_max, row[wm_idx])
                    if id_fields:
                        keep = {f: get_path(record, f) for f in id_fields}
                        keep.update({f"has:{f}": bool(get_path(record, f)) for f in flag_fields})
                        captured.append(keep)
            raw.flush()
            sink.commit()
        except Exception as exc:  # noqa: BLE001 - recorded in the manifest, run continues
            sink.abort()
            log.exception("%s failed", name)
            return {
                **result,
                "status": "failed",
                "error": str(exc),
                **stats.as_dict(),
                "seconds": round(time.monotonic() - t0, 1),
            }

        if id_fields:
            self._parents[name] = captured
        if wm_col and wm_max:
            self.watermarks.update(name, wm_col, wm_max, cfg.get("source_filter"), self.run_id)
            self.watermarks.save()
        seconds = round(time.monotonic() - t0, 1)
        log.info(
            "%s: %d rows, %d responses, %d requests, %d retries (%d x 429) in %.1fs",
            name,
            sink.rows,
            raw.responses,
            stats.requests,
            stats.retries,
            stats.rate_limited,
            seconds,
        )
        return {
            **result,
            "status": "succeeded",
            "load": load,
            "rows": sink.rows,
            "expected_rows_full": cfg.get("expected_rows"),
            "api_responses": raw.responses,
            "raw_files": raw.files,
            **stats.as_dict(),
            "watermark": self.watermarks.value(name) if wm_col else None,
            "csv": str(sink.path.relative_to(self.landing)),
            "seconds": seconds,
        }


def setup_logging(landing: Path, run_id: str) -> None:
    runs = landing / "_runs"
    runs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(runs / f"{run_id}.log", encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        root.addHandler(handler)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull source tables from the APIs.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true", help="every table in the config")
    which.add_argument("--tables", nargs="+", metavar="TABLE")
    parser.add_argument("--mode", choices=["full", "incremental"], default="full")
    parser.add_argument("--run-date", default=date.today().isoformat())
    parser.add_argument("--workers", type=int, default=16, help="parallel calls per table")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--landing", type=Path, default=DEFAULT_LANDING)
    args = parser.parse_args(argv)

    load_dotenv(PROJECT_ROOT / ".env")
    config = load_config(args.config)
    tables = plan(config, list(config["tables"]) if args.all else args.tables)
    extractor = Extractor(config, args.landing, args.run_date, args.mode, args.workers)
    setup_logging(args.landing, extractor.run_id)
    log.info("run %s (%s) - %d tables", extractor.run_id, args.mode, len(tables))
    manifest = extractor.run(tables)
    log.info("run %s", manifest["status"])
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
