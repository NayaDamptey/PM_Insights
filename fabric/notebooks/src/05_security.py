# %% [markdown]
# # 05_security: who may see which homes
#
# Builds `security_user_access` in **ll_gold**: one row per user per location they may
# see. The Power BI roles filter on it (see governance/rls.md).
#
# | Staff role | access_level | Locations |
# |---|---|---|
# | Property Manager | own homes | the towns of the homes they manage |
# | Lettings / Sales Negotiator, Lettings Manager | region | every town in their region |
#
# Leavers (`is_active = false`) get no rows, so access ends with the next run.
# Head Office and Data Steward users see everything and need no rows.
#
# Attach **ll_gold** (default) and **ll_silver**.

# %% tags=["parameters"]
silver_db = "ll_silver"
gold_db = "ll_gold"

# %%
spark.sql(f"""
    CREATE OR REPLACE TABLE {gold_db}.security_user_access USING DELTA AS
    WITH staff AS (
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY staff_code ORDER BY loaded_at DESC) AS rn
            FROM {silver_db}.silver_staff WHERE staff_code IS NOT NULL)
        WHERE rn = 1 AND is_active
    ),
    homes AS (
        SELECT DISTINCT manager_staff_code, town, region
        FROM {silver_db}.silver_property
        WHERE property_status <> 'Sold'
    )
    -- property managers: the towns of the homes they manage
    SELECT s.email AS user_email, s.staff_code, s.role, h.region, h.town AS location,
           'own homes' AS access_level
    FROM staff s JOIN homes h ON h.manager_staff_code = s.staff_code
    WHERE s.is_property_manager
    UNION
    -- negotiators and lettings managers: every town in their region
    SELECT s.email, s.staff_code, s.role, h.region, h.town, 'region'
    FROM staff s JOIN (SELECT DISTINCT town, region FROM homes) h ON h.region = s.region
    WHERE NOT s.is_property_manager
""")

summary = spark.sql(f"""
    SELECT access_level, COUNT(DISTINCT user_email) AS users, COUNT(*) AS rows
    FROM {gold_db}.security_user_access GROUP BY access_level
""")
summary.show()
