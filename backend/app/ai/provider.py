"""Provider-neutral AI interface. The rest of the app depends only on this module, so swapping
Groq for another provider means writing one class that implements `AIProvider`."""
from __future__ import annotations

from typing import Any, Optional, Protocol


class AIError(Exception):
    """Base class. `code` is stable for the frontend; `message` is safe to show to the user."""

    code = "ai_error"
    http_status = 502

    def __init__(self, message: str, *, retry_after: Optional[float] = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class AINotConfigured(AIError):
    code = "ai_not_configured"
    http_status = 503


class AIAuthError(AIError):
    code = "ai_auth_failed"


class AIRateLimited(AIError):
    code = "ai_rate_limited"
    http_status = 429


class AIQuotaExceeded(AIError):
    code = "ai_quota_exceeded"
    http_status = 429


class AITimeout(AIError):
    code = "ai_timeout"
    http_status = 504


class AIUnavailable(AIError):
    code = "ai_unavailable"
    http_status = 503


class AIRequestError(AIError):
    code = "ai_request_rejected"


class AIInvalidResponse(AIError):
    code = "ai_invalid_response"


class AIProvider(Protocol):
    name: str
    model: str

    def is_configured(self) -> bool: ...

    def complete_json(self, *, system: str, user: str, schema_name: str,
                      json_schema: dict[str, Any]) -> dict[str, Any]:
        """Return one JSON object for the given schema, or raise an AIError. Must never fabricate."""
        ...
