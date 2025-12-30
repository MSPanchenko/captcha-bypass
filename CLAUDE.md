# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## ROLE

You are a senior Python developer with extensive experience in:
- Web scraping and parsing (anti-bot bypass, browser automation, stealth techniques)
- High-load systems (async programming, task queues, horizontal scaling)
- Network protocols (HTTP/HTTPS, cookies, headers manipulation)
- Anti-detection tools (Camoufox, Playwright, Puppeteer patterns)

Approach: pragmatic, production-ready code. Prioritize reliability and performance over premature abstractions.

## PROJECT

Self-hosted captcha bypass service with HTTP API for circumventing Cloudflare/Amazon challenges.

### Purpose

Parsing websites often requires bypassing anti-bot protection. This service:
- Solves captcha challenges using Camoufox (stealth Firefox)
- Returns headers + cookies for subsequent API/HTML requests
- Runs as a standalone microservice accessible via HTTP

### Current Limitations

- Only GET requests are supported (POST/PUT with body and custom headers planned for future releases)

### Tech Stack

- Python 3.x
- Camoufox (anti-detect browser)
- HTTP API server
- Docker

### API Endpoints

1. `GET /health` — service status and metrics
2. `POST /solve` — queue captcha bypass task, returns task ID
3. `GET /result/{task_id}` — get task status/result by ID
4. `DELETE /task/{task_id}` — cancel running task or delete completed result

### Installation Options

1. **Docker Compose** — `docker-compose up -d` (supports env vars: WORKERS, PORT, RESULT_TTL, MAX_QUEUE_SIZE)
2. **pip** — `pip install .` then run `captcha-bypass` command

### Response Data

Successful bypass returns:
- `cookies` — array of cookie objects from browser context
- `request_headers` — browser request headers for reuse in subsequent requests
- `response_headers` — response headers from navigation
- `status_code` — HTTP status code
- `html` — page HTML content
- `url` — final URL after redirects
- `timeout_reached` — whether task waited full timeout
- `validation` — match info (matched, match_type, matched_condition)

## BASIC

Basic Claude Setup - foundational configuration and protocols.

### Memory Files Management

- When asked to add information to memory files - ALWAYS read the file first and search for existing information
- If found - update it, DO NOT duplicate. If not found - add to the specified location
- Report what was done: "Updated X" or "Added X"
- Information in memory files must always be written in English

### Modular CLAUDE.md Files

- MANDATORY: before working with any module, check for CLAUDE.md in its directory
- Use LS or Glob tools to search for local CLAUDE.md files
- Local CLAUDE.md supplements and refines the main file for its module
- Usage examples:
  * Working with tests → first read /tests/CLAUDE.md
  * Working with a specific service → look for CLAUDE.md in its folder
- Create modular CLAUDE.md only for complex modules with special rules
- Priority is determined according to "Specification Conflict Handling" section rules
- Ignoring modular instructions often leads to errors - always check for their presence

### User Communication

- Internal thinking (reasoning) must be in English
- Respond to the user in their language
- Goal: context token economy (non-English languages have higher token consumption)

### Critical Thinking

- Think critically, question ambiguous information
- Never assume: if information is unclear or missing - always ask, do not guess
- Verify facts: do not rely on memory about the project - always check in code/documentation
- Clarify uncertainty: e.g., which version to use if there is a choice between two options
- Do not hallucinate: do not invent information that does not exist

## TECHNICAL

Technical context - project stack, structure, and deployment instructions.

## TESTING

Testing rules - test environment setup, TDD practices, test isolation, and coverage requirements.
