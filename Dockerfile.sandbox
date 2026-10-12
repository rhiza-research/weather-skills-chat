# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/tmp/uv-cache \
    WORKSPACE=/workspace \
    RUNTIME_PORT=8888 \
    PATH="/root/.local/bin:${PATH}"

# Kaleido 1+ (Plotly write_image) needs a system Chromium plus these libs.
# https://github.com/plotly/Kaleido/issues/379
ENV BROWSER_PATH=/usr/bin/chromium
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

RUN uv python install 3.11 3.12

COPY sandbox_runtime.py /usr/local/bin/sandbox_runtime.py

RUN useradd --uid 1000 --create-home --shell /bin/bash runner \
    && mkdir -p /workspace /opt/uv-python \
    && chown -R 1000:1000 /workspace /opt/uv-python

USER 1000
WORKDIR /workspace
EXPOSE 8888
CMD ["python3", "/usr/local/bin/sandbox_runtime.py"]
