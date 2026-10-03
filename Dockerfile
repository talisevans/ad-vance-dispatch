FROM python:3.11-slim

# Liberation Sans is metric-compatible with Arial, so charts render the same in any container
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# matplotlib writes its font cache here; the container's home may not be writable
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install the package with its partials and the email skeleton
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

# Cloud Run passes only the arguments, e.g. --record-id <id>
ENTRYPOINT ["python", "-m", "dispatch.main"]
