# Adaptive Concurrency Limiter
# Multi-stage build for minimal image size

# Build stage (not needed for pure Python, but good practice)
FROM python:3.11-slim as builder

WORKDIR /app

# Copy source
COPY src/ /app/src/

# Verify syntax
RUN python -m py_compile src/main.py

# Production stage
FROM python:3.11-slim

# Security: run as non-root
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy from builder
COPY --from=builder /app/src /app/src

# Set ownership
RUN chown -R appuser:appuser /app

USER appuser

# Environment
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# No external dependencies - pure Python!

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import asyncio; print('ok')" || exit 1

# Default: run steady state simulation
# In production, this would be replaced with your app entrypoint
CMD ["python", "-m", "src.main", "--scenario", "steady_state", "--duration", "300"]
