"""CLI entrypoint for captcha-bypass service."""

import os
import sys

# Fix SSL certificates on macOS before any imports that use network
if sys.platform == 'darwin':
    try:
        import certifi
        os.environ.setdefault('SSL_CERT_FILE', certifi.where())
    except ImportError:
        pass

import argparse
import atexit

import psutil


def get_env_int(name: str, default: int) -> int:
    """Get integer from environment variable with error handling.

    Returns default if variable is not set or empty.
    """
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        print(f"Error: Environment variable {name}='{value}' is not a valid integer", file=sys.stderr)
        sys.exit(1)


def ensure_browser() -> None:
    """Ensure Camoufox browser and dependencies are downloaded."""
    from camoufox.pkgman import CamoufoxFetcher, installed_verstr
    from camoufox.addons import DefaultAddons, maybe_download_addons

    try:
        browser_installed = installed_verstr()
    except FileNotFoundError:
        browser_installed = None

    if not browser_installed:
        print("Downloading Camoufox browser...")
        fetcher = CamoufoxFetcher()
        fetcher.install()
        print("Camoufox browser downloaded.")

    maybe_download_addons(list(DefaultAddons))

    try:
        from camoufox._config import ALLOW_GEOIP

        if ALLOW_GEOIP:
            from camoufox.ip import download_mmdb

            download_mmdb()
    except ImportError:
        pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="captcha-bypass",
        description="Captcha bypass service with HTTP API",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=get_env_int("WORKERS", os.cpu_count() or 1),
        help="Number of parallel browser workers (default: CPU count)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=get_env_int("PORT", 8191),
        help="HTTP server port (default: 8191)",
    )
    parser.add_argument(
        "--result-ttl",
        type=int,
        default=get_env_int("RESULT_TTL", 300),
        help="Result TTL in seconds (default: 300)",
    )
    parser.add_argument(
        "--max-queue-size",
        type=int,
        default=get_env_int("MAX_QUEUE_SIZE", 1000),
        help="Maximum task queue size for backpressure (default: 1000)",
    )
    args = parser.parse_args()

    # Auto-detect workers if not set or <= 0
    if args.workers < 1:
        args.workers = os.cpu_count() or 1
    if not (1 <= args.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    if args.result_ttl < 1:
        parser.error("--result-ttl must be at least 1")
    if args.max_queue_size < 1:
        parser.error("--max-queue-size must be at least 1")

    return args


def kill_all_children() -> None:
    """Kill all child processes on exit.

    Fallback cleanup for abnormal termination (unhandled exceptions, etc.)
    Normal shutdown is handled by aiohttp on_cleanup -> solver.stop_workers()

    Kills: firefox, node (playwright driver), and any other spawned processes.
    Uses two-phase shutdown: first SIGTERM for graceful exit, then SIGKILL for stragglers.
    """
    try:
        current = psutil.Process()
        children = current.children(recursive=True)
        # First try graceful termination (SIGTERM)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        # Wait for graceful shutdown
        _, alive = psutil.wait_procs(children, timeout=2)
        # Force kill remaining processes (SIGKILL)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except Exception:
        pass  # Best effort cleanup


def main() -> None:
    # Register fallback cleanup for abnormal exits (kills firefox, node, etc.)
    atexit.register(kill_all_children)

    args = parse_args()
    ensure_browser()

    # Import here to avoid circular imports and speed up --help
    from captcha_bypass.server import run_server

    run_server(
        workers=args.workers,
        port=args.port,
        result_ttl=args.result_ttl,
        max_queue_size=args.max_queue_size,
    )


if __name__ == "__main__":
    main()
