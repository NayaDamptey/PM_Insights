"""Every DAX measure and relationship of the LL_Insights model, defined once, written as:

    powerbi/relationships.tmdl  paste into Power BI Desktop > TMDL view > Apply
    powerbi/measures.tmdl       the same for the measures (or run 06_model_measures in Fabric)
    powerbi/measures.dax        the measures as a readable DAX listing

    .venv\\Scripts\\python powerbi\\build_measures.py

Each measure is stored on the main fact table of its report page (HOME), in a display
folder named after the page.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

MONEY, PCT, WHOLE, ONE_DP = "£#,0", "0.0%", "#,0", "#,0.0"

# Small house drawings per property type, shown as pictures in the Property explorer.
PICTURE_DAX = "SWITCH (\n    SELECTEDVALUE ( dim_property[property_type] ),\n        \"House\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><polygon points='60,70 120,30 180,70' fill='%2300E676'/><rect x='72' y='70' width='96' height='60' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><rect x='110' y='95' width='20' height='35' fill='%2300E676'/></svg>\",\n        \"Flat\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><rect x='80' y='20' width='80' height='115' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><g fill='%2300E676'><rect x='92' y='32' width='14' height='12'/><rect x='134' y='32' width='14' height='12'/><rect x='92' y='58' width='14' height='12'/><rect x='134' y='58' width='14' height='12'/><rect x='92' y='84' width='14' height='12'/><rect x='134' y='84' width='14' height='12'/><rect x='112' y='110' width='16' height='25'/></g></svg>\",\n        \"Townhouse\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><polygon points='85,55 120,25 155,55' fill='%2300E676'/><rect x='92' y='55' width='56' height='80' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><g fill='%2300E676'><rect x='104' y='68' width='12' height='14'/><rect x='124' y='68' width='12' height='14'/><rect x='112' y='105' width='16' height='30'/></g></svg>\",\n        \"Bungalow\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><polygon points='40,80 120,50 200,80' fill='%2300E676'/><rect x='52' y='80' width='136' height='50' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><rect x='112' y='100' width='18' height='30' fill='%2300E676'/></svg>\",\n        \"Maisonette\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><rect x='70' y='40' width='100' height='95' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><line x1='70' y1='88' x2='170' y2='88' stroke='%2300E676' stroke-width='3'/><g fill='%2300E676'><rect x='85' y='55' width='18' height='16'/><rect x='137' y='55' width='18' height='16'/><rect x='111' y='105' width='18' height='30'/></g></svg>\",\n        \"Studio\", \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><rect x='90' y='60' width='60' height='70' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><rect x='100' y='75' width='16' height='14' fill='%2300E676'/><rect x='124' y='100' width='16' height='30' fill='%2300E676'/></svg>\",\n    \"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 150'><rect width='240' height='150' rx='12' fill='%23050A07'/><polygon points='60,70 120,30 180,70' fill='%2300E676'/><rect x='72' y='70' width='96' height='60' fill='%23103A27' stroke='%2300E676' stroke-width='3'/><rect x='110' y='95' width='20' height='35' fill='%2300E676'/></svg>\"\n)"

# (folder, name, format, description, DAX)
MEASURES: list[tuple[str, str, str, str, str]] = [
    # ------------------------------------------------------------------ Finance
    (
        "Finance",
        "Revenue Generated",
        MONEY,
        "Rent, service charge, ground rent and recharges billed in the period.",
        "SUM ( fact_rent_transaction[charged] )",
    ),
    (
        "Finance",
        "Rent Charged",
        MONEY,
        "Rent billed in the period.",
        'CALCULATE ( [Revenue Generated], fact_rent_transaction[transaction_type] = "Rent charge" )',
    ),
    (
        "Finance",
        "Service Charge Charged",
        MONEY,
        "Service charge billed in the period.",
        'CALCULATE ( [Revenue Generated], fact_rent_transaction[transaction_type] = "Service charge" )',
    ),
    (
        "Finance",
        "Ground Rent Charged",
        MONEY,
        "Ground rent billed in the period.",
        'CALCULATE ( [Revenue Generated], fact_rent_transaction[transaction_type] = "Ground rent" )',
    ),
    (
        "Finance",
        "Received",
        MONEY,
        "Rent receipts in the period.",
        "SUM ( fact_rent_transaction[paid] )",
    ),
    (
        "Finance",
        "Collection Rate",
        PCT,
        "Received ÷ charged.",
        "DIVIDE ( [Received], [Revenue Generated] )",
    ),
    (
        "Finance",
        "Last Ledger Date",
        "dd mmm yyyy",
        "Latest date with a ledger line in the current filters.",
        "CALCULATE ( MAX ( dim_date[date] ), fact_rent_transaction )",
    ),
    (
        "Finance",
        "Revenue Generated FYTD",
        MONEY,
        "Financial year to date (April to March).",
        'TOTALYTD ( [Revenue Generated], dim_date[date], "3/31" )',
    ),
    (
        "Finance",
        "Revenue Generated LY",
        MONEY,
        "Same period last year.",
        "CALCULATE ( [Revenue Generated], SAMEPERIODLASTYEAR ( dim_date[date] ) )",
    ),
    (
        "Finance",
        "Revenue vs LY %",
        PCT,
        "Change against the same period last year.",
        "DIVIDE ( [Revenue Generated] - [Revenue Generated LY], [Revenue Generated LY] )",
    ),
    (
        "Finance",
        "Revenue Last 12 Months",
        MONEY,
        "Twelve months up to the latest ledger date.",
        "CALCULATE ( [Revenue Generated], DATESINPERIOD ( dim_date[date], [Last Ledger Date], -12, MONTH ) )",
    ),
    (
        "Finance",
        "Arrears",
        MONEY,
        "Amount owed at the end of the latest month in the filters (a balance, so it is "
        "not summed across months).",
        """VAR LastMonth = MAX ( fact_arrears_monthly[month_key] )
RETURN
    CALCULATE (
        SUM ( fact_arrears_monthly[arrears] ),
        REMOVEFILTERS ( dim_date ),
        fact_arrears_monthly[month_key] = LastMonth
    )""",
    ),
    (
        "Finance",
        "Current Tenant Arrears",
        MONEY,
        "Arrears of tenancies still live.",
        "CALCULATE ( [Arrears], fact_arrears_monthly[is_current_tenant] = TRUE () )",
    ),
    (
        "Finance",
        "Former Tenant Arrears",
        MONEY,
        "Debt left by tenants who have moved out.",
        "CALCULATE ( [Arrears], fact_arrears_monthly[is_current_tenant] = FALSE () )",
    ),
    (
        "Finance",
        "Tenancies in Arrears",
        WHOLE,
        "Tenancies owing money at the end of the latest month in the filters.",
        """VAR LastMonth = MAX ( fact_arrears_monthly[month_key] )
RETURN
    CALCULATE (
        COUNTROWS ( fact_arrears_monthly ),
        REMOVEFILTERS ( dim_date ),
        fact_arrears_monthly[month_key] = LastMonth,
        fact_arrears_monthly[arrears] > 0
    )""",
    ),
    (
        "Finance",
        "Rent Roll (annual)",
        MONEY,
        "Annual rent of live tenancies.",
        "CALCULATE ( SUM ( fact_tenancy[rent_pcm] ) * 12, fact_tenancy[is_live] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Finance",
        "Arrears % of Rent Roll",
        PCT,
        "Current tenant arrears ÷ annual rent roll.",
        "DIVIDE ( [Current Tenant Arrears], [Rent Roll (annual)] )",
    ),
    (
        "Finance",
        "Aged Arrears",
        MONEY,
        "Arrears today by how long they have been owed (use with fact_arrears_aged[age_band]).",
        "SUM ( fact_arrears_aged[arrears] )",
    ),
    (
        "Finance",
        "Former Tenant Debt 90+ Days",
        MONEY,
        "Debt left by former tenants that is over 90 days old.",
        'CALCULATE ( [Aged Arrears], fact_arrears_aged[is_current_tenant] = FALSE (), fact_arrears_aged[age_band] = "90+ days" )',
    ),
    (
        "Finance",
        "Rent Lost to Voids",
        MONEY,
        "Void days × market rent.",
        "SUM ( fact_occupancy_monthly[rent_lost_to_voids] )",
    ),
    (
        "Finance",
        "Rent Lost to Voids FYTD",
        MONEY,
        "Financial year to date.",
        'TOTALYTD ( [Rent Lost to Voids], dim_date[date], "3/31" )',
    ),
    (
        "Finance",
        "Spend",
        MONEY,
        "Supplier invoices, gross.",
        "SUM ( fact_purchase_invoice[gross_amount] )",
    ),
    ("Finance", "Spend per Home", MONEY, "Spend ÷ homes held.", "DIVIDE ( [Spend], [Homes Held] )"),
    # --------------------------------------------------------- Property management
    (
        "Property management",
        "Homes Held",
        WHOLE,
        "Homes owned today (current version, not sold).",
        """CALCULATE (
    DISTINCTCOUNT ( dim_property[property_ref] ),
    dim_property[is_current] = TRUE (),
    dim_property[property_status] <> "Sold",
    dim_property[property_ref] <> "Unknown"
)""",
    ),
    (
        "Property management",
        "Current Tenants",
        WHOLE,
        "Live tenancies (households): one per let home, so it equals Homes Let.",
        "CALCULATE ( COUNTROWS ( fact_tenancy ), fact_tenancy[is_live] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Property management",
        "PRS Homes",
        WHOLE,
        "Rental homes held.",
        'CALCULATE ( [Homes Held], dim_property[tenure] = "PRS" )',
    ),
    (
        "Property management",
        "Shared Ownership Homes",
        WHOLE,
        "Shared Ownership homes held.",
        'CALCULATE ( [Homes Held], dim_property[tenure] = "Shared Ownership" )',
    ),
    (
        "Property management",
        "Stale Duplicate Homes",
        WHOLE,
        "Records that duplicate a home already sold (false actives found by DQ010).",
        "CALCULATE ( [Homes Held], dim_property[is_stale_duplicate] = TRUE () )",
    ),
    (
        "Property management",
        "Homes per Property Manager",
        ONE_DP,
        "Workload per manager.",
        """DIVIDE (
    [Homes Held],
    CALCULATE (
        DISTINCTCOUNT ( dim_property[manager_staff_code] ),
        dim_property[is_current] = TRUE (),
        dim_property[property_status] <> "Sold"
    )
)""",
    ),
    (
        "Property management",
        "Occupancy Rate (PRS)",
        PCT,
        "Let days ÷ days held, rental homes.",
        'CALCULATE ( DIVIDE ( SUM ( fact_occupancy_monthly[let_days] ), SUM ( fact_occupancy_monthly[held_days] ) ), dim_property[tenure] = "PRS" )',
    ),
    (
        "Property management",
        "Void Rate (PRS)",
        PCT,
        "Void days ÷ days held, rental homes.",
        "1 - [Occupancy Rate (PRS)]",
    ),
    (
        "Property management",
        "Current Voids (PRS)",
        WHOLE,
        "Rental homes empty today.",
        'CALCULATE ( COUNTROWS ( fact_void_period ), fact_void_period[is_current_void] = TRUE (), dim_property[tenure] = "PRS" )',
    ),
    (
        "Property management",
        "Void Rate Today (PRS)",
        PCT,
        "Rental homes empty today ÷ rental homes.",
        "DIVIDE ( [Current Voids (PRS)], [PRS Homes] )",
    ),
    (
        "Property management",
        "Avg Void Days",
        ONE_DP,
        "Average gap between tenancies (finished voids).",
        'CALCULATE ( AVERAGE ( fact_void_period[void_days] ), fact_void_period[void_type] = "Between tenancies", fact_void_period[is_current_void] = FALSE () )',
    ),
    (
        "Property management",
        "Avg Tenancy Length (months)",
        ONE_DP,
        "Average length of tenancy periods.",
        "AVERAGE ( fact_tenancy[length_months] )",
    ),
    (
        "Property management",
        "Renewal Rate",
        PCT,
        "Share of ended tenancy periods that renewed.",
        """DIVIDE (
    CALCULATE ( COUNTROWS ( fact_tenancy ), fact_tenancy[end_reason] = "Renewed" ),
    CALCULATE ( COUNTROWS ( fact_tenancy ), fact_tenancy[end_reason] IN { "Renewed", "Tenant left" } )
)""",
    ),
    (
        "Property management",
        "Avg Rent Increase at Renewal",
        PCT,
        "Rent rise on renewal.",
        "CALCULATE ( AVERAGE ( fact_tenancy[rent_increase_pct] ), fact_tenancy[renewal_number] > 0 ) / 100",
    ),
    (
        "Property management",
        "Move-outs",
        WHOLE,
        "Tenants leaving, by the month they left.",
        'CALCULATE ( COUNTROWS ( fact_tenancy ), fact_tenancy[end_reason] = "Tenant left", USERELATIONSHIP ( fact_tenancy[end_date_key], dim_date[date_key] ) )',
    ),
    (
        "Property management",
        "High Risk Tenancies",
        WHOLE,
        "Current tenancies with a risk score of 50+.",
        'CALCULATE ( COUNTROWS ( fact_arrears_risk ), fact_arrears_risk[risk_band] = "High" )',
    ),
    (
        "Property management",
        "Avg Risk Score",
        ONE_DP,
        "Average arrears risk score (0-100).",
        "AVERAGE ( fact_arrears_risk[risk_score] )",
    ),
    (
        "Property management",
        "Shared Owners",
        WHOLE,
        "Shared owners with an ownership period in the filters.",
        "DISTINCTCOUNT ( fact_ownership_share[tenant_key] )",
    ),
    (
        "Property management",
        "Owners Who Staircased",
        WHOLE,
        "Shared owners who bought a bigger share.",
        'CALCULATE ( DISTINCTCOUNT ( fact_ownership_share[tenant_key] ), fact_ownership_share[event_type] = "Staircasing" )',
    ),
    (
        "Property management",
        "Staircasing Rate",
        PCT,
        "Owners who staircased ÷ shared owners.",
        "DIVIDE ( [Owners Who Staircased], [Shared Owners] )",
    ),
    (
        "Property management",
        "Staircasing Events",
        WHOLE,
        "Share purchases after the first.",
        'CALCULATE ( COUNTROWS ( fact_ownership_share ), fact_ownership_share[event_type] = "Staircasing" )',
    ),
    (
        "Property management",
        "Homes Fully Staircased",
        WHOLE,
        "Homes whose owner reached 100%.",
        "CALCULATE ( DISTINCTCOUNT ( fact_ownership_share[property_key] ), fact_ownership_share[is_fully_owned] = TRUE () )",
    ),
    (
        "Property management",
        "Avg Share Owned",
        PCT,
        "Average current share owned.",
        "CALCULATE ( AVERAGE ( fact_ownership_share[percentage_share] ), fact_ownership_share[is_current] = TRUE (), REMOVEFILTERS ( dim_date ) ) / 100",
    ),
    (
        "Property management",
        "Avg Months to First Staircase",
        ONE_DP,
        "From first purchase to first staircase.",
        "AVERAGE ( fact_ownership_share[months_to_first_staircase] )",
    ),
    # ----------------------------------------------------- Operations: maintenance
    (
        "Operations\\Maintenance",
        "Repair Jobs",
        WHOLE,
        "Jobs created in the period.",
        "COUNTROWS ( fact_repair_job )",
    ),
    (
        "Operations\\Maintenance",
        "Avg Days to Complete",
        ONE_DP,
        "Job created to completed.",
        "AVERAGE ( fact_repair_job[days_to_complete] )",
    ),
    (
        "Operations\\Maintenance",
        "Median Days to Complete",
        ONE_DP,
        "Middle value, less skewed by outliers.",
        "MEDIAN ( fact_repair_job[days_to_complete] )",
    ),
    (
        "Operations\\Maintenance",
        "Last Job Date",
        "dd mmm yyyy",
        "Latest date a job was created.",
        "CALCULATE ( MAX ( dim_date[date] ), fact_repair_job, REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Operations\\Maintenance",
        "Contractors Not Used",
        WHOLE,
        "Active contractors (not insurers) with no jobs in the period.",
        """COUNTROWS (
    FILTER (
        dim_supplier,
        dim_supplier[is_active] = TRUE ()
            && dim_supplier[supplier_key] <> -1
            && dim_supplier[trade] <> "Insurance"
            && CALCULATE ( COUNTROWS ( fact_repair_job ) ) = 0
    )
)""",
    ),
    (
        "Operations\\Maintenance",
        "Contractors Not Used (12 months)",
        WHOLE,
        "Active contractors with no jobs in the last 12 months.",
        "CALCULATE ( [Contractors Not Used], DATESINPERIOD ( dim_date[date], [Last Job Date], -12, MONTH ) )",
    ),
    (
        "Operations\\Maintenance",
        "Open Jobs",
        WHOLE,
        "Jobs not completed today.",
        "CALCULATE ( COUNTROWS ( fact_repair_job ), fact_repair_job[is_open] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Operations\\Maintenance",
        "Jobs Open Over 15 Days",
        WHOLE,
        "Open jobs older than 15 days.",
        "CALCULATE ( COUNTROWS ( fact_repair_job ), fact_repair_job[is_open_over_15_days] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Operations\\Maintenance",
        "Contractors With Jobs Open Over 15 Days",
        WHOLE,
        "Contractors holding at least one job open over 15 days.",
        "CALCULATE ( DISTINCTCOUNT ( fact_repair_job[supplier_key] ), fact_repair_job[is_open_over_15_days] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Operations\\Maintenance",
        "Callback Rate",
        PCT,
        "Completed jobs followed by a new issue on the same home and fault within 30 days.",
        """DIVIDE (
    CALCULATE ( COUNTROWS ( fact_repair_job ), fact_repair_job[has_callback_30_days] = TRUE () ),
    CALCULATE ( COUNTROWS ( fact_repair_job ), fact_repair_job[is_completed] = TRUE () )
)""",
    ),
    (
        "Operations\\Maintenance",
        "Repair Spend",
        MONEY,
        "Gross cost of jobs.",
        "SUM ( fact_repair_job[payable_gross] )",
    ),
    (
        "Operations\\Maintenance",
        "Compliance %",
        PCT,
        "Required certificates that are valid today.",
        "DIVIDE ( CALCULATE ( COUNTROWS ( fact_compliance_status ), fact_compliance_status[is_compliant] = TRUE () ), COUNTROWS ( fact_compliance_status ) )",
    ),
    (
        "Operations\\Maintenance",
        "Gas Compliance %",
        PCT,
        "Gas Safety, homes with gas.",
        'CALCULATE ( [Compliance %], fact_compliance_status[certificate_type] = "Gas Safety Certificate" )',
    ),
    (
        "Operations\\Maintenance",
        "EICR Compliance %",
        PCT,
        "Electrical safety.",
        'CALCULATE ( [Compliance %], fact_compliance_status[certificate_type] = "EICR" )',
    ),
    (
        "Operations\\Maintenance",
        "EPC Compliance %",
        PCT,
        "Energy performance.",
        'CALCULATE ( [Compliance %], fact_compliance_status[certificate_type] = "EPC" )',
    ),
    (
        "Operations\\Maintenance",
        "Expired Certificates",
        WHOLE,
        "Required certificates past expiry.",
        'CALCULATE ( COUNTROWS ( fact_compliance_status ), fact_compliance_status[status] = "Expired" )',
    ),
    (
        "Operations\\Maintenance",
        "Missing Certificates",
        WHOLE,
        "Required certificates never issued.",
        'CALCULATE ( COUNTROWS ( fact_compliance_status ), fact_compliance_status[status] = "Missing" )',
    ),
    (
        "Operations\\Maintenance",
        "Certificates Expiring in 90 Days",
        WHOLE,
        "Due for renewal soon.",
        'CALCULATE ( COUNTROWS ( fact_compliance_status ), fact_compliance_status[status] IN { "Expires in 30 days", "Expires in 31-60 days", "Expires in 61-90 days" } )',
    ),
    (
        "Operations\\Maintenance",
        "Homes Not Compliant",
        WHOLE,
        "Homes with an expired or missing certificate.",
        "CALCULATE ( DISTINCTCOUNT ( fact_compliance_status[property_key] ), fact_compliance_status[is_compliant] = FALSE () )",
    ),
    (
        "Operations\\Maintenance",
        "Maintenance Insight",
        "",
        "One-line takeaway for the Maintenance page.",
        """"Jobs take " & FORMAT ( [Avg Days to Complete], "0.0" ) & " days on average; "
    & FORMAT ( [Jobs Open Over 15 Days], "#,0" ) & " jobs are open over 15 days across "
    & FORMAT ( [Contractors With Jobs Open Over 15 Days], "#,0" ) & " contractors. "
    & FORMAT ( [Contractors Not Used (12 months)], "#,0" ) & " active contractors had no work in 12 months. Compliance "
    & FORMAT ( [Compliance %], "0.0%" ) & ", " & FORMAT ( [Homes Not Compliant], "#,0" ) & " homes need action." """,
    ),
    # -------------------------------------------------------- Operations: lettings
    (
        "Operations\\Lettings",
        "Listings",
        WHOLE,
        "Homes listed in the period.",
        "COUNTROWS ( fact_lettings_funnel )",
    ),
    (
        "Operations\\Lettings",
        "Lets Agreed",
        WHOLE,
        "Lets or sales agreed, by agreed date.",
        "CALCULATE ( COUNTROWS ( fact_lettings_funnel ), fact_lettings_funnel[is_agreed] = TRUE (), USERELATIONSHIP ( fact_lettings_funnel[agreed_date_key], dim_date[date_key] ) )",
    ),
    (
        "Operations\\Lettings",
        "Avg Days to Agree",
        ONE_DP,
        "Listed to agreed.",
        "AVERAGE ( fact_lettings_funnel[days_to_agree] )",
    ),
    (
        "Operations\\Lettings",
        "Avg Days to Move In",
        ONE_DP,
        "Listed to move-in (days to let).",
        "AVERAGE ( fact_lettings_funnel[days_to_move_in] )",
    ),
    (
        "Operations\\Lettings",
        "Viewings Booked",
        WHOLE,
        "Viewings in the period.",
        "COUNTROWS ( fact_viewing )",
    ),
    (
        "Operations\\Lettings",
        "Viewing Attendance %",
        PCT,
        "Viewings the applicant turned up to.",
        "DIVIDE ( CALCULATE ( [Viewings Booked], fact_viewing[attended] = TRUE () ), [Viewings Booked] )",
    ),
    (
        "Operations\\Lettings",
        "Offers Made",
        WHOLE,
        "Offers made in the period.",
        "COUNTROWS ( fact_offer )",
    ),
    (
        "Operations\\Lettings",
        "Accepted Offers",
        WHOLE,
        "",
        'CALCULATE ( [Offers Made], fact_offer[offer_status] = "Accepted" )',
    ),
    (
        "Operations\\Lettings",
        "Rejected Offers",
        WHOLE,
        "",
        'CALCULATE ( [Offers Made], fact_offer[offer_status] = "Rejected" )',
    ),
    (
        "Operations\\Lettings",
        "Viewing to Offer %",
        PCT,
        "Offers ÷ viewings.",
        "DIVIDE ( [Offers Made], [Viewings Booked] )",
    ),
    (
        "Operations\\Lettings",
        "Offer to Let %",
        PCT,
        "Accepted ÷ offers.",
        "DIVIDE ( [Accepted Offers], [Offers Made] )",
    ),
    (
        "Operations\\Lettings",
        "Applicants",
        WHOLE,
        "Applicants registered in Engage.",
        "CALCULATE ( COUNTROWS ( dim_applicant ), dim_applicant[applicant_key] <> -1 )",
    ),
    (
        "Operations\\Lettings",
        "Applicants Who Viewed",
        WHOLE,
        "",
        "DISTINCTCOUNT ( fact_viewing[applicant_key] )",
    ),
    (
        "Operations\\Lettings",
        "Applicants Who Offered",
        WHOLE,
        "",
        "DISTINCTCOUNT ( fact_offer[applicant_key] )",
    ),
    (
        "Operations\\Lettings",
        "Active Applicants",
        WHOLE,
        "Applicants still looking.",
        "CALCULATE ( COUNTROWS ( dim_applicant ), dim_applicant[is_active_applicant] = TRUE () )",
    ),
    (
        "Operations\\Lettings",
        "Available Homes",
        WHOLE,
        "Listings available today.",
        "CALCULATE ( COUNTROWS ( fact_lettings_funnel ), fact_lettings_funnel[is_available] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
    (
        "Operations\\Lettings",
        "Applicants per Available Home",
        ONE_DP,
        "Demand vs supply.",
        "DIVIDE ( [Active Applicants], [Available Homes] )",
    ),
    (
        "Operations\\Lettings",
        "Lettings Insight",
        "",
        "One-line takeaway for the Lettings page.",
        """"Homes take " & FORMAT ( [Avg Days to Move In], "0" ) & " days from listing to move-in; "
    & FORMAT ( [Viewing to Offer %], "0%" ) & " of viewings lead to an offer; "
    & FORMAT ( [Applicants per Available Home], "0.0" ) & " active applicants per available home." """,
    ),
    # ------------------------------------------------------------- Finance: cash flow and NOI
    (
        "Finance",
        "Operating Expenses",
        MONEY,
        "Repairs, compliance, block services and insurance invoiced in the period.",
        "[Spend]",
    ),
    (
        "Finance",
        "Net Operating Income",
        MONEY,
        "Revenue charged minus operating expenses.",
        "[Revenue Generated] - [Operating Expenses]",
    ),
    (
        "Finance",
        "Operating Expense Ratio",
        PCT,
        "Operating expenses ÷ revenue charged; a rising ratio means margins are being squeezed.",
        "DIVIDE ( [Operating Expenses], [Revenue Generated] )",
    ),
    (
        "Finance",
        "Operating Expense Ratio (This Year)",
        PCT,
        "Operating expense ratio for the current calendar year, whatever year is picked in the slicers.",
        "CALCULATE ( [Operating Expense Ratio], REMOVEFILTERS ( dim_date ), dim_date[year] = YEAR ( TODAY () ) )",
    ),
    (
        "Finance",
        "Capital Expenditure",
        MONEY,
        "Cost of homes bought in the period (acquisitions are the capital spend in this data).",
        "CALCULATE ( SUM ( dim_property[acquisition_cost] ), dim_property[is_current] = TRUE (), TREATAS ( VALUES ( dim_date[date] ), dim_property[acquisition_date] ) )",
    ),
    (
        "Finance",
        "Operating Cash Flow",
        MONEY,
        "Cash received minus operating expenses (before buying homes).",
        "[Received] - [Operating Expenses]",
    ),
    (
        "Property management",
        "Homes Let",
        WHOLE,
        "Homes owned today that have a tenant (status Let).",
        'CALCULATE ( [Homes Held], dim_property[property_status] = "Let" )',
    ),
    (
        "Property management",
        "Homes Sold",
        WHOLE,
        "Homes bought since 2021 that have left the portfolio (Shared Ownership buy-outs and open-market sales).",
        'CALCULATE ( DISTINCTCOUNT ( dim_property[property_ref] ), dim_property[is_current] = TRUE (), dim_property[property_status] = "Sold" )',
    ),
    (
        "Property management",
        "Is Top 5 in Region",
        WHOLE,
        "1 if the home is one of its region's 5 rental homes with the longest current tenancy (ties broken by property ref).",
        """VAR ThisRegion = SELECTEDVALUE ( dim_property[region] )
VAR ThisHome = SELECTEDVALUE ( dim_property[property_ref] )
VAR ThisMonths = [Current Tenancy (months)]
VAR Candidates =
    CALCULATETABLE (
        ADDCOLUMNS ( VALUES ( dim_property[property_ref] ), "@months", [Current Tenancy (months)] ),
        REMOVEFILTERS ( dim_property ),
        dim_property[region] = ThisRegion,
        dim_property[tenure] = "PRS",
        dim_property[is_current] = TRUE ()
    )
VAR Top5 = TOPN ( 5, FILTER ( Candidates, NOT ISBLANK ( [@months] ) ), [@months], DESC, dim_property[property_ref], ASC )
-- Homes with no live tenancy can't be in the top 5, so the region ranking (the slow
-- part) is only worked out for homes that have one.
RETURN
    IF (
        NOT ISBLANK ( ThisHome ),
        IF (
            ISBLANK ( ThisMonths ),
            0,
            IF ( ThisHome IN SELECTCOLUMNS ( Top5, "ref", dim_property[property_ref] ), 1, 0 )
        )
    )""",
    ),
    (
        "Property management",
        "Homes Acquired",
        WHOLE,
        "Every home bought since 2021, including those since sold.",
        'CALCULATE ( DISTINCTCOUNT ( dim_property[property_ref] ), dim_property[is_current] = TRUE (), dim_property[property_ref] <> "Unknown" )',
    ),
    (
        "Property management",
        "Homes Acquired (cumulative)",
        WHOLE,
        "Running total of homes bought since 2021, up to the end of each year (or today, for the current year). Sales are not taken off, so it only goes up; blank for future years.",
        """VAR AsAt = MIN ( MAX ( dim_date[date] ), TODAY () )
RETURN
    IF (
        MIN ( dim_date[date] ) <= TODAY (),
        CALCULATE (
            DISTINCTCOUNT ( dim_property[property_ref] ),
            dim_property[is_current] = TRUE (),
            dim_property[property_ref] <> "Unknown",
            dim_property[acquisition_date] <= AsAt
        )
    )""",
    ),
    (
        "Property management",
        "Homes Projected",
        WHOLE,
        "Straight line from the homes acquired so far to the target of 30,000 by 2030. It starts at this year's figure, so it carries on from the Homes Acquired line.",
        """VAR ThisYear = YEAR ( TODAY () )
VAR Year = MAX ( dim_date[year] )
VAR OwnedNow = [Homes Acquired]
RETURN
    IF ( Year >= ThisYear && Year <= 2030, OwnedNow + ( 30000 - OwnedNow ) * ( Year - ThisYear ) / ( 2030 - ThisYear ) )""",
    ),
    (
        "Property management",
        "Current Tenancy (months)",
        ONE_DP,
        "How long the current tenant has lived in the home, renewals included (keeps rolling each month).",
        """VAR LiveJourneys =
    CALCULATETABLE ( VALUES ( fact_tenancy[original_tenancy_ref] ), fact_tenancy[is_live] = TRUE () )
RETURN
    MAXX ( LiveJourneys, CALCULATE ( SUM ( fact_tenancy[length_months] ) ) )""",
    ),
    (
        "Property management",
        "Property Picture",
        "",
        "Drawing of the home's property type (data category: Image URL).",
        PICTURE_DAX,
    ),
    (
        "Operations\\Lettings",
        "Avg Viewings per Listing",
        ONE_DP,
        "",
        "AVERAGE ( fact_lettings_funnel[viewings] )",
    ),
    (
        "Operations\\Lettings",
        "Avg Attended Viewings per Listing",
        ONE_DP,
        "",
        "AVERAGE ( fact_lettings_funnel[viewings_attended] )",
    ),
    (
        "Operations\\Lettings",
        "Avg Offers per Listing",
        ONE_DP,
        "",
        "AVERAGE ( fact_lettings_funnel[offers] )",
    ),
    (
        "Operations\\Lettings",
        "Avg Lets per Listing",
        "0.00",
        "",
        "AVERAGE ( fact_lettings_funnel[accepted_offers] )",
    ),
    (
        "Operations\\Maintenance",
        "Required Certificates",
        WHOLE,
        "Certificates rental homes need today (Gas only where there is gas).",
        "COUNTROWS ( fact_compliance_status )",
    ),
    (
        "Property management",
        "Avg Rent",
        MONEY,
        "Average monthly rent of live tenancies.",
        "CALCULATE ( AVERAGE ( fact_tenancy[rent_pcm] ), fact_tenancy[is_live] = TRUE (), REMOVEFILTERS ( dim_date ) )",
    ),
]

# Measures are stored on the main fact table of their page.
HOME = {
    "Finance": "fact_rent_transaction",
    "Property management": "fact_tenancy",
    "Operations\Maintenance": "fact_repair_job",
    "Operations\Lettings": "fact_lettings_funnel",
}

# (from table, from column, to table, to column, active). Facts to dimensions, many to one.
DATE_LINKS = [
    ("fact_rent_transaction", "date_key", True),
    ("fact_arrears_monthly", "month_key", True),
    ("fact_payment_timing", "paid_date_key", True),
    ("fact_tenancy", "start_date_key", True),
    ("fact_tenancy", "end_date_key", False),
    ("fact_occupancy_monthly", "month_key", True),
    ("fact_void_period", "void_start_key", True),
    ("fact_ownership_share", "effective_from_key", True),
    ("fact_repair_job", "created_date_key", True),
    ("fact_lettings_funnel", "listed_date_key", True),
    ("fact_lettings_funnel", "agreed_date_key", False),
    ("fact_viewing", "viewing_date_key", True),
    ("fact_offer", "offer_date_key", True),
    ("fact_purchase_invoice", "invoice_date_key", True),
]
PROPERTY_FACTS = [
    "fact_rent_transaction",
    "fact_arrears_monthly",
    "fact_arrears_aged",
    "fact_payment_timing",
    "fact_tenancy",
    "fact_occupancy_monthly",
    "fact_void_period",
    "fact_ownership_share",
    "fact_arrears_risk",
    "fact_repair_job",
    "fact_compliance_status",
    "fact_lettings_funnel",
    "fact_viewing",
    "fact_offer",
    "fact_purchase_invoice",
]
TENANT_FACTS = [
    "fact_rent_transaction",
    "fact_arrears_monthly",
    "fact_arrears_aged",
    "fact_payment_timing",
    "fact_tenancy",
    "fact_ownership_share",
    "fact_arrears_risk",
]
RELATIONSHIPS: list[tuple[str, str, str, str, bool]] = (
    [(f, c, "dim_date", "date_key", active) for f, c, active in DATE_LINKS]
    + [(f, "property_key", "dim_property", "property_key", True) for f in PROPERTY_FACTS]
    + [(f, "tenant_key", "dim_tenant", "tenant_key", True) for f in TENANT_FACTS]
    + [
        (f, "supplier_key", "dim_supplier", "supplier_key", True)
        for f in ("fact_repair_job", "fact_compliance_status", "fact_purchase_invoice")
    ]
    + [
        (f, "negotiator_staff_key", "dim_staff", "staff_key", True)
        for f in ("fact_lettings_funnel", "fact_viewing", "fact_offer")
    ]
    + [
        (f, "applicant_key", "dim_applicant", "applicant_key", True)
        for f in ("fact_viewing", "fact_offer")
    ]
)


def quote(name: str) -> str:
    return f"'{name}'" if not name.isidentifier() else name


# Measures whose text is a picture; Power BI shows them as images.
IMAGE_MEASURES = {"Property Picture"}


def measure_block(folder: str, name: str, fmt: str, desc: str, dax: str) -> list[str]:
    out = [f"\t\t/// {desc}"] if desc else []
    lines = dax.strip().splitlines()
    if len(lines) == 1:
        out.append(f"\t\tmeasure {quote(name)} = {lines[0]}")
    else:
        out.append(f"\t\tmeasure {quote(name)} =")
        out += [f"\t\t\t\t{line}" for line in lines]
    if fmt:
        out.append(f"\t\t\tformatString: {fmt}")
    if name in IMAGE_MEASURES:
        out.append("\t\t\tdataCategory: ImageUrl")
    out += [f"\t\t\tdisplayFolder: {folder}", ""]
    return out


def measures_tmdl() -> str:
    """createOrReplace script adding measures to existing tables (ref = don't touch the table)."""
    out = [
        "createOrReplace",
        "",
    ]
    # One "ref table" block per table, holding the measures of every folder stored on it.
    for home in dict.fromkeys(HOME.values()):
        block = [
            line
            for f, name, fmt, desc, dax in MEASURES
            if HOME[f] == home
            for line in measure_block(f, name, fmt, desc, dax)
        ]
        if block:
            out += [f"\tref table {home}", "", *block]
    return "\n".join(out)


def relationships_tmdl() -> str:
    out = [
        "createOrReplace",
        "",
    ]
    for frm, fcol, to, tcol, active in RELATIONSHIPS:
        out.append(f"\trelationship {frm}_{fcol}_{to}")
        if not active:
            out.append("\t\tisActive: false")
        out += [f"\t\tfromColumn: {frm}.{fcol}", f"\t\ttoColumn: {to}.{tcol}", ""]
    return "\n".join(out)


def dax_listing() -> str:
    out = ["-- Generated by powerbi/build_measures.py. Same measures as the .tmdl files.", ""]
    folder = None
    for f, name, _fmt, desc, dax in MEASURES:
        if f != folder:
            out += [f"-- ===== {f} (stored on {HOME[f]}) " + "=" * 30, ""]
            folder = f
        if desc:
            out.append(f"-- {desc}")
        out.append(f"[{name}] =")
        out += [f"    {line}" for line in dax.strip().splitlines()]
        out.append("")
    return "\n".join(out)


def main() -> None:
    (HERE / "relationships.tmdl").write_text(relationships_tmdl(), encoding="utf-8")
    (HERE / "measures.tmdl").write_text(measures_tmdl(), encoding="utf-8")
    (HERE / "measures.dax").write_text(dax_listing(), encoding="utf-8")
    print(f"wrote {len(RELATIONSHIPS)} relationships and {len(MEASURES)} measures to powerbi/")


if __name__ == "__main__":
    main()
