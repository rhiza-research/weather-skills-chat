# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/opt/uv-cache \
    WORKSPACE=/workspace \
    RUNTIME_PORT=8888 \
    PATH="/root/.local/bin:${PATH}"

# Kaleido 1+ (Plotly write_image) needs a system Chromium plus these libs.
# https://github.com/plotly/Kaleido/issues/379
# Non-root + gVisor cannot use Chromium's own sandbox.
ENV BROWSER_PATH=/usr/bin/chromium \
    CHROMIUM_FLAGS="--no-sandbox --disable-gpu --disable-dev-shm-usage"
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        fonts-liberation \
        fonts-dejavu-core \
        chromium \
        libnss3 \
        libatk-bridge2.0-0 \
        libcups2 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libxkbcommon0 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY sandbox_runtime.py /usr/local/bin/sandbox_runtime.py
COPY prewarm_uv_cache.py /opt/sandbox/prewarm_uv_cache.py

RUN useradd --uid 1000 --create-home --shell /bin/bash runner \
    && mkdir -p /workspace /opt/uv-python /opt/uv-cache \
    && chown -R 1000:1000 /workspace /opt/uv-python /opt/uv-cache /opt/sandbox

USER 1000
WORKDIR /workspace

RUN uv python install 3.11 3.12

# /workspace is an emptyDir at runtime. Keep the skill-package cache on
# /opt/uv-cache so chat's UV_CACHE_DIR matches this image layer.
ARG PREWARM=true
RUN if [ "$PREWARM" = "true" ]; then python3 /opt/sandbox/prewarm_uv_cache.py; fi

EXPOSE 8888
CMD ["python3", "-u", "/usr/local/bin/sandbox_runtime.py"]
