FROM python:3.12-slim

WORKDIR /app

# System dependencies for OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install from pyproject.toml (single source of truth for dependencies)
COPY pyproject.toml .
COPY core/ core/
RUN uv pip install --system --no-cache -e "."

# Pre-download RapidOCR PP-OCRv5 models at build time
RUN python -c "\
from rapidocr import RapidOCR, LangRec, ModelType, OCRVersion; \
RapidOCR(params={ \
    'Global.use_cls': False, \
    'Det.model_type': ModelType.MOBILE, \
    'Det.ocr_version': OCRVersion.PPOCRV5, \
    'Rec.lang_type': LangRec.EN, \
    'Rec.model_type': ModelType.MOBILE, \
    'Rec.ocr_version': OCRVersion.PPOCRV5, \
})"

# Copy server
COPY deploy/docker/server.py server.py

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30"]
