FROM python:3.12-slim

WORKDIR /app

# System dependencies for OpenCV and PaddlePaddle
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install from pyproject.toml (single source of truth for dependencies)
COPY pyproject.toml .
COPY core/ core/
RUN uv pip install --system --no-cache -e "."

# Pre-download PaddleOCR models at build time
# NOTE: Skip on cross-platform builds (QEMU + PaddlePaddle segfaults).
# Models auto-download on first request. Use /ready endpoint to check.
# On native amd64, uncomment:
# RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='en')"

# Copy server
COPY deploy/docker/server.py server.py

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30"]
