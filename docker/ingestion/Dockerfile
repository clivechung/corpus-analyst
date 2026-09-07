FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir \
    pydantic>=2.7.0 \
    pydantic-settings>=2.2.0 \
    pyyaml>=6.0.1 \
    watchdog>=4.0.0 \
    httpx>=0.27.0 \
    typer>=0.12.0 \
    azure-storage-blob>=12.19.0 \
    "unstructured>=0.14.0" \
    beautifulsoup4 \
    lxml

COPY . /app

HEALTHCHECK --interval=5s --timeout=3s --retries=5 --start-period=5s \
    CMD python -c 'import os, time; assert os.path.exists("/tmp/healthy") and (time.time() - os.path.getmtime("/tmp/healthy")) < 60' || exit 1

CMD ["python", "-m", "src.ingestion.runner"]

