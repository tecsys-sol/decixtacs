"""Exceptions raised by the client. Every HTTP error is an :class:`APIError` subclass."""

from __future__ import annotations

from typing import Any


class NetworkOpsError(Exception):
    """Base class for all SDK errors."""


class APIError(NetworkOpsError):
    """The API answered with a non-2xx status."""

    def __init__(self, status_code: int, detail: Any, *, method: str = "", path: str = "",
                 request_id: str | None = None):
        self.status_code = status_code
        self.detail = detail
        self.method = method
        self.path = path
        self.request_id = request_id
        msg = detail.get("message", detail) if isinstance(detail, dict) else detail
        super().__init__(f"{method} {path} -> HTTP {status_code}: {msg}")

    @property
    def code(self) -> str | None:
        """Machine readable code for auth errors (``mfa_required``, ``locked``, ``token_reuse`` ...)."""
        return self.detail.get("code") if isinstance(self.detail, dict) else None


class AuthenticationError(APIError):
    """401 - missing/invalid credentials or token."""


class MFARequiredError(AuthenticationError):
    """401 with code ``mfa_required``: pass ``otp=`` (or ``otp_provider=``) to the client."""


class PermissionDeniedError(APIError):
    """403 - authenticated but missing a permission (or a cross-tenant request)."""


class NotFoundError(APIError):
    """404 - object does not exist *in your tenant*."""


class ConflictError(APIError):
    """409 - state conflict (e.g. invalid change-request transition, restore without approved change)."""


class ValidationError(APIError):
    """422 - request body / parameters rejected."""


class RateLimitError(APIError):
    """429 - rate limit exceeded; ``retry_after`` seconds from the Retry-After header."""

    def __init__(self, *args: Any, retry_after: float | None = None, **kw: Any):
        super().__init__(*args, **kw)
        self.retry_after = retry_after


class ServerError(APIError):
    """5xx."""


_BY_STATUS: dict[int, type[APIError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def error_for(status_code: int) -> type[APIError]:
    if status_code >= 500:
        return ServerError
    return _BY_STATUS.get(status_code, APIError)
