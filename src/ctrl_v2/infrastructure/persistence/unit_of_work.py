from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .repository import SqlAlchemyStage1Repository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session], workspace_id: str | None) -> None:
        self.session_factory = session_factory
        self.workspace_id = workspace_id
        self.session: Session | None = None
        self.repo: SqlAlchemyStage1Repository
        self._committed = False

    def __enter__(self) -> SqlAlchemyUnitOfWork:
        self.session = self.session_factory()
        if self.workspace_id and self.session.get_bind().dialect.name == "postgresql":
            self.session.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": self.workspace_id},
            )
        self.repo = SqlAlchemyStage1Repository(self.session, self.workspace_id)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.session is None:
            return
        if exc_type is not None or not self._committed:
            self.session.rollback()
        self.session.close()

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork has not been entered")
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork has not been entered")
        self.session.rollback()


class SqlAlchemyUnitOfWorkFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def __call__(self, workspace_id: str | None) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self.session_factory, workspace_id)
