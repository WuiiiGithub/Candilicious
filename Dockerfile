FROM python:3.13.5-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ARG FLASK_APP_PORT=10000
EXPOSE ${FLASK_APP_PORT}

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl --fail http://localhost:${FLASK_APP_PORT}/ping || exit 1

CMD ["python3", "main.py"]
