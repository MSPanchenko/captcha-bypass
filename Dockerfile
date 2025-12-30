FROM python:3.12-slim

# Install system dependencies for Camoufox
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 \
    libx11-xcb1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md LICENSE ./
COPY captcha_bypass/ ./captcha_bypass/

# Install package
RUN pip install --no-cache-dir .

# Fetch Camoufox browser
RUN python -m camoufox fetch

CMD ["captcha-bypass"]
