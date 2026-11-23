# Property Manager Insights

Source APIs → CSV → Microsoft Fabric (Bronze / Silver / Gold) → semantic model → Power BI.

## Setup (Windows, Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
# Unzip Source_Extracts_CSV.zip into data\reference\  (extracts\, api_samples\)
```

## Mock source APIs

The vendor APIs are not reachable from here, so `mock_api/` serves the reference
extracts in each vendor's response format on `http://localhost:8000`:

| System | Base path | Auth | Paging |
|---|---|---|---|
| MRI Qube PM | `/qube/api/v1/{resource}[/{id}[/{child}]]` | Basic `ClientID/Database/User/PartnerKey:Password` | `$top` (max 1000) / `$skip`, `{"value", "NextPageLink"}` |
| MRI API Services | `/MRIAPIServices/api.asp?$api=…&$format=json` | same Basic | `NextPageLink` at top, records in `entry` |
| FixFlo v2 | `/fixflo/api/v2/...` | `Bearer` token | PrevNextPager: `page` on `/Issues`, `pg`/`pgsz` (max 100) on `/Property/Search` |
| MRI Engage CRM | `/engage/api/v1/{resource}[/{id}[/{child}]]` | `Bearer` token | as Qube |

```powershell
.venv\Scripts\python -m mock_api
.venv\Scripts\python -m mock_api --chaos         # ~2% of calls return 429 + Retry-After
```

Interactive docs: http://localhost:8000/docs. Startup takes about 20 s while the CSVs load.

The mock serves `data/source` when `.env` sets `MOCK_DATA_DIR=data/source`. That folder is
a copy of `data/reference` (never edited) in which viewings fall mostly at weekends, as in
real lettings. Make or refresh it with:

```powershell
.venv\Scripts\python -m mock_api.weekend_viewings
```

How values are served: each CSV column gets one JSON type (number, boolean, nested
JSON or string), chosen only if the whole column converts back to its exact original
text. That is why some amounts (e.g. `96.10`) are strings. Dot-named columns
(`Address.Town`) become nested objects, and an object with no values is `null`.

## Extract: API -> JSON -> CSV

```powershell
.venv\Scripts\python -m extract.build_config                    # dictionary -> config/sources.yaml
.venv\Scripts\python -m extract.run --all                       # full pull (mock must be running)
.venv\Scripts\python -m extract.run --all --mode incremental    # FixFlo issues changed since last run
.venv\Scripts\python -m extract.run --tables fixflo_jobs        # one table (its parent is pulled too)
```

`config/sources.yaml` is generated from the data dictionary. It tells the extractors,
per table, which endpoint to call, how that endpoint pages, which parent ids a child
endpoint needs, and which JSON path fills each CSV column.

| Module | Role |
|---|---|
| `extract/http.py` | Client: auth from `.env`, timeouts, retries (honours 429 `Retry-After`, backs off on 5xx/timeouts), request counts |
| `extract/fetchers.py` | One function per paging style; per-parent calls run in parallel but results stay in source order |
| `extract/flatten.py` | JSON record -> CSV row, with the same text rules the mock uses |
| `extract/landing.py` | Raw JSON pages, CSV (written to a temp file then swapped in), watermarks, run manifest |
| `extract/run.py` | Command line and orchestration |

Output in `data/landing/`:

```
json/<system>/<table>/<run_date>/page_00001.json   raw responses ({"responses": [{"url", "body"}]})
csv/<table>.csv                                    flattened, same columns and order as the reference
_watermarks.json                                   latest change time per table
_runs/<run_id>.json / .log, _runs/latest.json      manifest: rows, pages, requests, retries, 429s, timings, status
```

Incremental loads: only FixFlo `/Issues` can filter by change time (`UpdatedSince`), so
`--mode incremental` pulls issues changed since the stored watermark, plus their jobs,
quotes and completion details. Every other table has no source filter and is pulled in full.

## Bronze: CSV -> Fabric lakehouse

`data/landing/csv/` is the only local data folder: every table's CSV plus `_manifest.json`.
Upload its contents to `ll_bronze/Files/landing/<run_date>/` and run the `01_bronze`
notebook in Fabric.

After editing `fabric/notebooks/src/01_bronze.py`, rebuild the notebook you import:

```powershell
.venv\Scripts\python -m fabric.build_notebooks
```

## Silver: typed tables from the data dictionary

`fabric/notebooks/02_silver.ipynb` builds the 22 Silver tables in `ll_silver`: SQL staging
query per table, `TRY_CAST` to the dictionary types (failures logged to `_cast_errors`),
then `MERGE` on the key.

```powershell
.venv\Scripts\python -m fabric.silver_contract   # after a dictionary change
.venv\Scripts\python -m fabric.build_notebooks
```

## Data quality and governance

`fabric/notebooks/03_dq.ipynb` runs the 53 rules in
[governance/dq_rules.yaml](governance/dq_rules.yaml) on Silver and writes `dq_results`,
`dq_exceptions` and `dq_null_profile` in `ll_silver`. Attach `ll_silver` and Run all.

Governance documents in [governance/](governance/): data catalogue, lineage, personal
data, owners and stewards (generated), and the row-level security plan.

```powershell
.venv\Scripts\python -m fabric.build_notebooks     # after editing dq_rules.yaml or the dictionary
.venv\Scripts\python governance\build_docs.py      # refresh the generated governance docs
```

## Gold: star schema

`fabric/notebooks/04_gold.ipynb` builds 6 dimensions and 15 facts in `ll_gold` from Silver for the Operations, Finance and Property management tabs
(SCD2 on property and tenant; insights such as renewals, arrears, voids and staircasing
derived in SQL). Attach `ll_gold` (default) and `ll_silver`, then Run all.

## Security, semantic model and report

- `05_security` builds `ll_gold.security_user_access`, which the row-level security roles
  filter on ([governance/rls.md](governance/rls.md)).
- `06_model_measures` writes every measure from `powerbi/build_measures.py` into the
  Direct Lake semantic model **LL_Insights**.
- The report is `powerbi/Property_Manager_Insights.pbip`; see [powerbi/README.md](powerbi/README.md).

## Tests

```powershell
.venv\Scripts\python -m pytest -q
```

`tests/test_extracted_csvs.py` compares the CSVs of the last full run with the data the
mock serves (`data/source`, or `data/reference` if there is no copy); it is skipped until a
full run has been made.
