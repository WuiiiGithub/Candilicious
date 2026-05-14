FROM python:3.13.5-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP_PORT=10000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a non-root user and change ownership
RUN useradd -m candi && chown -R candi:candi /app

# Copy project files
COPY --chown=candi:candi . .

# Switch to non-root user
USER candi

EXPOSE ${FLASK_APP_PORT}

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl --fail http://localhost:${FLASK_APP_PORT}/ping || exit 1

CMD ["python3", "main.py"]
