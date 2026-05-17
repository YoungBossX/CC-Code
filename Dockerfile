# =============================================================================
# CC-Coder — Multi-stage Dockerfile
# =============================================================================
# Inspired by Hermes Agent's flexible deployment model:
#   - Lightweight CLI container for local/CI use
#   - Gateway-ready base for multi-platform access (Telegram/Discord/Web)
#   - Headless mode for cron/scheduled tasks
#
# Quick start:
#   docker build -t cc-coder .
#   docker run -it --rm \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v $(pwd):/workspace \
#     cc-coder
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Builder — install package into venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Copy package source
COPY pyproject.toml README.md ./
COPY cc_code/ ./cc_code/

# Install into a clean venv (keeps final image small)
RUN python -m venv /opt/cc-coder-venv && \
    /opt/cc-coder-venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/cc-coder-venv/bin/pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal image with only the venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="CC-Coder"
LABEL org.opencontainers.image.description="CC-Coder is a lightweight terminal coding assistant"
LABEL org.opencontainers.image.source="https://github.com/YoungBossX/CC-Code"

# Create non-root user for security
RUN groupadd --gid 1000 cc-coder && \
    useradd --uid 1000 --gid cc-coder --create-home --shell /bin/bash cc-coder

# Copy venv from builder
COPY --from=builder /opt/cc-coder-venv /opt/cc-coder-venv

# Make cc-coder available on PATH
ENV PATH="/opt/cc-coder-venv/bin:${PATH}"

# Create persistent data directories
RUN mkdir -p /home/cc-coder/.cc-code/memory /home/cc-coder/.cc-code/skills && \
    chown -R cc-coder:cc-coder /home/cc-coder/.cc-code

# Default workspace
RUN mkdir -p /workspace && chown cc-coder:cc-coder /workspace
WORKDIR /workspace

# Environment defaults (override at runtime)
ENV CC_CODE_LOG_LEVEL=WARNING \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    # Container hint — lets CC-Coder know it's running in Docker
    CC_CODE_CONTAINER=docker

# Health check: verify the CLI entry point works
HEALTHCHECK --interval=60s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from cc_code.main import main; print('ok')" || exit 1

# Switch to non-root user
USER cc-coder

# Default entry: interactive CLI mode
ENTRYPOINT ["cc-coder"]
CMD ["--help"]
