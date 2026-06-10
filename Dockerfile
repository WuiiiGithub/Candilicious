FROM python:3.13.5-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEBSITE_APP_PORT =10301

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd -m candi && chown -R candi:candi /app

COPY --chown=candi:candi . .

USER candi

EXPOSE ${WEBSITE_APP_PORT}

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl --fail http://localhost:${WEBSITE_APP_PORT}/ping || exit 1

CMD ["python3", "main.py"]
