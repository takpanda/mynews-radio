FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg, crontab, and curl (needed for voicevox health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8010

ENTRYPOINT ["/entrypoint.sh"]
