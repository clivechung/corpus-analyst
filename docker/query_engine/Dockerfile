FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Install lightweight dependencies required for Query Engine
RUN pip install --no-cache-dir \
    fastapi>=0.111.0 \
    uvicorn>=0.30.0 \
    pydantic>=2.7.0 \
    pydantic-settings>=2.2.0 \
    pyyaml>=6.0.1 \
    duckdb>=1.0.0 \
    pyarrow>=16.0.0 \
    sentence-transformers>=3.0.0 \
    httpx>=0.27.0

COPY . /app

EXPOSE 8000

HEALTHCHECK --interval=5s --timeout=3s --retries=5 --start-period=5s \
    CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz")' || exit 1

CMD ["uvicorn", "src.query_engine.main:app", "--host", "0.0.0.0", "--port", "8000"]

