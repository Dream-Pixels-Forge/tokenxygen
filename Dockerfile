FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY tokenxygen/ tokenxygen/
COPY README.md .

# Install package
RUN pip install --no-cache-dir .

# Create data directory
RUN mkdir -p /data

# Environment variables
ENV TOKENDATA_DIR=/data
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8420/health || exit 1

# Expose ports
# 8420 = proxy
# 8421 = dashboard
# 9090 = metrics (prometheus)
EXPOSE 8420 8421 9090

# Run
CMD ["tokenxygen", "serve", "--host", "0.0.0.0", "--port", "8420"]
