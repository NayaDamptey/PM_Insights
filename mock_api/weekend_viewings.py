"""Make a copy of the source data in which viewings happen mostly at weekends.

    .venv\\Scripts\\python -m mock_api.weekend_viewings

Copies data/reference (left untouched) to data/source and moves each Engage viewing to
another day of the same week, weighted like real lettings: Saturday busiest, Monday to
Wednesday quietest. Set MOCK_DATA_DIR=data/source in .env so the mock API serves it.

A viewing only moves to a day that keeps the data consistent: not before the listing
or the applicant's registration, not after that applicant's offer on the listing, the
move-in, a withdrawal, or the extract date. If no day in its week qualifies, it keeps
its original date. The same input always gives the same output.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE = PROJECT_ROOT / "data" / "reference"
SOURCE = PROJECT_ROOT / "data" / "source"
EXTRACT_DATE = date(2026, 11, 21)

# Monday = 0 ... Sunday = 6
WEIGHTS = {5: 30, 6: 15, 3: 15, 4: 15, 2: 9, 0: 8, 1: 8}


def _read(name: str) -> tuple[list[str], list[dict[str, str]]]:
    with (REFERENCE / "extracts" / f"{name}.csv").open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _d(text: str) -> date | None:
    return date.fromisoformat(text[:10]) if text else None


def _preferred_days(viewing_id: str) -> list[int]:
    """Weekdays in the order to try them: one weighted draw first, then by weight."""
    draw = int(hashlib.sha1(viewing_id.encode()).hexdigest(), 16) % sum(WEIGHTS.values())
    for day, weight in WEIGHTS.items():
        if draw < weight:
            first = day
            break
        draw -= weight
    return [first] + [d for d in sorted(WEIGHTS, key=WEIGHTS.get, reverse=True) if d != first]


def shift(rows, listings, applicants, offer_dates) -> tuple[list[dict[str, str]], int]:
    moved = 0
    for row in rows:
        original = _d(row["ViewingDate"])
        if original is None or original > EXTRACT_DATE:
            continue
        listing = listings.get(row["ListingId"], {})
        earliest = max(
            d
            for d in (
                _d(listing.get("ListedDate", "")),
                _d(applicants.get(row["ApplicantId"], {}).get("RegisteredDate", "")),
                date.min,
            )
            if d
        )
        latest = min(
            d
            for d in (
                offer_dates.get((row["ListingId"], row["ApplicantId"])),
                _d(listing.get("CompletionDate", "")),
                _d(listing.get("WithdrawnDate", "")),
                EXTRACT_DATE,
            )
            if d
        )
        if not earliest <= original <= latest:
            continue  # already outside its own window: leave the source as it was
        monday = original - timedelta(days=original.weekday())
        for day in _preferred_days(row["ViewingId"]):
            candidate = monday + timedelta(days=day)
            if earliest <= candidate <= latest:
                if candidate != original:
                    row["ViewingDate"] = candidate.isoformat()
                    moved += 1
                break
    return rows, moved


def main() -> None:
    if SOURCE.exists():
        shutil.rmtree(SOURCE)
    shutil.copytree(REFERENCE, SOURCE)

    header, rows = _read("engage_viewings")
    listings = {r["ListingId"]: r for r in _read("engage_listings")[1]}
    applicants = {r["ApplicantId"]: r for r in _read("engage_applicants")[1]}
    offer_dates: dict[tuple[str, str], date] = {}
    for o in _read("engage_offers")[1]:
        key, when = (o["ListingId"], o["ApplicantId"]), _d(o["OfferDate"])
        if when and (key not in offer_dates or when < offer_dates[key]):
            offer_dates[key] = when

    rows, moved = shift(rows, listings, applicants, offer_dates)
    out = SOURCE / "extracts" / "engage_viewings.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)

    by_day = [0] * 7
    for r in rows:
        by_day[date.fromisoformat(r["ViewingDate"]).weekday()] += 1
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    print(f"moved {moved:,} of {len(rows):,} viewings; written to {SOURCE}")
    counts = ", ".join(f"{n} {c:,}" for n, c in zip(names, by_day, strict=True))
    print(f"viewings by weekday: {counts}")


if __name__ == "__main__":
    main()
