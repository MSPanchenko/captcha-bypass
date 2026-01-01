"""Captcha-bypass client exceptions."""


class CaptchaBypassClientError(Exception):
    """Base exception for client errors."""

    def __init__(self, message: str, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class NetworkError(CaptchaBypassClientError):
    """Raised when network request fails (connection refused, timeout, DNS)."""

    pass
