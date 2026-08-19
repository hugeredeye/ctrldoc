from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    principal_type: str


class IdentityVerifier(Protocol):
    def verify_readiness(self) -> None: ...

    def verify(self, authorization: str | None) -> VerifiedIdentity: ...
