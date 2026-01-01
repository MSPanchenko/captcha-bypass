#!/usr/bin/env python3
"""Simple example of synchronous captcha-bypass client usage.

This example demonstrates:
- Basic usage with context manager
- solve_and_wait() for submitting and waiting for result
- Checking result status manually (no exceptions)
- Printing cookies and headers from the result

Usage:
    1. Start the captcha-bypass server: docker-compose up -d
    2. Run this script: python examples/sync_solve.py
"""

from captcha_bypass.client import CaptchaBypassClient

# Configuration
BASE_URL = "http://localhost:8191"
SOLVE_URL = "https://example.com/"
TIMEOUT = 30

# Success detection (optional)
SUCCESS_TEXTS = ["This domain is for use in illustrative examples"]
SUCCESS_SELECTORS = ["//h1[text()='Example Domain']"]


def main() -> None:
    """Run the sync client example."""
    print(f"Captcha Bypass Sync Client Example")
    print(f"Server: {BASE_URL}")
    print(f"Target URL: {SOLVE_URL}")
    print("-" * 40)

    with CaptchaBypassClient(BASE_URL) as client:
        # Check server health first
        health = client.health()
        if health.error:
            print(f"Health check failed: {health.error}")
            return
        if not health.data:
            print(f"Health check failed: no data (HTTP {health.status_code})")
            return

        print(f"Server status: {health.data.get('status')}")
        print(f"Workers: {health.data.get('active_workers')}/{health.data.get('workers')}")
        print("-" * 40)

        # Submit task and wait for result
        print(f"Submitting task for {SOLVE_URL}...")
        result = client.solve_and_wait(
            url=SOLVE_URL,
            timeout=TIMEOUT,
            success_texts=SUCCESS_TEXTS,
            success_selectors=SUCCESS_SELECTORS,
        )

        # Check result status (Response.data contains the API response)
        if result.error:
            print(f"\nClient error: {result.error}")
            return

        if not result.data:
            print(f"\nNo data in response (HTTP {result.status_code})")
            return

        status = result.data.get("status")

        if status == "completed":
            data = result.data.get("data", {})

            print(f"\nTask completed successfully!")
            print(f"Final URL: {data.get('url')}")
            print(f"Status code: {data.get('status_code')}")
            print(f"Timeout reached: {data.get('timeout_reached')}")

            # Print validation info
            validation = data.get("validation", {})
            if validation.get("matched"):
                print(f"Validation: matched via {validation.get('match_type')}")
            else:
                print("Validation: no match")

            # Print cookies
            cookies = data.get("cookies", [])
            print(f"\nCookies ({len(cookies)}):")
            for cookie in cookies:
                value = cookie.get("value", "")
                print(f"  {cookie.get('name')}: {value[:50]}..." if len(value) > 50 else f"  {cookie.get('name')}: {value}")

            # Print request headers
            request_headers = data.get("request_headers", {})
            print(f"\nRequest headers ({len(request_headers)}):")
            for name, value in list(request_headers.items())[:5]:
                print(f"  {name}: {value[:50]}..." if len(str(value)) > 50 else f"  {name}: {value}")

        elif status == "error":
            error = result.data.get("error", {})
            print(f"\nError: {error.get('code')} - {error.get('message')}")
            if "status_code" in error:
                print(f"HTTP status: {error['status_code']}")

        else:
            # pending, running, not_found
            print(f"\nUnexpected status: {status}")


if __name__ == "__main__":
    main()
