from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.utils import base64url_encode


def _integer_bytes(value: int) -> bytes:
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


@dataclass(slots=True)
class TokenIssuer:
    issuer: str = "https://identity.example.test/"
    audience: str = "ctrl-v2"
    key_id: str = "test-signing-key"
    private_key: rsa.RSAPrivateKey = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    @property
    def jwks_json(self) -> str:
        numbers = self.private_key.public_key().public_numbers()
        return json.dumps(
            {
                "keys": [
                    {
                        "kty": "RSA",
                        "kid": self.key_id,
                        "use": "sig",
                        "alg": "RS256",
                        "n": base64url_encode(_integer_bytes(numbers.n)).decode(),
                        "e": base64url_encode(_integer_bytes(numbers.e)).decode(),
                    }
                ]
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    def token(
        self,
        subject: str,
        *,
        expires_delta: timedelta = timedelta(minutes=5),
        issuer: str | None = None,
        audience: str | None = None,
        principal_type: str = "USER",
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": issuer or self.issuer,
            "aud": audience or self.audience,
            "sub": subject,
            "iat": now,
            "exp": now + expires_delta,
            "principal_type": principal_type,
        }
        claims.update(extra_claims or {})
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def dev_auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Dev {subject}"}
