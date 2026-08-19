from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from ctrl_v2.application.walking_skeleton import Stage1Workflow
from ctrl_v2.domain.enums import DocumentKind, ReviewMode
from ctrl_v2.domain.exceptions import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InvariantViolation,
    NotFoundError,
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
    ProductCreate,
    ProductVersionCreate,
    ProductVersionDocumentCreate,
    RequirementCreate,
    ResponseCreate,
    RfpCreate,
    WorkspaceCreate,
)


def _workflow(request: Request) -> Stage1Workflow:
    return request.app.state.workflow


def _workspace_access(
    request: Request,
    workspace_id: str,
    x_workspace_token: Annotated[str, Header(min_length=20)],
) -> str:
    _workflow(request).authenticate(workspace_id, x_workspace_token)
    return workspace_id


WorkspaceAccess = Annotated[str, Depends(_workspace_access)]


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
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.verify_runtime_readiness()
        yield

    app = FastAPI(title="CTRL v2", version="0.1.0", lifespan=lifespan)
    app.state.database = database
    app.state.workflow = workflow
    app.middleware("http")(safe_access_log)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
        if isinstance(exc, AuthenticationError | NotFoundError):
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

    @app.post("/api/v1/workspaces", status_code=201)
    def create_workspace(body: WorkspaceCreate, request: Request) -> dict[str, Any]:
        return _workflow(request).create_workspace(body.name)

    @app.post("/api/v1/workspaces/{workspace_id}/documents", status_code=201)
    async def upload_document(
        request: Request,
        workspace_id: str,
        _: WorkspaceAccess,
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
        request: Request, workspace_id: str, version_id: str, _: WorkspaceAccess
    ) -> StreamingResponse:
        content, media_type = _workflow(request).get_document_content(workspace_id, version_id)
        return StreamingResponse(iter([content]), media_type=media_type)

    @app.post("/api/v1/workspaces/{workspace_id}/rfps", status_code=201)
    def create_rfp(
        request: Request, workspace_id: str, body: RfpCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_rfp(
            workspace_id,
            body.name,
            body.source_document_version_id,
            body.assessment_as_of,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/requirements", status_code=201)
    def create_requirement(
        request: Request, workspace_id: str, body: RequirementCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_requirement(workspace_id=workspace_id, **body.model_dump())

    @app.post("/api/v1/workspaces/{workspace_id}/products", status_code=201)
    def create_product(
        request: Request, workspace_id: str, body: ProductCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_product(workspace_id, body.name)

    @app.post("/api/v1/workspaces/{workspace_id}/products/{product_id}/versions", status_code=201)
    def create_product_version(
        request: Request,
        workspace_id: str,
        product_id: str,
        body: ProductVersionCreate,
        _: WorkspaceAccess,
    ) -> dict[str, Any]:
        return _workflow(request).create_product_version(
            workspace_id, product_id, body.version_label, body.valid_from, body.valid_to
        )

    @app.post("/api/v1/workspaces/{workspace_id}/capabilities", status_code=201)
    def create_capability(
        request: Request, workspace_id: str, body: CapabilityCreate, _: WorkspaceAccess
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
        _: WorkspaceAccess,
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
        _: WorkspaceAccess,
    ) -> dict[str, Any]:
        return _workflow(request).attach_product_document(
            workspace_id,
            version_id,
            body.document_version_id,
            body.source_type.value,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/requirement-mappings", status_code=201)
    def create_mapping(
        request: Request, workspace_id: str, body: MappingCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_mapping(workspace_id, **body.model_dump())

    @app.post("/api/v1/workspaces/{workspace_id}/evidence-spans", status_code=201)
    def create_evidence_span(
        request: Request, workspace_id: str, body: EvidenceSpanCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        values = body.model_dump()
        return _workflow(request).create_evidence_span(workspace_id=workspace_id, **values)

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions", status_code=201)
    def create_decision(
        request: Request, workspace_id: str, body: DecisionCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_decision(workspace_id=workspace_id, **body.model_dump())

    @app.patch("/api/v1/workspaces/{workspace_id}/compliance-decisions/{decision_id}")
    def update_decision(
        request: Request,
        workspace_id: str,
        decision_id: str,
        body: DecisionUpdate,
        _: WorkspaceAccess,
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
        _: WorkspaceAccess,
    ) -> dict[str, Any]:
        return _workflow(request).approve_decision(
            workspace_id,
            decision_id,
            body.reviewer_subject,
            body.comment,
            ReviewMode.SINGLE,
        )

    @app.post("/api/v1/workspaces/{workspace_id}/compliance-decisions/batch-approve")
    def batch_approve(
        request: Request,
        workspace_id: str,
        body: BatchApprovalCreate,
        _: WorkspaceAccess,
    ) -> list[dict[str, Any]]:
        return _workflow(request).batch_approve(
            workspace_id, body.decision_ids, body.reviewer_subject, body.comment
        )

    @app.post("/api/v1/workspaces/{workspace_id}/responses", status_code=201)
    def create_response(
        request: Request, workspace_id: str, body: ResponseCreate, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).create_response(workspace_id, body.rfp_id, body.decision_ids)

    @app.post("/api/v1/workspaces/{workspace_id}/responses/{response_id}/export-xlsx")
    def export_response(
        request: Request, workspace_id: str, response_id: str, _: WorkspaceAccess
    ) -> dict[str, Any]:
        return _workflow(request).export_response(workspace_id, response_id)

    @app.get("/api/v1/workspaces/{workspace_id}/exports/{export_id}/content")
    def download_export(
        request: Request, workspace_id: str, export_id: str, _: WorkspaceAccess
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
