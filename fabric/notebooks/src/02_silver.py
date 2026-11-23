# %% [markdown]
# # 02_silver: Bronze text tables -> typed, conformed Silver tables
#
# Builds exactly the Silver tables in the data dictionary (`Layer = Silver`), in the
# **ll_silver** lakehouse:
#
# 1. **Stage** – one SQL query per Silver table reads the latest Bronze load, renames the
#    source fields to their Silver names and makes the joins the dictionary asks for.
#    Values are still text here and are not cleaned, trimmed or de-duplicated.
# 2. **Type** – every column is converted to its dictionary type with `TRY_CAST`. A value
#    that will not convert becomes NULL and is written to `_cast_errors`, so the data
#    quality checks (03_dq) can report it.
# 3. **Merge** – `MERGE` on the table's key, so running the notebook twice gives the same
#    result. Full loads also remove rows that have gone from the source.
#
# Attach **ll_silver** (default) and **ll_bronze** to this notebook.

# %% tags=["parameters"]
run_id = ""  # blank: the latest Bronze run
bronze_db = "ll_bronze"
silver_db = "ll_silver"

# %% [markdown]
# ## The contract
# Generated from the data dictionary: every Silver table, its key, where it comes from,
# and each column with its type. The staging queries below must return these columns.

# %%
# --- generated: contract ---
SILVER_CONTRACT = {'silver_staff': {'key': ['staff_code'],
                  'source_system': 'MRI Qube PM, MRI Engage CRM, FixFlo',
                  'source_table': 'qube_staff, engage_negotiators, fixflo_agents',
                  'columns': [('staff_code', 'STRING'),
                              ('first_name', 'STRING'),
                              ('last_name', 'STRING'),
                              ('full_name', 'STRING'),
                              ('role', 'STRING'),
                              ('region', 'STRING'),
                              ('location', 'STRING'),
                              ('email', 'STRING'),
                              ('start_date', 'DATE'),
                              ('end_date', 'DATE'),
                              ('is_active', 'BOOLEAN'),
                              ('is_property_manager', 'BOOLEAN'),
                              ('is_negotiator', 'BOOLEAN'),
                              ('fixflo_agent_id', 'STRING'),
                              ('source_system', 'STRING'),
                              ('source_table', 'STRING'),
                              ('loaded_at', 'TIMESTAMP')],
                  'foreign_keys': []},
 'silver_block': {'key': ['block_ref'],
                  'source_system': 'MRI Qube PM, FixFlo',
                  'source_table': 'qube_blocks, fixflo_blocks',
                  'columns': [('block_ref', 'STRING'),
                              ('block_name', 'STRING'),
                              ('address_line1', 'STRING'),
                              ('town', 'STRING'),
                              ('county', 'STRING'),
                              ('postcode', 'STRING'),
                              ('region', 'STRING'),
                              ('latitude', 'DECIMAL(9,5)'),
                              ('longitude', 'DECIMAL(9,5)'),
                              ('floors', 'INT'),
                              ('built_year', 'INT'),
                              ('units', 'INT'),
                              ('fixflo_block_id', 'STRING'),
                              ('source_system', 'STRING'),
                              ('source_table', 'STRING'),
                              ('loaded_at', 'TIMESTAMP')],
                  'foreign_keys': []},
 'silver_property': {'key': ['property_ref'],
                     'source_system': 'MRI Qube PM, FixFlo',
                     'source_table': 'qube_properties, fixflo_properties',
                     'columns': [('property_ref', 'STRING'),
                                 ('block_ref', 'STRING'),
                                 ('address_line1', 'STRING'),
                                 ('address_line2', 'STRING'),
                                 ('town', 'STRING'),
                                 ('county', 'STRING'),
                                 ('postcode', 'STRING'),
                                 ('region', 'STRING'),
                                 ('latitude', 'DECIMAL(9,5)'),
                                 ('longitude', 'DECIMAL(9,5)'),
                                 ('property_type', 'STRING'),
                                 ('bedrooms', 'INT'),
                                 ('bathrooms', 'INT'),
                                 ('tenure', 'STRING'),
                                 ('department', 'STRING'),
                                 ('has_gas', 'BOOLEAN'),
                                 ('manager_staff_code', 'STRING'),
                                 ('acquisition_date', 'DATE'),
                                 ('acquisition_cost', 'DECIMAL(18,2)'),
                                 ('market_value', 'DECIMAL(18,2)'),
                                 ('market_rent_pcm', 'DECIMAL(18,2)'),
                                 ('property_status', 'STRING'),
                                 ('disposal_date', 'DATE'),
                                 ('disposal_value', 'DECIMAL(18,2)'),
                                 ('fixflo_property_id', 'STRING'),
                                 ('source_system', 'STRING'),
                                 ('source_table', 'STRING'),
                                 ('loaded_at', 'TIMESTAMP')],
                     'foreign_keys': [('block_ref', 'silver_block'),
                                      ('manager_staff_code', 'silver_staff')]},
 'silver_landlord': {'key': ['landlord_ref'],
                     'source_system': 'MRI Qube PM',
                     'source_table': 'qube_landlords, qube_landlord_bank_accounts',
                     'columns': [('landlord_ref', 'STRING'),
                                 ('landlord_name', 'STRING'),
                                 ('category', 'STRING'),
                                 ('email', 'STRING'),
                                 ('phone', 'STRING'),
                                 ('address_line1', 'STRING'),
                                 ('town', 'STRING'),
                                 ('county', 'STRING'),
                                 ('postcode', 'STRING'),
                                 ('created_date', 'DATE'),
                                 ('modified_date', 'DATE'),
                                 ('bank_account_name', 'STRING'),
                                 ('bank_sort_code', 'STRING'),
                                 ('bank_account_number', 'STRING'),
                                 ('source_system', 'STRING'),
                                 ('source_table', 'STRING'),
                                 ('loaded_at', 'TIMESTAMP')],
                     'foreign_keys': []},
 'silver_tenant': {'key': ['tenant_ref'],
                   'source_system': 'MRI Qube PM',
                   'source_table': 'qube_tenants',
                   'columns': [('tenant_ref', 'STRING'),
                               ('title', 'STRING'),
                               ('first_name', 'STRING'),
                               ('last_name', 'STRING'),
                               ('full_name', 'STRING'),
                               ('email', 'STRING'),
                               ('mobile', 'STRING'),
                               ('engage_applicant_id', 'STRING'),
                               ('right_to_rent_checked', 'BOOLEAN'),
                               ('right_to_rent_check_date', 'DATE'),
                               ('source_system', 'STRING'),
                               ('source_table', 'STRING'),
                               ('loaded_at', 'TIMESTAMP')],
                   'foreign_keys': [('engage_applicant_id', 'silver_applicant')]},
 'silver_applicant': {'key': ['applicant_id'],
                      'source_system': 'MRI Engage CRM',
                      'source_table': 'engage_applicants',
                      'columns': [('applicant_id', 'STRING'),
                                  ('applicant_type', 'STRING'),
                                  ('first_name', 'STRING'),
                                  ('last_name', 'STRING'),
                                  ('email', 'STRING'),
                                  ('mobile', 'STRING'),
                                  ('registered_date', 'DATE'),
                                  ('preferred_town', 'STRING'),
                                  ('min_bedrooms', 'INT'),
                                  ('max_budget', 'DECIMAL(18,2)'),
                                  ('status', 'STRING'),
                                  ('negotiator_code', 'STRING'),
                                  ('qube_tenant_ref', 'STRING'),
                                  ('source_system', 'STRING'),
                                  ('source_table', 'STRING'),
                                  ('loaded_at', 'TIMESTAMP')],
                      'foreign_keys': [('negotiator_code', 'silver_staff'),
                                       ('qube_tenant_ref', 'silver_tenant')]},
 'silver_tenancy': {'key': ['tenancy_ref'],
                    'source_system': 'MRI Qube PM',
                    'source_table': 'qube_tenancies',
                    'columns': [('tenancy_ref', 'STRING'),
                                ('property_ref', 'STRING'),
                                ('lead_tenant_ref', 'STRING'),
                                ('previous_tenancy_ref', 'STRING'),
                                ('tenancy_type', 'STRING'),
                                ('start_date', 'DATE'),
                                ('fixed_term_end_date', 'DATE'),
                                ('actual_end_date', 'DATE'),
                                ('tenancy_status', 'STRING'),
                                ('rent_pcm', 'DECIMAL(18,2)'),
                                ('rent_frequency', 'STRING'),
                                ('rent_due_day', 'DECIMAL(18,2)'),
                                ('ownership_share_pct', 'DECIMAL(18,2)'),
                                ('full_market_value', 'DECIMAL(18,2)'),
                                ('share_value', 'DECIMAL(18,2)'),
                                ('rent_rate_pct', 'DECIMAL(18,2)'),
                                ('rent_percentage_paid', 'DECIMAL(18,2)'),
                                ('deposit_amount', 'DECIMAL(18,2)'),
                                ('deposit_scheme', 'STRING'),
                                ('deposit_protected_date', 'DATE'),
                                ('deposit_status', 'STRING'),
                                ('closing_balance', 'DECIMAL(18,2)'),
                                ('last_updated_date', 'DATE'),
                                ('source_system', 'STRING'),
                                ('source_table', 'STRING'),
                                ('loaded_at', 'TIMESTAMP')],
                    'foreign_keys': [('property_ref', 'silver_property'),
                                     ('lead_tenant_ref', 'silver_tenant')]},
 'silver_tenancy_tenant': {'key': ['tenancy_ref', 'tenant_ref'],
                           'source_system': 'MRI Qube PM',
                           'source_table': 'qube_tenancy_tenants',
                           'columns': [('tenancy_ref', 'STRING'),
                                       ('tenant_ref', 'STRING'),
                                       ('is_lead_tenant', 'BOOLEAN'),
                                       ('rent_share_pct', 'DECIMAL(18,2)'),
                                       ('start_date', 'DATE'),
                                       ('end_date', 'DATE'),
                                       ('source_system', 'STRING'),
                                       ('source_table', 'STRING'),
                                       ('loaded_at', 'TIMESTAMP')],
                           'foreign_keys': [('tenant_ref', 'silver_tenant')]},
 'silver_ownership': {'key': ['owner_id'],
                      'source_system': 'MRI Qube PM',
                      'source_table': 'qube_property_owners',
                      'columns': [('owner_id', 'STRING'),
                                  ('property_ref', 'STRING'),
                                  ('owner_type', 'STRING'),
                                  ('landlord_ref', 'STRING'),
                                  ('tenant_ref', 'STRING'),
                                  ('percentage_share', 'DECIMAL(18,2)'),
                                  ('effective_from', 'DATE'),
                                  ('effective_to', 'DATE'),
                                  ('is_current', 'BOOLEAN'),
                                  ('source_system', 'STRING'),
                                  ('source_table', 'STRING'),
                                  ('loaded_at', 'TIMESTAMP')],
                      'foreign_keys': [('property_ref', 'silver_property'),
                                       ('landlord_ref', 'silver_landlord'),
                                       ('tenant_ref', 'silver_tenant')]},
 'silver_rent_transaction': {'key': ['transaction_id'],
                             'source_system': 'MRI Qube PM',
                             'source_table': 'qube_transactions',
                             'columns': [('transaction_id', 'STRING'),
                                         ('tenancy_ref', 'STRING'),
                                         ('property_ref', 'STRING'),
                                         ('tenant_ref', 'STRING'),
                                         ('transaction_date', 'DATE'),
                                         ('period_month', 'DATE'),
                                         ('transaction_type', 'STRING'),
                                         ('transaction_group', 'STRING'),
                                         ('amount', 'DECIMAL(18,2)'),
                                         ('payment_method', 'STRING'),
                                         ('reference', 'STRING'),
                                         ('ownership_share_pct', 'DECIMAL(18,2)'),
                                         ('source_system', 'STRING'),
                                         ('source_table', 'STRING'),
                                         ('loaded_at', 'TIMESTAMP')],
                             'foreign_keys': [('tenancy_ref', 'silver_tenancy'),
                                              ('property_ref', 'silver_property'),
                                              ('tenant_ref', 'silver_tenant')]},
 'silver_income_category': {'key': ['income_category'],
                            'source_system': 'MRI Qube PM',
                            'source_table': 'qube_income_categories',
                            'columns': [('income_category', 'STRING'),
                                        ('description', 'STRING'),
                                        ('priority_code', 'STRING'),
                                        ('billing_frequency', 'STRING'),
                                        ('source_system', 'STRING'),
                                        ('source_table', 'STRING'),
                                        ('loaded_at', 'TIMESTAMP')],
                            'foreign_keys': []},
 'silver_suspense_item': {'key': ['item_id'],
                          'source_system': 'MRI Qube PM',
                          'source_table': 'qube_suspense_items',
                          'columns': [('item_id', 'STRING'),
                                      ('item_type', 'STRING'),
                                      ('property_ref', 'STRING'),
                                      ('raised_date', 'DATE'),
                                      ('amount', 'DECIMAL(18,2)'),
                                      ('status', 'STRING'),
                                      ('cleared_date', 'DATE'),
                                      ('owner_staff_code', 'STRING'),
                                      ('notes', 'STRING'),
                                      ('source_system', 'STRING'),
                                      ('source_table', 'STRING'),
                                      ('loaded_at', 'TIMESTAMP')],
                          'foreign_keys': [('property_ref', 'silver_property'),
                                           ('owner_staff_code', 'silver_staff')]},
 'silver_supplier': {'key': ['supplier_code'],
                     'source_system': 'MRI Qube PM, FixFlo',
                     'source_table': 'qube_suppliers, fixflo_contractors',
                     'columns': [('supplier_code', 'STRING'),
                                 ('fixflo_contractor_id', 'STRING'),
                                 ('supplier_name', 'STRING'),
                                 ('trade', 'STRING'),
                                 ('region', 'STRING'),
                                 ('email', 'STRING'),
                                 ('phone', 'STRING'),
                                 ('gas_safe_number', 'STRING'),
                                 ('insurance_expiry', 'DATE'),
                                 ('is_active', 'BOOLEAN'),
                                 ('is_vat_registered', 'BOOLEAN'),
                                 ('source_system', 'STRING'),
                                 ('source_table', 'STRING'),
                                 ('loaded_at', 'TIMESTAMP')],
                     'foreign_keys': []},
 'silver_purchase_invoice': {'key': ['invoice_id'],
                             'source_system': 'MRI Qube PM',
                             'source_table': 'qube_purchase_invoices',
                             'columns': [('invoice_id', 'STRING'),
                                         ('supplier_code', 'STRING'),
                                         ('property_ref', 'STRING'),
                                         ('block_ref', 'STRING'),
                                         ('invoice_date', 'DATE'),
                                         ('category', 'STRING'),
                                         ('sub_category', 'STRING'),
                                         ('net_amount', 'DECIMAL(18,2)'),
                                         ('vat_amount', 'DECIMAL(18,2)'),
                                         ('gross_amount', 'DECIMAL(18,2)'),
                                         ('fixflo_issue_id', 'STRING'),
                                         ('status', 'STRING'),
                                         ('source_system', 'STRING'),
                                         ('source_table', 'STRING'),
                                         ('loaded_at', 'TIMESTAMP')],
                             'foreign_keys': [('supplier_code', 'silver_supplier'),
                                              ('property_ref', 'silver_property'),
                                              ('block_ref', 'silver_block')]},
 'silver_compliance_certificate': {'key': ['certificate_id'],
                                   'source_system': 'MRI Qube PM',
                                   'source_table': 'qube_compliance_certificates',
                                   'columns': [('certificate_id', 'STRING'),
                                               ('property_ref', 'STRING'),
                                               ('certificate_type', 'STRING'),
                                               ('issue_date', 'DATE'),
                                               ('expiry_date', 'DATE'),
                                               ('supplier_code', 'STRING'),
                                               ('outcome', 'STRING'),
                                               ('document_ref', 'STRING'),
                                               ('source_system', 'STRING'),
                                               ('source_table', 'STRING'),
                                               ('loaded_at', 'TIMESTAMP')],
                                   'foreign_keys': [('property_ref', 'silver_property'),
                                                    ('supplier_code', 'silver_supplier')]},
 'silver_repair_issue': {'key': ['issue_id'],
                         'source_system': 'FixFlo',
                         'source_table': 'fixflo_issues, fixflo_properties',
                         'columns': [('issue_id', 'STRING'),
                                     ('property_ref', 'STRING'),
                                     ('fixflo_property_id', 'STRING'),
                                     ('block_ref', 'STRING'),
                                     ('tenancy_ref', 'STRING'),
                                     ('issue_type', 'STRING'),
                                     ('title', 'STRING'),
                                     ('fault_title', 'STRING'),
                                     ('fault_category', 'STRING'),
                                     ('priority', 'INT'),
                                     ('is_emergency', 'BOOLEAN'),
                                     ('is_communal', 'BOOLEAN'),
                                     ('status', 'STRING'),
                                     ('created_at', 'TIMESTAMP'),
                                     ('status_changed_at', 'TIMESTAMP'),
                                     ('close_reason', 'STRING'),
                                     ('close_reason_description', 'STRING'),
                                     ('job_id', 'STRING'),
                                     ('source_system', 'STRING'),
                                     ('source_table', 'STRING'),
                                     ('loaded_at', 'TIMESTAMP')],
                         'foreign_keys': [('property_ref', 'silver_property'),
                                          ('block_ref', 'silver_block'),
                                          ('tenancy_ref', 'silver_tenancy'),
                                          ('job_id', 'silver_repair_job')]},
 'silver_repair_job': {'key': ['job_id'],
                       'source_system': 'FixFlo',
                       'source_table': 'fixflo_jobs, fixflo_job_completion_details',
                       'columns': [('job_id', 'STRING'),
                                   ('issue_id', 'STRING'),
                                   ('supplier_code', 'STRING'),
                                   ('fixflo_contractor_id', 'STRING'),
                                   ('works_order_number', 'STRING'),
                                   ('created_at', 'TIMESTAMP'),
                                   ('start_at', 'TIMESTAMP'),
                                   ('completed_at', 'TIMESTAMP'),
                                   ('job_duration', 'STRING'),
                                   ('appointment', 'STRING'),
                                   ('payable_net', 'DECIMAL(18,2)'),
                                   ('payable_tax', 'DECIMAL(18,2)'),
                                   ('payable_gross', 'DECIMAL(18,2)'),
                                   ('quoted_gross', 'DECIMAL(18,2)'),
                                   ('invoice_number', 'STRING'),
                                   ('completion_date', 'DATE'),
                                   ('feedback', 'STRING'),
                                   ('source_system', 'STRING'),
                                   ('source_table', 'STRING'),
                                   ('loaded_at', 'TIMESTAMP')],
                       'foreign_keys': [('issue_id', 'silver_repair_issue'),
                                        ('supplier_code', 'silver_supplier')]},
 'silver_repair_quote': {'key': ['quote_id'],
                         'source_system': 'FixFlo',
                         'source_table': 'fixflo_quotes',
                         'columns': [('quote_id', 'STRING'),
                                     ('issue_id', 'STRING'),
                                     ('supplier_code', 'STRING'),
                                     ('status', 'STRING'),
                                     ('payable_net', 'DECIMAL(18,2)'),
                                     ('payable_tax', 'DECIMAL(18,2)'),
                                     ('payable_gross', 'DECIMAL(18,2)'),
                                     ('source_system', 'STRING'),
                                     ('source_table', 'STRING'),
                                     ('loaded_at', 'TIMESTAMP')],
                         'foreign_keys': [('issue_id', 'silver_repair_issue'),
                                          ('supplier_code', 'silver_supplier')]},
 'silver_listing': {'key': ['listing_id'],
                    'source_system': 'MRI Engage CRM',
                    'source_table': 'engage_listings',
                    'columns': [('listing_id', 'STRING'),
                                ('property_ref', 'STRING'),
                                ('listing_type', 'STRING'),
                                ('listed_date', 'DATE'),
                                ('asking_rent_pcm', 'DECIMAL(18,2)'),
                                ('asking_price', 'DECIMAL(18,2)'),
                                ('listing_status', 'STRING'),
                                ('agreed_date', 'DATE'),
                                ('completion_date', 'DATE'),
                                ('achieved_rent_pcm', 'DECIMAL(18,2)'),
                                ('achieved_price', 'DECIMAL(18,2)'),
                                ('negotiator_code', 'STRING'),
                                ('withdrawn_date', 'DATE'),
                                ('source_system', 'STRING'),
                                ('source_table', 'STRING'),
                                ('loaded_at', 'TIMESTAMP')],
                    'foreign_keys': [('property_ref', 'silver_property'),
                                     ('negotiator_code', 'silver_staff')]},
 'silver_viewing': {'key': ['viewing_id'],
                    'source_system': 'MRI Engage CRM',
                    'source_table': 'engage_viewings',
                    'columns': [('viewing_id', 'STRING'),
                                ('listing_id', 'STRING'),
                                ('applicant_id', 'STRING'),
                                ('viewing_date', 'DATE'),
                                ('outcome', 'STRING'),
                                ('negotiator_code', 'STRING'),
                                ('source_system', 'STRING'),
                                ('source_table', 'STRING'),
                                ('loaded_at', 'TIMESTAMP')],
                    'foreign_keys': [('listing_id', 'silver_listing'),
                                     ('applicant_id', 'silver_applicant'),
                                     ('negotiator_code', 'silver_staff')]},
 'silver_offer': {'key': ['offer_id'],
                  'source_system': 'MRI Engage CRM',
                  'source_table': 'engage_offers',
                  'columns': [('offer_id', 'STRING'),
                              ('listing_id', 'STRING'),
                              ('applicant_id', 'STRING'),
                              ('offer_date', 'DATE'),
                              ('offer_amount', 'DECIMAL(18,2)'),
                              ('offer_status', 'STRING'),
                              ('source_system', 'STRING'),
                              ('source_table', 'STRING'),
                              ('loaded_at', 'TIMESTAMP')],
                  'foreign_keys': [('listing_id', 'silver_listing'),
                                   ('applicant_id', 'silver_applicant')]},
 'silver_calendar': {'key': ['date'],
                     'source_system': 'Reference',
                     'source_table': 'dim_calendar',
                     'columns': [('date', 'DATE'),
                                 ('year', 'INT'),
                                 ('quarter', 'STRING'),
                                 ('month_number', 'STRING'),
                                 ('month_name', 'STRING'),
                                 ('month_short', 'STRING'),
                                 ('year_month', 'STRING'),
                                 ('year_quarter', 'STRING'),
                                 ('weekday_name', 'STRING'),
                                 ('is_weekend', 'BOOLEAN'),
                                 ('financial_year', 'STRING'),
                                 ('source_system', 'STRING'),
                                 ('source_table', 'STRING'),
                                 ('loaded_at', 'TIMESTAMP')],
                     'foreign_keys': []}}
# --- end generated ---

METADATA = ("source_system", "source_table", "loaded_at")

# %% [markdown]
# ## Which Bronze rows to use
# Bronze keeps every load. Silver is built from the most recent successful load of each
# Bronze table. A temporary view with the Bronze table's own name (e.g. `qube_staff`)
# points at just those rows, so the staging queries read like plain SQL.

# %%
from datetime import UTC, datetime

loaded_at = datetime.now(UTC).replace(tzinfo=None)

latest_loads = spark.sql(f"""
    WITH ranked AS (
        SELECT table_name, run_id, load_mode,
               ROW_NUMBER() OVER (PARTITION BY table_name ORDER BY ended_at DESC) AS rn
        FROM {bronze_db}._ingestion_log
        WHERE status = 'succeeded'
    )
    SELECT table_name, run_id, load_mode FROM ranked WHERE rn = 1
""").collect()

load_mode = {}
for row in latest_loads:
    spark.sql(f"""
        CREATE OR REPLACE TEMP VIEW {row.table_name} AS
        SELECT * FROM {bronze_db}.{row.table_name} WHERE _run_id = '{row.run_id}'
    """)
    load_mode[row.table_name] = row.load_mode

run_id = run_id or max(latest_loads, key=lambda r: r.run_id).run_id
print(f"Silver run {run_id}: {len(latest_loads)} Bronze tables available")

# %% [markdown]
# ## Staging queries
# One query per Silver table. Each returns the Silver column names (except the three
# load columns, which are added for every table) with values still as text.
#
# Lookups into another system (e.g. a FixFlo id by Qube reference) go through a CTE that
# keeps one row per lookup key with `ROW_NUMBER()`. If a source ever holds the same
# reference twice, the Silver row is not repeated; the duplicate itself is reported by
# the uniqueness checks in 03_dq.

# %%
STAGING = {}

# People: staff, landlords, tenants, applicants

STAGING["silver_staff"] = """
WITH negotiators AS (
    SELECT NegotiatorCode,
           ROW_NUMBER() OVER (PARTITION BY NegotiatorCode ORDER BY NegotiatorCode) AS rn
    FROM engage_negotiators
),
agents AS (
    SELECT ExternalRef, Id,
           ROW_NUMBER() OVER (PARTITION BY ExternalRef ORDER BY Id) AS rn
    FROM fixflo_agents
)
SELECT s.StaffCode                               AS staff_code,
       s.FirstName                               AS first_name,
       s.LastName                                AS last_name,
       concat_ws(' ', s.FirstName, s.LastName)   AS full_name,
       s.Role                                    AS role,
       s.Region                                  AS region,
       s.Location                                AS location,
       s.Email                                   AS email,
       s.StartDate                               AS start_date,
       s.EndDate                                 AS end_date,
       s.Active                                  AS is_active,
       CAST(s.Role = 'Property Manager' AS STRING)    AS is_property_manager,
       CAST(n.NegotiatorCode IS NOT NULL AS STRING)   AS is_negotiator,
       a.Id                                      AS fixflo_agent_id
FROM qube_staff s
LEFT JOIN negotiators n ON n.NegotiatorCode = s.StaffCode AND n.rn = 1
LEFT JOIN agents      a ON a.ExternalRef    = s.StaffCode AND a.rn = 1
"""

STAGING["silver_landlord"] = """
WITH bank AS (
    SELECT LandlordRef, AccountName, SortCode, AccountNumber,
           ROW_NUMBER() OVER (PARTITION BY LandlordRef ORDER BY AccountNumber) AS rn
    FROM qube_landlord_bank_accounts
)
SELECT l.LandlordRef                                     AS landlord_ref,
       l.CompanyName                                     AS landlord_name,
       l.Category                                        AS category,
       l.Email                                           AS email,
       l.Phone                                           AS phone,
       concat_ws(' ', l.AddressNameNumber, l.AddressStreet) AS address_line1,
       l.AddressTown                                     AS town,
       l.AddressCounty                                   AS county,
       l.AddressPostcode                                 AS postcode,
       l.CreatedDate                                     AS created_date,
       l.ModifiedDate                                    AS modified_date,
       b.AccountName                                     AS bank_account_name,
       b.SortCode                                        AS bank_sort_code,
       b.AccountNumber                                   AS bank_account_number
FROM qube_landlords l
LEFT JOIN bank b ON b.LandlordRef = l.LandlordRef AND b.rn = 1
"""

STAGING["silver_tenant"] = """
SELECT TenantRef                              AS tenant_ref,
       Title                                  AS title,
       FirstName                              AS first_name,
       LastName                               AS last_name,
       concat_ws(' ', FirstName, LastName)    AS full_name,
       Email                                  AS email,
       Mobile                                 AS mobile,
       EngageApplicantId                      AS engage_applicant_id,
       RightToRentChecked                     AS right_to_rent_checked,
       RightToRentCheckDate                   AS right_to_rent_check_date
FROM qube_tenants
"""

STAGING["silver_applicant"] = """
WITH housed AS (
    SELECT EngageApplicantId, TenantRef,
           ROW_NUMBER() OVER (PARTITION BY EngageApplicantId ORDER BY TenantRef) AS rn
    FROM qube_tenants
    WHERE EngageApplicantId IS NOT NULL
)
SELECT a.ApplicantId      AS applicant_id,
       a.ApplicantType    AS applicant_type,
       a.FirstName        AS first_name,
       a.LastName         AS last_name,
       a.Email            AS email,
       a.Mobile           AS mobile,
       a.RegisteredDate   AS registered_date,
       a.PreferredTown    AS preferred_town,
       a.MinBedrooms      AS min_bedrooms,
       a.MaxBudget        AS max_budget,
       a.Status           AS status,
       a.NegotiatorCode   AS negotiator_code,
       h.TenantRef        AS qube_tenant_ref
FROM engage_applicants a
LEFT JOIN housed h ON h.EngageApplicantId = a.ApplicantId AND h.rn = 1
"""

# %%
# Homes: blocks, properties, ownership

STAGING["silver_block"] = """
WITH fixflo AS (
    SELECT ExternalBlockReference, Id,
           ROW_NUMBER() OVER (PARTITION BY ExternalBlockReference ORDER BY Id) AS rn
    FROM fixflo_blocks
)
SELECT b.BlockRef                          AS block_ref,
       b.BlockName                         AS block_name,
       concat_ws(' ', b.StreetNumber, b.Street) AS address_line1,
       b.Town                              AS town,
       b.County                            AS county,
       b.Postcode                          AS postcode,
       b.Region                            AS region,
       b.Latitude                          AS latitude,
       b.Longitude                         AS longitude,
       b.Floors                            AS floors,
       b.BuiltYear                         AS built_year,
       b.Units                             AS units,
       f.Id                                AS fixflo_block_id
FROM qube_blocks b
LEFT JOIN fixflo f ON f.ExternalBlockReference = b.BlockRef AND f.rn = 1
"""

STAGING["silver_property"] = """
WITH fixflo AS (
    SELECT ExternalPropertyRef, id,
           ROW_NUMBER() OVER (PARTITION BY ExternalPropertyRef ORDER BY id) AS rn
    FROM fixflo_properties
)
SELECT p.PropertyRef        AS property_ref,
       p.BlockRef           AS block_ref,
       p.AddressLine1       AS address_line1,
       p.AddressLine2       AS address_line2,
       p.Town               AS town,
       p.County             AS county,
       p.Postcode           AS postcode,
       p.Region             AS region,
       p.Latitude           AS latitude,
       p.Longitude          AS longitude,
       p.PropertyType       AS property_type,
       p.Bedrooms           AS bedrooms,
       p.Bathrooms          AS bathrooms,
       p.Tenure             AS tenure,
       p.Department         AS department,
       p.GasSupply          AS has_gas,
       p.ManagerCode        AS manager_staff_code,
       p.AcquisitionDate    AS acquisition_date,
       p.AcquisitionCost    AS acquisition_cost,
       p.MarketValue        AS market_value,
       p.MarketRentPCM      AS market_rent_pcm,
       p.PropertyStatus     AS property_status,
       p.DisposalDate       AS disposal_date,
       p.DisposalValue      AS disposal_value,
       f.id                 AS fixflo_property_id
FROM qube_properties p
LEFT JOIN fixflo f ON f.ExternalPropertyRef = p.PropertyRef AND f.rn = 1
"""

STAGING["silver_ownership"] = """
SELECT OwnerId          AS owner_id,
       PropertyRef      AS property_ref,
       OwnerType        AS owner_type,
       LandlordRef      AS landlord_ref,
       TenantRef        AS tenant_ref,
       PercentageShare  AS percentage_share,
       EffectiveFrom    AS effective_from,
       EffectiveTo      AS effective_to,
       Active           AS is_current
FROM qube_property_owners
"""

# %%
# Tenancies and the rent ledger

STAGING["silver_tenancy"] = """
SELECT TenancyRef            AS tenancy_ref,
       PropertyRef           AS property_ref,
       LeadTenantRef         AS lead_tenant_ref,
       PreviousTenancyRef    AS previous_tenancy_ref,
       TenancyType           AS tenancy_type,
       StartDate             AS start_date,
       FixedTermEndDate      AS fixed_term_end_date,
       ActualEndDate         AS actual_end_date,
       TenancyStatus         AS tenancy_status,
       RentPCM               AS rent_pcm,
       RentFrequency         AS rent_frequency,
       RentDueDay            AS rent_due_day,
       OwnershipSharePct     AS ownership_share_pct,
       FullMarketValue       AS full_market_value,
       ShareValue            AS share_value,
       RentRatePct           AS rent_rate_pct,
       RentPercentagePaid    AS rent_percentage_paid,
       DepositAmount         AS deposit_amount,
       DepositScheme         AS deposit_scheme,
       DepositProtectedDate  AS deposit_protected_date,
       DepositStatus         AS deposit_status,
       ClosingBalance        AS closing_balance,
       LastUpdatedDate       AS last_updated_date
FROM qube_tenancies
"""

STAGING["silver_tenancy_tenant"] = """
SELECT TenancyRef     AS tenancy_ref,
       TenantRef      AS tenant_ref,
       IsLeadTenant   AS is_lead_tenant,
       RentSharePct   AS rent_share_pct,
       StartDate      AS start_date,
       EndDate        AS end_date
FROM qube_tenancy_tenants
"""

# transaction_group sorts the ledger's transaction types into the three groups the
# dictionary names. A type not listed here gets no group, which 03_dq reports.
STAGING["silver_rent_transaction"] = """
SELECT TransactionId       AS transaction_id,
       TenancyRef          AS tenancy_ref,
       PropertyRef         AS property_ref,
       TenantRef           AS tenant_ref,
       TransactionDate     AS transaction_date,
       Period              AS period_month,
       TransactionType     AS transaction_type,
       CASE
           WHEN TransactionType IN ('Rent charge', 'Service charge', 'Ground rent',
                                    'Tenant recharge invoice')        THEN 'Charge'
           WHEN TransactionType = 'Receipt'                           THEN 'Payment'
           WHEN TransactionType IN ('Deposit received', 'Deposit returned',
                                    'Deposit deduction')              THEN 'Deposit'
       END                 AS transaction_group,
       Amount              AS amount,
       PaymentMethod       AS payment_method,
       Reference           AS reference,
       OwnershipSharePct   AS ownership_share_pct
FROM qube_transactions
"""

# %%
# Finance and suppliers

STAGING["silver_income_category"] = """
SELECT IncomeCategory     AS income_category,
       Description        AS description,
       PriorityCode       AS priority_code,
       BillingFrequency   AS billing_frequency
FROM qube_income_categories
"""

STAGING["silver_suspense_item"] = """
SELECT ItemId           AS item_id,
       ItemType         AS item_type,
       PropertyRef      AS property_ref,
       RaisedDate       AS raised_date,
       Amount           AS amount,
       Status           AS status,
       ClearedDate      AS cleared_date,
       OwnerStaffCode   AS owner_staff_code,
       Notes            AS notes
FROM qube_suspense_items
"""

STAGING["silver_supplier"] = """
SELECT SupplierCode         AS supplier_code,
       FixFloContractorId   AS fixflo_contractor_id,
       SupplierName         AS supplier_name,
       Trade                AS trade,
       Region               AS region,
       Email                AS email,
       Phone                AS phone,
       GasSafeNumber        AS gas_safe_number,
       InsuranceExpiry      AS insurance_expiry,
       Active               AS is_active,
       VATRegistered        AS is_vat_registered
FROM qube_suppliers
"""

STAGING["silver_purchase_invoice"] = """
SELECT InvoiceId       AS invoice_id,
       SupplierCode    AS supplier_code,
       PropertyRef     AS property_ref,
       BlockRef        AS block_ref,
       InvoiceDate     AS invoice_date,
       Category        AS category,
       SubCategory     AS sub_category,
       NetAmount       AS net_amount,
       VATAmount       AS vat_amount,
       GrossAmount     AS gross_amount,
       FixFloIssueId   AS fixflo_issue_id,
       Status          AS status
FROM qube_purchase_invoices
"""

# %%
# Compliance and repairs

STAGING["silver_compliance_certificate"] = """
SELECT CertificateId     AS certificate_id,
       PropertyRef       AS property_ref,
       CertificateType   AS certificate_type,
       IssueDate         AS issue_date,
       ExpiryDate        AS expiry_date,
       Contractor        AS supplier_code,
       Outcome           AS outcome,
       DocumentRef       AS document_ref
FROM qube_compliance_certificates
"""

# FixFlo issues point at FixFlo's own property id; the Qube reference comes from
# fixflo_properties.
STAGING["silver_repair_issue"] = """
WITH fixflo_property AS (
    SELECT id, ExternalPropertyRef,
           ROW_NUMBER() OVER (PARTITION BY id ORDER BY ExternalPropertyRef) AS rn
    FROM fixflo_properties
)
SELECT i.Id                              AS issue_id,
       p.ExternalPropertyRef             AS property_ref,
       i.Property                        AS fixflo_property_id,
       i.`Block.ExternalBlockReference`  AS block_ref,
       i.ExternalRefTenancyAgreement     AS tenancy_ref,
       i.IssueType                       AS issue_type,
       i.Title                           AS title,
       i.FaultTitle                      AS fault_title,
       i.FaultCategory                   AS fault_category,
       i.FaultPriority                   AS priority,
       i.IsEmergency                     AS is_emergency,
       i.IsCommunal                      AS is_communal,
       i.Status                          AS status,
       i.Created                         AS created_at,
       i.StatusChanged                   AS status_changed_at,
       i.CloseReason                     AS close_reason,
       i.CloseReasonDescription          AS close_reason_description,
       i.`Job.id`                        AS job_id
FROM fixflo_issues i
LEFT JOIN fixflo_property p ON p.id = i.Property AND p.rn = 1
"""

STAGING["silver_repair_job"] = """
WITH completion AS (
    SELECT IssueId, JobCompletionDate, FeedbackToAgent,
           ROW_NUMBER() OVER (PARTITION BY IssueId ORDER BY JobCompletionDate DESC) AS rn
    FROM fixflo_job_completion_details
)
SELECT j.id                               AS job_id,
       j.IssueId                          AS issue_id,
       j.`Contractor.ExternalRef`         AS supplier_code,
       j.`Contractor.Id`                  AS fixflo_contractor_id,
       j.ExternalRefJob                   AS works_order_number,
       j.CreatedDate                      AS created_at,
       j.StartDate                        AS start_at,
       j.JobCompleted                     AS completed_at,
       j.JobDuration                      AS job_duration,
       j.AppointmentDescription           AS appointment,
       j.PriceAgencyPayableNet            AS payable_net,
       j.PriceAgencyPayableTax            AS payable_tax,
       j.PriceAgencyPayableGross          AS payable_gross,
       j.QuotedPriceAgencyPayableGross    AS quoted_gross,
       j.JobInvoiceNumber                 AS invoice_number,
       c.JobCompletionDate                AS completion_date,
       c.FeedbackToAgent                  AS feedback
FROM fixflo_jobs j
LEFT JOIN completion c ON c.IssueId = j.IssueId AND c.rn = 1
"""

STAGING["silver_repair_quote"] = """
SELECT id                          AS quote_id,
       IssueId                     AS issue_id,
       `Contractor.ExternalRef`    AS supplier_code,
       Status                      AS status,
       PriceAgencyPayableNet       AS payable_net,
       PriceAgencyPayableTax       AS payable_tax,
       PriceAgencyPayableGross     AS payable_gross
FROM fixflo_quotes
"""

# %%
# Lettings and sales (Engage)

STAGING["silver_listing"] = """
SELECT ListingId         AS listing_id,
       QubePropertyRef   AS property_ref,
       ListingType       AS listing_type,
       ListedDate        AS listed_date,
       AskingRentPCM     AS asking_rent_pcm,
       AskingPrice       AS asking_price,
       ListingStatus     AS listing_status,
       AgreedDate        AS agreed_date,
       CompletionDate    AS completion_date,
       AchievedRentPCM   AS achieved_rent_pcm,
       AchievedPrice     AS achieved_price,
       NegotiatorCode    AS negotiator_code,
       WithdrawnDate     AS withdrawn_date
FROM engage_listings
"""

STAGING["silver_viewing"] = """
SELECT ViewingId        AS viewing_id,
       ListingId        AS listing_id,
       ApplicantId      AS applicant_id,
       ViewingDate      AS viewing_date,
       Outcome          AS outcome,
       NegotiatorCode   AS negotiator_code
FROM engage_viewings
"""

STAGING["silver_offer"] = """
SELECT OfferId       AS offer_id,
       ListingId     AS listing_id,
       ApplicantId   AS applicant_id,
       OfferDate     AS offer_date,
       OfferAmount   AS offer_amount,
       OfferStatus   AS offer_status
FROM engage_offers
"""

# %%
# Reference

STAGING["silver_calendar"] = """
SELECT Date            AS date,
       Year            AS year,
       Quarter         AS quarter,
       MonthNumber     AS month_number,
       MonthName       AS month_name,
       MonthShort      AS month_short,
       YearMonth       AS year_month,
       YearQuarter     AS year_quarter,
       WeekdayName     AS weekday_name,
       IsWeekend       AS is_weekend,
       FinancialYear   AS financial_year
FROM dim_calendar
"""

# %% [markdown]
# ## Typing and merging
# These functions write SQL from the contract, so every table is typed and merged the
# same way. Each step's SQL is printed for the first table, to show what runs.

# %%


def q(name: str) -> str:
    """Backtick a column name (names such as `date` and `year` are SQL keywords)."""
    return f"`{name}`"


def data_columns(table: str) -> list[tuple[str, str]]:
    return [(c, t) for c, t in SILVER_CONTRACT[table]["columns"] if c not in METADATA]


def typed_sql(table: str) -> str:
    """SELECT that converts every staged text column to its dictionary type."""
    spec = SILVER_CONTRACT[table]
    cols = [
        q(c) if t == "STRING" else f"TRY_CAST({q(c)} AS {t}) AS {q(c)}"
        for c, t in data_columns(table)
    ]
    cols += [
        f"'{spec['source_system']}' AS source_system",
        f"'{spec['source_table']}' AS source_table",
        f"TIMESTAMP '{loaded_at.isoformat(sep=' ')}' AS loaded_at",
    ]
    return "SELECT " + ",\n       ".join(cols) + f"\nFROM stg_{table}"


def cast_errors_sql(table: str) -> str:
    """One row per value that is present in the source but would not convert.

    All non-text columns are checked in one pass: each row is turned into an array of
    (column, raw value, converted?) entries, exploded, and filtered to the failures.
    """
    key = SILVER_CONTRACT[table]["key"]
    checks = [
        f"named_struct('column_name', '{c}', 'raw_value', {q(c)}, 'target_type', '{t}', "
        f"'converted', TRY_CAST({q(c)} AS {t}) IS NOT NULL)"
        for c, t in data_columns(table)
        if t != "STRING"
    ]
    if not checks:
        return ""
    return f"""
        SELECT '{run_id}' AS run_id, '{table}' AS table_name,
               concat_ws('|', {", ".join(q(k) for k in key)}) AS record_key,
               e.column_name, e.raw_value, e.target_type,
               TIMESTAMP '{loaded_at.isoformat(sep=' ')}' AS loaded_at
        FROM stg_{table}
        LATERAL VIEW explode(array({", ".join(checks)})) v AS e
        WHERE e.raw_value IS NOT NULL AND trim(e.raw_value) <> '' AND NOT e.converted
    """


def create_table_sql(table: str) -> str:
    cols = ", ".join(f"{q(c)} {t}" for c, t in SILVER_CONTRACT[table]["columns"])
    return f"CREATE TABLE IF NOT EXISTS {silver_db}.{table} ({cols}) USING DELTA"


def merge_table(table: str, full_load: bool, show_sql: bool = False) -> dict:
    """Bring the Silver table in line with this load. Returns counts for the summary.

    MERGE needs each key to appear once in the source. Silver must not de-duplicate,
    so rows whose key is blank or appears more than once are kept apart: the rows
    already in Silver for those keys are deleted and this load's rows inserted as they
    are. Every other row goes through a normal MERGE on the key.
    """
    target = f"{silver_db}.{table}"
    key = SILVER_CONTRACT[table]["key"]
    on = " AND ".join(f"t.{q(k)} = s.{q(k)}" for k in key)
    key_list = ", ".join(q(k) for k in key)
    key_blank = " OR ".join(f"{q(k)} IS NULL" for k in key)

    # Keys that can't be merged one-to-one: repeated in this load or already in Silver.
    # Worked out once, before anything changes, and kept for the steps below.
    problem_sql = f"""
        SELECT {key_list} FROM typed_{table} WHERE NOT ({key_blank})
        GROUP BY {key_list} HAVING COUNT(*) > 1
        UNION
        SELECT {key_list} FROM {target} WHERE NOT ({key_blank})
        GROUP BY {key_list} HAVING COUNT(*) > 1"""
    spark.sql(create_table_sql(table))
    spark.sql(problem_sql).localCheckpoint().createOrReplaceTempView("problem_keys")

    statements = [
        problem_sql,
        f"DELETE FROM {target} WHERE {key_blank}",
        f"""MERGE INTO {target} t USING problem_keys s ON {on}
            WHEN MATCHED THEN DELETE""",
        f"""MERGE INTO {target} t
            USING (
                SELECT r.* FROM typed_{table} r
                LEFT ANTI JOIN problem_keys p
                    ON {" AND ".join(f"r.{q(k)} = p.{q(k)}" for k in key)}
                WHERE NOT ({" OR ".join(f"r.{q(k)} IS NULL" for k in key)})
            ) s
            ON {on}
            WHEN MATCHED THEN UPDATE SET *
            WHEN NOT MATCHED THEN INSERT *
            {"WHEN NOT MATCHED BY SOURCE THEN DELETE" if full_load else ""}""",
        f"""INSERT INTO {target}
            SELECT r.* FROM typed_{table} r
            WHERE {" OR ".join(f"r.{q(k)} IS NULL" for k in key)}
               OR EXISTS (SELECT 1 FROM problem_keys p
                          WHERE {" AND ".join(f"p.{q(k)} = r.{q(k)}" for k in key)})""",
    ]
    for sql in statements:
        if show_sql:
            print(sql.strip(), end="\n\n")
        spark.sql(sql)
    problem_rows = spark.sql(f"""
        SELECT COUNT(*) FROM typed_{table} r
        WHERE {" OR ".join(f"r.{q(k)} IS NULL" for k in key)}
           OR EXISTS (SELECT 1 FROM problem_keys p
                      WHERE {" AND ".join(f"p.{q(k)} = r.{q(k)}" for k in key)})
    """).first()[0]
    return {"problem_key_rows": problem_rows}


# %% [markdown]
# ## Load every Silver table

# %%
missing = set(SILVER_CONTRACT) ^ set(STAGING)
if missing:
    raise ValueError(f"staging queries and contract differ: {sorted(missing)}")

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {silver_db}._cast_errors (
        run_id STRING, table_name STRING, record_key STRING, column_name STRING,
        raw_value STRING, target_type STRING, loaded_at TIMESTAMP
    ) USING DELTA
""")
spark.sql(f"DELETE FROM {silver_db}._cast_errors WHERE run_id = '{run_id}'")

results = []
for i, table in enumerate(SILVER_CONTRACT):
    spec = SILVER_CONTRACT[table]
    main_source = spec["source_table"].split(",")[0].strip()
    full_load = load_mode.get(main_source, "full") == "full"
    try:
        spark.sql(f"CREATE OR REPLACE TEMP VIEW stg_{table} AS {STAGING[table]}")
        staged_cols = spark.table(f"stg_{table}").columns
        expected = [c for c, _ in data_columns(table)]
        if staged_cols != expected:
            raise ValueError(f"staging columns {staged_cols} != contract {expected}")

        spark.sql(f"CREATE OR REPLACE TEMP VIEW typed_{table} AS {typed_sql(table)}")
        errors_sql = cast_errors_sql(table)
        cast_errors = 0
        if errors_sql:
            spark.sql(f"INSERT INTO {silver_db}._cast_errors {errors_sql}")
            cast_errors = spark.sql(
                f"SELECT COUNT(*) FROM {silver_db}._cast_errors "
                f"WHERE run_id = '{run_id}' AND table_name = '{table}'"
            ).first()[0]

        counts = merge_table(table, full_load, show_sql=(i == 0))
        results.append(
            {
                "table": table,
                "mode": "full" if full_load else "incremental",
                "staged": spark.table(f"stg_{table}").count(),
                "in_silver": spark.table(f"{silver_db}.{table}").count(),
                "cast_errors": cast_errors,
                **counts,
                "status": "succeeded",
            }
        )
    except Exception as exc:  # noqa: BLE001 - reported below, other tables still load
        results.append({"table": table, "status": "failed", "error": str(exc)[:500]})
    r = results[-1]
    print(
        f"  {table:32} {r['status']:9} "
        + (
            f"staged={r['staged']} silver={r['in_silver']} cast_errors={r['cast_errors']} "
            f"blank_or_repeated_keys={r['problem_key_rows']} ({r['mode']})"
            if r["status"] == "succeeded"
            else r["error"]
        )
    )

# %% [markdown]
# ## Summary

# %%
failed = [r["table"] for r in results if r["status"] != "succeeded"]
print(
    f"Silver run {run_id}: {len(results) - len(failed)} of {len(results)} tables loaded; "
    f"cast errors: {sum(r.get('cast_errors', 0) for r in results)}; failed: {failed or 'none'}"
)
if failed:
    raise RuntimeError(f"Silver load failed for: {', '.join(failed)}")
