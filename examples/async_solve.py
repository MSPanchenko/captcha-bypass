#!/usr/bin/env python3
"""Simple example of async captcha-bypass client usage.

This example demonstrates:
- Using AsyncCaptchaBypassClient with async context manager
- solve_and_wait() method for simple one-call workflow
- Checking result status manually (no exceptions)
- Printing cookies and headers from the result
"""

import asyncio

from captcha_bypass.client import AsyncCaptchaBypassClient

# Configuration
BASE_URL = "http://localhost:8191"
SOLVE_URL = "https://example.com/"
TIMEOUT = 30

# Optional: success conditions
SUCCESS_TEXTS = ["Example Domain"]
SUCCESS_SELECTORS = ["//h1[text()='Example Domain']"]


async def main():
    """Main entry point demonstrating AsyncCaptchaBypassClient usage."""
    print(f"Solving captcha for: {SOLVE_URL}")
    print(f"Server: {BASE_URL}")
    print(f"Timeout: {TIMEOUT}s")
    print("-" * 50)

    async with AsyncCaptchaBypassClient(BASE_URL) as client:
        result = await client.solve_and_wait(
            url=SOLVE_URL,
            timeout=TIMEOUT,
            success_texts=SUCCESS_TEXTS,
            success_selectors=SUCCESS_SELECTORS,
        )

        # Check result status (Response.data contains the API response)
        if result.error:
            print(f"Client error: {result.error}")
            return

        if not result.data:
            print(f"No data in response (HTTP {result.status_code})")
            return

        status = result.data.get("status")

        if status == "completed":
            data = result.data.get("data", {})

            print(f"Status: {status}")
            print(f"Final URL: {data.get('url')}")
            print(f"Status code: {data.get('status_code')}")
            print(f"Timeout reached: {data.get('timeout_reached')}")

            # Print cookies
            cookies = data.get("cookies", [])
            print(f"\nCookies ({len(cookies)}):")
            for cookie in cookies:
                value = cookie.get("value", "")
                print(f"  {cookie.get('name')}: {value[:50]}..." if len(value) > 50 else f"  {cookie.get('name')}: {value}")

            # Print request headers (for reuse in subsequent requests)
            request_headers = data.get("request_headers", {})
            print(f"\nRequest headers ({len(request_headers)}):")
            for key, value in list(request_headers.items())[:5]:
                print(f"  {key}: {value[:50]}..." if len(str(value)) > 50 else f"  {key}: {value}")
            if len(request_headers) > 5:
                print(f"  ... and {len(request_headers) - 5} more")

            # Print validation info
            validation = data.get("validation", {})
            if validation:
                print(f"\nValidation: matched={validation.get('matched')}, "
                      f"type={validation.get('match_type')}")

        elif status == "error":
            error = result.data.get("error", {})
            print(f"Error: {error.get('code')} - {error.get('message')}")
            if "status_code" in error:
                print(f"HTTP status: {error['status_code']}")

        else:
            # pending, running, not_found
            print(f"Unexpected status: {status}")


if __name__ == "__main__":
    asyncio.run(main())
