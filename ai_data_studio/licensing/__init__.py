# -*- coding: utf-8 -*-
"""Licensing package for AI Synthetic Data Studio (Open-Core SaaS)."""
from .manager import (
    LicenseInfo,
    LicenseManager,
    LicenseStatus,
    LicenseTier,
    ProFeatureRequiredError,
    generate_signed_license,
    get_license_manager,
    is_enterprise,
    is_pro,
    verify_lemonsqueezy_webhook,
    verify_polar_webhook,
)

__all__ = [
    "LicenseInfo",
    "LicenseManager",
    "LicenseStatus",
    "LicenseTier",
    "ProFeatureRequiredError",
    "generate_signed_license",
    "get_license_manager",
    "is_enterprise",
    "is_pro",
    "verify_lemonsqueezy_webhook",
    "verify_polar_webhook",
]
