# -*- coding: utf-8 -*-
"""Licensing package for AI Synthetic Data Studio (Open-Core SaaS).

Client side only: this package VERIFIES licences and provenance. Issuing
licences and verifying payment webhooks live in ``tools/license_admin.py``,
outside the shipped package.
"""
from .manager import (
    LicenseInfo,
    LicenseManager,
    LicenseStatus,
    LicenseTier,
    ProFeatureRequiredError,
    get_license_manager,
    is_enterprise,
    is_pro,
    load_revoked_keys,
)
from .provenance import (
    ProvenanceVerification,
    sign_provenance,
    verify_provenance,
)

__all__ = [
    "LicenseInfo",
    "LicenseManager",
    "LicenseStatus",
    "LicenseTier",
    "ProFeatureRequiredError",
    "ProvenanceVerification",
    "get_license_manager",
    "is_enterprise",
    "is_pro",
    "load_revoked_keys",
    "sign_provenance",
    "verify_provenance",
]
