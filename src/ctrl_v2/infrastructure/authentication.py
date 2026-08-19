from __future__ import annotations

import json
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWK, PyJWKClient

from ctrl_v2.application.ports.authentication import VerifiedIdentity
from ctrl_v2.domain.enums import PrincipalType
from ctrl_v2.domain.exceptions import AuthenticationError

MAX_AUTHORIZATION_LENGTH = 16_384


def _bearer_token(authorization: str | None, expected_scheme: str) -> str:
    if authorization is None or len(authorization) > MAX_AUTHORIZATION_LENGTH:
        raise AuthenticationError("Authentication failed")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].casefold() != expected_scheme.casefold() or not parts[1]:
        raise AuthenticationError("Authentication failed")
    return parts[1]


class DevelopmentIdentityVerifier:
    """Explicit non-production bypass using a fixed local issuer and Dev auth scheme."""

    issuer = "urn:ctrl-v2:development"

    def verify_readiness(self) -> None:
        return None

    def verify(self, authorization: str | None) -> VerifiedIdentity:
        subject = _bearer_token(authorization, "Dev")
        if len(subject) > 500 or any(character.isspace() for character in subject):
            raise AuthenticationError("Authentication failed")
        return VerifiedIdentity(self.issuer, subject, PrincipalType.USER.value)


class OidcIdentityVerifier:
    """Validates signed OIDC access tokens against an explicitly configured trust boundary."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        allowed_algorithms: tuple[str, ...],
        principal_type_claim: str,
        jwks_json: str | None = None,
        jwks_url: str | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.allowed_algorithms = allowed_algorithms
        self.principal_type_claim = principal_type_claim
        self._inline_keys: dict[str, PyJWK] = {}
        self._jwks_client: PyJWKClient | None = None
        if jwks_json is not None:
            self._inline_keys = self._parse_inline_jwks(jwks_json)
        elif jwks_url is not None:
            self._jwks_client = PyJWKClient(
                jwks_url,
                cache_jwk_set=True,
                lifespan=300,
                timeout=5,
            )
        else:
            raise ValueError("OIDC requires JWKS_JSON or JWKS_URL")

    def verify_readiness(self) -> None:
        if self._inline_keys:
            return
        if self._jwks_client is None:
            raise RuntimeError("OIDC JWKS verifier is unavailable")
        try:
            jwk_set = self._jwks_client.get_jwk_set(refresh=True)
        except Exception as exc:
            raise RuntimeError("OIDC JWKS readiness verification failed") from exc
        if not jwk_set.keys:
            raise RuntimeError("OIDC JWKS contains no signing keys")

    def verify(self, authorization: str | None) -> VerifiedIdentity:
        token = _bearer_token(authorization, "Bearer")
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if (
                algorithm not in self.allowed_algorithms
                or not isinstance(key_id, str)
                or not key_id
            ):
                raise AuthenticationError("Authentication failed")
            signing_key = self._signing_key(token, key_id)
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(self.allowed_algorithms),
                issuer=self.issuer,
                audience=self.audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject or len(subject) > 500:
                raise AuthenticationError("Authentication failed")
            principal_type_value = claims.get(
                self.principal_type_claim,
                PrincipalType.USER.value,
            )
            principal_type = PrincipalType(principal_type_value)
        except AuthenticationError:
            raise
        except (InvalidTokenError, ValueError, TypeError, KeyError) as exc:
            raise AuthenticationError("Authentication failed") from exc
        return VerifiedIdentity(self.issuer, subject, principal_type.value)

    def _signing_key(self, token: str, key_id: str) -> Any:
        if self._inline_keys:
            key = self._inline_keys.get(key_id)
            if key is None:
                raise AuthenticationError("Authentication failed")
            return key.key
        if self._jwks_client is None:
            raise AuthenticationError("Authentication failed")
        try:
            return self._jwks_client.get_signing_key_from_jwt(token).key
        except Exception as exc:
            raise AuthenticationError("Authentication failed") from exc

    def _parse_inline_jwks(self, value: str) -> dict[str, PyJWK]:
        try:
            payload = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("OIDC_JWKS_JSON must be valid JSON") from exc
        raw_keys = payload.get("keys") if isinstance(payload, dict) else None
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ValueError("OIDC_JWKS_JSON must contain signing keys")
        parsed: dict[str, PyJWK] = {}
        private_parameters = {"d", "p", "q", "dp", "dq", "qi", "k"}
        for raw_key in raw_keys:
            if not isinstance(raw_key, dict) or private_parameters.intersection(raw_key):
                raise ValueError("OIDC_JWKS_JSON must contain public keys only")
            key_id = raw_key.get("kid")
            algorithm = raw_key.get("alg")
            if (
                not isinstance(key_id, str)
                or not key_id
                or key_id in parsed
                or algorithm not in self.allowed_algorithms
                or raw_key.get("kty") not in {"RSA", "EC"}
                or raw_key.get("use", "sig") != "sig"
            ):
                raise ValueError("OIDC_JWKS_JSON contains an unsafe signing key")
            parsed[key_id] = PyJWK.from_dict(raw_key, algorithm=algorithm)
        return parsed
