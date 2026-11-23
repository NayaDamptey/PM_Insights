"""MRI Qube PM v1: https://[MRIWebDomain]/qube/api/v1/..."""

from mock_api.auth import require_mri_basic
from mock_api.routers.mri_v1 import Child, Resource, build_router

RESOURCES = {
    "staff": Resource("qube_staff", "StaffCode"),
    "blocks": Resource("qube_blocks", "BlockRef"),
    "properties": Resource("qube_properties", "PropertyRef"),
    "tenants": Resource("qube_tenants", "TenantRef"),
    "tenancies": Resource("qube_tenancies", "TenancyRef"),
    "suppliers": Resource("qube_suppliers", "SupplierCode"),
    "purchase-invoices": Resource("qube_purchase_invoices", "InvoiceId"),
    "suspense-items": Resource("qube_suspense_items", "ItemId"),
    "landlords": Resource("qube_landlords", "LandlordRef"),
}

CHILDREN = {
    ("tenancies", "tenants"): Child("qube_tenancy_tenants", "TenancyRef"),
    ("tenancies", "transactions"): Child("qube_transactions", "TenancyRef"),
    ("properties", "certificates"): Child("qube_compliance_certificates", "PropertyRef"),
    ("properties", "owners"): Child("qube_property_owners", "PropertyRef"),
    ("landlords", "bank-accounts"): Child("qube_landlord_bank_accounts", "LandlordRef"),
}

router = build_router("/qube/api/v1", "MRI Qube PM", RESOURCES, CHILDREN, require_mri_basic)
