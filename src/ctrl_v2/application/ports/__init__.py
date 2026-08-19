"""Outbound ports implemented by infrastructure adapters."""
from .authentication import IdentityVerifier, VerifiedIdentity

__all__ = ["IdentityVerifier", "VerifiedIdentity"]
