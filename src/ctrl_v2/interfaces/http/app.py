from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ctrl_v2.application.access_control import AccessControlService, WorkspaceAccess
from ctrl_v2.application.records import PrincipalRecord
from ctrl_v2.application.walking_skeleton import Stage1Workflow
from ctrl_v2.domain.enums import DocumentKind, ReviewMode, WorkspaceRole
from ctrl_v2.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    DomainError,
    InvariantViolation,
    NotFoundError,
    ObjectIntegrityError,
)
from ctrl_v2.infrastructure.authentication import (
    DevelopmentIdentityVerifier,
    OidcIdentityVerifier,
)
from ctrl_v2.infrastructure.export import DeterministicXlsxExporter
from ctrl_v2.infrastructure.ingestion import ParserRegistry
from ctrl_v2.infrastructure.object_storage import PrivateFileObjectStorage
from ctrl_v2.infrastructure.persistence import Database, SqlAlchemyUnitOfWorkFactory

from .config import Settings
from .logging import safe_access_log
from .schemas import (
    ApprovalCreate,
    BatchApprovalCreate,
    CapabilityAssignmentCreate,
    CapabilityCreate,
    DecisionCreate,
    DecisionUpdate,
    EvidenceSpanCreate,
    MappingCreate,
    MembershipCreate,
    MembershipUpdate,
    ProductCreate,
    ProductVersionCreate,
    ProductVersionDocumentCreate,
    RequirementCreate,
    ResponseCreate,
    ReviewCreate,
    RfpCreate,
    WorkspaceCreate,
)


def _workflow(request: Request) -> Stage1Workflow:
    return request.app.state.workflow


def _access_control(request: Request) -> AccessControlService:
    return request.app.state.access_control


def _current_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> PrincipalRecord:
    return _access_control(request).authenticate(authorization)


CurrentPrincipal = Annotated[PrincipalRecord, Depends(_current_principal)]


def _operator_principal(
    request: Request,
    principal: CurrentPrincipal,
) -> PrincipalRecord:
    _access_control(request).require_operator(principal)
    return principal


OperatorPrincipal = Annotated[PrincipalRecord, Depends(_operator_principal)]


def _authorize_workspace(
    request: Request,
    principal: PrincipalRecord,
    workspace_id: str,
    roles: frozenset[WorkspaceRole],
) -> WorkspaceAccess:
    return _access_control(request).authorize_workspace(principal, workspace_id, roles)


def _viewer_access(
    request: Request, workspace_id: str, principal: CurrentPrincipal
) -> WorkspaceAccess:
    return _authorize_workspace(request, principal, workspace_id, frozenset(WorkspaceRole))


def _editor_access(
    request: Request, workspace_id: str, principal: CurrentPrincipal
) -> WorkspaceAccess:
    return _authorize_workspace(
        request,
        principal,
        workspace_id,
        frozenset({WorkspaceRole.EDITOR, WorkspaceRole.ADMIN}),
    )


def _approver_access(
    request: Request, workspace_id: str, principal: CurrentPrincipal
) -> WorkspaceAccess:
    return _authorize_workspace(
        request,
        principal,
        workspace_id,
        frozenset({WorkspaceRole.APPROVER, WorkspaceRole.ADMIN}),
    )


def _admin_access(
    request: Request, workspace_id: str, principal: CurrentPrincipal
) -> WorkspaceAccess:
    return _authorize_workspace(
        request,
        principal,
        workspace_id,
        frozenset({WorkspaceRole.ADMIN}),
    )


ViewerAccess = Annotated[WorkspaceAccess, Depends(_viewer_access)]
EditorAccess = Annotated[WorkspaceAccess, Depends(_editor_access)]
ApproverAccess = Annotated[WorkspaceAccess, Depends(_approver_access)]
AdminAccess = Annotated[WorkspaceAccess, Depends(_admin_access)]


def create_app(settings: Settings) -> FastAPI:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    database = Database(settings.database_url.get_secret_value())
    storage = PrivateFileObjectStorage(settings.object_storage_root)
    workflow = Stage1Workflow(
        SqlAlchemyUnitOfWorkFactory(database.session_factory),
        storage,
        ParserRegistry(),
        DeterministicXlsxExporter(),
        max_upload_bytes=settings.max_upload_bytes,
    )
    if settings.auth_mode == "dev":
        identity_verifier = DevelopmentIdentityVerifier()
    else:
        identity_verifier = OidcIdentityVerifier(
            issuer=settings.oidc_issuer or "",
            audience=settings.oidc_audience or "",
            allowed_algorithms=settings.oidc_allowed_algorithms,
            principal_type_claim=settings.oidc_principal_type_claim,
            jwks_json=(
                settings.oidc_jwks_json.get_secret_value()
                if settings.oidc_jwks_json is not None
                else None
            ),
            jwks_url=settings.oidc_jwks_url,
        )
    access_control = AccessControlService(
        identity_verifier,
        SqlAlchemyUnitOfWorkFactory(database.session_factory),
        settings.provisioning_principals,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.verify_runtime_readiness()
        access_control.verify_readiness()
        yield

    production_docs_url = None if settings.environment == "production" else "/docs"
    production_redoc_url = None if settings.environment == "production" else "/redoc"
    production_openapi_url = (
        None if settings.environment == "production" else "/openapi.json"
    )
    app = FastAPI(
        title="CTRL v2",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(_current_principal)],
        docs_url=production_docs_url,
        redoc_url=production_redoc_url,
        openapi_url=production_openapi_url,
    )
    app.state.database = database
    app.state.workflow = workflow
    app.state.access_control = access_control
    app.middleware("http")(safe_access_log)

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(_: Request, __: AuthenticationError) -> JSONResponse:
        return JSONResponse(
            content={
                "type": "authentication-error",
                "title": "Authentication required",
                "status": 401,
                "detail": "Authentication failed",
            },
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            media_type="application/problem+json",
        )

    @app.exception_handler(AuthorizationError)
    async def authorization_error_handler(_: Request, __: AuthorizationError) -> JSONResponse:
        return JSONResponse(
            content={
                "type": "authorization-error",
                "title": "Access denied",
                "status": 403,
                "detail": "Access denied",
            },
            status_code=403,
            media_type="application/problem+json",
        )

    @app.exception_handler(ObjectIntegrityError)
    async def object_integrity_error_handler(
        _: Request, __: ObjectIntegrityError
    ) -> JSONResponse:
        return JSONResponse(
            content={
                "type": "object-integrity-error",
                "title": "Stored object integrity failure",
                "status": 409,
                "detail": "Stored object failed integrity verification",
            },
            status_code=409,
            media_type="application/problem+json",
        )

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, NotFoundError):
            status = 404
        elif isinstance(exc, ConflictError | InvariantViolation):
            status = 409
        else:
            status = 400
        return JSONResponse(
            content={
                "type": "domain-error",
                "title": "Request rejected",
                "status": status,
                "detail": str(exc),
            },
            status_code=status,
            media_type="application/problem+json",
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        database.verify_runtime_readiness()
        return {"status": "ready"}

    @app.get("/api/v1/me")
    def me(principal: CurrentPrincipal) -> dict[str, object]:
        return {
            "id": principal.id,
            "issuer": principal.issuer,
            "subject": principal.subject,
            "principal_type": principal.principal_type,
            "active": principal.active,
        }

    @app.post("/api/v1/workspaces", status_code=201)
    def create_workspace(
        body: WorkspaceCreate,
        request: Request,
        principal: OperatorPrincipal,
    ) -> dict[str, Any]:
        return _workflow(request).create_workspace(body.name, principal.id)

    @app.post(
        "/api/v1/operator/workspaces/{workspace_id}/bootstrap-admin",
        status_code=201,
    )
    def bootstrap_workspace_admin(
        request: Request,
        workspace_id: str,
        principal: OperatorPrincipal,
    ) -> dict[str, object]:
        service = _access_control(request)
        membership = service.bootstrap_operator_admin(workspace_id, principal)
        return service.membership_dict(membership)

    @app.get("/api/v1/workspaces/{workspace_id}/memberships")
    def list_memberships(
        request: Request,
        workspace_id: str,
        _: AdminAccess,
    ) -> list[dict[str, object]]:
        service = _access_control(request)
        return [
            service.membership_dict(item) for item in service.list_memberships(workspace_id)
        ]

    @app.post("/api/v1/workspaces/{workspace_id}/memberships", status_code=201)
    def create_membership(
        request: Request,
        workspace_id: str,
        body: MembershipCreate,
        _: AdminAccess,
    ) -> dict[str, object]:
        service = _access_control(request)
        membership = service.add_membership(workspace_id, body.principal_id, body.role)
        return service.membership_dict(membership)

    @app.patch("/api/v1/workspaces/{workspace_id}/memberships/{principal_id}")
    def update_membership(
        request: Request,
        workspace_id: str,
        principal_id: str,
        body: MembershipUpdate,
        _: AdminAccess,
    ) -> dict[str, object]:
        service = _access_control(request)
        membership = service.update_membership(
            workspace_id,
            principal_id,
            role=body.role,
            active=body.active,
        )
        return service.membership_dict(membership)

    @app.post("/api/v1/workspaces/{workspace_id}/documents", status_code=201)
    async def upload_document(
        request: Request,
        workspace_id: str,
        _: EditorAccess,
        title: Annotated[str, Form(min_length=1)],
        kind: Annotated[DocumentKind, Form()],
        file: Annotated[UploadFile, File()],
        published_at: Annotated[date | None, Form()] = None,
    ) -> dict[str, Any]:
        content = await file.read(settings.max_upload_bytes + 1)
        return _workflow(request).upload_document(
            workspace_id=workspace_id,
            title=title,
            kind=kind.value,
            filename=file.filename or "unnamed",
            media_type=file.content_type or "application/octet-stream",
            content=content,
            published_at=published_at,
        )

    @app.get("/api/v1/workspaces/{workspace_id}/document-versions/{version_id}/content")
    def download_document(
        request: Request, workspace_id: str, version_id: str, _: ViewerAccess
    ) -> StreamingResponse:
        content, media_type = _workflow(request).get_document_content(workspace_id, version_id)
        return StreamingResponse(iter([content]), media_type=media_type)

    @app.post("/api/v1/workspaces/{workspace_id}/rfps", status_code=201)
    def create_rfp(
        request: Request, workspace_id: str, body: RfpCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_rfp(
            workspace_id,
            body.name,
            body.source_document_version_id,
            body.assessment_as_of,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/requirements", status_code=201)
    def create_requirement(
        request: Request, workspace_id: str, body: RequirementCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_requirement(workspace_id=workspace_id, **body.model_dump())

    @app.post("/api/v1/workspaces/{workspace_id}/products", status_code=201)
    def create_product(
        request: Request, workspace_id: str, body: ProductCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_product(workspace_id, body.name)

    @app.post("/api/v1/workspaces/{workspace_id}/products/{product_id}/versions", status_code=201)
    def create_product_version(
        request: Request,
        workspace_id: str,
        product_id: str,
        body: ProductVersionCreate,
        _: EditorAccess,
    ) -> dict[str, Any]:
        return _workflow(request).create_product_version(
            workspace_id, product_id, body.version_label, body.valid_from, body.valid_to
        )

    @app.post("/api/v1/workspaces/{workspace_id}/capabilities", status_code=201)
    def create_capability(
        request: Request, workspace_id: str, body: CapabilityCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_capability(
            workspace_id, body.canonical_key, body.name, body.description
        )

    @app.post(
        "/api/v1/workspaces/{workspace_id}/product-versions/{version_id}/capabilities",
        status_code=201,
    )
    def assign_capability(
        request: Request,
        workspace_id: str,
        version_id: str,
        body: CapabilityAssignmentCreate,
        _: EditorAccess,
    ) -> dict[str, Any]:
        return _workflow(request).assign_capability(
            workspace_id, version_id, body.capability_id, body.valid_from, body.valid_to
        )

    @app.post(
        "/api/v1/workspaces/{workspace_id}/product-versions/{version_id}/documents",
        status_code=201,
    )
    def attach_product_document(
        request: Request,
        workspace_id: str,
        version_id: str,
        body: ProductVersionDocumentCreate,
        _: EditorAccess,
    ) -> dict[str, Any]:
        return _workflow(request).attach_product_document(
            workspace_id,
            version_id,
            body.document_version_id,
            body.source_type.value,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/requirement-mappings", status_code=201)
    def create_mapping(
        request: Request, workspace_id: str, body: MappingCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_mapping(workspace_id, **body.model_dump())

    @app.post("/api/v1/workspaces/{workspace_id}/evidence-spans", status_code=201)
    def create_evidence_span(
        request: Request, workspace_id: str, body: EvidenceSpanCreate, access: EditorAccess
    ) -> dict[str, Any]:
        values = body.model_dump()
        return _workflow(request).create_evidence_span(
            workspace_id=workspace_id,
            created_by_principal_id=access.principal.id,
            **values,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions", status_code=201)
    def create_decision(
        request: Request, workspace_id: str, body: DecisionCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_decision(workspace_id=workspace_id, **body.model_dump())

    @app.patch("/api/v1/workspaces/{workspace_id}/compliance-decisions/{decision_id}")
    def update_decision(
        request: Request,
        workspace_id: str,
        decision_id: str,
        body: DecisionUpdate,
        _: EditorAccess,
    ) -> dict[str, Any]:
        return _workflow(request).update_decision(
            workspace_id, decision_id, rationale=body.rationale, confidence=body.confidence
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions/{decision_id}/approve")
    def approve_decision(
        request: Request,
        workspace_id: str,
        decision_id: str,
        body: ApprovalCreate,
        access: ApproverAccess,
    ) -> dict[str, Any]:
        return _workflow(request).approve_decision(
            workspace_id,
            decision_id,
            access.principal.id,
            body.comment,
            ReviewMode.SINGLE,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions/batch-approve")
    def batch_approve(
        request: Request,
        workspace_id: str,
        body: BatchApprovalCreate,
        access: ApproverAccess,
    ) -> list[dict[str, Any]]:
        return _workflow(request).batch_approve(
            workspace_id, body.decision_ids, access.principal.id, body.comment
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions/{decision_id}/reject")
    def reject_decision(
        request: Request,
        workspace_id: str,
        decision_id: str,
        body: ReviewCreate,
        access: ApproverAccess,
    ) -> dict[str, Any]:
        return _workflow(request).reject_decision(
            workspace_id,
            decision_id,
            access.principal.id,
            body.comment,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions/{decision_id}/escalate")
    def escalate_decision(
        request: Request,
        workspace_id: str,
        decision_id: str,
        body: ReviewCreate,
        access: ApproverAccess,
    ) -> dict[str, Any]:
        return _workflow(request).escalate_decision(
            workspace_id,
            decision_id,
            access.principal.id,
            body.comment,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/responses", status_code=201)
    def create_response(
        request: Request, workspace_id: str, body: ResponseCreate, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_response(workspace_id, body.rfp_id, body.decision_ids)

    @app.post("/api/v1/workspaces/{workspace_id}/responses/{response_id}/export-xlsx")
    def export_response(
        request: Request, workspace_id: str, response_id: str, _: EditorAccess
    ) -> dict[str, Any]:
        return _workflow(request).export_response(workspace_id, response_id)

    @app.get("/api/v1/workspaces/{workspace_id}/exports/{export_id}/content")
    def download_export(
        request: Request, workspace_id: str, export_id: str, _: ViewerAccess
    ) -> StreamingResponse:
        content = _workflow(request).get_export_content(workspace_id, export_id)
        return StreamingResponse(
            iter([content]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(create_app(Settings()), host="127.0.0.1", port=8000)
