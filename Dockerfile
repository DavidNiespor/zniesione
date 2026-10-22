FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY zniesione ./zniesione
ENV DATABASE=/data/zniesione.db RUN_SCHEDULER=1
VOLUME /data
EXPOSE 8000
# jeden proces, bo harmonogram działa w wątku aplikacji
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "--threads", "4", "zniesione:create_app()"]
