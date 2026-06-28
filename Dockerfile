# Coffer — application image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_PATH=/app/data/coffer.db

WORKDIR /app

# Dependencies first, for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code. Runtime data (the SQLite DB + uploaded logos) is NOT baked
# in — it lives in the bind-mounted /app/data volume at runtime.
COPY app.py db.py pdf_gen.py ./
COPY static ./static
COPY templates ./templates

# Created so the app can write even if the volume is empty on first boot.
RUN mkdir -p /app/data
VOLUME /app/data

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3).status==200 else 1)"

CMD ["gunicorn", "-b", "0.0.0.0:5000", "-k", "gthread", "-w", "2", \
     "--threads", "8", "--timeout", "60", "--preload", "app:app"]
