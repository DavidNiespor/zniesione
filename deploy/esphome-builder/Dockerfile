# Budowanie firmware ESPHome dla sterowników (kontener „esphome” w docker-compose.yml)
FROM esphome/esphome:2026.9.1
COPY builder.py /builder.py
ENV CONFIG_DIR=/config PORT=6100 HOST=127.0.0.1
ENTRYPOINT ["python3", "/builder.py"]
