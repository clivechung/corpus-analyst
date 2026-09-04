FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

RUN pip install --no-cache-dir \
    streamlit>=1.35.0 \
    httpx>=0.27.0

COPY . /app

EXPOSE 8501

HEALTHCHECK --interval=5s --timeout=3s --retries=5 --start-period=10s \
    CMD python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8501/_stcore/health")' || exit 1

CMD ["streamlit", "run", "ui/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]

