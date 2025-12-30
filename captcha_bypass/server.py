"""HTTP API server using aiohttp."""

import asyncio
import logging

from aiohttp import web

from captcha_bypass.storage import TaskStorage
from captcha_bypass.solver import CaptchaSolver

logger = logging.getLogger(__name__)

MAX_TIMEOUT = 300


def create_app(storage: TaskStorage, solver: CaptchaSolver) -> web.Application:
    """Create aiohttp application with routes."""
    app = web.Application()
    app["storage"] = storage
    app["solver"] = solver

    app.router.add_get("/health", health_handler)
    app.router.add_post("/solve", solve_handler)
    app.router.add_get("/result/{task_id}", result_handler)
    app.router.add_delete("/task/{task_id}", delete_handler)

    return app


async def health_handler(request: web.Request) -> web.Response:
    """GET /health - Service status."""
    storage: TaskStorage = request.app["storage"]
    solver: CaptchaSolver = request.app["solver"]

    return web.json_response({
        "status": "ok",
        "workers": solver.max_workers,
        "active_workers": solver.active_workers,
        "queue_size": storage.queue_size,
    })


async def solve_handler(request: web.Request) -> web.Response:
    """POST /solve - Queue captcha bypass task."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response(
            {"error": "invalid_json", "message": "Request body must be valid JSON"},
            status=400,
        )

    if not isinstance(data, dict):
        return web.json_response(
            {"error": "invalid_json", "message": "Request body must be a JSON object"},
            status=400,
        )

    # Validate required fields
    url = data.get("url")
    timeout = data.get("timeout")

    if not url:
        return web.json_response(
            {"error": "missing_field", "message": "Field 'url' is required"},
            status=400,
        )
    if not isinstance(url, str) or len(url) > 2048:
        return web.json_response(
            {"error": "invalid_field", "message": "Field 'url' must be a string up to 2048 chars"},
            status=400,
        )
    if not url.startswith(("http://", "https://")):
        return web.json_response(
            {"error": "invalid_field", "message": "Field 'url' must start with http:// or https://"},
            status=400,
        )

    # Validate success conditions
    success_texts_raw = data.get("success_texts")
    success_selectors_raw = data.get("success_selectors")

    # Initialize lists for validation conditions
    success_texts: list[str] = []
    success_selectors: list[str] = []

    # Validate success_texts list
    if success_texts_raw is not None:
        if not isinstance(success_texts_raw, list):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'success_texts' must be an array"},
                status=400,
            )
        for i, item in enumerate(success_texts_raw):
            if not isinstance(item, str):
                return web.json_response(
                    {"error": "invalid_field", "message": f"Field 'success_texts[{i}]' must be a string"},
                    status=400,
                )
            if item.strip():  # Filter empty strings
                success_texts.append(item.strip())

    # Validate success_selectors list
    if success_selectors_raw is not None:
        if not isinstance(success_selectors_raw, list):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'success_selectors' must be an array"},
                status=400,
            )
        for i, item in enumerate(success_selectors_raw):
            if not isinstance(item, str):
                return web.json_response(
                    {"error": "invalid_field", "message": f"Field 'success_selectors[{i}]' must be a string"},
                    status=400,
                )
            if item.strip():  # Filter empty strings
                success_selectors.append(item.strip())

    # Deduplicate while preserving order
    success_texts = list(dict.fromkeys(success_texts))
    success_selectors = list(dict.fromkeys(success_selectors))

    # Note: Both lists can be empty - solver will wait until timeout and return timeout_reached=true

    if timeout is None:
        return web.json_response(
            {"error": "missing_field", "message": "Field 'timeout' is required"},
            status=400,
        )

    try:
        timeout = int(timeout)
        if timeout <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return web.json_response(
            {"error": "invalid_field", "message": "Field 'timeout' must be a positive integer"},
            status=400,
        )

    if timeout > MAX_TIMEOUT:
        return web.json_response(
            {"error": "invalid_field", "message": f"Field 'timeout' must not exceed {MAX_TIMEOUT} seconds"},
            status=400,
        )

    proxy = data.get("proxy")
    if proxy is not None:
        if not isinstance(proxy, dict):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'proxy' must be an object"},
                status=400,
            )
        proxy_server = proxy.get("server")
        if not proxy_server:
            return web.json_response(
                {"error": "missing_field", "message": "Field 'proxy.server' is required"},
                status=400,
            )
        if not isinstance(proxy_server, str) or len(proxy_server) > 2048:
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'proxy.server' must be a string up to 2048 chars"},
                status=400,
            )
        if not proxy_server.startswith(("http://", "https://", "socks4://", "socks5://")):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'proxy.server' must start with http://, https://, socks4://, or socks5://"},
                status=400,
            )
        proxy_username = proxy.get("username")
        proxy_password = proxy.get("password")
        if proxy_username is not None and not isinstance(proxy_username, str):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'proxy.username' must be a string"},
                status=400,
            )
        if proxy_password is not None and not isinstance(proxy_password, str):
            return web.json_response(
                {"error": "invalid_field", "message": "Field 'proxy.password' must be a string"},
                status=400,
            )
        # Build clean proxy config
        proxy = {"server": proxy_server}
        if proxy_username:
            proxy["username"] = proxy_username
        if proxy_password:
            proxy["password"] = proxy_password

    storage: TaskStorage = request.app["storage"]

    try:
        task_id = storage.create_task(
            url=url,
            timeout=timeout,
            proxy=proxy,
            success_texts=success_texts,
            success_selectors=success_selectors,
        )
    except asyncio.QueueFull:
        return web.json_response(
            {
                "error": "queue_full",
                "message": f"Task queue is full (max {storage.max_queue_size}). Try again later.",
            },
            status=503,
        )

    return web.json_response({"task_id": task_id})


async def result_handler(request: web.Request) -> web.Response:
    """GET /result/{task_id} - Get task status/result."""
    task_id = request.match_info["task_id"]
    if len(task_id) > 36:  # UUID length
        return web.json_response({
            "status": "not_found",
            "error": {"code": "invalid_task_id", "message": "Invalid task ID format"},
            "data": None,
        }, status=400)
    storage: TaskStorage = request.app["storage"]

    result = await storage.get_result(task_id)
    # get_result() now always returns a dict (never None)
    # with status: pending|running|completed|error|not_found

    return web.json_response(result)


async def delete_handler(request: web.Request) -> web.Response:
    """DELETE /task/{task_id} - Cancel or delete task."""
    task_id = request.match_info["task_id"]
    if len(task_id) > 36:  # UUID length
        return web.json_response({
            "success": False,
            "message": "Invalid task ID",
        }, status=400)
    storage: TaskStorage = request.app["storage"]

    success, message = await storage.cancel_task(task_id)

    return web.json_response({
        "success": success,
        "message": message,
    })


def run_server(workers: int, port: int, result_ttl: int, max_queue_size: int = 1000) -> None:
    """Run the HTTP server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info(f"Starting captcha-bypass server on port {port}")
    logger.info(f"Workers: {workers}, Result TTL: {result_ttl}s, Max queue size: {max_queue_size}")

    storage = TaskStorage(result_ttl=result_ttl, max_queue_size=max_queue_size)
    solver = CaptchaSolver(storage=storage, max_workers=workers)

    app = create_app(storage, solver)

    async def start_background_tasks(app: web.Application) -> None:
        """Start cleanup loop and worker pool."""
        app["cleanup_task"] = asyncio.create_task(storage.cleanup_loop())
        await solver.start_workers()

    async def stop_background_tasks(app: web.Application) -> None:
        """Stop workers and cleanup task."""
        # Stop worker pool first
        await solver.stop_workers()

        # Then stop cleanup task
        cleanup_task = app.get("cleanup_task")
        if cleanup_task:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(stop_background_tasks)

    web.run_app(app, port=port, print=lambda x: logger.info(x))
