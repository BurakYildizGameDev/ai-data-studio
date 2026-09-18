# -*- coding: utf-8 -*-
"""Ephemeral Ed25519 key material for the licensing test-suite.

The suite used to sign its fixtures with the *production* private key, pasted
as a literal next to the public key it matched.  That made the master signing
key a public artifact: anyone with a checkout could mint lifetime Enterprise
tokens, and no rotation could undo it once the commit was pushed.

Tests do not need the production key.  They need *a* key pair whose public half
the manager under test trusts.  Every helper here generates a fresh pair per
call, so the repository carries no secret and a leak of the test-suite leaks
nothing.
"""
from __future__ import annotations

import base64
from typing import Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from ai_data_studio.licensing import manager as _manager
from ai_data_studio.licensing.manager import LicenseManager

__all__ = [
    "ephemeral_keypair",
    "ephemeral_manager",
    "install_ephemeral_global_manager",
    "restore_global_manager",
]


def ephemeral_keypair() -> Tuple[str, str]:
    """Return a freshly generated ``(private_b64, public_b64)`` Ed25519 pair.

    Both halves are raw 32-byte keys in standard base64, the encoding
    :func:`generate_signed_license` and :class:`LicenseManager` expect.
    """
    private = ed25519.Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return (
        base64.b64encode(private_raw).decode("ascii"),
        base64.b64encode(public_raw).decode("ascii"),
    )


def ephemeral_manager() -> Tuple[LicenseManager, str]:
    """Return a ``(manager, private_key_b64)`` pair that trust each other.

    Sign fixtures with the returned private key and the returned manager will
    verify them, without the production key being involved at any point.
    """
    private_b64, public_b64 = ephemeral_keypair()
    return LicenseManager(public_key_b64=public_b64), private_b64


def install_ephemeral_global_manager() -> str:
    """Point the module-level singleton at an ephemeral key; return its private half.

    Code paths that reach for :func:`get_license_manager` — the GUI badge, the
    license dialog, PDF export gating — resolve the singleton rather than an
    injected manager, so they can only be exercised by swapping it out.  Pair
    with :func:`restore_global_manager` in ``tearDown``.
    """
    manager, private_b64 = ephemeral_manager()
    _manager._GLOBAL_MANAGER = manager
    return private_b64


def restore_global_manager() -> None:
    """Drop the swapped-in singleton so later tests rebuild the real one."""
    _manager._GLOBAL_MANAGER = None
