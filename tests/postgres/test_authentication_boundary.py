from __future__ import annotations

import json
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ctrl_v2.infrastructure.authentication import OidcIdentityVerifier
from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings
from tests.auth_helpers import TokenIssuer, bearer

pytestmark = pytest.mark.postgres


@pytest.fixture()
def oidc_client(postgres_urls, tmp_path):
    issuer = TokenIssuer()
    settings = Settings(
        database_url=postgres_urls.runtime,
        object_storage_root=tmp_path / "private-objects",
        environment="production",
        auth_mode="oidc",
        oidc_issuer=issuer.issuer,
        oidc_audience=issuer.audience,
        oidc_jwks_json=issuer.jwks_json,
        provisioning_principals={f"{issuer.issuer}|operator"},
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client, issuer


@pytest.mark.parametrize("path", ["/api/v1/me", "/health"])
def test_unauthenticated_request_is_401(oidc_client, path):
    client, _ = oidc_client

    response = client.get(path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_api_documentation_is_not_exposed(oidc_client, path):
    client, issuer = oidc_client

    response = client.get(path, headers=bearer(issuer.token("docs-check")))

    assert response.status_code == 404


@pytest.mark.parametrize(
    "token_factory",
    [
        pytest.param(lambda trusted: TokenIssuer().token("user"), id="invalid-signature"),
        pytest.param(
            lambda trusted: trusted.token("user", expires_delta=timedelta(seconds=-1)),
            id="expired",
        ),
        pytest.param(
            lambda trusted: trusted.token("user", issuer="https://attacker.example/"),
            id="wrong-issuer",
        ),
        pytest.param(
            lambda trusted: trusted.token("user", audience="other-api"),
            id="wrong-audience",
        ),
        pytest.param(lambda trusted: "not-a-jwt", id="malformed"),
    ],
)
def test_invalid_oidc_token_is_denied(oidc_client, token_factory):
    client, issuer = oidc_client

    response = client.get("/api/v1/me", headers=bearer(token_factory(issuer)))

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication failed"


def test_valid_signed_identity_is_persisted_and_returned(oidc_client):
    client, issuer = oidc_client
    headers = bearer(issuer.token("alice"))

    first = client.get("/api/v1/me", headers=headers)
    second = client.get("/api/v1/me", headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["issuer"] == issuer.issuer
    assert first.json()["subject"] == "alice"
    assert first.json()["principal_type"] == "USER"


def test_service_principal_type_is_derived_from_verified_claim(oidc_client):
    client, issuer = oidc_client

    response = client.get(
        "/api/v1/me",
        headers=bearer(issuer.token("service-account", principal_type="SERVICE")),
    )

    assert response.status_code == 200
    assert response.json()["principal_type"] == "SERVICE"


def test_principal_type_cannot_change_for_existing_identity(oidc_client):
    client, issuer = oidc_client
    user = client.get("/api/v1/me", headers=bearer(issuer.token("stable-type")))

    changed = client.get(
        "/api/v1/me",
        headers=bearer(issuer.token("stable-type", principal_type="SERVICE")),
    )

    assert user.status_code == 200
    assert changed.status_code == 401


def test_production_dev_bypass_is_rejected(postgres_urls, tmp_path):
    with pytest.raises(ValidationError, match="forbidden in production"):
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path,
            environment="production",
            auth_mode="dev",
            dev_auth_enabled=True,
        )


def test_production_requires_complete_oidc_configuration(postgres_urls, tmp_path):
    with pytest.raises(ValidationError, match="OIDC_ISSUER and OIDC_AUDIENCE"):
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path,
            environment="production",
            auth_mode="oidc",
        )


def test_production_rejects_unsafe_oidc_configuration(postgres_urls, tmp_path):
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            database_url=postgres_urls.runtime,
            object_storage_root=tmp_path,
            environment="production",
            auth_mode="oidc",
            oidc_issuer="http://identity.invalid/",
            oidc_audience="ctrl-v2",
            oidc_jwks_url="http://identity.invalid/jwks",
        )


def test_inline_jwks_rejects_private_signing_material():
    with pytest.raises(ValueError, match="public keys only"):
        OidcIdentityVerifier(
            issuer="https://identity.example/",
            audience="ctrl-v2",
            allowed_algorithms=("RS256",),
            principal_type_claim="principal_type",
            jwks_json=json.dumps(
                {
                    "keys": [
                        {
                            "kty": "RSA",
                            "kid": "unsafe",
                            "alg": "RS256",
                            "use": "sig",
                            "n": "AQAB",
                            "e": "AQAB",
                            "d": "private",
                        }
                    ]
                }
            ),
        )


def test_authentication_logs_do_not_contain_token_or_claims(oidc_client, caplog):
    client, issuer = oidc_client
    caplog.set_level(logging.INFO)
    token = issuer.token("log-secret-subject")

    response = client.get("/api/v1/me", headers=bearer(token))

    assert response.status_code == 200
    assert token not in caplog.text
    assert "log-secret-subject" not in caplog.text
