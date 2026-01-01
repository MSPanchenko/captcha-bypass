"""Captcha-bypass client response."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Response:
    """HTTP response from captcha-bypass service.

    Attributes:
        status_code: HTTP status code. None only for network errors.
        data: Parsed JSON response body. None if JSON parsing failed.
        error: Client-side error message (for parse failures). None on success.
    """

    status_code: int | None = None
    data: dict[str, Any] | None = None
    error: str | None = None
