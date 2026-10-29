FROM python:3.12-slim

# System deps – ffmpeg is required
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render expects the process to listen on $PORT (health check)
# Our main.py starts a tiny HTTP server on that port automatically.

CMD ["python", "main.py"]
