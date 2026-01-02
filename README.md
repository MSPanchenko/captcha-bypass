# captcha-bypass

Self-hosted async captcha bypass service with HTTP API. Tested on Cloudflare and Amazon challenges.

> **Current limitation:** Only GET requests are supported. POST/PUT with body and custom headers planned for future releases.

## Installation

### Docker (recommended)

```bash
# default settings
docker-compose up -d

# with custom params
WORKERS=4 PORT=9000 RESULT_TTL=300 MAX_QUEUE_SIZE=500 docker-compose up -d
```

### pip

```bash
pip install captcha-bypass

# run (browser is auto-downloaded on first run)
captcha-bypass

# with custom params
captcha-bypass --workers 4 --port 9000 --result-ttl 300 --max-queue-size 500
```

**System dependencies (Linux only):**
```bash
# Debian/Ubuntu
sudo apt-get install libgtk-3-0 libx11-xcb1 libasound2

# RHEL/CentOS/Fedora
sudo dnf install gtk3 libX11-xcb alsa-lib
```

> macOS and Windows: dependencies are typically bundled with the browser.

### Custom Docker Image

If you install via pip in your own Docker image, add these to avoid zombie processes from Camoufox:

**docker-compose.yml:**
```yaml
services:
  your-service:
    init: true  # reaps zombie processes from browser
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8191/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

**Or in Dockerfile (alternative to `init: true`):**
```dockerfile
RUN apt-get update && apt-get install -y tini curl
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["captcha-bypass"]
```

## Python Client

<details>
<summary><strong>Sync</strong></summary>

```python
from captcha_bypass.client import CaptchaBypassClient

with CaptchaBypassClient("http://localhost:8191") as client:
    result = client.solve_and_wait(
        url="https://example.com",
        timeout=60,
        success_texts=["Welcome"],
    )

    if result.data and result.data["status"] == "completed":
        data = result.data["data"]
        cookies = data["cookies"]
        headers = data["request_headers"]
```

</details>

<details>
<summary><strong>Async</strong></summary>

```python
import asyncio
from captcha_bypass.client import AsyncCaptchaBypassClient

async def main():
    async with AsyncCaptchaBypassClient("http://localhost:8191") as client:
        result = await client.solve_and_wait(
            url="https://example.com",
            timeout=60,
            success_selectors=["#dashboard"],
        )

        if result.data and result.data["status"] == "completed":
            data = result.data["data"]
            cookies = data["cookies"]
            headers = data["request_headers"]

asyncio.run(main())
```

</details>

<details>
<summary><strong>With Proxy (Sync)</strong></summary>

```python
from captcha_bypass.client import CaptchaBypassClient

proxy = {
    "server": "socks5://proxy.example.com:1080",
    "username": "user",      # optional
    "password": "pass",      # optional
}

with CaptchaBypassClient("http://localhost:8191") as client:
    result = client.solve_and_wait(
        url="https://example.com",
        timeout=60,
        proxy=proxy,
        success_texts=["Welcome"],
    )
```

</details>

<details>
<summary><strong>With Proxy (Async)</strong></summary>

```python
import asyncio
from captcha_bypass.client import AsyncCaptchaBypassClient

proxy = {
    "server": "socks5://proxy.example.com:1080",
    "username": "user",      # optional
    "password": "pass",      # optional
}

async def main():
    async with AsyncCaptchaBypassClient("http://localhost:8191") as client:
        result = await client.solve_and_wait(
            url="https://example.com",
            timeout=60,
            proxy=proxy,
            success_selectors=["#dashboard"],
        )

asyncio.run(main())
```

</details>

See [examples/](examples/) for complete usage.

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PORT` | 8191 | HTTP server port |
| `WORKERS` | CPU cores | Number of browser workers (~500MB RAM each) |
| `RESULT_TTL` | 300 | Seconds to keep completed results before auto-delete |
| `MAX_QUEUE_SIZE` | 1000 | Maximum pending tasks in queue |

## API Reference

<details>
<summary><strong>GET /health</strong> — Service status and metrics</summary>

Use for health checks and monitoring.

```bash
curl http://localhost:8191/health
```

**Response (HTTP 200):**
```json
{
  "status": "ok",
  "workers": 4,
  "active_workers": 1,
  "queue_size": 3
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Service status. Always `"ok"` if server responds |
| `workers` | integer | Total configured workers (browser instances) |
| `active_workers` | integer | Workers currently processing tasks |
| `queue_size` | integer | Pending tasks waiting for a free worker |

**Notes:**
- If `active_workers == workers` and `queue_size > 0`, all workers are busy
- If server is down, connection will fail (no response)
- Suitable for load balancer health checks and Kubernetes probes

</details>

<details>
<summary><strong>POST /solve</strong> — Queue a captcha bypass task</summary>

Returns immediately with `task_id`.

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/protected",
    "timeout": 60,
    "success_texts": ["Welcome"],
    "success_selectors": ["#dashboard", ".user-profile"]
  }'
```

#### Parameters

| Parameter | Required | Type | Description |
|-----------|----------|------|-------------|
| `url` | Yes | string | Target URL (max 2048 chars, must start with `http://` or `https://`) |
| `timeout` | Yes | integer | Max wait time in seconds (1-300) |
| `success_texts` | No | array | Texts indicating successful bypass |
| `success_selectors` | No | array | CSS/XPath selectors indicating success |
| `proxy` | No | object | Proxy configuration |

#### Success Conditions

The service polls the page every 2 seconds checking for success conditions. Uses **OR logic** — returns as soon as **any** condition matches.

**Important:** If both `success_texts` and `success_selectors` are empty or omitted, the service waits the full `timeout` period before returning the result. Use this when you don't know what indicates success and just need to wait for the challenge to complete.

**Text matching** (`success_texts`):
- Searches for substring in page body text
- Case-sensitive
- Example: `["Welcome back", "Dashboard"]`

**Selector matching** (`success_selectors`):
- **CSS selectors** — standard querySelector syntax
- **XPath selectors** — start with `//` (search anywhere) or `/` (absolute path from root)
- Example: `["#main-content", ".logged-in", "//div[@data-auth='true']"]`

#### Selector Syntax

**CSS selectors** (see [MDN CSS Selectors](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_selectors)):
```
#id                  — by ID
.class               — by class
div                  — by tag
[attr="value"]       — by attribute
div.class#id         — combined
div > p              — direct child
div p                — descendant
```

**XPath selectors** (see [MDN XPath](https://developer.mozilla.org/en-US/docs/Web/XPath)):
```
//div[@id="main"]           — div with id="main"
//button[text()="Submit"]   — button with exact text
//input[@type="email"]      — input with type="email"
//*[contains(@class,"btn")] — any element with "btn" in class
```

#### Proxy Configuration

```json
{
  "proxy": {
    "server": "socks5://proxy.example.com:1080",
    "username": "user",
    "password": "pass"
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `server` | Yes | Proxy URL (max 2048 chars) |
| `username` | No | Proxy username |
| `password` | No | Proxy password |

Supported protocols: `http://`, `https://`, `socks4://`, `socks5://`

When proxy is configured, GeoIP-based fingerprint (timezone, language) is automatically applied.

#### Response

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Errors

All error responses follow this structure:

```json
{
  "error": "<error_code>",
  "message": "<human-readable description>"
}
```

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `invalid_json` | Request body is not valid JSON |
| 400 | `missing_field` | Required field missing |
| 400 | `invalid_field` | Field has invalid value |
| 503 | `queue_full` | Task queue at capacity, retry later |

**Example error responses:**

```json
// 400 Bad Request - invalid JSON
{
  "error": "invalid_json",
  "message": "Request body must be valid JSON"
}

// 400 Bad Request - missing field
{
  "error": "missing_field",
  "message": "Field 'url' is required"
}

// 400 Bad Request - invalid field value
{
  "error": "invalid_field",
  "message": "Field 'timeout' must be a positive integer"
}

// 503 Service Unavailable - queue full
{
  "error": "queue_full",
  "message": "Task queue is full (max 1000). Try again later."
}
```

</details>

<details>
<summary><strong>GET /result/{task_id}</strong> — Get task status and result</summary>

Poll this endpoint until status is `completed` or `error`.

```bash
curl http://localhost:8191/result/550e8400-e29b-41d4-a716-446655440000
```

#### Response Examples

**Completed (success condition matched):**
```json
{
  "status": "completed",
  "error": null,
  "data": {
    "cookies": [
      {
        "name": "cf_clearance",
        "value": "...",
        "domain": ".example.com",
        "path": "/",
        "expires": 1234567890,
        "httpOnly": true,
        "secure": true,
        "sameSite": "None"
      }
    ],
    "request_headers": {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.5",
      "Accept-Encoding": "gzip, deflate, br",
      "Sec-Fetch-Dest": "document",
      "Sec-Fetch-Mode": "navigate",
      "Sec-Fetch-Site": "none",
      "Sec-Fetch-User": "?1",
      "Upgrade-Insecure-Requests": "1"
    },
    "response_headers": {
      "content-type": "text/html; charset=utf-8",
      "set-cookie": "...",
      "cf-ray": "..."
    },
    "status_code": 200,
    "html": "<!DOCTYPE html>...",
    "url": "https://example.com/dashboard",
    "timeout_reached": false,
    "validation": {
      "matched": true,
      "match_type": "selector",
      "matched_condition": "#dashboard"
    }
  }
}
```

**Pending/Running:**
```json
{
  "status": "pending",
  "error": null,
  "data": null
}
```

**Error:**
```json
{
  "status": "error",
  "error": {
    "code": "browser_error",
    "message": "Timeout starting camoufox"
  },
  "data": null
}
```

**Not Found (HTTP 200):**
```json
{
  "status": "not_found",
  "error": null,
  "data": null
}
```

**Invalid Task ID (HTTP 400):**
```json
{
  "status": "not_found",
  "error": {
    "code": "invalid_task_id",
    "message": "Invalid task ID format"
  },
  "data": null
}
```

#### Status Values

| Status | Description |
|--------|-------------|
| `pending` | Task waiting in queue |
| `running` | Browser is processing the task |
| `completed` | Task finished (check `data.validation.matched` for success) |
| `error` | Task failed (see `error.code`) |
| `not_found` | Task doesn't exist, was deleted, or expired |

#### Result Fields

| Field | Description |
|-------|-------------|
| `cookies` | Array of cookies from browser context |
| `request_headers` | Browser request headers (User-Agent, Accept, etc.) for reuse in Python requests |
| `response_headers` | Response headers from initial navigation (Set-Cookie, Content-Type, etc.) |
| `status_code` | HTTP status code (may be `null` if navigation timed out) |
| `html` | Page HTML content |
| `url` | Final URL after all redirects |
| `timeout_reached` | `true` if task waited full timeout without validation match |
| `validation.matched` | `true` if any success condition was found |
| `validation.match_type` | `"text"` or `"selector"` (which type matched), `null` if not matched |
| `validation.matched_condition` | The specific text or selector that matched, `null` if not matched |

#### Error Codes

| Code | Description |
|------|-------------|
| `invalid_task_id` | Task ID format is invalid (HTTP 400) |
| `cancelled` | Task was cancelled via DELETE endpoint |
| `browser_error` | Browser crashed or failed to start |
| `browser_closed` | Browser/page closed unexpectedly |

</details>

<details>
<summary><strong>DELETE /task/{task_id}</strong> — Cancel or delete a task</summary>

```bash
curl -X DELETE http://localhost:8191/task/550e8400-e29b-41d4-a716-446655440000
```

#### Response

**Success (HTTP 200):**
```json
{
  "success": true,
  "message": "Task cancelled (was pending)"
}
```

**Invalid task ID (HTTP 400):**
```json
{
  "success": false,
  "message": "Invalid task ID"
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `true` if operation succeeded, `false` if task not found or invalid |
| `message` | string | Human-readable result description |

#### HTTP Status Codes

| Status | Condition |
|--------|-----------|
| 200 | Operation performed (check `success` field for result) |
| 400 | Invalid task ID format |

#### Messages

| Message | success | HTTP | Description |
|---------|---------|------|-------------|
| `Task cancelled (was pending)` | true | 200 | Removed from queue before processing |
| `Task marked for cancellation` | true | 200 | Running task will stop at next check |
| `Result deleted` | true | 200 | Completed task result removed |
| `Task not found` | false | 200 | Task doesn't exist |
| `Invalid task ID` | false | 400 | Task ID format validation failed |

</details>

## Usage Examples

### Basic: Wait for text

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "timeout": 60,
    "success_texts": ["Welcome"]
  }'
```

### Wait for element to appear

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "timeout": 90,
    "success_selectors": ["#content-loaded", "[data-ready=true]"]
  }'
```

### Combined conditions (OR logic)

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "timeout": 120,
    "success_texts": ["Dashboard", "Welcome back"],
    "success_selectors": ["#user-menu", ".authenticated"]
  }'
```

### No conditions (wait full timeout)

Use when you don't know what indicates success. Service waits full timeout, then returns whatever state the page is in.

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "timeout": 30
  }'
```

### With proxy

```bash
curl -X POST http://localhost:8191/solve \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "timeout": 60,
    "success_texts": ["Success"],
    "proxy": {
      "server": "socks5://proxy.example.com:1080",
      "username": "user",
      "password": "pass"
    }
  }'
```

---

## Resource Usage

- ~500MB RAM per worker
- Recommended: 1-2 workers per CPU core

---

## Notes

- Browser uses stealth mode (Camoufox) with WebRTC blocking

---

## TODO

- [ ] SSRF protection — validate URLs against internal addresses (169.254.169.254, localhost, private IPs)
- [ ] Difficulty levels — `headless="virtual"` mode selection for different challenge complexity
- [ ] HTTP methods — support POST, PUT, DELETE with request body and custom headers
- [ ] Browser fingerprint options — OS, locale, screen size, timezone via Camoufox config

