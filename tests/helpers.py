from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook


def xlsx_bytes(*values: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Requirements"
    for row_index, value in enumerate(values, start=1):
        sheet.cell(row=row_index, column=1, value=value)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class Journey:
    def __init__(
        self,
        client: TestClient,
        workspace_name: str = "Acme",
        *,
        principal_subject: str = "operator",
    ) -> None:
        self.client = client
        self.principal_subject = principal_subject
        auth_headers = {"Authorization": f"Dev {principal_subject}"}
        created = client.post(
            "/api/v1/workspaces",
            headers=auth_headers,
            json={"name": workspace_name},
        )
        assert created.status_code == 201, created.text
        self.workspace = created.json()
        self.workspace_id = self.workspace["id"]
        self.headers = auth_headers
        if "access_token" in self.workspace:
            self.headers = {"X-Workspace-Token": self.workspace["access_token"]}

    def post(self, path: str, **kwargs):
        return self.client.post(
            f"/api/v1/workspaces/{self.workspace_id}{path}",
            headers=self.headers,
            **kwargs,
        )

    def upload(self, text: str, kind: str, filename: str) -> dict:
        response = self.post(
            "/documents",
            data={"title": filename, "kind": kind, "published_at": "2026-01-01"},
            files={
                "file": (
                    filename,
                    xlsx_bytes(text),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
        assert response.status_code == 201, response.text
        return response.json()

    def build_until_decision(self, *, with_evidence: bool = True) -> dict:
        rfp_document = self.upload("The platform shall support SAML SSO.", "RFP", "rfp.xlsx")
        product_document = self.upload(
            "Product 7 supports SAML 2.0 single sign-on.",
            "PRODUCT_KNOWLEDGE",
            "official-spec.xlsx",
        )
        rfp_response = self.post(
            "/rfps",
            json={
                "name": "Security RFP",
                "source_document_version_id": rfp_document["document_version_id"],
                "assessment_as_of": "2026-08-17",
            },
        )
        assert rfp_response.status_code == 201, rfp_response.text
        rfp = rfp_response.json()
        source_text = rfp_document["blocks"][0]["text"]
        requirement_response = self.post(
            "/requirements",
            json={
                "rfp_id": rfp["id"],
                "source_order": 1,
                "atomic_text": "The platform shall support SAML SSO.",
                "modality": "MUST",
                "confidence": 0.98,
                "ambiguity_flags": [],
                "document_block_id": rfp_document["blocks"][0]["id"],
                "start_offset": 0,
                "end_offset": len(source_text),
            },
        )
        assert requirement_response.status_code == 201, requirement_response.text
        requirement = requirement_response.json()

        product_response = self.post("/products", json={"name": "CTRL Product"})
        assert product_response.status_code == 201, product_response.text
        product = product_response.json()
        version_response = self.post(
            f"/products/{product['id']}/versions",
            json={
                "version_label": "7.0",
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
            },
        )
        assert version_response.status_code == 201, version_response.text
        product_version = version_response.json()
        capability_response = self.post(
            "/capabilities",
            json={
                "canonical_key": "security.sso.saml",
                "name": "SAML SSO",
                "description": "SAML 2.0 single sign-on",
            },
        )
        assert capability_response.status_code == 201, capability_response.text
        capability = capability_response.json()
        assignment_response = self.post(
            f"/product-versions/{product_version['id']}/capabilities",
            json={
                "capability_id": capability["id"],
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
            },
        )
        assert assignment_response.status_code == 201, assignment_response.text
        document_link_response = self.post(
            f"/product-versions/{product_version['id']}/documents",
            json={
                "document_version_id": product_document["document_version_id"],
                "source_type": "OFFICIAL_SPECIFICATION",
            },
        )
        assert document_link_response.status_code == 201, document_link_response.text
        mapping_response = self.post(
            "/requirement-mappings",
            json={
                "requirement_id": requirement["id"],
                "product_version_id": product_version["id"],
                "capability_id": capability["id"],
                "rationale": "The requirement directly asks for the SAML SSO capability.",
                "confidence": 0.97,
            },
        )
        assert mapping_response.status_code == 201, mapping_response.text
        mapping = mapping_response.json()

        span = None
        if with_evidence:
            evidence_text = product_document["blocks"][0]["text"]
            evidence_response = self.post(
                "/evidence-spans",
                json={
                    "requirement_id": requirement["id"],
                    "product_version_id": product_version["id"],
                    "summary": "The official specification states SAML 2.0 support.",
                    "source_type": "OFFICIAL_SPECIFICATION",
                    "authority_level": "AUTHORITATIVE",
                    "valid_from": "2026-01-01",
                    "valid_to": "2026-12-31",
                    "document_version_id": product_document["document_version_id"],
                    "document_block_id": product_document["blocks"][0]["id"],
                    "start_offset": 0,
                    "end_offset": len(evidence_text),
                },
            )
            assert evidence_response.status_code == 201, evidence_response.text
            span = evidence_response.json()

        decision_response = self.post(
            "/compliance-decisions",
            json={
                "mapping_id": mapping["id"],
                "outcome": "COMPLY",
                "rationale": "Supported by the exact official specification span.",
                "confidence": 0.96,
                "evidence_span_ids": [span["evidence_span_id"]] if span else [],
                "policy_required": False,
            },
        )
        assert decision_response.status_code == 201, decision_response.text
        return {
            "rfp": rfp,
            "requirement": requirement,
            "product_version": product_version,
            "mapping": mapping,
            "evidence": span,
            "decision": decision_response.json(),
            "product_document": product_document,
        }
