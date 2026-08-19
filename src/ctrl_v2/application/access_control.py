from __future__ import annotations

from dataclasses import dataclass

from ctrl_v2.application.ports.authentication import IdentityVerifier
from ctrl_v2.application.ports.unit_of_work import UnitOfWorkFactory
from ctrl_v2.application.records import PrincipalRecord, WorkspaceMembershipRecord
from ctrl_v2.domain.enums import WorkspaceRole
from ctrl_v2.domain.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
)


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    principal: PrincipalRecord
    membership: WorkspaceMembershipRecord


class AccessControlService:
    """Resolves verified identities and enforces persisted workspace membership."""

    def __init__(
        self,
        verifier: IdentityVerifier,
        uow_factory: UnitOfWorkFactory,
        operator_principals: frozenset[str],
    ) -> None:
        self.verifier = verifier
        self.uow_factory = uow_factory
        self.operator_principals = operator_principals

    def verify_readiness(self) -> None:
        self.verifier.verify_readiness()

    def authenticate(self, authorization: str | None) -> PrincipalRecord:
        identity = self.verifier.verify(authorization)
        with self.uow_factory(None) as uow:
            principal = uow.repo.get_or_create_principal(
                identity.issuer,
                identity.subject,
                identity.principal_type,
            )
            uow.commit()
        if not principal.active:
            raise AuthenticationError("Authentication failed")
        if principal.principal_type != identity.principal_type:
            raise AuthenticationError("Authentication failed")
        return principal

    def require_operator(self, principal: PrincipalRecord) -> None:
        if self._external_key(principal) not in self.operator_principals:
            raise AuthorizationError("Operator permission is required")

    def authorize_workspace(
        self,
        principal: PrincipalRecord,
        workspace_id: str,
        allowed_roles: frozenset[WorkspaceRole],
    ) -> WorkspaceAccess:
        with self.uow_factory(workspace_id) as uow:
            membership = uow.repo.get_membership(principal.id)
        if membership is None or not membership.active:
            raise AuthorizationError("Workspace access is denied")
        if WorkspaceRole(membership.role) not in allowed_roles:
            raise AuthorizationError("Workspace role does not permit this operation")
        return WorkspaceAccess(principal=principal, membership=membership)

    def add_membership(
        self, workspace_id: str, principal_id: str, role: WorkspaceRole
    ) -> WorkspaceMembershipRecord:
        with self.uow_factory(None) as uow:
            if uow.repo.get_principal(principal_id) is None:
                raise NotFoundError("Principal was not found")
        with self.uow_factory(workspace_id) as uow:
            membership = uow.repo.create_membership(principal_id, role.value)
            uow.commit()
        return membership

    def bootstrap_operator_admin(
        self,
        workspace_id: str,
        principal: PrincipalRecord,
    ) -> WorkspaceMembershipRecord:
        self.require_operator(principal)
        with self.uow_factory(workspace_id) as uow:
            if uow.repo.get_workspace(workspace_id) is None:
                raise NotFoundError("Workspace was not found")
            memberships = uow.repo.list_memberships()
            if any(
                item.active and item.role == WorkspaceRole.ADMIN.value
                for item in memberships
            ):
                raise ConflictError("Workspace already has an active administrator")
            existing = uow.repo.get_membership(principal.id)
            if existing is None:
                membership = uow.repo.create_membership(
                    principal.id,
                    WorkspaceRole.ADMIN.value,
                )
            else:
                membership = uow.repo.update_membership(
                    principal.id,
                    WorkspaceRole.ADMIN.value,
                    True,
                )
            uow.commit()
        return membership

    def update_membership(
        self,
        workspace_id: str,
        principal_id: str,
        *,
        role: WorkspaceRole | None,
        active: bool | None,
    ) -> WorkspaceMembershipRecord:
        with self.uow_factory(workspace_id) as uow:
            membership = uow.repo.update_membership(
                principal_id,
                role.value if role else None,
                active,
            )
            uow.commit()
        return membership

    def list_memberships(self, workspace_id: str) -> list[WorkspaceMembershipRecord]:
        with self.uow_factory(workspace_id) as uow:
            return uow.repo.list_memberships()

    @staticmethod
    def membership_dict(membership: WorkspaceMembershipRecord) -> dict[str, object]:
        return {
            "workspace_id": membership.workspace_id,
            "principal_id": membership.principal_id,
            "role": membership.role,
            "active": membership.active,
            "created_at": membership.created_at.isoformat(),
        }

    @staticmethod
    def _external_key(principal: PrincipalRecord) -> str:
        return f"{principal.issuer}|{principal.subject}"
