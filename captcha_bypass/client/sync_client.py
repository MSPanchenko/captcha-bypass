"""Synchronous captcha-bypass client using requests."""

import time
from typing import Any

import requests

from .exceptions import NetworkError, CaptchaBypassClientError
from .response import Response


class CaptchaBypassClient:
    """Synchronous client for captcha-bypass service."""

    def __init__(self, base_url: str, request_timeout: float = 30.0):
        """Initialize the client.

        Args:
            base_url: Base URL of the captcha-bypass service (e.g., "http://localhost:8080").
            request_timeout: Timeout for HTTP requests to the service.
        """
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self._session: requests.Session | None = None

    def __enter__(self) -> "CaptchaBypassClient":
        self._session = requests.Session()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._session:
            self._session.close()
            self._session = None

    @property
    def session(self) -> requests.Session:
        """Get or create a session."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def _request(self, method: str, path: str, **kwargs: Any) -> Response:
        """Make HTTP request and return Response.

        Raises:
            NetworkError: On connection refused, timeout, DNS failure, etc.

        Returns:
            Response with status_code and data (or error if JSON parse failed).
        """
        url = f"{self.base_url}{path}"
        kwargs.setdefault("timeout", self.request_timeout)

        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            raise NetworkError(str(e), cause=e) from e
        except Exception as e:
            raise CaptchaBypassClientError(str(e), cause=e) from e

        status_code = None
        try:
            status_code = response.status_code
            data = response.json()
            return Response(status_code=response.status_code, data=data)
        except Exception:
            return Response(
                status_code=status_code,
                data=None,
                error="Failed to parse JSON",
            )

    def solve(
            self,
            url: str,
            timeout: int = 30,
            proxy: dict[str, str] | None = None,
            success_texts: list[str] | None = None,
            success_selectors: list[str] | None = None,
    ) -> Response:
        """Submit a captcha bypass task.

        Args:
            url: Target URL to solve captcha for.
            timeout: Max time in seconds for the solver to wait.
            proxy: Optional proxy config {"server": "...", "username": "...", "password": "..."}.
            success_texts: Optional list of text patterns to detect success.
            success_selectors: Optional list of CSS selectors to detect success.

        Returns:
            Response with task_id in data on success.

        Raises:
            NetworkError: On network failure.
            CaptchaBypassClientError: On unexpected error.
        """
        payload: dict[str, Any] = {"url": url, "timeout": timeout}
        if proxy:
            payload["proxy"] = proxy
        if success_texts:
            payload["success_texts"] = success_texts
        if success_selectors:
            payload["success_selectors"] = success_selectors

        return self._request("POST", "/solve", json=payload)

    def get_result(self, task_id: str) -> Response:
        """Get the result of a task.

        Args:
            task_id: Task identifier returned by solve().

        Returns:
            Response with task result in data.

        Raises:
            NetworkError: On network failure.
            CaptchaBypassClientError: On unexpected error.
        """
        return self._request("GET", f"/result/{task_id}")

    def delete_task(self, task_id: str) -> Response:
        """Delete or cancel a task.

        Args:
            task_id: Task identifier.

        Returns:
            Response with deletion status in data.

        Raises:
            NetworkError: On network failure.
            CaptchaBypassClientError: On unexpected error.
        """
        return self._request("DELETE", f"/task/{task_id}")

    def health(self) -> Response:
        """Get service health status.

        Returns:
            Response with health info in data.

        Raises:
            NetworkError: On network failure.
            CaptchaBypassClientError: On unexpected error.
        """
        return self._request("GET", "/health")

    def solve_and_wait(
            self,
            url: str,
            timeout: int = 30,
            poll_interval: float = 1.0,
            proxy: dict[str, str] | None = None,
            success_texts: list[str] | None = None,
            success_selectors: list[str] | None = None,
    ) -> Response:
        """Submit task and wait for result with polling.

        Args:
            url: Target URL to solve captcha for.
            timeout: Max time in seconds for the solver to wait.
            poll_interval: How often to poll for results (seconds).
            proxy: Optional proxy config.
            success_texts: Optional list of text patterns to detect success.
            success_selectors: Optional list of CSS selectors to detect success.

        Returns:
            Response with final task result in data.

        Raises:
            NetworkError: On network failure.
            CaptchaBypassClientError: On unexpected error.
        """
        response = self.solve(
            url=url,
            timeout=timeout,
            proxy=proxy,
            success_texts=success_texts,
            success_selectors=success_selectors,
        )

        # Non-2xx status code - return immediately
        if response.status_code is None or not (200 <= response.status_code < 300):
            return response

        # No data or no task_id - return as-is
        if not response.data:
            return response

        task_id = response.data.get("task_id")
        if not task_id:
            return response

        while True:
            result = self.get_result(task_id)

            # Check for terminal states
            if result.data:
                status = result.data.get("status")
                if status not in ("pending", "running"):
                    return result

            # Still pending or running - wait and poll again
            time.sleep(poll_interval)
