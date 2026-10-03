FROM python:3.14-slim

# Liberation Sans is metric-compatible with Arial, so charts render the same in any container
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# matplotlib writes its font cache here; the container's home may not be writable
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV PYTHONUNBUFFERED=1

# publish-templates finds templates/ and the made-up sample data under this folder
ENV DISPATCH_HOME=/app

WORKDIR /app

# Install the pinned dependencies first, so this layer is reused until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install the package with its partials and the email skeleton
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --no-deps .

# The email templates and the made-up data samples are rendered from, for publish-templates
COPY templates/ templates/
COPY tests/fixtures/gold/ tests/fixtures/gold/
COPY tests/fixtures/lookups/ tests/fixtures/lookups/

# Cloud Run passes only the arguments: --record-id <id>, or publish-templates --build-tag <tag>
ENTRYPOINT ["python", "-m", "dispatch.main"]
