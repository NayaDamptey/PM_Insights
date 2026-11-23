# Row-level security plan

Who may see which homes, and everything linked to them. Implemented in three layers (semantic
model roles, SQL endpoint security policy, OneLake data access roles); this is the design.

## Roles

| Role | Sees | Personal data (names, contacts, bank) |
|---|---|---|
| **Property Manager** | Only the homes they manage (`silver_property.manager_staff_code` = their staff code) and every tenancy, rent line, arrears figure, repair, certificate, invoice and suspense item on those homes | Yes, for their homes |
| **Location Manager** | Every home in their location(s), including other property managers' homes | No (hidden with OLS) |
| **Regional / Lettings Manager** | Every home in their region; lettings negotiators see Engage listings, viewings and offers for their region | No |
| **Head Office / Finance** | Everything | Yes |
| **Data Steward** | Everything, including the data quality pages and exception rows | No |

## The security table

`ll_gold.security_user_access`, built from `silver_staff` and `silver_property`, one row
per user per location they may see:

| Column | Example |
|---|---|
| user_email | kemi.ward.1@example.com |
| staff_code | PM001 |
| role | Property Manager |
| region | Yorkshire and The Humber |
| location | Pontefract |
| access_level | own homes / location / region / all |

- A property manager can cover more than one location, and a location has 2–3 property
  managers, so there is one row per user per location.
- Leavers (`is_active = false`) get no rows, so their access ends with the next load.

## How the filter works

1. The semantic model filters `security_user_access[user_email] = USERPRINCIPALNAME()`.
2. Relationships carry that filter to `dim_property` (by location, region or manager) and
   from there to every fact table.
3. Measures must not use `ALL()` in a way that lifts the security filter; the security
   table is hidden from report users.
4. The same rule is enforced on the SQL analytics endpoint of `ll_gold` (a predicate
   function and security policy), and with OneLake data access roles on the lakehouse
   folders, so people querying directly see only their own rows.

## Adding a property manager or location

1. Add or update the person in Qube (`qube_staff`) with role, region and location, and
   assign homes to them (`ManagerCode` on the property).
2. The next pipeline run rebuilds `security_user_access`; nothing is edited by hand.
3. Add their account to the matching role in the semantic model (Security → Manage
   roles), or to the Entra ID group mapped to that role.

## Testing

- Test users (one per role) are added to `security_user_access`.
- **Model view → Manage roles → View as** shows the report as each role.
- A validation query compares rows per role with a direct query on Silver, e.g. PM001
  sees exactly the homes where `manager_staff_code = 'PM001'`.
