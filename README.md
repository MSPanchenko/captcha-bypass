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

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PORT` | 8191 | HTTP server port |
| `WORKERS` | CPU cores | Number of browser workers (~500MB RAM each) |
| `RESULT_TTL` | 300 | Seconds to keep completed results before auto-delete |
| `MAX_QUEUE_SIZE` | 1000 | Maximum pending tasks in queue |

## API Reference

### GET /health

Service status and metrics.

```bash
curl http://localhost:8191/health
```

**Response:**
```json
{
  "status": "ok",
  "workers": 4,
  "active_workers": 1,
  "queue_size": 3
}
```

---

### POST /solve

Queue a captcha bypass task. Returns immediately with `task_id`.

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

Supported protocols: `http://`, `https://`, `socks4://`, `socks5://`

When proxy is configured, GeoIP-based fingerprint (timezone, language) is automatically applied.

#### Response

```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### Errors

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_json` | Request body is not valid JSON |
| 400 | `missing_field` | Required field missing |
| 400 | `invalid_field` | Field has invalid value |
| 503 | `queue_full` | Task queue at capacity, retry later |

---

### GET /result/{task_id}

Get task status and result. Poll this endpoint until status is `completed` or `error`.

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
| `validation.match_type` | `"text"` or `"selector"` (which type matched) |
| `validation.matched_condition` | The specific text or selector that matched |

#### Error Codes

| Code | Description |
|------|-------------|
| `cancelled` | Task was cancelled via DELETE endpoint |
| `browser_error` | Browser crashed or failed to start |
| `browser_closed` | Browser/page closed unexpectedly |

---

### DELETE /task/{task_id}

Cancel a running task or delete a completed result.

```bash
curl -X DELETE http://localhost:8191/task/550e8400-e29b-41d4-a716-446655440000
```

#### Response

```json
{
  "success": true,
  "message": "Task cancelled (was pending)"
}
```

#### Messages

| Message | Description |
|---------|-------------|
| `Task cancelled (was pending)` | Removed from queue before processing |
| `Task marked for cancellation` | Running task will stop at next check |
| `Result deleted` | Completed task result removed |
| `Task not found` | Task doesn't exist |

---

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

