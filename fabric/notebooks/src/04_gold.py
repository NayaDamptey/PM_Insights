# %% [markdown]
# # 04_gold: Silver -> star schema for reporting
#
# Builds the Kimball star schema in **ll_gold** for three report tabs:
#
# | Tab | Questions answered |
# |---|---|
# | **Operations: maintenance** | contractors not used, repair speed, expired or missing compliance, contractors with jobs open over 15 days |
# | **Operations: lettings** | days to let, occupancy, viewings by month and weekday, lets agreed by month, funnel, asking vs achieved, negotiators, rejected vs accepted offers, registration to move-in, demand vs supply |
# | **Finance** | revenue by month, collection rate, arrears and aged arrears, rent lost to voids, spend and invoice lag |
# | **Property management** | portfolio and workload, occupancy and voids, tenancies and renewals, arrears risk, Shared Ownership staircasing |
#
# Insights are **derived here** from Silver, not read from the source.
#
# - **Dimensions** have surrogate keys (`*_key`) and an `Unknown` row (key -1), so a fact
#   with a missing link still shows up in reports.
# - `dim_property` and `dim_tenant` keep history (**SCD type 2**); facts join to the
#   version that was true on the event's date.
# - **Facts** are rebuilt in full each run, so running twice gives the same result.
#
# Attach **ll_gold** (default) and **ll_silver**.

# %% tags=["parameters"]
silver_db = "ll_silver"
gold_db = "ll_gold"
as_of = ""  # blank: today. "Expired", "open for 15 days", "current void" are judged at this date.

# %%
from datetime import date

as_of = as_of or date.today().isoformat()
s, g = silver_db, gold_db
AS_OF = f"DATE '{as_of}'"
FOREVER = "DATE '9999-12-31'"
BEGINNING = "DATE '1900-01-01'"


def dk(expr: str) -> str:
    """Date key (yyyymmdd as INT) for a date or timestamp expression."""
    return f"CAST(date_format({expr}, 'yyyyMMdd') AS INT)"


def build(table: str, select_sql: str) -> None:
    """Replace a Gold table with the result of a query and report its row count."""
    spark.sql(f"CREATE OR REPLACE TABLE {g}.{table} USING DELTA AS {select_sql}")
    print(f"  {table:32} {spark.table(f'{g}.{table}').count():>9,} rows")


def add_unknown(table: str, key: str, natural_key: str) -> None:
    """The key -1 row that facts point at when their link is missing (other columns blank)."""
    schema = spark.table(f"{g}.{table}").schema
    row = [-1 if f.name == key else "Unknown" if f.name == natural_key else None for f in schema]
    spark.createDataFrame([row], schema).write.mode("append").saveAsTable(f"{g}.{table}")


def latest(table: str, key: str) -> str:
    """One row per key from a Silver table (Silver keeps duplicates; DQ reports them)."""
    return f"""(SELECT * FROM (
                   SELECT *, ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY loaded_at DESC) AS _rn
                   FROM {s}.{table} WHERE {key} IS NOT NULL) WHERE _rn = 1)"""


print(f"Gold build as of {as_of}")

# %% [markdown]
# ## Dimensions without history

# %%
build(
    "dim_date",
    f"""
    WITH calendar AS (
        SELECT date, year, quarter, month_number, month_name, month_short, year_month,
               year_quarter, weekday_name, is_weekend, financial_year
        FROM {s}.silver_calendar
        UNION ALL
        SELECT d, year(d), concat('Q', quarter(d)), CAST(month(d) AS STRING),
               date_format(d, 'MMMM'), date_format(d, 'MMM'), date_format(d, 'yyyy-MM'),
               concat(year(d), '-Q', quarter(d)), date_format(d, 'EEEE'),
               dayofweek(d) IN (1, 7),
               concat('FY', year(d) - IF(month(d) < 4, 1, 0), '/',
                      lpad(CAST((year(d) + IF(month(d) < 4, 0, 1)) % 100 AS STRING), 2, '0'))
        FROM (SELECT explode(sequence(DATE '2021-01-01', DATE '2030-12-31', INTERVAL 1 DAY)) AS d)
        WHERE d > (SELECT max(date) FROM {s}.silver_calendar)
    )
    SELECT {dk("date")}                                         AS date_key,
           date, year, quarter,
           CAST(month_number AS INT)                          AS month_number,
           month_name, month_short, year_month, year_quarter,
           trunc(date, 'MM')                                  AS month_start,
           weekday_name,
           dayofweek(date)                                    AS weekday_number,
           is_weekend,
           financial_year,
           -- UK financial year runs April to March, so April is month 1.
           ((CAST(month_number AS INT) + 8) % 12) + 1         AS financial_month_number,
           CASE WHEN CAST(month_number AS INT) IN (12, 1, 2) THEN 'Winter'
                WHEN CAST(month_number AS INT) IN (3, 4, 5)  THEN 'Spring'
                WHEN CAST(month_number AS INT) IN (6, 7, 8)  THEN 'Summer'
                ELSE 'Autumn' END                             AS season
    FROM calendar
""",
)

build(
    "dim_staff",
    f"""
    SELECT xxhash64(staff_code) AS staff_key, staff_code, full_name, role,
           CASE WHEN is_property_manager THEN 'Property manager'
                WHEN is_negotiator       THEN 'Negotiator'
                ELSE 'Other' END AS staff_type,
           region, location, email, start_date, end_date, is_active
    FROM {latest("silver_staff", "staff_code")}
    """,
)
add_unknown("dim_staff", "staff_key", "staff_code")

build(
    "dim_supplier",
    f"""
    SELECT xxhash64(supplier_code) AS supplier_key, supplier_code, supplier_name, trade,
           region, is_active, is_vat_registered
    FROM {latest("silver_supplier", "supplier_code")}
    """,
)
add_unknown("dim_supplier", "supplier_key", "supplier_code")

# Applicants: for the lettings funnel and demand vs supply. Contact details stay in Silver.
build(
    "dim_applicant",
    f"""
    SELECT xxhash64(applicant_id) AS applicant_key, applicant_id, applicant_type,
           registered_date, preferred_town, min_bedrooms, max_budget, status,
           status = 'Active' AS is_active_applicant,
           qube_tenant_ref IS NOT NULL AS became_resident
    FROM {latest("silver_applicant", "applicant_id")}
    """,
)
add_unknown("dim_applicant", "applicant_key", "applicant_id")

# %% [markdown]
# ## Dimensions with history (SCD type 2)
#
# Each run compares a fingerprint (hash) of the tracked columns with the current version:
# a **changed** record has its current version closed (`valid_to` = yesterday) and a new
# one opened from today; a **new** record starts from 1900-01-01 so older facts still find
# it; an **unchanged** one is left alone. The key is a hash of the natural key and
# `valid_from`, so it never changes once issued.

# %%


def scd2(table: str, key: str, natural_key: str, source_sql: str) -> None:
    spark.sql(f"CREATE OR REPLACE TEMP VIEW scd_source AS {source_sql}")
    attrs = [c for c in spark.table("scd_source").columns if c != natural_key]
    fingerprint = (
        "sha2(concat_ws('||', "
        + ", ".join(f"coalesce(CAST(`{c}` AS STRING), '~')" for c in attrs)
        + "), 256)"
    )
    spark.sql(
        f"CREATE OR REPLACE TEMP VIEW scd_incoming AS SELECT *, {fingerprint} AS row_hash FROM scd_source"
    )
    cols = [natural_key, *attrs, "row_hash"]
    col_list = ", ".join(f"`{c}`" for c in cols)

    if not spark.catalog.tableExists(f"{g}.{table}"):
        spark.sql(f"""
            CREATE TABLE {g}.{table} USING DELTA AS
            SELECT xxhash64({natural_key}, {BEGINNING}) AS {key}, {col_list},
                   {BEGINNING} AS valid_from, {FOREVER} AS valid_to, true AS is_current
            FROM scd_incoming
        """)
        add_unknown(table, key, natural_key)
    else:
        # 1. close the current version of records that changed
        spark.sql(f"""
            MERGE INTO {g}.{table} d
            USING scd_incoming s
               ON d.{natural_key} = s.{natural_key} AND d.is_current
            WHEN MATCHED AND d.row_hash <> s.row_hash THEN UPDATE SET
                 is_current = false, valid_to = date_sub(current_date(), 1)
        """)
        # 2. open a version for every record without a current one (changed or new)
        spark.sql(f"""
            INSERT INTO {g}.{table}
            SELECT xxhash64(s.{natural_key}, s.valid_from), {", ".join(f"s.`{c}`" for c in cols)},
                   s.valid_from, {FOREVER}, true
            FROM (
                SELECT s.*, CASE WHEN seen.{natural_key} IS NOT NULL THEN current_date()
                                 ELSE {BEGINNING} END AS valid_from
                FROM scd_incoming s
                LEFT ANTI JOIN {g}.{table} d ON d.{natural_key} = s.{natural_key} AND d.is_current
                LEFT JOIN (SELECT DISTINCT {natural_key} FROM {g}.{table}) seen
                       ON seen.{natural_key} = s.{natural_key}
            ) s
        """)
    versions = spark.table(f"{g}.{table}").count()
    current = spark.table(f"{g}.{table}").where("is_current").count()
    print(f"  {table:32} {current:>9,} current, {versions - current:,} closed versions")


# Location is the home's town (each property manager covers whole towns).
# New build: no source field says so; a home counts as new-build if a defect was referred
# to the developer (only possible under the new-build warranty) or its block was built no
# more than a year before the company bought it.
# Stale duplicate: not Sold, but shares its address with a record that is (DQ010).
scd2(
    "dim_property",
    "property_key",
    "property_ref",
    f"""
    WITH p AS {latest("silver_property", "property_ref")},
    referred AS (
        SELECT DISTINCT property_ref FROM {s}.silver_repair_issue
        WHERE close_reason = 'Referred to developer'
    ),
    blocks AS {latest("silver_block", "block_ref")},
    sold_addresses AS (
        SELECT DISTINCT upper(trim(address_line1)) AS a1,
               upper(trim(coalesce(address_line2, ''))) AS a2,
               upper(replace(postcode, ' ', '')) AS pc
        FROM p WHERE property_status = 'Sold'
    )
    SELECT p.property_ref, p.block_ref, p.address_line1, p.address_line2, p.town, p.postcode,
           p.region, p.town AS location, p.latitude, p.longitude, p.property_type, p.bedrooms,
           p.tenure, p.department, p.has_gas,
           (r.property_ref IS NOT NULL OR b.built_year >= year(p.acquisition_date) - 1)
                                                                  AS is_new_build,
           p.manager_staff_code, m.full_name                      AS manager_name,
           p.acquisition_date, p.acquisition_cost, p.market_value, p.market_rent_pcm,
           p.property_status, p.disposal_date, p.disposal_value,
           (p.property_status <> 'Sold' AND sa.pc IS NOT NULL)    AS is_stale_duplicate
    FROM p
    LEFT JOIN referred r ON r.property_ref = p.property_ref
    LEFT JOIN blocks b   ON b.block_ref = p.block_ref
    LEFT JOIN {g}.dim_staff m ON m.staff_code = p.manager_staff_code
    LEFT JOIN sold_addresses sa
           ON sa.a1 = upper(trim(p.address_line1))
          AND sa.a2 = upper(trim(coalesce(p.address_line2, '')))
          AND sa.pc = upper(replace(p.postcode, ' ', ''))
    """,
)

scd2(
    "dim_tenant",
    "tenant_key",
    "tenant_ref",
    f"""
    SELECT tenant_ref, title, first_name, last_name, full_name, email, mobile,
           engage_applicant_id, right_to_rent_checked
    FROM {latest("silver_tenant", "tenant_ref")}
    """,
)

# Facts find the dimension version true on a date through these views.
spark.sql(f"""CREATE OR REPLACE TEMP VIEW property_versions AS
              SELECT property_key, property_ref, valid_from, valid_to FROM {g}.dim_property""")
spark.sql(f"""CREATE OR REPLACE TEMP VIEW tenant_versions AS
              SELECT tenant_key, tenant_ref, valid_from, valid_to FROM {g}.dim_tenant""")
spark.sql(f"""CREATE OR REPLACE TEMP VIEW current_property AS
              SELECT * FROM {g}.dim_property WHERE is_current""")


def at_date(alias: str, view: str, ref_col: str, ref_expr: str, date_expr: str) -> str:
    """LEFT JOIN to the dimension version of ref_expr valid on date_expr."""
    return (
        f"LEFT JOIN {view} {alias} ON {alias}.{ref_col} = {ref_expr} "
        f"AND CAST({date_expr} AS DATE) BETWEEN {alias}.valid_from AND {alias}.valid_to"
    )


# %% [markdown]
# ## Finance: rent, collection, arrears

# %%
print("Facts")

# F1, F2: one row per ledger line; charged / paid split out so measures can just sum them.
build(
    "fact_rent_transaction",
    f"""
    SELECT t.transaction_id,
           {dk("t.transaction_date")}                         AS date_key,
           {dk("t.period_month")}                             AS period_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           t.tenancy_ref, t.transaction_type, t.transaction_group, t.payment_method, t.amount,
           CASE WHEN t.transaction_group = 'Charge'  THEN t.amount  ELSE 0 END AS charged,
           CASE WHEN t.transaction_group = 'Payment' THEN -t.amount ELSE 0 END AS paid
    FROM {s}.silver_rent_transaction t
    {at_date("p", "property_versions", "property_ref", "t.property_ref", "t.transaction_date")}
    {at_date("tn", "tenant_versions", "tenant_ref", "t.tenant_ref", "t.transaction_date")}
    """,
)

# F3: balance per tenancy per month = running total of the ledger (deposits held for the
# tenant excluded, as in Qube's closing balance; checked by DQ068), carried forward
# through months with no activity and up to the as-of month while money is still owed.
build(
    "fact_arrears_monthly",
    f"""
    WITH ledger AS (
        SELECT tenancy_ref, period_month AS month_start,
               SUM(CASE WHEN transaction_group = 'Charge'  THEN amount  ELSE 0 END) AS charged,
               SUM(CASE WHEN transaction_group = 'Payment' THEN -amount ELSE 0 END) AS paid,
               SUM(CASE WHEN transaction_type NOT IN ('Deposit received', 'Deposit returned')
                        THEN amount ELSE 0 END)                                    AS movement
        FROM {s}.silver_rent_transaction
        WHERE period_month IS NOT NULL
        GROUP BY tenancy_ref, period_month
    ),
    span AS (
        SELECT t.tenancy_ref, t.property_ref, t.lead_tenant_ref, t.rent_pcm, t.tenancy_status,
               trunc(t.start_date, 'MM') AS first_month,
               greatest(trunc(least(coalesce(t.actual_end_date, {AS_OF}), {AS_OF}), 'MM'),
                        coalesce(max(l.month_start), trunc(t.start_date, 'MM')),
                        CASE WHEN coalesce(t.closing_balance, 0) <> 0
                             THEN trunc({AS_OF}, 'MM') END) AS last_month
        FROM {latest("silver_tenancy", "tenancy_ref")} t
        LEFT JOIN ledger l ON l.tenancy_ref = t.tenancy_ref
        WHERE t.start_date IS NOT NULL
        GROUP BY t.tenancy_ref, t.property_ref, t.lead_tenant_ref, t.rent_pcm,
                 t.tenancy_status, t.start_date, t.actual_end_date, t.closing_balance
    ),
    months AS (
        SELECT sp.*, explode(sequence(first_month, last_month, INTERVAL 1 MONTH)) AS month_start
        FROM span sp
    ),
    running AS (
        SELECT m.*, coalesce(l.charged, 0) AS charged, coalesce(l.paid, 0) AS paid,
               SUM(coalesce(l.movement, 0)) OVER (
                   PARTITION BY m.tenancy_ref ORDER BY m.month_start
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS balance
        FROM months m
        LEFT JOIN ledger l ON l.tenancy_ref = m.tenancy_ref AND l.month_start = m.month_start
    )
    SELECT {dk("r.month_start")}                              AS month_key,
           r.tenancy_ref,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           r.charged, r.paid, r.balance,
           greatest(r.balance, 0)                             AS arrears,
           r.rent_pcm,
           r.tenancy_status IN ('Active', 'Periodic')         AS is_current_tenant
    FROM running r
    {at_date("p", "property_versions", "property_ref", "r.property_ref", "last_day(r.month_start)")}
    {at_date("tn", "tenant_versions", "tenant_ref", "r.lead_tenant_ref", "last_day(r.month_start)")}
    """,
)

# F3: aged arrears at the as-of date. Payments clear the oldest charges first, so what is
# still owed sits on the newest charges: walk back from the newest charge until the
# balance is used up, then age each unpaid piece from its charge date.
build(
    "fact_arrears_aged",
    f"""
    WITH balance AS (
        SELECT tenancy_ref, SUM(amount) AS balance
        FROM {s}.silver_rent_transaction
        WHERE transaction_type NOT IN ('Deposit received', 'Deposit returned')
          AND transaction_date <= {AS_OF}
        GROUP BY tenancy_ref
        HAVING SUM(amount) > 0
    ),
    charges AS (
        SELECT c.tenancy_ref, c.transaction_date, c.amount, b.balance,
               SUM(c.amount) OVER (PARTITION BY c.tenancy_ref
                                   ORDER BY c.transaction_date DESC, c.transaction_id DESC
                                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS newer_total
        FROM {s}.silver_rent_transaction c
        JOIN balance b ON b.tenancy_ref = c.tenancy_ref
        WHERE c.transaction_group = 'Charge' AND c.amount > 0 AND c.transaction_date <= {AS_OF}
    ),
    unpaid AS (
        SELECT tenancy_ref,
               least(amount, greatest(balance - (newer_total - amount), 0)) AS unpaid,
               datediff({AS_OF}, transaction_date)                          AS age_days
        FROM charges
    )
    SELECT u.tenancy_ref,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           CASE WHEN age_days <= 30 THEN '0-30 days'  WHEN age_days <= 60 THEN '31-60 days'
                WHEN age_days <= 90 THEN '61-90 days' ELSE '90+ days' END AS age_band,
           CASE WHEN age_days <= 30 THEN 1 WHEN age_days <= 60 THEN 2
                WHEN age_days <= 90 THEN 3 ELSE 4 END         AS age_band_order,
           t.tenancy_status IN ('Active', 'Periodic')         AS is_current_tenant,
           SUM(u.unpaid)                                      AS arrears
    FROM unpaid u
    JOIN {latest("silver_tenancy", "tenancy_ref")} t ON t.tenancy_ref = u.tenancy_ref
    LEFT JOIN current_property p ON p.property_ref = t.property_ref
    LEFT JOIN {g}.dim_tenant tn  ON tn.tenant_ref = t.lead_tenant_ref AND tn.is_current
    WHERE u.unpaid > 0
    GROUP BY 1, 2, 3, 4, 5, 6
    """,
)

# Payment timing (feeds the arrears risk score): each receipt against the same month's
# rent charge, which falls on the tenancy's rent due day. The tenant's habit comes from
# the pattern of all their receipts: erratic if the days vary a lot, "own payday" if they
# are usually late but always on the same day of the month.
build(
    "fact_payment_timing",
    f"""
    WITH due AS (
        SELECT tenancy_ref, period_month,
               coalesce(min(CASE WHEN transaction_type = 'Rent charge' THEN transaction_date END),
                        min(transaction_date)) AS due_date
        FROM {s}.silver_rent_transaction
        WHERE transaction_group = 'Charge'
        GROUP BY tenancy_ref, period_month
    ),
    receipts AS (
        SELECT r.transaction_id, r.tenancy_ref, r.property_ref, r.tenant_ref, r.period_month,
               r.transaction_date AS paid_date, -r.amount AS paid_amount, r.payment_method,
               d.due_date, datediff(r.transaction_date, d.due_date) AS days_from_due
        FROM {s}.silver_rent_transaction r
        LEFT JOIN due d ON d.tenancy_ref = r.tenancy_ref AND d.period_month = r.period_month
        WHERE r.transaction_group = 'Payment'
    ),
    timed AS (
        SELECT *, CASE WHEN days_from_due IS NULL THEN 'No charge to match'
                       WHEN days_from_due < 0     THEN 'Early'
                       WHEN days_from_due <= 1    THEN 'On time'
                       ELSE 'Late' END AS timing
        FROM receipts
    ),
    payday AS (
        SELECT tenant_ref, max(n) / sum(n) AS same_day_share
        FROM (SELECT tenant_ref, dayofmonth(paid_date) AS d, COUNT(*) AS n
              FROM timed GROUP BY tenant_ref, dayofmonth(paid_date))
        GROUP BY tenant_ref
    ),
    habit AS (
        SELECT t.tenant_ref,
               CASE WHEN stddev(t.days_from_due) > 5                       THEN 'Erratic'
                    WHEN avg(CASE WHEN t.timing = 'Early' THEN 1 ELSE 0 END) >= 0.5 THEN 'Early'
                    WHEN avg(CASE WHEN t.timing = 'Late'  THEN 1 ELSE 0 END) >= 0.5
                         AND max(pd.same_day_share) >= 0.6                 THEN 'Own payday'
                    WHEN avg(CASE WHEN t.timing = 'Late'  THEN 1 ELSE 0 END) >= 0.5 THEN 'Late'
                    ELSE 'On time' END AS payment_habit
        FROM timed t LEFT JOIN payday pd ON pd.tenant_ref = t.tenant_ref
        GROUP BY t.tenant_ref
    )
    SELECT t.transaction_id,
           {dk("t.paid_date")}                                AS paid_date_key,
           {dk("t.period_month")}                             AS period_key,
           t.tenancy_ref,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           t.paid_amount, t.payment_method, t.days_from_due, t.timing,
           h.payment_habit
    FROM timed t
    LEFT JOIN habit h ON h.tenant_ref = t.tenant_ref
    {at_date("p", "property_versions", "property_ref", "t.property_ref", "t.paid_date")}
    {at_date("tn", "tenant_versions", "tenant_ref", "t.tenant_ref", "t.paid_date")}
    """,
)

# %% [markdown]
# ## Property management: tenancies, occupancy, voids, ownership
#
# A renewal points at the tenancy it replaced (`previous_tenancy_ref`). Spark SQL has no
# recursive CTE, so the chain is walked one step at a time until every tenancy knows the
# original tenancy it descends from and how many renewals came before it.

# %%
spark.sql(f"""
    CREATE OR REPLACE TEMP VIEW chain AS
    SELECT tenancy_ref, previous_tenancy_ref AS next_back, tenancy_ref AS original_ref,
           0 AS renewal_number
    FROM {latest("silver_tenancy", "tenancy_ref")}
""")
for step in range(1, 51):  # noqa: B007 - printed after the loop; >50 renewals = data error
    spark.sql(f"""
        CREATE OR REPLACE TEMP VIEW chain_step AS
        SELECT c.tenancy_ref,
               CASE WHEN p.tenancy_ref IS NOT NULL THEN p.previous_tenancy_ref END AS next_back,
               coalesce(p.tenancy_ref, c.original_ref)                            AS original_ref,
               c.renewal_number + CASE WHEN p.tenancy_ref IS NOT NULL THEN 1 ELSE 0 END
                                                                                  AS renewal_number
        FROM chain c
        LEFT JOIN {latest("silver_tenancy", "tenancy_ref")} p ON p.tenancy_ref = c.next_back
    """)
    spark.table("chain_step").localCheckpoint().createOrReplaceTempView("chain")
    if spark.table("chain").where("next_back IS NOT NULL").limit(1).count() == 0:
        break
print(f"  renewal chains resolved in {step} steps")

# P3 + P4: one row per tenancy period. A renter is "stretched" if the rent agreed when they
# first moved in was above the maximum budget they gave as an Engage applicant.
build(
    "fact_tenancy",
    f"""
    WITH t AS {latest("silver_tenancy", "tenancy_ref")},
    tenants AS (
        SELECT tenancy_ref, COUNT(*) AS tenant_count,
               SUM(CASE WHEN tt.start_date > t.start_date
                          OR tt.end_date < coalesce(t.actual_end_date, {FOREVER})
                        THEN 1 ELSE 0 END) AS tenant_changes
        FROM {s}.silver_tenancy_tenant tt
        JOIN t USING (tenancy_ref)
        GROUP BY tenancy_ref
    ),
    budget AS (
        SELECT tn.tenant_ref, a.max_budget
        FROM {latest("silver_tenant", "tenant_ref")} tn
        JOIN {latest("silver_applicant", "applicant_id")} a ON a.applicant_id = tn.engage_applicant_id
    )
    SELECT t.tenancy_ref,
           c.original_ref                                     AS original_tenancy_ref,
           c.renewal_number,
           {dk("t.start_date")}                               AS start_date_key,
           {dk("t.actual_end_date")}                          AS end_date_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           t.tenancy_type, t.tenancy_status,
           t.tenancy_status IN ('Active', 'Periodic')         AS is_live,
           t.start_date, t.actual_end_date,
           datediff(coalesce(t.actual_end_date, {AS_OF}), t.start_date) + 1 AS length_days,
           round(months_between(coalesce(t.actual_end_date, {AS_OF}), t.start_date), 1)
                                                              AS length_months,
           CASE WHEN t.tenancy_status IN ('Active', 'Periodic') THEN 'Still live'
                WHEN t.tenancy_status = 'Renewed'             THEN 'Renewed'
                WHEN pr.disposal_date = t.actual_end_date      THEN 'Home sold'
                ELSE 'Tenant left' END                        AS end_reason,
           t.rent_pcm,
           prev.rent_pcm                                      AS previous_rent_pcm,
           round(100 * (t.rent_pcm / prev.rent_pcm - 1), 2)   AS rent_increase_pct,
           coalesce(tt.tenant_count, 0)                       AS tenant_count,
           coalesce(tt.tenant_changes, 0)                     AS tenant_changes,
           b.max_budget                                       AS applicant_max_budget,
           CASE WHEN t.tenancy_type = 'Assured Shorthold Tenancy' AND b.max_budget IS NOT NULL
                THEN orig.rent_pcm > b.max_budget END         AS is_stretched,
           t.deposit_amount, t.closing_balance, t.ownership_share_pct
    FROM t
    LEFT JOIN chain c     ON c.tenancy_ref = t.tenancy_ref
    LEFT JOIN t prev      ON prev.tenancy_ref = t.previous_tenancy_ref
    LEFT JOIN t orig      ON orig.tenancy_ref = c.original_ref
    LEFT JOIN tenants tt  ON tt.tenancy_ref = t.tenancy_ref
    LEFT JOIN budget b    ON b.tenant_ref = t.lead_tenant_ref
    LEFT JOIN current_property pr ON pr.property_ref = t.property_ref
    {at_date("p", "property_versions", "property_ref", "t.property_ref", "t.start_date")}
    {at_date("tn", "tenant_versions", "tenant_ref", "t.lead_tenant_ref", "t.start_date")}
    """,
)

# P2, F4, lettings occupancy: one row per home per month it was held, up to the as-of
# month. Let days are covered by a tenancy, the rest are void; void days are costed at the
# home's market rent.
build(
    "fact_occupancy_monthly",
    f"""
    WITH held AS (
        SELECT property_ref, acquisition_date, market_rent_pcm,
               least(coalesce(disposal_date, {AS_OF}), {AS_OF}) AS held_until
        FROM {latest("silver_property", "property_ref")}
        WHERE acquisition_date IS NOT NULL
    ),
    property_months AS (
        SELECT h.property_ref, h.market_rent_pcm, m.month_start,
               greatest(m.month_start, h.acquisition_date)  AS from_day,
               least(last_day(m.month_start), h.held_until) AS to_day
        FROM held h
        LATERAL VIEW explode(sequence(trunc(h.acquisition_date, 'MM'),
                                      trunc(h.held_until, 'MM'), INTERVAL 1 MONTH)) m AS month_start
        WHERE h.held_until >= h.acquisition_date
    ),
    let AS (
        SELECT pm.property_ref, pm.month_start,
               SUM(greatest(0, datediff(least(pm.to_day, coalesce(t.actual_end_date, {AS_OF})),
                                        greatest(pm.from_day, t.start_date)) + 1)) AS let_days,
               MAX(CASE WHEN t.start_date <= pm.to_day
                         AND coalesce(t.actual_end_date, {AS_OF}) >= pm.to_day THEN 1 ELSE 0 END)
                                                                            AS let_on_last_day
        FROM property_months pm
        JOIN {latest("silver_tenancy", "tenancy_ref")} t
          ON t.property_ref = pm.property_ref
         AND t.start_date <= pm.to_day
         AND coalesce(t.actual_end_date, {AS_OF}) >= pm.from_day
        GROUP BY pm.property_ref, pm.month_start
    ),
    days AS (
        SELECT pm.*, datediff(pm.to_day, pm.from_day) + 1 AS held_days,
               least(coalesce(l.let_days, 0), datediff(pm.to_day, pm.from_day) + 1) AS let_days,
               coalesce(l.let_on_last_day, 0) = 1 AS is_let_on_last_day
        FROM property_months pm
        LEFT JOIN let l ON l.property_ref = pm.property_ref AND l.month_start = pm.month_start
    )
    SELECT {dk("d.month_start")}                              AS month_key,
           coalesce(p.property_key, -1)                       AS property_key,
           d.held_days, d.let_days,
           d.held_days - d.let_days                           AS void_days,
           d.is_let_on_last_day,
           round((d.held_days - d.let_days) * d.market_rent_pcm * 12 / 365, 2) AS rent_lost_to_voids
    FROM days d
    {at_date("p", "property_versions", "property_ref", "d.property_ref", "d.to_day")}
    """,
)

# P2: one row per empty spell: from purchase to the first let, between one tenancy ending
# and the next starting (a renewal starts the next day, so it leaves no gap), or still
# empty at the as-of date.
build(
    "fact_void_period",
    f"""
    WITH p AS (
        SELECT * FROM {latest("silver_property", "property_ref")} WHERE acquisition_date IS NOT NULL
    ),
    seq AS (
        SELECT t.property_ref, t.start_date, t.actual_end_date, t.tenancy_status,
               LAG(t.actual_end_date) OVER (PARTITION BY t.property_ref ORDER BY t.start_date) AS prev_end,
               ROW_NUMBER() OVER (PARTITION BY t.property_ref ORDER BY t.start_date) AS n
        FROM {latest("silver_tenancy", "tenancy_ref")} t
    ),
    past_voids AS (
        SELECT s.property_ref,
               CASE WHEN s.n = 1 THEN 'Before first let' ELSE 'Between tenancies' END AS void_type,
               CASE WHEN s.n = 1 THEN p.acquisition_date ELSE date_add(s.prev_end, 1) END AS void_start,
               date_sub(s.start_date, 1) AS void_end,
               false AS is_current_void
        FROM seq s JOIN p ON p.property_ref = s.property_ref
    ),
    current_voids AS (
        SELECT p.property_ref,
               CASE WHEN max(s.start_date) IS NULL THEN 'Before first let'
                    ELSE 'Between tenancies' END AS void_type,
               coalesce(date_add(max(s.actual_end_date), 1), p.acquisition_date) AS void_start,
               {AS_OF} AS void_end,
               true AS is_current_void
        FROM p LEFT JOIN seq s ON s.property_ref = p.property_ref
        WHERE p.disposal_date IS NULL
        GROUP BY p.property_ref, p.acquisition_date
        HAVING SUM(CASE WHEN s.tenancy_status IN ('Active', 'Periodic') THEN 1 ELSE 0 END) = 0
    ),
    voids AS (
        SELECT * FROM past_voids UNION ALL SELECT * FROM current_voids
    )
    SELECT v.property_ref,
           coalesce(cp.property_key, -1)                      AS property_key,
           v.void_type,
           {dk("v.void_start")}                               AS void_start_key,
           {dk("v.void_end")}                                 AS void_end_key,
           v.is_current_void,
           datediff(v.void_end, v.void_start) + 1             AS void_days,
           CASE WHEN month(v.void_start) IN (12, 1, 2) THEN 'Winter'
                WHEN month(v.void_start) IN (3, 4, 5)  THEN 'Spring'
                WHEN month(v.void_start) IN (6, 7, 8)  THEN 'Summer'
                ELSE 'Autumn' END                             AS season_started,
           round((datediff(v.void_end, v.void_start) + 1) * p.market_rent_pcm * 12 / 365, 2)
                                                              AS rent_lost
    FROM voids v
    JOIN p ON p.property_ref = v.property_ref
    LEFT JOIN current_property cp ON cp.property_ref = v.property_ref
    WHERE v.void_start IS NOT NULL AND v.void_end >= v.void_start
    """,
)

# P5: one row per shared owner's ownership period. Staircasing (buying a bigger share) is
# derived by comparing each period's share with the owner's previous one; time to first
# staircase is measured from their first purchase.
build(
    "fact_ownership_share",
    f"""
    WITH periods AS (
        SELECT o.*,
               LAG(percentage_share) OVER (PARTITION BY property_ref, tenant_ref
                                           ORDER BY effective_from) AS previous_share,
               MIN(effective_from) OVER (PARTITION BY property_ref, tenant_ref) AS purchase_date
        FROM {latest("silver_ownership", "owner_id")} o
        WHERE owner_type = 'Shared owner'
    ),
    events AS (
        SELECT *,
               CASE WHEN previous_share IS NULL              THEN 'Initial purchase'
                    WHEN percentage_share > previous_share   THEN 'Staircasing'
                    WHEN percentage_share < previous_share   THEN 'Share reduced'
                    ELSE 'No change' END AS event_type
        FROM periods
    ),
    first_stair AS (
        SELECT property_ref, tenant_ref, MIN(effective_from) AS first_staircase_date
        FROM events WHERE event_type = 'Staircasing'
        GROUP BY property_ref, tenant_ref
    ),
    leases AS (
        SELECT property_ref, start_date, full_market_value, rent_pcm
        FROM {latest("silver_tenancy", "tenancy_ref")}
        WHERE tenancy_type = 'Shared Ownership Lease'
    ),
    lease_before AS (  -- rent on the lease in place just before each ownership change
        SELECT e.owner_id, l.rent_pcm, l.full_market_value,
               ROW_NUMBER() OVER (PARTITION BY e.owner_id ORDER BY l.start_date DESC) AS rn
        FROM events e
        JOIN leases l ON l.property_ref = e.property_ref AND l.start_date < e.effective_from
    )
    SELECT e.owner_id,
           {dk("e.effective_from")}                           AS effective_from_key,
           coalesce(cp.property_key, -1)                      AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           e.effective_from, e.effective_to, e.is_current, e.event_type,
           e.percentage_share, e.previous_share,
           e.percentage_share - coalesce(e.previous_share, 0) AS share_increase_pct,
           CASE WHEN e.percentage_share < 25 THEN 'Under 25%'
                WHEN e.percentage_share < 50 THEN '25-49%'
                WHEN e.percentage_share < 75 THEN '50-74%'
                WHEN e.percentage_share < 100 THEN '75-99%'
                ELSE '100%' END                               AS share_band,
           e.percentage_share >= 100                          AS is_fully_owned,
           e.purchase_date,
           CASE WHEN e.event_type = 'Staircasing' AND e.effective_from = f.first_staircase_date
                THEN round(months_between(e.effective_from, e.purchase_date), 1) END
                                                              AS months_to_first_staircase,
           round((e.percentage_share - coalesce(e.previous_share, 0)) / 100
                 * lb.full_market_value, 2)                   AS share_bought_value,
           CASE WHEN e.percentage_share >= 100 AND e.event_type = 'Staircasing'
                THEN lb.rent_pcm END                          AS rent_lost_pcm
    FROM events e
    LEFT JOIN first_stair f ON f.property_ref = e.property_ref AND f.tenant_ref = e.tenant_ref
    LEFT JOIN lease_before lb ON lb.owner_id = e.owner_id AND lb.rn = 1
    LEFT JOIN current_property cp ON cp.property_ref = e.property_ref
    {at_date("tn", "tenant_versions", "tenant_ref", "e.tenant_ref", "e.effective_from")}
    """,
)

# P4: arrears risk for every current tenancy, at the as-of date. Four warning signs, each
# adding to a 0-100 score: stretched budget (30), late in 2 of the last 3 months (30),
# erratic payer (20), balance higher than 3 months ago (20).
build(
    "fact_arrears_risk",
    f"""
    WITH t AS (
        SELECT * FROM {latest("silver_tenancy", "tenancy_ref")}
        WHERE tenancy_status IN ('Active', 'Periodic')
    ),
    now_balance AS (
        SELECT tenancy_ref, balance FROM (
            SELECT tenancy_ref, balance,
                   ROW_NUMBER() OVER (PARTITION BY tenancy_ref ORDER BY month_key DESC) AS rn
            FROM {g}.fact_arrears_monthly WHERE month_key <= {dk(AS_OF)})
        WHERE rn = 1
    ),
    earlier_balance AS (
        SELECT tenancy_ref, balance FROM {g}.fact_arrears_monthly
        WHERE month_key = {dk(f"add_months(trunc({AS_OF}, 'MM'), -3)")}
    ),
    late AS (
        SELECT tenancy_ref, COUNT(DISTINCT period_key) AS late_months
        FROM {g}.fact_payment_timing
        WHERE timing = 'Late'
          AND period_key >= {dk(f"add_months(trunc({AS_OF}, 'MM'), -3)")}
          AND period_key <  {dk(f"trunc({AS_OF}, 'MM')")}
        GROUP BY tenancy_ref
    ),
    habit AS (
        SELECT tenancy_ref, max_by(payment_habit, paid_date_key) AS payment_habit
        FROM {g}.fact_payment_timing GROUP BY tenancy_ref
    ),
    flags AS (
        SELECT t.tenancy_ref, t.property_ref, t.lead_tenant_ref, t.rent_pcm,
               coalesce(ft.is_stretched, false)                        AS is_stretched,
               coalesce(l.late_months, 0)                              AS late_months_last_3,
               coalesce(l.late_months, 0) >= 2                         AS is_late_2_of_3,
               h.payment_habit,
               h.payment_habit = 'Erratic'                             AS is_erratic,
               coalesce(nb.balance, 0)                                 AS balance_now,
               coalesce(eb.balance, 0)                                 AS balance_3_months_ago,
               coalesce(nb.balance, 0) > 0
                 AND coalesce(nb.balance, 0) > coalesce(eb.balance, 0) AS is_balance_rising
        FROM t
        LEFT JOIN {g}.fact_tenancy ft ON ft.tenancy_ref = t.tenancy_ref
        LEFT JOIN late l              ON l.tenancy_ref = t.tenancy_ref
        LEFT JOIN habit h             ON h.tenancy_ref = t.tenancy_ref
        LEFT JOIN now_balance nb      ON nb.tenancy_ref = t.tenancy_ref
        LEFT JOIN earlier_balance eb  ON eb.tenancy_ref = t.tenancy_ref
    )
    SELECT f.tenancy_ref,
           coalesce(cp.property_key, -1)                      AS property_key,
           coalesce(tn.tenant_key, -1)                        AS tenant_key,
           f.rent_pcm, f.balance_now, f.balance_3_months_ago,
           f.is_stretched, f.late_months_last_3, f.is_late_2_of_3, f.payment_habit,
           f.is_erratic, f.is_balance_rising,
           30 * CAST(f.is_stretched AS INT) + 30 * CAST(f.is_late_2_of_3 AS INT)
             + 20 * CAST(coalesce(f.is_erratic, false) AS INT)
             + 20 * CAST(f.is_balance_rising AS INT)          AS risk_score,
           CASE WHEN 30 * CAST(f.is_stretched AS INT) + 30 * CAST(f.is_late_2_of_3 AS INT)
                     + 20 * CAST(coalesce(f.is_erratic, false) AS INT)
                     + 20 * CAST(f.is_balance_rising AS INT) >= 50 THEN 'High'
                WHEN 30 * CAST(f.is_stretched AS INT) + 30 * CAST(f.is_late_2_of_3 AS INT)
                     + 20 * CAST(coalesce(f.is_erratic, false) AS INT)
                     + 20 * CAST(f.is_balance_rising AS INT) >= 30 THEN 'Medium'
                ELSE 'Low' END                                AS risk_band
    FROM flags f
    LEFT JOIN current_property cp ON cp.property_ref = f.property_ref
    LEFT JOIN {g}.dim_tenant tn   ON tn.tenant_ref = f.lead_tenant_ref AND tn.is_current
    """,
)

# %% [markdown]
# ## Operations: maintenance and compliance

# %%
# Repair speed, contractors not used, jobs open over 15 days, callbacks: one row per job,
# with its issue's details. A callback is a new issue on the same home and same fault
# within 30 days of the job being completed.
build(
    "fact_repair_job",
    f"""
    WITH j AS {latest("silver_repair_job", "job_id")},
    i AS {latest("silver_repair_issue", "issue_id")},
    jobs AS (
        SELECT j.*, i.property_ref, i.fault_category, i.issue_type, i.is_emergency,
               i.status AS issue_status, i.close_reason, i.created_at AS reported_at
        FROM j LEFT JOIN i ON i.issue_id = j.issue_id
    ),
    callbacks AS (
        SELECT jb.job_id, COUNT(*) AS callbacks
        FROM jobs jb
        JOIN i ON i.property_ref = jb.property_ref
              AND i.fault_category = jb.fault_category
              AND i.issue_id <> jb.issue_id
              AND i.created_at >  jb.completed_at
              AND i.created_at <= jb.completed_at + INTERVAL 30 DAYS
        GROUP BY jb.job_id
    )
    SELECT jb.job_id, jb.issue_id,
           {dk("jb.created_at")}                              AS created_date_key,
           {dk("jb.completed_at")}                            AS completed_date_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(su.supplier_key, -1)                      AS supplier_key,
           jb.fault_category, jb.issue_type, jb.is_emergency,
           jb.close_reason = 'Referred to developer'          AS is_referred_to_developer,
           jb.completed_at IS NOT NULL                        AS is_completed,
           jb.completed_at IS NULL
             AND coalesce(jb.issue_status, '') NOT IN ('Closed', 'JobCompleted') AS is_open,
           CASE WHEN jb.completed_at IS NULL THEN datediff({AS_OF}, CAST(jb.created_at AS DATE)) END
                                                              AS open_age_days,
           jb.completed_at IS NULL
             AND coalesce(jb.issue_status, '') NOT IN ('Closed', 'JobCompleted')
             AND datediff({AS_OF}, CAST(jb.created_at AS DATE)) > 15 AS is_open_over_15_days,
           round((unix_timestamp(jb.completed_at) - unix_timestamp(jb.created_at)) / 86400, 1)
                                                              AS days_to_complete,
           round((unix_timestamp(jb.completed_at) - unix_timestamp(jb.reported_at)) / 86400, 1)
                                                              AS days_reported_to_complete,
           coalesce(cb.callbacks, 0) > 0                      AS has_callback_30_days,
           jb.payable_net, jb.payable_tax, jb.payable_gross, jb.quoted_gross
    FROM jobs jb
    LEFT JOIN callbacks cb        ON cb.job_id = jb.job_id
    LEFT JOIN {g}.dim_supplier su ON su.supplier_code = jb.supplier_code
    {at_date("p", "property_versions", "property_ref", "jb.property_ref", "jb.created_at")}
    """,
)

# Expired / missing compliance: one row per rental home held today and certificate it
# needs (Gas Safety only where the home has gas; EICR and EPC always), with the newest
# certificate of that type and its status at the as-of date.
build(
    "fact_compliance_status",
    f"""
    WITH homes AS (
        SELECT property_ref, has_gas FROM {latest("silver_property", "property_ref")}
        WHERE tenure = 'PRS' AND disposal_date IS NULL
    ),
    required AS (
        SELECT h.property_ref, r.certificate_type
        FROM homes h
        LATERAL VIEW explode(array('Gas Safety Certificate', 'EICR', 'EPC')) r AS certificate_type
        WHERE r.certificate_type <> 'Gas Safety Certificate' OR h.has_gas
    ),
    newest AS (
        SELECT * FROM (
            SELECT c.*, ROW_NUMBER() OVER (PARTITION BY property_ref, certificate_type
                                           ORDER BY issue_date DESC) AS rn
            FROM {latest("silver_compliance_certificate", "certificate_id")} c)
        WHERE rn = 1
    ),
    status AS (
        SELECT r.property_ref, r.certificate_type, n.certificate_id, n.issue_date,
               n.expiry_date, n.outcome, n.supplier_code,
               datediff(n.expiry_date, {AS_OF}) AS days_to_expiry,
               CASE WHEN n.certificate_id IS NULL                      THEN 'Missing'
                    WHEN n.expiry_date < {AS_OF}                       THEN 'Expired'
                    WHEN n.expiry_date <= date_add({AS_OF}, 30)        THEN 'Expires in 30 days'
                    WHEN n.expiry_date <= date_add({AS_OF}, 60)        THEN 'Expires in 31-60 days'
                    WHEN n.expiry_date <= date_add({AS_OF}, 90)        THEN 'Expires in 61-90 days'
                    ELSE 'Valid' END AS status
        FROM required r
        LEFT JOIN newest n ON n.property_ref = r.property_ref AND n.certificate_type = r.certificate_type
    )
    SELECT coalesce(cp.property_key, -1)                      AS property_key,
           coalesce(su.supplier_key, -1)                      AS supplier_key,
           st.certificate_type, st.certificate_id,
           {dk("st.issue_date")}                              AS issue_date_key,
           {dk("st.expiry_date")}                             AS expiry_date_key,
           st.outcome, st.days_to_expiry, st.status,
           st.status NOT IN ('Missing', 'Expired')            AS is_compliant,
           {AS_OF}                                            AS as_of_date
    FROM status st
    LEFT JOIN current_property cp ON cp.property_ref = st.property_ref
    LEFT JOIN {g}.dim_supplier su ON su.supplier_code = st.supplier_code
    """,
)

# %% [markdown]
# ## Operations: lettings

# %%
# Funnel, days to let, lets agreed by month, asking vs achieved, negotiators: one row per
# listing.
build(
    "fact_lettings_funnel",
    f"""
    WITH v AS (
        SELECT listing_id, COUNT(*) AS viewings,
               SUM(CASE WHEN outcome <> 'Did not attend' THEN 1 ELSE 0 END) AS viewings_attended
        FROM {s}.silver_viewing GROUP BY listing_id
    ),
    o AS (
        SELECT listing_id, COUNT(*) AS offers,
               SUM(CASE WHEN offer_status = 'Accepted' THEN 1 ELSE 0 END) AS accepted_offers
        FROM {s}.silver_offer GROUP BY listing_id
    )
    SELECT l.listing_id,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(st.staff_key, -1)                         AS negotiator_staff_key,
           {dk("l.listed_date")}                              AS listed_date_key,
           {dk("l.agreed_date")}                              AS agreed_date_key,
           {dk("l.completion_date")}                          AS move_in_date_key,
           l.listing_type, l.listing_status,
           coalesce(v.viewings, 0)                            AS viewings,
           coalesce(v.viewings_attended, 0)                   AS viewings_attended,
           coalesce(o.offers, 0)                              AS offers,
           coalesce(o.accepted_offers, 0)                     AS accepted_offers,
           l.agreed_date IS NOT NULL                          AS is_agreed,
           l.completion_date IS NOT NULL                      AS is_moved_in,
           l.listing_status = 'Available'                     AS is_available,
           datediff(l.agreed_date, l.listed_date)             AS days_to_agree,
           datediff(l.completion_date, l.listed_date)         AS days_to_move_in,
           coalesce(l.asking_rent_pcm, l.asking_price)        AS asking,
           coalesce(l.achieved_rent_pcm, l.achieved_price)    AS achieved,
           round(100 * (coalesce(l.achieved_rent_pcm, l.achieved_price)
                        / coalesce(l.asking_rent_pcm, l.asking_price) - 1), 2) AS achieved_vs_asking_pct
    FROM {latest("silver_listing", "listing_id")} l
    LEFT JOIN v ON v.listing_id = l.listing_id
    LEFT JOIN o ON o.listing_id = l.listing_id
    LEFT JOIN {g}.dim_staff st ON st.staff_code = l.negotiator_code
    {at_date("p", "property_versions", "property_ref", "l.property_ref", "l.listed_date")}
    """,
)

# Viewings by month and weekday, viewings per applicant and negotiator: one row per viewing.
build(
    "fact_viewing",
    f"""
    SELECT v.viewing_id, v.listing_id,
           {dk("v.viewing_date")}                             AS viewing_date_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(a.applicant_key, -1)                      AS applicant_key,
           coalesce(st.staff_key, -1)                         AS negotiator_staff_key,
           l.listing_type, v.outcome,
           v.outcome <> 'Did not attend'                      AS attended,
           v.outcome = 'Offer made'                           AS led_to_offer
    FROM {latest("silver_viewing", "viewing_id")} v
    LEFT JOIN {latest("silver_listing", "listing_id")} l ON l.listing_id = v.listing_id
    LEFT JOIN {g}.dim_applicant a ON a.applicant_id = v.applicant_id
    LEFT JOIN {g}.dim_staff st    ON st.staff_code = v.negotiator_code
    {at_date("p", "property_versions", "property_ref", "l.property_ref", "v.viewing_date")}
    """,
)

# Rejected vs accepted offers, registration to move-in: one row per offer. Each offer is
# compared with the offer accepted on the same listing; for accepted offers, the days
# from the applicant registering with Engage to moving in.
build(
    "fact_offer",
    f"""
    WITH accepted AS (
        SELECT listing_id, max(offer_amount) AS accepted_amount
        FROM {s}.silver_offer WHERE offer_status = 'Accepted' GROUP BY listing_id
    )
    SELECT o.offer_id, o.listing_id,
           {dk("o.offer_date")}                               AS offer_date_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(a.applicant_key, -1)                      AS applicant_key,
           coalesce(st.staff_key, -1)                         AS negotiator_staff_key,
           l.listing_type, o.offer_status, o.offer_amount,
           coalesce(l.asking_rent_pcm, l.asking_price)        AS asking,
           ac.accepted_amount,
           round(100 * (o.offer_amount / ac.accepted_amount - 1), 2) AS vs_accepted_pct,
           round(100 * (o.offer_amount / coalesce(l.asking_rent_pcm, l.asking_price) - 1), 2)
                                                              AS vs_asking_pct,
           CASE WHEN o.offer_status = 'Accepted'
                THEN datediff(l.completion_date, a.registered_date) END AS days_registration_to_move_in
    FROM {latest("silver_offer", "offer_id")} o
    LEFT JOIN {latest("silver_listing", "listing_id")} l ON l.listing_id = o.listing_id
    LEFT JOIN accepted ac          ON ac.listing_id = o.listing_id
    LEFT JOIN {g}.dim_applicant a  ON a.applicant_id = o.applicant_id
    LEFT JOIN {g}.dim_staff st     ON st.staff_code = l.negotiator_code
    {at_date("p", "property_versions", "property_ref", "l.property_ref", "o.offer_date")}
    """,
)

# %% [markdown]
# ## Finance: spend

# %%
# F5: one row per supplier invoice. Invoice lag = days from the FixFlo job being completed
# to the invoice date (repairs and compliance work; other spend has no job).
build(
    "fact_purchase_invoice",
    f"""
    SELECT v.invoice_id,
           {dk("v.invoice_date")}                             AS invoice_date_key,
           coalesce(p.property_key, -1)                       AS property_key,
           coalesce(su.supplier_key, -1)                      AS supplier_key,
           v.category, v.sub_category, v.status,
           v.net_amount, v.vat_amount, v.gross_amount,
           CAST(j.completed_at AS DATE)                       AS work_completed_date,
           datediff(v.invoice_date, CAST(j.completed_at AS DATE)) AS invoice_lag_days
    FROM {latest("silver_purchase_invoice", "invoice_id")} v
    LEFT JOIN {latest("silver_repair_issue", "issue_id")} i ON i.issue_id = v.fixflo_issue_id
    LEFT JOIN {latest("silver_repair_job", "job_id")} j     ON j.job_id = i.job_id
    LEFT JOIN {g}.dim_supplier su ON su.supplier_code = v.supplier_code
    {at_date("p", "property_versions", "property_ref", "v.property_ref", "v.invoice_date")}
    """,
)

print("Gold build complete")
