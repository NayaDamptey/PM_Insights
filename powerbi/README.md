# Power BI

The semantic model **LL_Insights** (Direct Lake on `ll_gold`, in the PM Insights workspace)
and the report built on it.

| File | What it is |
|---|---|
| `Property_Manager_Insights.pbip` | **The report.** Open this in Power BI Desktop |
| `Property_Manager_Insights.Report\` | The report's pages and visuals (PBIR format) |
| `relationships.tmdl` | All 45 relationships: TMDL view → paste → Apply |
| `measures.tmdl` | All measures, in display folders: TMDL view → paste → Apply |
| `measures.dax` | The same measures, readable |
| `build_measures.py` | Writes the three files above from one list of measures |

## Report pages

Overview · Finance · Property management · Property explorer · Operations: Lettings ·
Operations: Maintenance, switched with the page tabs. Each has a header, slicers and KPI
tiles.

## Public version

Publish to web does not accept Direct Lake models or models with security roles, so the
public report runs on a copy of the model in Import mode (**LL_Insights_Public**). It holds
the dimension and fact tables only, with no `security_user_access` table and no roles. It
is a snapshot: refresh it in Fabric when the Gold tables change.

## Changing measures

1. Edit `build_measures.py`, then regenerate:
   ```powershell
   .venv\Scripts\python powerbi\build_measures.py
   .venv\Scripts\python -m fabric.build_notebooks
   ```
2. Re-import `fabric\notebooks\06_model_measures.ipynb` in Fabric and Run all. It adds,
   updates and deletes measures to match `build_measures.py`. Then refresh LL_Insights.

## Notes

- The maps are Azure Maps visuals: the tenant settings *Users can use the Azure Maps
  visual* and the two *Data sent to Azure Maps…* settings must be on (Admin portal →
  Tenant settings → Integration settings).
- Row-level security roles: `governance/rls.md`.
