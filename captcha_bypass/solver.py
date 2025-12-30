"""Captcha solver workers using Camoufox."""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from captcha_bypass.storage import Task, TaskStorage

logger = logging.getLogger(__name__)

# Polling interval for validation checks (seconds)
VALIDATION_POLL_INTERVAL = 2.0


def _error_result(code: str, message: str) -> dict[str, Any]:
    """Create standard error result structure.

    All error responses follow the format:
    {"error": {"code": "...", "message": "..."}, "data": None}
    """
    return {
        "error": {"code": code, "message": message},
        "data": None,
    }


def _cancelled_result(message: str = "Task was cancelled") -> dict[str, Any]:
    """Create standard cancelled task result."""
    return _error_result("cancelled", message)


def _browser_error_result(message: str) -> dict[str, Any]:
    """Create standard browser error result."""
    return _error_result("browser_error", message)


@dataclass
class ValidationResult:
    """Result of success condition validation."""

    matched: bool
    match_type: Literal["text", "selector"] | None = None
    matched_condition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        return {
            "matched": self.matched,
            "match_type": self.match_type,
            "matched_condition": self.matched_condition,
        }


def _build_validation_js(texts: list[str], selectors: list[str]) -> str:
    """Build JavaScript code for batch validation of success conditions.

    Returns JS that checks all conditions in a single evaluate() call.
    CSS selectors are used with querySelector, XPath selectors (starting with /)
    are used with document.evaluate().

    Security: json.dumps() properly escapes all special characters, preventing
    JS injection attacks. Invalid selectors are caught by try/catch in JS.
    """
    # Escape strings for safe JSON embedding in JS (handles quotes, backslashes, etc.)
    texts_json = json.dumps(texts)
    selectors_json = json.dumps(selectors)

    return f"""
    (() => {{
        const texts = {texts_json};
        const selectors = {selectors_json};
        const bodyText = document.body ? document.body.innerText : '';

        // Check text conditions (OR logic)
        for (const text of texts) {{
            if (bodyText.includes(text)) {{
                return {{ matched: true, match_type: 'text', matched_condition: text }};
            }}
        }}

        // Check selector conditions (OR logic)
        for (const selector of selectors) {{
            try {{
                let element = null;
                if (selector.startsWith('/')) {{
                    // XPath selector
                    const result = document.evaluate(
                        selector,
                        document,
                        null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                        null
                    );
                    element = result.singleNodeValue;
                }} else {{
                    // CSS selector
                    element = document.querySelector(selector);
                }}
                if (element) {{
                    return {{ matched: true, match_type: 'selector', matched_condition: selector }};
                }}
            }} catch (e) {{
                // Invalid selector - skip it
                console.warn('Invalid selector:', selector, e);
            }}
        }}

        return {{ matched: false, match_type: null, matched_condition: null }};
    }})()
    """


async def check_validation_conditions(
        page: Page,
        success_texts: list[str],
        success_selectors: list[str],
) -> ValidationResult:
    """Check if any success condition is met on the page.

    Uses a single page.evaluate() call for efficiency.
    Returns ValidationResult with match details.
    """
    if not success_texts and not success_selectors:
        # No conditions to check
        return ValidationResult(matched=False)

    js_code = _build_validation_js(success_texts, success_selectors)

    try:
        result = await asyncio.wait_for(page.evaluate(js_code), timeout=5.0)
        return ValidationResult(
            matched=result["matched"],
            match_type=result["match_type"],
            matched_condition=result["matched_condition"],
        )
    except asyncio.TimeoutError:
        logger.warning("Validation check timed out")
        return ValidationResult(matched=False)
    except Exception as e:
        logger.warning(f"Validation check failed: {e}")
        return ValidationResult(matched=False)


def _is_browser_closed_error(error: Exception) -> bool:
    """Check if exception indicates browser/page was closed."""
    error_msg = str(error).lower()
    return "has been closed" in error_msg or "disconnected" in error_msg


def _browser_closed_result(message: str = "Browser or page closed unexpectedly") -> dict[str, Any]:
    """Create standard result for browser closed error."""
    return _error_result("browser_closed", message)


async def _extract_request_headers(page: Page) -> dict[str, str]:
    """Extract browser request headers that can be reused for subsequent requests.

    Returns headers that the browser would send, useful for maintaining
    fingerprint consistency when making requests from Python.
    """
    js_code = """
    (() => {
        const headers = {};

        // User-Agent from navigator
        headers['User-Agent'] = navigator.userAgent;

        // Accept-Language from navigator
        if (navigator.language) {
            const langs = navigator.languages ? navigator.languages.join(', ') : navigator.language;
            headers['Accept-Language'] = langs;
        }

        // Platform hint (useful for some fingerprint checks)
        if (navigator.platform) {
            headers['Sec-Ch-Ua-Platform'] = '"' + navigator.platform + '"';
        }

        // Standard Accept headers (browser defaults)
        headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8';
        headers['Accept-Encoding'] = 'gzip, deflate, br';

        // Sec-Fetch headers (modern browsers)
        headers['Sec-Fetch-Dest'] = 'document';
        headers['Sec-Fetch-Mode'] = 'navigate';
        headers['Sec-Fetch-Site'] = 'none';
        headers['Sec-Fetch-User'] = '?1';

        // Upgrade-Insecure-Requests
        headers['Upgrade-Insecure-Requests'] = '1';

        return headers;
    })()
    """
    try:
        return await asyncio.wait_for(page.evaluate(js_code), timeout=5.0)
    except Exception as e:
        logger.warning(f"Failed to extract request headers: {e}")
        return {}


async def _extract_page_content(page: Page, max_retries: int = 3) -> str | None:
    """Extract page HTML content with retry logic for navigation states.

    Returns:
        HTML content as string, empty string if extraction failed but page is accessible,
        or None if browser/page was closed.
    """
    for _ in range(max_retries):
        try:
            return await asyncio.wait_for(page.content(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Page content extraction timed out")
            return ""
        except Exception as content_error:
            error_msg = str(content_error).lower()
            if "navigating" in error_msg:
                await asyncio.sleep(0.5)
                continue
            if _is_browser_closed_error(content_error):
                return None
            # Other errors - return empty string
            return ""
    return ""  # All retries exhausted


class CaptchaSolver:
    """Manages browser workers for solving captchas using worker pool pattern."""

    def __init__(self, storage: TaskStorage, max_workers: int = 1) -> None:
        self.storage = storage
        self.max_workers = max_workers
        self._active_count = 0
        self._lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []
        self._shutdown_event = asyncio.Event()

    @property
    def active_workers(self) -> int:
        """Current number of active workers (processing tasks)."""
        return self._active_count

    async def start_workers(self) -> None:
        """Start the worker pool. Call this on application startup."""
        logger.info(f"Starting {self.max_workers} worker(s)")
        self._shutdown_event.clear()
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

    async def stop_workers(self) -> None:
        """Stop all workers gracefully. Call this on application shutdown."""
        logger.info("Stopping workers...")
        self._shutdown_event.set()

        # Send shutdown sentinels to unblock workers waiting on queue
        await self.storage.send_shutdown_signal(self.max_workers)

        # Wait for all workers to finish with timeout
        if self._workers:
            done, pending = await asyncio.wait(
                self._workers,
                timeout=30.0,
                return_when=asyncio.ALL_COMPLETED,
            )

            # Cancel any workers that didn't finish in time
            for task in pending:
                task.cancel()

            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        self._workers.clear()
        logger.info("All workers stopped")

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker loop that processes tasks from the queue."""
        logger.info(f"Worker {worker_id} started")

        while not self._shutdown_event.is_set():
            try:
                task = await self.storage.get_next_task()

                # None means either cancelled task or shutdown sentinel
                if task is None:
                    if self._shutdown_event.is_set():
                        break
                    # Cancelled task - continue to next
                    continue

                await self._process_task(task)

            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.exception(f"Worker {worker_id} error: {e}")
                # Continue processing - don't let one error kill the worker

        logger.info(f"Worker {worker_id} stopped")

    async def _process_task(self, task: Task) -> None:
        """Process a single task with browser."""
        # Set status to running - returns False if task was cancelled
        if not await self.storage.set_running(task.id):
            logger.info(f"Task {task.id} was cancelled before processing")
            return

        async with self._lock:
            self._active_count += 1

        try:
            result = await self._solve(task.id, task)
            await self.storage.complete_task(task.id, result)
        except asyncio.CancelledError:
            # Handle graceful shutdown - mark task as cancelled
            logger.info(f"Task {task.id} cancelled due to shutdown")
            await self.storage.complete_task(
                task.id, _cancelled_result("Task was cancelled due to shutdown")
            )
            raise  # Re-raise to propagate cancellation
        except Exception as e:
            logger.exception(f"Task {task.id} failed with error: {e}")
            await self.storage.complete_task(task.id, _browser_error_result(str(e)))
        finally:
            async with self._lock:
                self._active_count -= 1

    async def _check_cancelled(self, task_id: str, log_message: str | None = None) -> dict[str, Any] | None:
        """Check if task was cancelled and return result if so.

        Returns:
            Cancelled result dict if task was cancelled, None otherwise.
        """
        if await self.storage.is_cancel_requested(task_id):
            logger.info(log_message or f"Task {task_id} cancelled")
            return _cancelled_result()
        return None

    async def _get_cookies_safe(self, page: Page, task_id: str) -> tuple[list[dict], bool]:
        """Get cookies with timeout handling.

        Returns:
            (cookies, browser_closed) - cookies list and whether browser was closed.
        """
        try:
            cookies = await asyncio.wait_for(page.context.cookies(), timeout=5.0)
            return cookies, False
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting cookies for task {task_id}")
            return [], False
        except Exception as e:
            if _is_browser_closed_error(e):
                logger.warning(f"Failed to get cookies for task {task_id}: page closed")
                return [], True
            raise

    async def _solve(self, task_id: str, task: Task) -> dict[str, Any]:
        """Run browser and solve captcha with extended validation."""
        # Check for cancellation before starting browser
        if cancelled := await self._check_cancelled(
            task_id, f"Task {task_id} cancelled before browser launch"
        ):
            return cancelled

        logger.info(f"Starting browser for task {task_id}: {task.url}")

        proxy_config = task.proxy  # Already a dict with server, username, password or None
        has_validation_conditions = bool(task.success_texts or task.success_selectors)

        # Start timing BEFORE browser launch (per TASKS.md requirements)
        start_time = time.monotonic()

        # Enable geoip when using proxy for consistent fingerprint (timezone, language, etc.)
        # Store AsyncCamoufox instance to properly call __aexit__ (stops playwright)
        camoufox = AsyncCamoufox(
            headless=True,
            proxy=proxy_config,
            geoip=bool(proxy_config),
            humanize=True,
            block_webrtc=True,
        )
        try:
            try:
                browser = await asyncio.wait_for(camoufox.start(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error(f"Timeout starting camoufox for task {task_id}")
                return _browser_error_result("Timeout starting camoufox")

            try:
                page = await asyncio.wait_for(browser.new_page(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.error(f"Timeout creating new page for task {task_id}")
                return _browser_error_result("Timeout creating new page")

            try:
                # Calculate remaining time after browser startup
                elapsed_ms = (time.monotonic() - start_time) * 1000
                goto_timeout = max(1000, (task.timeout * 1000) - elapsed_ms)

                # Wrap page.goto in separate try/except for PlaywrightTimeout
                response = None
                status_code = None
                try:
                    response = await page.goto(task.url, timeout=goto_timeout)
                    status_code = response.status if response else None
                except PlaywrightTimeout:
                    # Check for cancellation before collecting partial data
                    if cancelled := await self._check_cancelled(
                        task_id, f"Task {task_id} cancelled during navigation timeout"
                    ):
                        return cancelled

                    # Timeout during navigation - collect current page state
                    logger.warning(f"Navigation timeout for task {task_id}, collecting partial data")
                    cookies, browser_closed = await self._get_cookies_safe(page, task_id)
                    if browser_closed:
                        return _browser_closed_result("Page closed during data collection")

                    html = await _extract_page_content(page)
                    if html is None:
                        logger.warning(f"Page closed during content extraction for task {task_id}")
                        return _browser_closed_result("Page closed during data collection")

                    final_url = page.url

                    # Extract request headers even on timeout
                    request_headers = await _extract_request_headers(page)

                    return {
                        "error": None,
                        "data": {
                            "cookies": cookies,
                            "request_headers": request_headers,
                            "response_headers": {},
                            "status_code": None,
                            "html": html,
                            "url": final_url,
                            "timeout_reached": True,
                            "validation": ValidationResult(matched=False).to_dict(),
                        },
                    }

                elapsed = time.monotonic() - start_time
                remaining_timeout = max(1, task.timeout - elapsed)

                timeout_reached = False
                validation_result = ValidationResult(matched=False)
                deadline = time.monotonic() + remaining_timeout

                # Validation polling loop
                while time.monotonic() < deadline:
                    # Check for cancellation before each poll iteration
                    if cancelled := await self._check_cancelled(task_id):
                        return cancelled

                    time_left = deadline - time.monotonic()
                    if time_left <= 0:
                        timeout_reached = True
                        break

                    # If no validation conditions, just wait until timeout
                    if not has_validation_conditions:
                        wait_time = min(VALIDATION_POLL_INTERVAL, time_left)
                        await asyncio.sleep(wait_time)
                        continue

                    # Check validation conditions using batch evaluate
                    try:
                        validation_result = await check_validation_conditions(
                            page, task.success_texts, task.success_selectors
                        )
                        if validation_result.matched:
                            logger.info(
                                f"Task {task_id} validation matched: "
                                f"{validation_result.match_type}='{validation_result.matched_condition}'"
                            )
                            break
                    except Exception as e:
                        if _is_browser_closed_error(e):
                            # Execution context destroyed - navigation, reload, or actual close
                            try:
                                # Check if page is still accessible (doesn't require JS)
                                _ = page.url
                                logger.info(f"Page navigated for task {task_id}, collecting data")
                                break
                            except Exception:
                                logger.warning(f"Page/browser unavailable for task {task_id}: {e}")
                                return _browser_closed_result()
                        logger.warning(f"Validation check error for task {task_id}: {e}")
                        # Continue polling - transient errors should not stop the loop

                    # Wait before next poll (recalculate time_left as it may have changed)
                    time_left = deadline - time.monotonic()
                    if time_left <= 0:
                        timeout_reached = True
                        break
                    wait_time = min(VALIDATION_POLL_INTERVAL, time_left)
                    await asyncio.sleep(wait_time)
                else:
                    # Loop exhausted without success
                    timeout_reached = True

                # Final validation check before closing (in case condition appeared during last sleep)
                if timeout_reached and has_validation_conditions and not validation_result.matched:
                    try:
                        validation_result = await check_validation_conditions(
                            page, task.success_texts, task.success_selectors
                        )
                        if validation_result.matched:
                            logger.info(
                                f"Task {task_id} matched on final check: "
                                f"{validation_result.match_type}='{validation_result.matched_condition}'"
                            )
                    except Exception as e:
                        logger.debug(f"Final validation check failed for task {task_id}: {e}")

                # Collect page data - wait for page to stabilize first
                try:
                    await page.wait_for_load_state('domcontentloaded', timeout=5000)
                except PlaywrightTimeout:
                    pass  # Continue anyway - page might be stuck
                except Exception as e:
                    if _is_browser_closed_error(e):
                        logger.warning(f"Page closed during stabilization for task {task_id}")
                        return _browser_closed_result("Page closed during data collection")
                    raise

                cookies, browser_closed = await self._get_cookies_safe(page, task_id)
                if browser_closed:
                    return _browser_closed_result("Page closed during data collection")

                # Extract page content with retry logic
                html = await _extract_page_content(page)
                if html is None:
                    logger.warning(f"Page closed during content extraction for task {task_id}")
                    return _browser_closed_result("Page closed during data collection")

                final_url = page.url

                # Extract request headers (browser fingerprint for reuse in Python requests)
                request_headers = await _extract_request_headers(page)

                # Get response headers (from initial navigation)
                response_headers = {}
                if response:
                    response_headers = dict(response.headers)

                # Check for cancellation before returning success
                if cancelled := await self._check_cancelled(task_id):
                    return cancelled

                return {
                    "error": None,
                    "data": {
                        "cookies": cookies,
                        "request_headers": request_headers,
                        "response_headers": response_headers,
                        "status_code": status_code,
                        "html": html,
                        "url": final_url,
                        "timeout_reached": timeout_reached,
                        "validation": validation_result.to_dict(),
                    },
                }

            except Exception as e:
                logger.error(f"Browser error for task {task_id}: {e}")
                return _browser_error_result(str(e))
        except asyncio.CancelledError:
            # Graceful shutdown: close browser before re-raising
            logger.info(f"Task {task_id} cancelled, closing browser gracefully")
            raise
        finally:
            # Direct __aexit__ call rationale:
            # - AsyncCamoufox.start() internally calls __aenter__, so __aexit__ is the correct cleanup
            # - browser.close() alone leaves node/playwright driver processes running
            # - async with is not used because we need browser instance before the main try block
            # - Passing (None, None, None) is safe: Camoufox doesn't use exc_info in __aexit__
            try:
                await asyncio.wait_for(camoufox.__aexit__(None, None, None), timeout=60.0)
            except asyncio.TimeoutError:
                logger.error(f"Browser cleanup timeout for task {task_id}, may leave orphan process")
            except Exception as cleanup_error:
                logger.warning(f"Error closing browser for task {task_id}: {cleanup_error}")
