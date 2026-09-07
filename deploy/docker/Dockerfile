FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN python -m pip install --no-cache-dir -r requirements.lock
COPY core/ core/
ARG DOCUMENT_OCR_KYC_LANGS=en
ENV DOCUMENT_OCR_KYC_LANGS=${DOCUMENT_OCR_KYC_LANGS}
RUN python -m core.model_setup
COPY deploy/docker/server.py server.py
RUN useradd --create-home --uid 10001 ocr && mkdir -p /var/lib/document-ocr/jobs && chown -R ocr:ocr /app /var/lib/document-ocr
USER ocr
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=120s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "30"]
