"""MRI Engage CRM v1: https://[EngageDomain]/engage/api/v1/..."""

from mock_api.auth import require_engage_bearer
from mock_api.routers.mri_v1 import Child, Resource, build_router

RESOURCES = {
    "negotiators": Resource("engage_negotiators", "NegotiatorCode"),
    "applicants": Resource("engage_applicants", "ApplicantId"),
    "listings": Resource("engage_listings", "ListingId"),
}

CHILDREN = {
    ("listings", "viewings"): Child("engage_viewings", "ListingId"),
    ("listings", "offers"): Child("engage_offers", "ListingId"),
}

router = build_router(
    "/engage/api/v1", "MRI Engage CRM", RESOURCES, CHILDREN, require_engage_bearer
)
