"""Katalog sterowników sprzedawanych przez operatora. Tylko te modele można zamówić.
Ceny ustala operator poza kodem; `cheapest` oznacza najtańszy model w ofercie."""
MODELS = {
    "tr4": dict(name="LilyGO T-Relay: ESP32, 4 przekaźniki", channels=4, board="esp32dev",
                tunnels=("wg",), relays=[21, 19, 18, 5], cheapest=True),
    "trs3": dict(name="LilyGO T-RelayS3: ESP32-S3, 6 przekaźników, DIN", channels=6,
                 board="esp32-s3-devkitc-1", tunnels=("wg", "ts"), sr=dict(data=7, clock=5, latch=6)),
    "wsp": dict(name="Waveshare ESP32-S3-POE-ETH-8DI-8RO-C", channels=8, board="esp32-s3-devkitc-1",
                tunnels=("wg", "ts"), eth=True),
    "shp": dict(name="Shelly Pro 4PM", channels=4, tunnels=("mqtt",), shelly=True),
    # własny sterownik spięty z Home Assistant: nie ma go w ofercie, włącza go administrator dla wybranej farmy
    "ha": dict(name="Home Assistant (własny sterownik)", channels=0, tunnels=("wg", "url"), own=True),
}
KINDS = ("light", "door_open", "door_close", "vent", "heater", "water_heater",
         "valve", "pump", "feeder", "other")
KIND_NAMES = {"light": "Światło", "door_open": "Drzwi: otwórz", "door_close": "Drzwi: zamknij", "vent": "Wentylacja",
              "heater": "Ogrzewanie", "water_heater": "Grzałka wody", "valve": "Elektrozawór", "pump": "Pompa",
              "feeder": "Karmnik", "other": "Inne"}
COOL, HEAT = {"vent"}, {"heater", "water_heater"}
DOORS = {"door_open", "door_close"}
DEFAULT_MODEL = "tr4"


def default_channels(model):
    n = MODELS[model]["channels"]
    out = [("ch1", "Światło", "light"), ("ch2", "Drzwi: otwórz", "door_open"),
           ("ch3", "Drzwi: zamknij", "door_close")]
    return out[:n] + [(f"ch{i}", f"Przekaźnik {i}", "other") for i in range(4, n + 1)]
