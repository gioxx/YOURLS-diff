FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    YOURLS_DIFF_DATA_DIR=/data \
    YOURLS_DIFF_CACHE_DIR=/data/cache \
    YOURLS_DIFF_OUTPUT_DIR=/data/outputs \
    YOURLS_DIFF_HOST=0.0.0.0 \
    YOURLS_DIFF_PORT=8000

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/cache /data/outputs

EXPOSE 8000

CMD ["python", "-m", "web.yourls_diff_web"]
