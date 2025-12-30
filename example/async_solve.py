#!/usr/bin/env python3
"""
Example script to test captcha-bypass server.
Sends 2 concurrent /solve requests per proxy and fetches results on 'r' keypress.
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

# Directory to save timeout results
RESULTS_DIR = Path(__file__).parent / "results"

# Track saved task IDs to avoid duplicate saves
saved_task_ids: set[str] = set()

# Server configuration
BASE_URL = "http://localhost:8191"

# Base request parameters
SOLVE_URL = "https://example.com/"
SUCCESS_TEXTS = [
    "This domain is for use in documentation examples without needing permission. Avoid use in operations"
]
SUCCESS_SELECTORS = ["//h1[text()='Example Domain']"]
TIMEOUT = 60

# Add yours proxy configurations (examples - replace with your actual proxy credentials)
# Supported formats:
#   - HTTP proxy: {"server": "http://host:port", "username": "user", "password": "pass"}
#   - HTTP proxy without auth: {"server": "http://host:port"}
#   - SOCKS5 proxy: {"server": "socks5://host:port", "username": "user", "password": "pass"}
#   - SOCKS5 proxy without auth: {"server": "socks5://host:port"}
#   - No proxy: None
PROXY_CONFIGS: list[dict | None] = [
    # HTTP proxy with authentication
    # {"server": "http://host:port", "username": "your_username", "password": "your_password"},

    # HTTP proxy without authentication
    # {"server": "http://host:port"},

    # SOCKS5 proxy with authentication
    # {"server": "socks5://host:port", "username": "your_username", "password": "your_password"},

    # SOCKS5 proxy without authentication
    # {"server": "socks5://host:port"},

    None,  # No proxy (direct connection)
]


def get_proxy_label(proxy_config: dict | None) -> str:
    """Get a human-readable label for a proxy config."""
    if proxy_config is None:
        return "NO_PROXY"
    # Extract host:port from server URL
    server = proxy_config["server"]
    # Remove http:// prefix
    host_port = server.replace("http://", "").replace("https://", "")
    return host_port


def build_payload(proxy_config: dict | None) -> dict:
    """Build a solve payload with the given proxy config."""
    payload = {
        "url": SOLVE_URL,
        "success_texts": SUCCESS_TEXTS,
        "success_selectors": SUCCESS_SELECTORS,
        "timeout": TIMEOUT,
    }
    if proxy_config is not None:
        payload["proxy"] = proxy_config
    return payload


async def submit_task(
        session: aiohttp.ClientSession,
        task_num: int,
        proxy_config: dict | None,
) -> tuple[str | None, str]:
    """Submit a single /solve request and return (task_id, proxy_label)."""
    proxy_label = get_proxy_label(proxy_config)
    print(f"[Task {task_num}] Sending /solve request with proxy: {proxy_label}...")

    payload = build_payload(proxy_config)

    try:
        async with session.post(f"{BASE_URL}/solve", json=payload) as resp:
            data = await resp.json()
            task_id = data.get("task_id")
            print(f"[Task {task_num}] Received task_id: {task_id} (proxy: {proxy_label})")
            return task_id, proxy_label
    except Exception as e:
        print(f"[Task {task_num}] Error submitting task: {e}")
        return None, proxy_label


async def fetch_result(
        session: aiohttp.ClientSession, task_num: int, task_id: str
) -> dict:
    """Fetch result for a single task."""
    try:
        async with session.get(f"{BASE_URL}/result/{task_id}") as resp:
            return await resp.json()
    except Exception as e:
        return {"status": "fetch_error", "error": {"code": "fetch_error", "message": str(e)}}


def save_timeout_result(task_id: str, result: dict) -> bool:
    """Save result to file if timeout_reached and not already saved.

    Returns True if saved, False if skipped (already saved).
    """
    if task_id in saved_task_ids:
        return False

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = RESULTS_DIR / f"{task_id}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    saved_task_ids.add(task_id)
    return True


def should_save_result(status: str, data: dict | None) -> bool:
    """Determine if result should be saved to file.

    Save all errors and failures, skip only successful completions and not_found.
    """
    if status in ["pending", "not_found", "running"]:
        return False
    if status == "completed" and data:
        # Save if timeout_reached, skip if truly successful
        return data.get("timeout_reached", False)
    # Save all other statuses (error, fetch_error, etc.)
    return status not in ("completed",)


def print_result(task_num: int, task_id: str, proxy_label: str, result: dict) -> None:
    """Print result for a task."""
    status = result.get("status")
    data = result.get("data")
    error = result.get("error")

    print(f"  [Task {task_num}] {task_id[:8]}... | Proxy: {proxy_label} | Status: {status}", end="")

    if status == "completed" and data:
        timeout_reached = data.get("timeout_reached", False)
        cookies_count = len(data.get("cookies", []))
        req_headers_count = len(data.get("request_headers", {}))
        resp_headers_count = len(data.get("response_headers", {}))
        print(
            f" | timeout_reached: {timeout_reached} | cookies: {cookies_count} "
            f"| req_headers: {req_headers_count} | resp_headers: {resp_headers_count}",
            end="",
        )
    elif status == "error" and error:
        print(f" | error: {error.get('code')} - {error.get('message')}", end="")

    # Save failures and errors (not successful completions or not_found)
    if should_save_result(status, data):
        if save_timeout_result(task_id, result):
            print(f" | SAVED to {task_id}.json", end="")
        else:
            print(f" | (already saved)", end="")

    print()


async def fetch_all_results(
        session: aiohttp.ClientSession,
        tasks: list[tuple[int, str, str]],
) -> None:
    """Fetch and print results for all tasks."""
    print("\n--- Fetching results ---")
    fetch_tasks = [fetch_result(session, num, tid) for num, tid, _ in tasks]
    results = await asyncio.gather(*fetch_tasks)

    for (task_num, task_id, proxy_label), result in zip(tasks, results):
        print_result(task_num, task_id, proxy_label, result)

    # Check if all completed
    all_done = all(r.get("status") in ("completed", "error", "not_found") for r in results)
    if all_done:
        print("\n*** All tasks finished! ***")
    else:
        pending = sum(1 for r in results if r.get("status") in ("pending", "running"))
        print(f"\n*** {pending} task(s) still processing ***")


async def read_input() -> str:
    """Read input asynchronously."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, sys.stdin.readline)


async def main():
    """Main entry point."""
    total_requests = len(PROXY_CONFIGS) * 2
    print("=" * 60)
    print("Captcha Bypass Test Script")
    print(f"Server: {BASE_URL}")
    print(f"URL to solve: {SOLVE_URL}")
    print(f"Proxy configs: {len(PROXY_CONFIGS)} (including 1 without proxy)")
    print(f"Requests per proxy: 2")
    print(f"Total concurrent requests: {total_requests}")
    print("=" * 60)
    print()

    async with aiohttp.ClientSession() as session:
        # Step 1: Submit 2 tasks per proxy concurrently
        print(f"--- Submitting {total_requests} tasks ---")

        # Build list of (task_num, proxy_config) for all requests
        submit_requests = []
        task_num = 1
        for proxy_config in PROXY_CONFIGS:
            for _ in range(2):  # 2 requests per proxy
                submit_requests.append((task_num, proxy_config))
                task_num += 1

        # Submit all tasks concurrently
        submit_tasks = [
            submit_task(session, num, proxy)
            for num, proxy in submit_requests
        ]
        results = await asyncio.gather(*submit_tasks)

        # Filter out None values (failed submissions) and build valid_tasks
        # valid_tasks: list of (task_num, task_id, proxy_label)
        valid_tasks = []
        for (num, _), (task_id, proxy_label) in zip(submit_requests, results):
            if task_id is not None:
                valid_tasks.append((num, task_id, proxy_label))

        if not valid_tasks:
            print("No tasks were submitted successfully. Exiting.")
            return

        print(f"\n--- Submitted {len(valid_tasks)} tasks successfully ---")
        print("\nPress 'r' + Enter to fetch results, 'q' + Enter to quit\n")

        # Step 2: Wait for user input
        while True:
            user_input = (await read_input()).strip().lower()

            if user_input == "r":
                await fetch_all_results(session, valid_tasks)
            elif user_input == "q":
                print("Exiting...")
                break
            elif user_input:
                print("Unknown command. Press 'r' for results, 'q' to quit.")


if __name__ == "__main__":
    asyncio.run(main())
