FROM python:3.12-slim
# tzdata: harmonogramy i wschód/zachód słońca liczone są w strefie czasowej serwera (TZ)
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY zniesione ./zniesione
ENV DATABASE=/data/zniesione.db RUN_SCHEDULER=1 TZ=Europe/Warsaw PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)"
# jeden proces, bo harmonogram i limit logowania działają w pamięci procesu aplikacji
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "--threads", "4", "--access-logfile", "-", "zniesione:create_app()"]
