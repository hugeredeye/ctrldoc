class DomainError(Exception):
    """Base class for expected domain failures."""


class NotFoundError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class InvariantViolation(DomainError):
    pass


class AuthenticationError(DomainError):
    pass


class AuthorizationError(DomainError):
    pass


class ObjectIntegrityError(InvariantViolation):
    """Stored bytes do not match their immutable identity or expected metadata."""
