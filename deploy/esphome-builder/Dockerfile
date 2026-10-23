# Budowanie firmware ESPHome dla sterowników (kontener „esphome” w docker-compose.yml).
# Wersja 2026.10.0: na niej sprawdzono pełną kompilację konfiguracji z portalu.
FROM esphome/esphome:2026.10.0
COPY builder.py /builder.py
ENV CONFIG_DIR=/config PORT=6100 HOST=127.0.0.1
ENTRYPOINT ["python3", "/builder.py"]
